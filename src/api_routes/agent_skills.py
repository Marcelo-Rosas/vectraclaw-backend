"""W15.1 — Endpoints Agent Skills + Operation Types Catalog.

Suporta refator arquitetural do Step (Marcelo 2026-05-18):
- Canvas usa 1 dropdown "Agent Skill" (combo agent_specialty_configs) — não 2 dropdowns separados
- TASK_OPERATION_TYPES hardcoded no frontend (VectraClip src/lib/display.ts:201) substituído por GET catalog

Endpoints:
- GET /api/companies/{company_id}/agent-skills
    Lista combos de agent_specialty_configs joined com agents.name + agent_specialties.name.
    Filtro opcional ?agent_id= pra reduzir payload.
    Auditor P1 #3: filtro company_id EXPLÍCITO na query (não confia só em RLS — api usa service_role).

- GET /api/operation-types-catalog
    Lista operation_types_catalog (47 rows hoje). Filtro opcional ?primary_agent_id=.
    Catalog é GLOBAL (sem company_id) — não precisa filter por tenant.

Auth: middleware existente (request.state.company_id + user_id).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request

logger = logging.getLogger("api.agent_skills")

router = APIRouter(tags=["agent-skills"])


def _resolve_caller(request: Request) -> tuple[str, str]:
    """Devolve (company_id, user_id). Levanta 401 se faltam."""
    company_id = getattr(request.state, "company_id", None)
    user_id = getattr(request.state, "user_id", None)
    if not company_id or not user_id:
        raise HTTPException(status_code=401, detail="unauthenticated")
    return str(company_id), str(user_id)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/companies/{company_id}/agent-skills
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/companies/{company_id}/agent-skills")
@router.get("/companies/{company_id}/agent-skills")
async def list_agent_skills(
    request: Request,
    company_id: str = Path(..., description="Tenant company_id"),
    agent_id: Optional[str] = Query(
        default=None,
        description="Filtro opcional: lista apenas skills do agente especificado.",
    ),
) -> List[Dict[str, Any]]:
    """Lista combos agent_specialty_configs joined com agents + agent_specialties.

    Usado pelo dropdown único 'Agent Skill' no canvas — cada item carrega
    agent_id + specialty + operation_types embutidos.

    Auditor P1 #3: filtra company_id explicitamente (não delegar a RLS — api
    usa service_role que bypassa). Cross-tenant tem que ser bloqueado aqui.
    """
    caller_company, _ = _resolve_caller(request)

    # Cross-tenant guard — path param tem que bater com JWT
    if caller_company != company_id:
        raise HTTPException(status_code=403, detail="cross_company_forbidden")

    from src.api import supabase
    if not supabase:
        return []

    try:
        # Join: agent_specialty_configs → agents (nome) + agent_specialties (nome)
        # Filtro company_id obrigatório (Regra Ouro auditor P1.3).
        q = (
            supabase.table("agent_specialty_configs")
            .select("id,agent_id,specialty_id,values,agents(name),agent_specialties(name)")
            .eq("company_id", company_id)
        )
        if agent_id:
            q = q.eq("agent_id", agent_id)

        res = q.order("agent_id").execute()
        rows = res.data or []

        skills: List[Dict[str, Any]] = []
        for r in rows:
            values = r.get("values") or {}
            # operation_types pode vir no values.operation_types[] (Athena pattern)
            # ou ser inferido depois via operation_types_catalog (não neste endpoint —
            # frontend faz lookup com /api/operation-types-catalog se precisar).
            op_types = values.get("operation_types") if isinstance(values, dict) else None
            if not isinstance(op_types, list):
                op_types = []

            agents_join = r.get("agents") or {}
            specialties_join = r.get("agent_specialties") or {}

            skills.append({
                "id": r.get("id"),
                "agentId": r.get("agent_id"),
                "agentName": agents_join.get("name") if isinstance(agents_join, dict) else None,
                "specialtySlug": r.get("specialty_id"),
                "specialtyName": specialties_join.get("name") if isinstance(specialties_join, dict) else None,
                "operationTypes": op_types,
                "values": values,
            })
        return skills
    except Exception as e:
        logger.error("list_agent_skills failed company=%s agent=%s: %s", company_id, agent_id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/operation-types-catalog
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/operation-types-catalog")
@router.get("/operation-types-catalog")
async def list_operation_types_catalog(
    request: Request,
    primary_agent_id: Optional[str] = Query(
        default=None,
        description="Filtro opcional: lista apenas operations vinculadas a esse agente (primary_agent_id).",
    ),
    only_active: bool = Query(default=True),
) -> List[Dict[str, Any]]:
    """Lista operation_types_catalog (47 rows). Catalog é GLOBAL (sem company_id).

    Substitui TASK_OPERATION_TYPES hardcoded em VectraClip src/lib/display.ts:201.
    Frontend novos (W15.2) consomem este endpoint.
    """
    _resolve_caller(request)  # apenas valida auth

    from src.api import supabase
    if not supabase:
        return []

    try:
        q = (
            supabase.table("operation_types_catalog")
            .select("id,name,description,category,icon,color,display_order,primary_agent_id,default_specialty_slug,is_active,routing_score")
            .order("category")
            .order("display_order")
        )
        if only_active:
            q = q.eq("is_active", True)
        if primary_agent_id:
            q = q.eq("primary_agent_id", primary_agent_id)

        res = q.execute()
        return res.data or []
    except Exception as e:
        logger.error("list_operation_types_catalog failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/workflow-trigger-types — W15.1.5
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/workflow-trigger-types")
@router.get("/workflow-trigger-types")
async def list_workflow_trigger_types(
    request: Request,
    only_active: bool = Query(default=True),
) -> List[Dict[str, Any]]:
    """Lista workflow_trigger_types (5 slugs hoje: manual/cron/webhook/event/realtime).
    Catalog GLOBAL. Alimenta dropdown 'Modo de disparo' do canvas (W15.2).
    """
    _resolve_caller(request)
    from src.api import supabase
    if not supabase:
        return []
    try:
        q = (
            supabase.table("workflow_trigger_types")
            .select("slug,name,description,icon,display_order,is_active")
            .order("display_order")
        )
        if only_active:
            q = q.eq("is_active", True)
        res = q.execute()
        return res.data or []
    except Exception as e:
        logger.error("list_workflow_trigger_types failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/workflow-logic-patterns — W15.1.5
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/workflow-logic-patterns")
@router.get("/workflow-logic-patterns")
async def list_workflow_logic_patterns(
    request: Request,
    only_active: bool = Query(default=True),
) -> List[Dict[str, Any]]:
    """Lista workflow_logic_patterns (8 patterns: simple/split-if/split-switch/
    merge-by-key/loop-batch/wait-event/subflow/error-handler). Catalog GLOBAL.
    Alimenta dropdown 'Lógica' do canvas (W15.2) — só roteamento, não disparo.
    """
    _resolve_caller(request)
    from src.api import supabase
    if not supabase:
        return []
    try:
        q = (
            supabase.table("workflow_logic_patterns")
            .select("id,taxonomy,category,name,description,icon,color,display_order,engine_handler,is_active")
            .order("display_order")
        )
        if only_active:
            q = q.eq("is_active", True)
        res = q.execute()
        return res.data or []
    except Exception as e:
        logger.error("list_workflow_logic_patterns failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
