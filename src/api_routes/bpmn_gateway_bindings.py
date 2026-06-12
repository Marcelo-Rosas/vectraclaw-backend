"""P0-BE-1 — GET /api/bpmn/gateway-bindings

Catálogo global BPMN gateway (tipo + fork/join) → workflow_logic_patterns.
Alimenta sidebar 'Ponte Workflow' no VectraClip (HANDOFF-BPMN-FRONTEND-PRIORIDADE P0-FE-3).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, Request

from src.services.bpmn_gateway_catalog import fetch_gateway_bindings

logger = logging.getLogger("api.bpmn_gateway_bindings")
router = APIRouter(tags=["bpmn-gateway-bindings"])


def _to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def _row_to_response(row: Dict[str, Any]) -> Dict[str, Any]:
    """CamelCase para consumo frontend (sem Pydantic model dedicado — alinha workflow-logic-patterns)."""
    return {
        "bpmnGatewayType": row.get("bpmn_gateway_type"),
        "topology": row.get("topology"),
        "logicPatternId": row.get("logic_pattern_id"),
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "engineStatus": row.get("engine_status") or "pending",
        "displayOrder": row.get("display_order", 100),
        "isActive": row.get("is_active", True),
    }


@router.get("/api/bpmn/gateway-bindings")
@router.get("/bpmn/gateway-bindings")
async def list_bpmn_gateway_bindings(
    request: Request,
    only_active: bool = Query(default=True, description="Filtra is_active=true"),
) -> List[Dict[str, Any]]:
    """Lista mapeamento gateway BPMN → logic_pattern.

    Catálogo GLOBAL (sem company_id). Autenticação: company_id no JWT
    (mesmo padrão workflow-logic-patterns).

    Retorna 4 bindings seed:
    - gateway_exclusive / fork → split-if (active)
    - gateway_parallel / fork → simple (pending)
    - gateway_parallel / join → merge-by-key (pending)
    - gateway_inclusive / fork → split-switch (pending)
    """
    company_id = getattr(request.state, "company_id", None)
    if not company_id:
        raise HTTPException(status_code=401, detail="company_id missing (auth required)")

    from src.api import supabase

    if not supabase:
        return []

    try:
        q = (
            supabase.table("bpmn_gateway_bindings")
            .select(
                "bpmn_gateway_type,topology,logic_pattern_id,name,description,"
                "engine_status,display_order,is_active"
            )
            .order("display_order")
        )
        if only_active:
            q = q.eq("is_active", True)
        res = q.execute()
        rows = res.data or []
    except Exception as exc:
        # Tabela ainda não migrada em ambiente dev
        logger.error("list_bpmn_gateway_bindings failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not rows:
        # Fallback via service (mesma query — útil se PostgREST schema cache atrasar)
        rows = fetch_gateway_bindings(supabase)

    return [_row_to_response(r) for r in rows]
