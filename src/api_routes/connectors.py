"""
src.api_routes.connectors — W3 PRD Fundação Orchestration.

Endpoints de canais externos (Navi/WhatsApp via Evolution API, futuros canais).
Sessões persistem em vectraclip.connector_sessions; orquestração via
src/services/connector_bus.py.

- POST   /api/connectors/navi/webhook                  navi_webhook
- GET    /api/companies/{company_id}/connector-sessions   list_connector_sessions
- POST   /api/connector-sessions/{session_id}/reply       reply_connector_session

Auth segue padrão do projeto: middleware setta request.state.token/company_id.
Webhook Navi é interno (Evolution API → este endpoint) — autenticado via
header X-Navi-Token comparado a NAVI_WEBHOOK_SECRET no .env.
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Request

logger = logging.getLogger("api.connectors")
router = APIRouter(tags=["connectors"])


def _check_navi_webhook_secret(x_navi_token: Optional[str]) -> None:
    """Compara header X-Navi-Token com NAVI_WEBHOOK_SECRET via hmac.compare_digest.
    Se NAVI_WEBHOOK_SECRET não estiver setado, rejeita por default (fail-closed).
    Em dev, exportar NAVI_WEBHOOK_SECRET=dev pra liberar."""
    expected = os.getenv("NAVI_WEBHOOK_SECRET", "").strip()
    if not expected:
        raise HTTPException(503, "navi_webhook_secret_not_configured")
    if not x_navi_token or not hmac.compare_digest(x_navi_token.strip(), expected):
        raise HTTPException(401, "invalid_navi_webhook_token")


def _resolve_company_id_from_navi(payload: Dict[str, Any]) -> Optional[str]:
    """Webhook Navi pode entregar company_id em vários lugares dependendo da
    instância. Procura em ordem: payload.company_id, payload.metadata.company_id,
    payload.instance.company_id. Retorna None se não achar (caller decide 4xx)."""
    if not isinstance(payload, dict):
        return None
    direct = payload.get("company_id") or payload.get("companyId")
    if direct:
        return str(direct)
    meta = payload.get("metadata") or {}
    if isinstance(meta, dict):
        v = meta.get("company_id") or meta.get("companyId")
        if v:
            return str(v)
    instance = payload.get("instance") or {}
    if isinstance(instance, dict):
        v = instance.get("company_id") or instance.get("companyId")
        if v:
            return str(v)
    return None


@router.post("/api/connectors/navi/webhook")
@router.post("/connectors/navi/webhook")
async def navi_webhook(
    payload: Dict[str, Any] = Body(...),
    x_navi_token: Optional[str] = Header(default=None, alias="X-Navi-Token"),
):
    """Recebe payload do Evolution API/Navi. Cria/atualiza connector_session
    e faz append da mensagem ao history. Não dispatcha task aqui — fluxo de
    routing/enqueue ficará em PR seguinte (PRD Fundação F2)."""
    from src.api import _validate_connector_channel
    from src.services import connector_bus

    _check_navi_webhook_secret(x_navi_token)

    company_id = _resolve_company_id_from_navi(payload)
    if not company_id:
        raise HTTPException(400, "missing_company_id_in_navi_payload")

    # Evolution API: payload.data.key.remoteJid = JID do remetente.
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise HTTPException(400, "malformed_navi_data")
    key = data.get("key") or {}
    remote_jid = (key.get("remoteJid") or "").strip()
    if not remote_jid:
        raise HTTPException(400, "missing_remote_jid")

    external_id = remote_jid.split("@", 1)[0] or remote_jid
    external_name = data.get("pushName") or None
    connector_id = (payload.get("instance") or {}).get("instanceName") or os.getenv(
        "NAVI_INSTANCE", "default"
    )

    msg = data.get("message") or {}
    content = (
        msg.get("conversation")
        or (msg.get("extendedTextMessage") or {}).get("text")
        or msg.get("text")
        or ""
    ).strip()

    try:
        channel = _validate_connector_channel("whatsapp")
        session = connector_bus.get_or_open_session(
            company_id=company_id,
            channel=channel,
            connector_id=str(connector_id),
            external_id=external_id,
            external_name=external_name,
            external_meta={"remote_jid": remote_jid},
        )
        if content:
            connector_bus.append_history(
                session_id=session["id"],
                role="user",
                content=content,
                extra={"navi_message_id": key.get("id")},
            )
    except RuntimeError as e:
        logger.error("navi_webhook bus failure: %s", e)
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.exception("navi_webhook unexpected failure")
        raise HTTPException(500, str(e))

    return {
        "session_id": session["id"],
        "status": session.get("status"),
        "external_id": external_id,
        "had_content": bool(content),
    }


@router.get("/api/companies/{company_id}/connector-sessions")
@router.get("/companies/{company_id}/connector-sessions")
async def list_connector_sessions(
    request: Request,
    company_id: str,
    channel: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    """Lista sessões da company. Filtros opcionais por channel/status (slugs
    catalog-driven). Limit padrão 50."""
    from src.api import (
        supabase,
        get_authenticated_client,
        validate_jwt_company_id,
        _validate_connector_channel,
        _validate_connector_session_status,
    )
    from src.models import ConnectorSession

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        return []

    try:
        client = get_authenticated_client(request.state.token)
        q = (
            client.table("connector_sessions")
            .select("*")
            .eq("company_id", company_id)
            .order("updated_at", desc=True)
            .limit(max(1, min(int(limit), 200)))
        )
        if channel:
            q = q.eq("channel", _validate_connector_channel(channel))
        if status:
            q = q.eq("status", _validate_connector_session_status(status))
        res = q.execute()
        return [ConnectorSession(**row).to_zod_dict() for row in (res.data or [])]
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("list_connector_sessions failed: %s", e)
        raise HTTPException(500, str(e))


@router.post("/api/connector-sessions/{session_id}/reply")
@router.post("/connector-sessions/{session_id}/reply")
async def reply_connector_session(
    request: Request,
    session_id: str,
    payload: Dict[str, Any] = Body(...),
):
    """Humano responde manualmente a uma sessão. Faz append ao history como
    role='operator'. Não chama Navi outbound aqui (PRD F2 fará). Reply opaco
    só persiste a intenção."""
    from src.api import supabase, validate_jwt_company_id
    from src.services import connector_bus

    if not supabase:
        raise HTTPException(503, "supabase_required")

    sess = (
        supabase.table("connector_sessions")
        .select("company_id,status")
        .eq("id", session_id)
        .limit(1)
        .execute()
    )
    if not sess.data:
        raise HTTPException(404, "connector_session_not_found")

    validate_jwt_company_id(request.state.token, sess.data[0]["company_id"])

    content = str(payload.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "content_required")

    try:
        updated = connector_bus.append_history(
            session_id=session_id,
            role="operator",
            content=content,
            extra={"actor_user_id": getattr(request.state, "user_id", None)},
        )
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.exception("reply_connector_session failed")
        raise HTTPException(500, str(e))

    return {
        "session_id": session_id,
        "appended": True,
        "last_message_at": updated.get("last_message_at"),
    }
