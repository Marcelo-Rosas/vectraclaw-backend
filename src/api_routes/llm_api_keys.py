"""W13.1 — Endpoints CRUD pra llm_api_keys (AI Gateway).

Painel admin /admin/llm-keys (a ser implementado em W13.4 frontend) lista, cria,
edita e reseta status das keys por company+provider+model. Sync pra UI.

Auth: middleware existente (request.state.user_id + company_id + role).
RBAC: writes só pra admin (verifica role). Reads pra qualquer authenticated da
mesma company. Cross-company: bloqueado explicitamente (P1.3 W15.1).

Padrão de submodule conforme src/api_routes/CLAUDE.md.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("api.llm_api_keys")

router = APIRouter(tags=["llm-api-keys"])

_ADMIN_ROLES = {"admin", "owner", "root"}


def _resolve_caller(request: Request) -> tuple[str, str, Optional[str]]:
    company_id = getattr(request.state, "company_id", None)
    user_id = getattr(request.state, "user_id", None)
    role = getattr(request.state, "user_role", None)
    if not company_id or not user_id:
        raise HTTPException(status_code=401, detail="unauthenticated")
    return str(company_id), str(user_id), (str(role) if role else None)


def _assert_admin(role: Optional[str]) -> None:
    if (role or "").lower() not in _ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="admin_only")


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/llm-api-keys — lista da company do caller
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/llm-api-keys")
@router.get("/llm-api-keys")
async def list_llm_api_keys(
    request: Request,
    provider: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista keys LLM da company do caller. NÃO devolve o vault_secret_id
    decifrado — apenas o UUID-ref. Painel mostra status/priority/last_used."""
    company_id, _, _ = _resolve_caller(request)
    from src.api import supabase
    if not supabase:
        return []

    try:
        q = (
            supabase.table("llm_api_keys")
            .select(
                "id,company_id,provider,model_id,vault_secret_id,priority,"
                "status,last_error,exhausted_at,last_used_at,metadata,"
                "created_at,updated_at"
            )
            .eq("company_id", company_id)  # auditor A3 — EXPLÍCITO
            .order("provider")
            .order("priority")
        )
        if provider:
            q = q.eq("provider", provider)
        if status:
            q = q.eq("status", status)
        res = q.execute()
        return res.data or []
    except Exception as e:
        logger.error("list_llm_api_keys failed company=%s: %s", company_id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/llm-api-keys — cria nova (admin-only)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/llm-api-keys")
@router.post("/llm-api-keys")
async def create_llm_api_key(request: Request) -> Dict[str, Any]:
    """Cria nova llm_api_key. Espera body:
        {
          "provider": "anthropic",
          "model_id": "claude-sonnet-4-6"|null,
          "vault_secret_id": "<uuid>"|null,  // null SÓ se provider=ollama
          "priority": 100,
          "metadata": {...}
        }
    Admin-only. Cross-company blocking: company_id vem do JWT (state), nunca do body."""
    company_id, _, role = _resolve_caller(request)
    _assert_admin(role)

    body = await request.json()
    provider = body.get("provider")
    if not provider:
        raise HTTPException(status_code=422, detail="provider_required")

    vault_secret_id = body.get("vault_secret_id")
    if not vault_secret_id and provider != "ollama":
        # Defensive — CHECK do DB já bloqueia, mas UX melhor falhar antes
        raise HTTPException(
            status_code=422,
            detail=f"vault_secret_id required for provider={provider} (only ollama allows null)",
        )

    from src.api import supabase
    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_unavailable")

    payload = {
        "company_id": company_id,  # do JWT, nunca do body
        "provider": provider,
        "model_id": body.get("model_id"),
        "vault_secret_id": vault_secret_id,
        "priority": int(body.get("priority", 100)),
        "metadata": body.get("metadata") or {},
    }
    try:
        res = supabase.table("llm_api_keys").insert(payload).execute()
        return (res.data or [{}])[0]
    except Exception as e:
        logger.error("create_llm_api_key failed company=%s: %s", company_id, e)
        raise HTTPException(status_code=400, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /api/llm-api-keys/{id} — edit priority/status/metadata (admin-only)
# ─────────────────────────────────────────────────────────────────────────────

@router.patch("/api/llm-api-keys/{key_id}")
@router.patch("/llm-api-keys/{key_id}")
async def update_llm_api_key(key_id: str, request: Request) -> Dict[str, Any]:
    """Atualiza priority/status/metadata. Admin-only. Cross-company guard:
    valida company_id ANTES do update (não confiar em RLS com service_role)."""
    company_id, _, role = _resolve_caller(request)
    _assert_admin(role)

    from src.api import supabase
    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_unavailable")

    # P1.3 — cross-company guard EXPLÍCITO
    owner = (
        supabase.table("llm_api_keys")
        .select("company_id")
        .eq("id", key_id)
        .limit(1)
        .execute()
    )
    if not owner.data:
        raise HTTPException(status_code=404, detail="not_found")
    if str(owner.data[0]["company_id"]) != company_id:
        raise HTTPException(status_code=403, detail="cross_company_forbidden")

    body = await request.json()
    allowed = {"priority", "status", "metadata", "model_id"}
    patch = {k: v for k, v in body.items() if k in allowed}
    if not patch:
        raise HTTPException(status_code=422, detail="no_editable_fields")
    if "status" in patch and patch["status"] not in ("active", "exhausted", "disabled"):
        raise HTTPException(status_code=422, detail="invalid_status")

    # Reset diagnostics quando volta pra active
    if patch.get("status") == "active":
        patch["last_error"] = None
        patch["exhausted_at"] = None

    try:
        res = (
            supabase.table("llm_api_keys")
            .update(patch)
            .eq("id", key_id)
            .eq("company_id", company_id)  # double-check
            .execute()
        )
        return (res.data or [{}])[0]
    except Exception as e:
        logger.error("update_llm_api_key failed id=%s company=%s: %s", key_id, company_id, e)
        raise HTTPException(status_code=400, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/llm-api-keys/{id}/reset — atalho pra status='active' + clear errors
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/llm-api-keys/{key_id}/reset")
@router.post("/llm-api-keys/{key_id}/reset")
async def reset_llm_api_key(key_id: str, request: Request) -> Dict[str, Any]:
    """Reseta status pra active (manual refresh após investigar quota). Admin-only."""
    company_id, _, role = _resolve_caller(request)
    _assert_admin(role)

    from src.api import supabase
    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_unavailable")

    owner = (
        supabase.table("llm_api_keys")
        .select("company_id")
        .eq("id", key_id)
        .limit(1)
        .execute()
    )
    if not owner.data:
        raise HTTPException(status_code=404, detail="not_found")
    if str(owner.data[0]["company_id"]) != company_id:
        raise HTTPException(status_code=403, detail="cross_company_forbidden")

    try:
        res = (
            supabase.table("llm_api_keys")
            .update({"status": "active", "last_error": None, "exhausted_at": None})
            .eq("id", key_id)
            .eq("company_id", company_id)
            .execute()
        )
        return (res.data or [{}])[0]
    except Exception as e:
        logger.error("reset_llm_api_key failed id=%s: %s", key_id, e)
        raise HTTPException(status_code=400, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /api/llm-api-keys/{id} — hard delete (admin-only)
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/api/llm-api-keys/{key_id}")
@router.delete("/llm-api-keys/{key_id}")
async def delete_llm_api_key(key_id: str, request: Request) -> Dict[str, Any]:
    """Remove key. Admin-only. Cross-company guard explícito."""
    company_id, _, role = _resolve_caller(request)
    _assert_admin(role)

    from src.api import supabase
    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_unavailable")

    owner = (
        supabase.table("llm_api_keys")
        .select("company_id")
        .eq("id", key_id)
        .limit(1)
        .execute()
    )
    if not owner.data:
        raise HTTPException(status_code=404, detail="not_found")
    if str(owner.data[0]["company_id"]) != company_id:
        raise HTTPException(status_code=403, detail="cross_company_forbidden")

    try:
        supabase.table("llm_api_keys").delete().eq("id", key_id).eq("company_id", company_id).execute()
        return {"deleted": True, "id": key_id}
    except Exception as e:
        logger.error("delete_llm_api_key failed id=%s: %s", key_id, e)
        raise HTTPException(status_code=400, detail=str(e))
