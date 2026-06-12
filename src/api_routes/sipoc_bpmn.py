"""src.api_routes.sipoc_bpmn — BPMN diagram lookup por processo SIPOC.

Endpoint:
  GET /api/sipoc/{process_id}/bpmn_diagram   (+ alias sem /api)

Retorna o diagram_json do BPMN vinculado a um processo SIPOC.
Acesso: todos os usuários autenticados do tenant (sem bloqueio de role).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("api.sipoc_bpmn")
router = APIRouter(tags=["sipoc-bpmn"])


@router.get("/api/sipoc/{process_id}/bpmn_diagram")
@router.get("/sipoc/{process_id}/bpmn_diagram")
async def get_bpmn_diagram(request: Request, process_id: str):
    """Retorna o diagrama BPMN vinculado a um processo SIPOC.

    Auth: middleware popula request.state.token / .company_id.
    Tenant isolation: filtra por company_id no DB.
    Sem bloqueio de role — todos os usuários do tenant podem consultar.

    Returns:
        {processId, diagramId, diagramJson}
    """
    from src.api import supabase
    from src.services.bpmn_materialize import get_bpmn_diagram_by_process_id

    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_unavailable")

    company_id = getattr(request.state, "company_id", None)
    if not company_id:
        raise HTTPException(status_code=401, detail="company_id missing (auth required)")

    try:
        result = get_bpmn_diagram_by_process_id(supabase, process_id, str(company_id))
        return {
            "processId": process_id,
            **result,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_bpmn_diagram failed process_id=%s", process_id)
        raise HTTPException(status_code=500, detail=str(exc))
