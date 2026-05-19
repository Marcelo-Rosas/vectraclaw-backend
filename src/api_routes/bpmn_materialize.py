"""src.api_routes.bpmn_materialize — PR Phase 3 autopilot (2026-05-19).

POST /api/bpmn/diagrams/{diagram_id}/materialize
   Materializa BPMN diagram em workflow_definitions + workflow_steps.

Implementa Phase 3 do `docs/HANDOFF-BPMN-WORKFLOW-BRIDGE.md`. Frontend Phase
1+2 já feito no VectraClip (modelador + agent_specialty_config_id em
service_task). Este endpoint fecha a ponte BPMN → workflow executável.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.services.bpmn_materialize import (
    BpmnMaterializeError,
    materialize_bpmn_to_workflow,
)

logger = logging.getLogger("api.bpmn_materialize")
router = APIRouter(tags=["bpmn-materialize"])


def _to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


class _CamelModel(BaseModel):
    class Config:
        populate_by_name = True
        alias_generator = _to_camel


class BpmnMaterializeResponse(_CamelModel):
    workflow_id: str = Field(..., description="UUID do workflow_definitions criado")
    workflow_slug: str
    steps_created: int = Field(..., description="Número de workflow_steps inseridos com sucesso")
    warnings: list[str] = Field(default_factory=list)
    linked_diagram_id: str
    replaced: bool = Field(False, description="True se substituiu workflow anterior (replace=true)")


@router.post(
    "/api/bpmn/diagrams/{diagram_id}/materialize",
    response_model=BpmnMaterializeResponse,
    response_model_by_alias=True,
)
async def materialize_bpmn_diagram(
    request: Request,
    diagram_id: str,
    replace: bool = Query(False, description="Se True, sobrescreve linked_workflow_id existente"),
) -> BpmnMaterializeResponse:
    """Phase 3 do HANDOFF-BPMN-WORKFLOW-BRIDGE.md.

    Lê `bpmn_diagrams.diagram_json`, cria workflow_definition + workflow_steps
    em ordem topológica. Copia agent_specialty_config_id, default_operation_type,
    responsavel do `node.data`. Atualiza bpmn_diagrams.linked_workflow_id.

    Auth: middleware setta request.state.company_id. Cross-tenant blocked.
    Idempotency: 409 se diagrama já tem linked_workflow_id, salvo replace=true.
    """
    from src.api import supabase

    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_unavailable")

    company_id = getattr(request.state, "company_id", None)
    if not company_id:
        raise HTTPException(status_code=401, detail="company_id missing (auth required)")

    logger.info(
        "bpmn_materialize start diagram=%s company=%s replace=%s",
        diagram_id, company_id, replace,
    )

    try:
        result = materialize_bpmn_to_workflow(
            supabase,
            diagram_id=diagram_id,
            user_company_id=str(company_id),
            replace=replace,
        )
    except BpmnMaterializeError as exc:
        logger.warning("bpmn_materialize rejected code=%s diagram=%s: %s", exc.code, diagram_id, exc)
        raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": str(exc)})
    except Exception as exc:
        logger.exception("bpmn_materialize unexpected error diagram=%s", diagram_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return BpmnMaterializeResponse(
        workflow_id=result["workflow_id"],
        workflow_slug=result["workflow_slug"],
        steps_created=result["steps_created"],
        warnings=result["warnings"],
        linked_diagram_id=result["linked_diagram_id"],
        replaced=result["replaced"],
    )
