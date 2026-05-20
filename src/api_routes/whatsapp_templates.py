"""W11 PR1 — Endpoints WhatsApp Templates (WABA catalog).

- POST /api/connectors/whatsapp/templates/sync — admin-only, force refresh
- GET  /api/connectors/whatsapp/templates       — lista templates do catalog local
- GET  /api/connectors/channels                 — lista catalog connector_channels
  (gap descoberto no PR #48 VectraClip — desbloqueia filtros server-side)

Auth: middleware existente (request.state.user_id + company_id). Sem JWT
inline. ConnectorChannels é leitura pra UI (sem RBAC além de company filter).
Sync é admin (verifica role).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger("api.whatsapp_templates")

router = APIRouter(tags=["whatsapp-templates"])

# JWT vectraclip.role → admin | member (_zod_user_role em api.py). owner/founder
# ficam reservados se o claim evoluir; hoje só admin passa o gate de sync.
_SYNC_ADMIN_ROLES = frozenset({"admin", "owner", "founder"})


def _resolve_caller(request: Request) -> tuple[str, str, Optional[str]]:
    """Devolve (company_id, user_id, role). Levanta 401 se faltam."""
    company_id = getattr(request.state, "company_id", None)
    user_id = getattr(request.state, "user_id", None)
    # Middleware grava request.state.role (não user_role).
    role = getattr(request.state, "role", None) or getattr(
        request.state, "user_role", None
    )
    if not company_id or not user_id:
        raise HTTPException(status_code=401, detail="unauthenticated")
    return str(company_id), str(user_id), (str(role) if role else None)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/connectors/whatsapp/templates
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/connectors/whatsapp/templates")
@router.get("/connectors/whatsapp/templates")
async def list_whatsapp_templates(
    request: Request,
    adapter_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None,
        description="Filtro Meta status (APPROVED|PENDING|REJECTED|PAUSED|...)"),
    language_in: Optional[str] = Query(default=None,
        description="CSV de language codes (ex: 'pt_BR,pt,und')"),
    only_active: bool = Query(default=True),
) -> List[Dict[str, Any]]:
    """Lista templates locais espelho da WABA. Usado pelo DynamicFieldRenderer
    (options_json.source='whatsapp_templates' resolve via este endpoint).

    Filtros vêm de adapter_field_definitions.options_json.filter — frontend
    repassa como query params.
    """
    company_id, _, _ = _resolve_caller(request)
    from src.api import supabase
    if not supabase:
        return []

    try:
        q = (
            supabase.table("whatsapp_templates")
            .select("id,name,language,category,status,components,quality_score,is_active,last_synced_at")
            .eq("company_id", company_id)
            .order("name")
        )
        if only_active:
            q = q.eq("is_active", True)
        if status:
            q = q.eq("status", status)
        if language_in:
            langs = [s.strip() for s in language_in.split(",") if s.strip()]
            if langs:
                q = q.in_("language", langs)
        # adapter_id atualmente não filtra (templates são por company/WABA,
        # não por adapter). Mantemos o param na assinatura pra futuro multi-adapter.
        _ = adapter_id
        res = q.execute()
        return res.data or []
    except Exception as e:
        logger.error("list_whatsapp_templates failed company=%s: %s", company_id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/connectors/whatsapp/templates/sync
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/connectors/whatsapp/templates/sync")
@router.post("/connectors/whatsapp/templates/sync")
async def sync_whatsapp_templates(
    request: Request,
    adapter_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Force refresh dos templates WABA via Meta Graph API.

    Admin-only. Resolve adapter meta-whatsapp da company se adapter_id não vier.
    Best-effort: erros parciais retornam status='partial', sync continua.
    """
    company_id, user_id, role = _resolve_caller(request)

    if (role or "").lower() not in _SYNC_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="admin_only")

    from src.api import supabase
    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_unavailable")

    try:
        # Resolve adapter_id se não veio
        if not adapter_id:
            ac = (
                supabase.table("adapter_catalog")
                .select("id")
                .eq("company_id", company_id)
                .eq("slug", "meta-whatsapp")
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            if not ac.data:
                raise HTTPException(
                    status_code=404,
                    detail="meta_whatsapp_adapter_not_configured",
                )
            adapter_id = ac.data[0]["id"]

        from src.services.whatsapp_template_sync import sync_company_templates

        return await sync_company_templates(
            company_id=company_id,
            adapter_id=str(adapter_id),
            triggered_by_user_id=user_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "sync_whatsapp_templates failed company=%s adapter=%s: %s",
            company_id,
            adapter_id,
            e,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"sync_failed: {e}") from e


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/connectors/channels — catalog (gap PR #48)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/connectors/channels")
@router.get("/connectors/channels")
async def list_connector_channels(request: Request) -> List[Dict[str, Any]]:
    """Lista connector_channels ativos. Catalog endpoint pra filtros server-side
    da página /connectors/sessions (PR #48 VectraClip mencionou esse gap)."""
    _resolve_caller(request)  # apenas valida auth
    from src.api import supabase
    if not supabase:
        return []
    try:
        res = (
            supabase.table("connector_channels")
            .select("slug,name,is_active,fallback_operation_type")
            .eq("is_active", True)
            .order("slug")
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error("list_connector_channels failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
