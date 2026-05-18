"""
src.api_routes.connectors — W3 PRD Fundação Orchestration (W3.1 hotfix: Meta).

Endpoints de canais externos. Webhook WhatsApp roteado via **Meta Cloud API
oficial** (NÃO Evolution/Navi — decisão Marcelo 2026-05-17 + memory
adapter-catalog meta-whatsapp). Sessões persistem em vectraclip.connector_sessions;
orquestração via src/services/connector_bus.py.

Endpoints:
- GET  /api/connectors/whatsapp/webhook   meta_whatsapp_webhook_verify  (handshake hub.challenge)
- POST /api/connectors/whatsapp/webhook   meta_whatsapp_webhook         (mensagens inbound)
- GET  /api/companies/{company_id}/connector-sessions  list_connector_sessions
- POST /api/connector-sessions/{session_id}/reply      reply_connector_session

Auth do webhook: NÃO usa JWT Supabase (chamada vem da Meta). Validação:
- GET: compara `hub.verify_token` com `webhook_verify_token` do agent_adapter_configs
  do adapter meta-whatsapp (catalog-driven via adapter_catalog + field_values_json).
- POST: HMAC SHA-256 sobre body com `app_secret` (mesmo lugar, field novo W3.1).

Roteamento company_id: extrai `phone_number_id` do payload Meta
(entry[].changes[].value.metadata.phone_number_id) e busca em
agent_adapter_configs.field_values_json->>'phone_number_id'. Catalog-driven,
sem hardcode (Regra Ouro #2).

Endpoint `/api/connectors/whatsapp/webhook` precisa estar em `public_paths`
de src/api.py:769 (webhook externo nunca tem JWT Supabase).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request, Response

logger = logging.getLogger("api.connectors")
router = APIRouter(tags=["connectors"])

# Slug canônico do adapter Meta WhatsApp Cloud API no adapter_catalog.
# Não é hardcode de catálogo (slug é a CHAVE de lookup, não o dado).
META_WHATSAPP_ADAPTER_SLUG = "meta-whatsapp"


# ─────────────────────────────────────────────────────────────────────────────
# Lookup adapter config (catalog-driven, sem env)
# ─────────────────────────────────────────────────────────────────────────────

def _load_meta_adapter_targets() -> List[Dict[str, Any]]:
    """Lista (company_id, adapter_id) de TODA company que tem adapter
    meta-whatsapp ativo no catalog. Não carrega values ainda — quem itera
    decide ler company_adapter_values e/ou agent_adapter_configs."""
    from src.api import supabase
    if not supabase:
        return []
    try:
        adapters = (
            supabase.table("adapter_catalog")
            .select("id,company_id")
            .eq("slug", META_WHATSAPP_ADAPTER_SLUG)
            .eq("is_active", True)
            .execute()
        )
        return adapters.data or []
    except Exception as e:
        logger.error("_load_meta_adapter_targets failed: %s", e)
        return []


def _resolve_meta_config_for_company(
    company_id: str, adapter_id: str
) -> Optional[Dict[str, Any]]:
    """W5 — Resolve config Meta efetiva pra (company, adapter), aplicando
    lookup híbrido em CADA field individualmente:
      1. agent_adapter_configs.field_values_json[field] (override de exceção)
      2. company_adapter_values.field_values_json[field] (PRIMARY)
    Retorna dict {company_id, agent_id_override, phone_number_id, app_secret,
    webhook_verify_token, access_token, api_version} com valores JÁ
    desreferenciados (vault:// resolvido). Retorna None se phone_number_id
    não está setado (config incompleta — não dá pra rotear webhook)."""
    from src.api import (
        supabase,
        get_company_adapter_values,
        resolve_adapter_field_value,
    )
    if not supabase:
        return None

    company_values = get_company_adapter_values(company_id, adapter_id) or {}

    # Carrega agent overrides (0..N). Usamos só o PRIMEIRO se houver — múltiplos
    # agentes na mesma company usando mesmo Meta WhatsApp = mesma identidade.
    agent_values: Dict[str, Any] = {}
    agent_id_override: Optional[str] = None
    try:
        agent_cfgs = (
            supabase.table("agent_adapter_configs")
            .select("agent_id,field_values_json")
            .eq("company_id", company_id)
            .eq("adapter_id", adapter_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if agent_cfgs.data:
            row = agent_cfgs.data[0]
            agent_values = row.get("field_values_json") or {}
            agent_id_override = row.get("agent_id")
    except Exception as e:
        logger.warning("agent_adapter_configs lookup failed for company=%s: %s",
                       company_id, e)

    def _r(field: str) -> Optional[str]:
        return resolve_adapter_field_value(field, agent_values, company_values, company_id)

    resolved = {
        "company_id": company_id,
        "adapter_id": adapter_id,
        "agent_id_override": agent_id_override,
        "phone_number_id": _r("phone_number_id"),
        "app_secret": _r("app_secret"),
        "webhook_verify_token": _r("webhook_verify_token"),
        "access_token": _r("access_token"),
        "api_version": _r("api_version"),
    }
    if not resolved["phone_number_id"]:
        return None  # config incompleta — não roteia
    return resolved


def _find_meta_config_by_phone_number_id(phone_number_id: str) -> Optional[Dict[str, Any]]:
    """Resolve config Meta pela chave de roteamento `phone_number_id` (vem do
    payload Meta). Itera companies com adapter meta-whatsapp e devolve a que
    bate. W5 — usa resolver híbrido company→agent."""
    if not phone_number_id:
        return None
    pid_target = phone_number_id.strip()
    for adapter_row in _load_meta_adapter_targets():
        resolved = _resolve_meta_config_for_company(
            adapter_row["company_id"], adapter_row["id"]
        )
        if resolved and resolved["phone_number_id"].strip() == pid_target:
            return resolved
    return None


def _find_any_meta_config_with_verify_token(verify_token: str) -> Optional[Dict[str, Any]]:
    """Handshake GET vem ANTES do POST e Meta não envia phone_number_id no GET.
    Aceita qualquer config Meta cujo webhook_verify_token (resolvido via W5)
    bata. Multi-tenant com mesmo verify_token: primeiro match — admin deve
    usar tokens distintos."""
    if not verify_token:
        return None
    vt = verify_token.strip()
    for adapter_row in _load_meta_adapter_targets():
        resolved = _resolve_meta_config_for_company(
            adapter_row["company_id"], adapter_row["id"]
        )
        if not resolved:
            continue
        cfg_token = (resolved.get("webhook_verify_token") or "").strip()
        if cfg_token and hmac.compare_digest(cfg_token, vt):
            return resolved
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Meta webhook — GET (handshake) e POST (mensagens)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/connectors/whatsapp/webhook")
@router.get("/connectors/whatsapp/webhook")
async def meta_whatsapp_webhook_verify(
    hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
):
    """Handshake da Meta: subscribe verification. Meta App Dashboard chama
    GET ?hub.mode=subscribe&hub.verify_token=X&hub.challenge=Y esperando echo
    de Y se X bater com o verify_token salvo (em agent_adapter_configs.field_values_json)."""
    if hub_mode != "subscribe":
        raise HTTPException(400, "invalid_hub_mode")
    if not hub_verify_token or not hub_challenge:
        raise HTTPException(400, "missing_hub_params")
    cfg = _find_any_meta_config_with_verify_token(hub_verify_token)
    if not cfg:
        logger.warning("meta_whatsapp verify token mismatch (token first 4 chars: %s)",
                       hub_verify_token[:4])
        raise HTTPException(403, "verify_token_mismatch")
    logger.info("meta_whatsapp webhook verified for company_id=%s", cfg.get("company_id"))
    # Meta espera o challenge ECOADO EXATAMENTE como string (não JSON).
    return Response(content=hub_challenge, media_type="text/plain")


def _verify_meta_signature(body_bytes: bytes, signature_header: str, app_secret: str) -> bool:
    """X-Hub-Signature-256 = 'sha256=<hex_hmac>'. Compara via hmac.compare_digest."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = signature_header.split("=", 1)[1].strip()
    digest = hmac.new(
        app_secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, digest)


def _parse_meta_message(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extrai a primeira mensagem útil do payload Meta Cloud API.
    Schema: entry[].changes[].value.messages[] + value.metadata.phone_number_id
    + value.contacts[].profile.name. Retorna None se não houver mensagem (eg
    status/delivery updates)."""
    entries = payload.get("entry") or []
    if not entries:
        return None
    for entry in entries:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            phone_number_id = str(metadata.get("phone_number_id") or "").strip()
            messages = value.get("messages") or []
            if not messages:
                continue
            msg = messages[0]
            text_obj = msg.get("text") or {}
            content = str(
                text_obj.get("body")
                or (msg.get("image") or {}).get("caption")
                or (msg.get("document") or {}).get("caption")
                or ""
            ).strip()
            contacts = value.get("contacts") or []
            external_name = None
            if contacts:
                external_name = ((contacts[0].get("profile") or {}).get("name")) or None
            return {
                "phone_number_id": phone_number_id,
                "external_id": str(msg.get("from") or "").strip(),
                "external_name": external_name,
                "content": content,
                "message_id": msg.get("id"),
                "msg_type": msg.get("type") or "text",
                "timestamp": msg.get("timestamp"),
            }
    return None


@router.post("/api/connectors/whatsapp/webhook")
@router.post("/connectors/whatsapp/webhook")
async def meta_whatsapp_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None, alias="X-Hub-Signature-256"),
):
    """Recebe payload Meta. Valida HMAC com app_secret do adapter config da
    company-alvo (resolvida por phone_number_id). Cria/atualiza connector_session
    + append message ao history. Não dispatcha task aqui (W3 F2)."""
    from src.services import connector_bus

    body_bytes = await request.body()
    if not body_bytes:
        raise HTTPException(400, "empty_body")
    try:
        import json
        payload = json.loads(body_bytes)
    except Exception:
        raise HTTPException(400, "invalid_json")

    msg = _parse_meta_message(payload)
    if not msg:
        # Status/delivery update — Meta exige 200 OK pra não retry.
        logger.info("meta_whatsapp webhook: no message in payload (likely status update)")
        return {"received": True, "had_message": False}

    if not msg["phone_number_id"]:
        raise HTTPException(400, "missing_phone_number_id")
    if not msg["external_id"]:
        raise HTTPException(400, "missing_message_from")

    cfg = _find_meta_config_by_phone_number_id(msg["phone_number_id"])
    if not cfg:
        logger.warning("meta_whatsapp webhook: no adapter config for phone_number_id=%s",
                       msg["phone_number_id"])
        raise HTTPException(404, "no_adapter_config_for_phone_number_id")

    # W5 — cfg vem JÁ resolvido pelo _resolve_meta_config_for_company:
    # phone_number_id, app_secret, webhook_verify_token, etc desreferenciados
    # via resolver híbrido (agent override → company primary → None).
    app_secret = str(cfg.get("app_secret") or "").strip()
    if not app_secret:
        raise HTTPException(503, "app_secret_not_configured_for_company")
    if not x_hub_signature_256 or not _verify_meta_signature(
        body_bytes, x_hub_signature_256, app_secret
    ):
        raise HTTPException(401, "invalid_meta_signature")

    company_id = str(cfg.get("company_id") or "").strip()
    if not company_id:
        raise HTTPException(500, "adapter_config_missing_company_id")

    try:
        session = connector_bus.get_or_open_session(
            company_id=company_id,
            channel="whatsapp",
            connector_id=msg["phone_number_id"],  # phone_number_id é a identidade do business
            external_id=msg["external_id"],
            external_name=msg["external_name"],
            external_meta={"wamid": msg["message_id"], "msg_type": msg["msg_type"]},
        )
        if msg["content"]:
            connector_bus.append_history(
                session_id=session["id"],
                role="user",
                content=msg["content"],
                extra={"wamid": msg["message_id"], "timestamp": msg["timestamp"]},
            )
    except RuntimeError as e:
        logger.error("meta_whatsapp_webhook bus failure: %s", e)
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.exception("meta_whatsapp_webhook unexpected failure")
        raise HTTPException(500, str(e))

    return {
        "session_id": session["id"],
        "status": session.get("status"),
        "external_id": msg["external_id"],
        "had_content": bool(msg["content"]),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Lista + reply (autenticados via JWT do middleware)
# ─────────────────────────────────────────────────────────────────────────────

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
    role='operator'. NÃO chama Meta outbound aqui (PRD F2 fará via meta_client).
    Reply opaco persiste só a intenção."""
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
