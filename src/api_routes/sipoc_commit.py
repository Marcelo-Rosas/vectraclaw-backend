"""src.api_routes.sipoc_commit — PR2.3 autopilot.

POST /api/sipoc/sessions/{session_id}/commit
   Materializa SIPOC vindo do chat Oracle em sipoc_processes/components/raci.

Opção B do F-008: aceita estado completo no body. Frontend monta a partir do
histórico de chat. session_id no path é apenas pra audit metadata — não
lê in-memory state (que está sempre vazio hoje — gap fundamental do Oracle
chat documentado em F-008).

Endpoint:
- POST /api/sipoc/sessions/{session_id}/commit   commit_sipoc_session
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.services.sipoc_commit_service import (
    SipocCommitError,
    commit_sipoc,
)

logger = logging.getLogger("api.sipoc_commit")
router = APIRouter(tags=["sipoc-commit"])


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models (camelCase via alias pra parear frontend; snake_case interno)
# ─────────────────────────────────────────────────────────────────────────────

def _to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


class _CamelModel(BaseModel):
    class Config:
        populate_by_name = True
        alias_generator = _to_camel


class SipocCommitComponentInput(_CamelModel):
    type: str = Field(..., description="FK sipoc_component_types.slug")
    name: Optional[str] = Field(None, description="Nome do componente (vai pra content.name)")
    order: Optional[int] = Field(None, description="Ordem dentro do processo (default = index)")
    content: Optional[Dict[str, Any]] = Field(default_factory=dict, description="JSONB livre. 5W2H pra type=activity.")
    responsible_position_id: Optional[str] = Field(None, description="FK sipoc_positions (soft validate)")
    suggested_operation_type: Optional[str] = Field(None, description="FK operation_types_catalog (soft validate)")
    automation_status: Optional[str] = Field(None, description="manual | hybrid | automated | undefined")


class SipocCommitRaciInput(_CamelModel):
    component_index: int = Field(..., description="Index no array components (0-based)")
    position_id: str = Field(..., description="FK sipoc_positions")
    role: str = Field(..., description="responsible | accountable | consulted | informed (livre)")


class SipocCommitRequest(_CamelModel):
    sector_id: str = Field(..., description="FK sipoc_sectors. Validado contra user company.")
    process_name: str = Field(..., description="Nome do SIPOC process sendo materializado")
    process_description: Optional[str] = Field(None)
    owner_position_id: Optional[str] = Field(None, description="FK sipoc_positions (soft validate)")
    components: List[SipocCommitComponentInput] = Field(default_factory=list)
    raci: List[SipocCommitRaciInput] = Field(default_factory=list)


class SipocCommitResponse(_CamelModel):
    process_id: str
    components_created: int
    raci_created: int
    warnings: List[str]
    session_id: Optional[str]


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/api/sipoc/sessions/{session_id}/commit",
    response_model=SipocCommitResponse,
    response_model_by_alias=True,
)
async def commit_sipoc_session(
    request: Request, session_id: str, payload: SipocCommitRequest
) -> SipocCommitResponse:
    """Materializa estado SIPOC do payload em vectraclip.sipoc_*.

    Auth via middleware: usa `request.state.company_id` pra validar tenant
    contra `sector_id` antes de qualquer INSERT.

    Body shape (camelCase aceito + snake_case alias):
    ```json
    {
      "sectorId": "uuid",
      "processName": "Cotação de Frete",
      "processDescription": "...",
      "ownerPositionId": "uuid",
      "components": [
        {"type": "supplier", "name": "Embarcador", "order": 0},
        {"type": "activity", "name": "Cotar frete", "order": 1,
         "content": {"what":"...","why":"...","how_much":"..."},
         "responsiblePositionId": "uuid",
         "suggestedOperationType": "freight-quotation"}
      ],
      "raci": [
        {"componentIndex": 1, "positionId": "uuid", "role": "responsible"}
      ]
    }
    ```
    """
    # Get supabase service-role client (cross-table validation needs it).
    # Lazy import to avoid circular.
    from src.api import supabase

    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase not available")

    company_id = getattr(request.state, "company_id", None)
    if not company_id:
        raise HTTPException(status_code=401, detail="company_id missing (auth required)")

    logger.info(
        "sipoc_commit start session=%s sector=%s components=%d raci=%d user_company=%s",
        session_id, payload.sector_id, len(payload.components), len(payload.raci), company_id,
    )

    try:
        result = commit_sipoc(
            supabase,
            user_company_id=str(company_id),
            session_id=session_id,
            sector_id=payload.sector_id,
            process_name=payload.process_name,
            process_description=payload.process_description,
            owner_position_id=payload.owner_position_id,
            components=[c.model_dump(exclude_none=False, by_alias=False) for c in payload.components],
            raci=[r.model_dump(exclude_none=False, by_alias=False) for r in payload.raci],
        )
    except SipocCommitError as exc:
        logger.warning("sipoc_commit rejected code=%s session=%s: %s", exc.code, session_id, exc)
        raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": str(exc)})
    except Exception as exc:
        logger.exception("sipoc_commit unexpected error session=%s", session_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return SipocCommitResponse(
        process_id=result["process_id"],
        components_created=result["components_created"],
        raci_created=result["raci_created"],
        warnings=result["warnings"],
        session_id=result.get("session_id"),
    )
