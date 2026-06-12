"""
API routes for native Gemini integration.
Allows testing and executing Gemini native capabilities directly, mirroring the Hermes interface.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.services import gemini_native as gn
from src.services import nous_hermes as nh

logger = logging.getLogger("api.gemini_native")
router = APIRouter(tags=["gemini-native"])

_ADMIN_ROLES = frozenset({"admin", "platform_admin", "company_admin"})

class GeminiExecBody(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=200_000)
    agent_id: Optional[str] = None
    timeout_seconds: int = Field(default=60, ge=30, le=300)

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


@router.post("/api/gemini/exec")
async def gemini_exec_route(request: Request, body: GeminiExecBody) -> Dict[str, Any]:
    from src.api import supabase

    company_id = _auth_admin(request)
    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_unavailable")
    
    # We reuse the logic from nous_hermes config resolver or just pull native if built
    if not gn.is_gemini_active(supabase, company_id):
        raise HTTPException(status_code=503, detail="adapter_gemini_inactive")

    try:
        # Puxamos as chaves da config do nous_hermes para simplificar a migração
        # Ou se existir a tabela gemini, podemos buscar de lá.
        hermes_config, api_key = nh.resolve_nous_hermes_config(
            supabase, company_id, agent_id=body.agent_id
        )
    except nh.NousHermesConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not api_key:
        raise HTTPException(status_code=400, detail="Gemini API Key missing")

    try:
        return await gn.gemini_exec(
            prompt=body.prompt,
            gemini_config=hermes_config,
            api_key=api_key,
            timeout_seconds=body.timeout_seconds,
        )
    except Exception as exc:
        logger.error("gemini_exec failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
