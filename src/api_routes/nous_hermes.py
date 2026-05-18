"""
Runtime Nous Hermes — health proxy + exec admin (PRD F1).

Config de produto vive em adapter_catalog / company_adapter_values;
runtime recebe payload já resolvido.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.services import nous_hermes as nh

logger = logging.getLogger("api.nous_hermes")
router = APIRouter(tags=["nous-hermes"])

_ADMIN_ROLES = frozenset({"admin", "platform_admin", "company_admin"})


class NousHermesExecBody(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=200_000)
    agent_id: Optional[str] = Field(
        default=None,
        description="Opcional — override de agent_adapter_configs",
    )
    max_turns: Optional[int] = Field(default=None, ge=1, le=90)
    timeout_seconds: int = Field(default=180, ge=30, le=600)


def _auth_admin(request: Request) -> str:
    from src.api import get_user_scope, validate_jwt, _resolve_company_id

    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    token = auth[7:].strip()
    if not validate_jwt(token):
        raise HTTPException(status_code=401, detail="invalid_token")

    scope = get_user_scope(token)
    role = scope.get("role") or ""
    if role not in _ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="admin_role_required")

    company_id = _resolve_company_id(request) or scope.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id_required")
    return str(company_id)


@router.get("/api/nous-hermes/health")
async def nous_hermes_health(request: Request) -> Dict[str, Any]:
    """Proxy do healthcheck do container nous-hermes-runtime."""
    _auth_admin(request)
    try:
        data = await nh.runtime_health()
        return {"runtime": data, "runtime_url": nh.runtime_base_url()}
    except Exception as exc:
        logger.error("nous_hermes_health failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"runtime_unreachable: {exc}") from exc


@router.post("/api/nous-hermes/exec")
async def nous_hermes_exec(request: Request, body: NousHermesExecBody) -> Dict[str, Any]:
    """Smoke / admin exec via Hermes-Nous. Requer adapter ativo na company."""
    from src.api import supabase

    company_id = _auth_admin(request)
    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_unavailable")
    if not nh.is_adapter_active(supabase, company_id):
        raise HTTPException(
            status_code=503,
            detail="adapter_nous_hermes_inactive — ative em Admin Connectors",
        )

    try:
        hermes_config, api_key = nh.resolve_nous_hermes_config(
            supabase, company_id, agent_id=body.agent_id
        )
    except nh.NousHermesConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    timeout_seconds = int(hermes_config["timeout_seconds"])
    payload_cfg = {k: v for k, v in hermes_config.items() if k != "timeout_seconds"}
    try:
        return await nh.runtime_exec(
            prompt=body.prompt,
            hermes_config=payload_cfg,
            api_key=api_key,
            max_turns=body.max_turns,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        logger.error("nous_hermes_exec failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
