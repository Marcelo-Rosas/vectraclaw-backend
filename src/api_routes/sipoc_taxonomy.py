"""src.api_routes.sipoc_taxonomy — Marketplace SIPOC templates (Fase A / P1).

Backend pro marketplace global de atividades por vertical/setor. Cliente
escolhe um template e clona pro seu Process — vira um sipoc_component
type='activity' já com 5W2H + suggested_operation_type preenchidos.

Endpoints:
- GET   /api/sipoc/taxonomy                                                    list_templates
- GET   /api/sipoc/taxonomy/{template_id}                                       get_template
- POST  /api/sipoc/processes/{process_id}/import-template/{template_id}         clone_to_process

Catálogo é global (vectraclip.sipoc_taxonomy_global sem company_id).
RLS habilitado, SELECT authenticated. Criação/edição de templates fica
restrita a service_role (admin, via migration ou endpoint futuro PR-Admin).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger("api.sipoc_taxonomy")
router = APIRouter(tags=["sipoc-taxonomy"])


def _taxonomy_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize DB row → wire format (camelCase)."""
    created_at = row.get("created_at")
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat().replace("+00:00", "Z")
    return {
        "id": row["id"],
        "vertical": row["vertical"],
        "category": row["category"],
        "activityName": row["activity_name"],
        "default5w2h": row.get("default_5w2h"),
        "suggestedOperationType": row.get("suggested_operation_type"),
        "description": row.get("description"),
        "createdAt": created_at,
    }


@router.get("/api/sipoc/taxonomy")
@router.get("/sipoc/taxonomy")
async def list_templates(
    request: Request,
    vertical: Optional[str] = Query(None, description="Filtro por vertical (ex: logistica, financeiro)"),
    category: Optional[str] = Query(None, description="Filtro por categoria (ex: Contas a Pagar)"),
):
    """Lista templates do marketplace SIPOC global.

    Filtros opcionais (combináveis): `vertical` e `category`.
    Retorna lista vazia se não houver match. RLS permite read a qualquer
    user authenticated.
    """
    from src.api import supabase, get_authenticated_client

    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        q = client.table("sipoc_taxonomy_global").select("*")
        if vertical:
            q = q.eq("vertical", vertical)
        if category:
            q = q.eq("category", category)
        res = (
            q.order("vertical")
            .order("category")
            .order("activity_name")
            .execute()
        )
        return [_taxonomy_to_dict(row) for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_templates failed: {e}")
        raise HTTPException(500, str(e))


@router.get("/api/sipoc/taxonomy/{template_id}")
@router.get("/sipoc/taxonomy/{template_id}")
async def get_template(request: Request, template_id: str):
    """Detalhe de um template específico do marketplace."""
    from src.api import supabase, get_authenticated_client

    if not supabase:
        raise HTTPException(404, "template_not_found")
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("sipoc_taxonomy_global")
            .select("*")
            .eq("id", template_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(404, "template_not_found")
        return _taxonomy_to_dict(res.data[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_template failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/api/sipoc/processes/{process_id}/import-template/{template_id}")
@router.post("/sipoc/processes/{process_id}/import-template/{template_id}")
async def clone_to_process(
    request: Request,
    process_id: str,
    template_id: str,
):
    """Clona um template do marketplace como sipoc_component (type='activity')
    vinculado a um process do tenant.

    Effects:
    - Insere row em vectraclip.sipoc_components com:
      - process_id = process_id
      - type = 'activity'
      - content = {name, description, ...default_5w2h do template}
      - order = max(existing) + 10  (cabe no final do process)
      - suggested_operation_type = template.suggested_operation_type
      - cloned_from_template_id = template_id
      - automation_status = 'undefined'  (default da coluna; Athena classifica depois)

    Returns: novo component em camelCase.

    Erros:
    - 404 template_not_found
    - 404 process_not_found_or_not_accessible (RLS bloqueou se tenant errado)
    """
    from src.api import supabase, get_authenticated_client, get_user_scope, require_role_not

    if not supabase:
        return {"id": "mock-id"}
    try:
        client = get_authenticated_client(request.state.token)

        # PR6: sector_responsible e viewer não podem importar templates
        # (ação de admin/consultant/company_admin). Bloqueia early.
        scope = get_user_scope(request.state.token)
        require_role_not(
            scope,
            blocked_roles=["sector_responsible", "viewer"],
            action="importar templates do marketplace SIPOC (peça ao company_admin)",
        )

        # 1) Carrega template (catálogo global; RLS permite read authenticated)
        tres = (
            client.table("sipoc_taxonomy_global")
            .select("*")
            .eq("id", template_id)
            .limit(1)
            .execute()
        )
        if not tres.data:
            raise HTTPException(404, "template_not_found")
        template = tres.data[0]

        # 2) Confirma que process existe e pertence ao tenant (RLS filtra)
        pres = (
            client.table("sipoc_processes")
            .select("id, sector_id")
            .eq("id", process_id)
            .limit(1)
            .execute()
        )
        if not pres.data:
            raise HTTPException(404, "process_not_found_or_not_accessible")

        # 3) Próximo order — final do process
        ores = (
            client.table("sipoc_components")
            .select("order")
            .eq("process_id", process_id)
            .order("order", desc=True)
            .limit(1)
            .execute()
        )
        next_order = (ores.data[0]["order"] + 10) if ores.data else 0

        # 4) Monta content (5W2H + meta do template)
        content = {
            "name": template["activity_name"],
            "description": template.get("description"),
        }
        d5w2h = template.get("default_5w2h") or {}
        if isinstance(d5w2h, dict):
            content.update(d5w2h)

        new_row = {
            "process_id": process_id,
            "type": "activity",
            "content": content,
            "order": next_order,
            "suggested_operation_type": template.get("suggested_operation_type"),
            "cloned_from_template_id": template_id,
        }
        ires = client.table("sipoc_components").insert(new_row).execute()
        if not ires.data:
            raise HTTPException(500, "insert_failed")

        component = ires.data[0]
        logger.info(
            "clone_template_to_process OK: template=%s process=%s new_component=%s",
            template_id,
            process_id,
            component["id"],
        )

        return {
            "id": component["id"],
            "processId": process_id,
            "templateId": template_id,
            "type": "activity",
            "automationStatus": component.get("automation_status") or "undefined",
            "suggestedOperationType": component.get("suggested_operation_type"),
            "responsiblePositionId": component.get("responsible_position_id"),
            "content": component["content"],
            "order": component["order"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"clone_to_process failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))
