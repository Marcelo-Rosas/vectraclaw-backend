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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request, Response

logger = logging.getLogger("api.connectors")

# W7 P0-9 (2026-05-18) — Catalog-driven routing. Sem const Python, sem
# import de AGENT_ID. Fluxo:
#   1) session["channel"] (já populado em get_or_open_session)
#   2) SELECT connector_channels WHERE slug=<channel>
#        → default_inbound_operation_type (FK pra operation_types_catalog)
#   3) SELECT operation_types_catalog WHERE id=<op_type>
#        → primary_agent_id (uuid)
# Trocar canal/op/agent vira UPDATE SQL — sem deploy. Regra Ouro #2 NO HARDCODE.
# Hardcode-auditor 2026-05-18: GO. Migration 20260518113229 setou whatsapp →
# freight-quotation (Caminho A Miro).
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

    # F2 — Criar task VectraClaw para o Oracle processar a mensagem.
    # Só dispatcha se houver conteúdo (ignora ack/delivery sem texto).
    task_id: Optional[str] = None
    if msg["content"]:
        task_id = _dispatch_inbound_task(
            company_id=company_id,
            session=session,
            msg=msg,
        )

    return {
        "session_id": session["id"],
        "status": session.get("status"),
        "external_id": msg["external_id"],
        "had_content": bool(msg["content"]),
        "task_id": task_id,
    }


def _resolve_inbound_routing(channel: str) -> Optional[Dict[str, Any]]:
    """W7 P0-9 — Lookup catalog-driven do roteamento default pra um canal inbound.

    Retorna `{"operation_type": str, "assigned_to_agent_id": Optional[uuid]}` ou
    None se o canal não tem default cadastrado (sinal pra caller skipar dispatch).

    Fluxo:
      1. SELECT connector_channels.default_inbound_operation_type WHERE slug=<channel>
      2. SELECT operation_types_catalog.primary_agent_id WHERE id=<op_type>

    Falhas de SELECT: log + None (best-effort, caller decide).
    Sem cache — `_dispatch_inbound_task` é chamado por webhook (não loop quente).
    """
    from src.api import supabase
    if not supabase or not channel:
        return None
    try:
        ch_res = (
            supabase.table("connector_channels")
            .select("default_inbound_operation_type")
            .eq("slug", channel)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.error("_resolve_inbound_routing: query channel=%s falhou: %s", channel, e)
        return None
    if not ch_res.data:
        logger.warning("_resolve_inbound_routing: canal %r não existe em connector_channels", channel)
        return None
    op_type = ch_res.data[0].get("default_inbound_operation_type")
    if not op_type:
        logger.info("_resolve_inbound_routing: canal %r sem default_inbound_operation_type — skip dispatch", channel)
        return None
    try:
        op_res = (
            supabase.table("operation_types_catalog")
            .select("primary_agent_id")
            .eq("id", op_type)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.error("_resolve_inbound_routing: query op_type=%s falhou: %s", op_type, e)
        return None
    if not op_res.data:
        logger.warning("_resolve_inbound_routing: op_type %r não existe em operation_types_catalog", op_type)
        return None
    return {
        "operation_type": op_type,
        "assigned_to_agent_id": op_res.data[0].get("primary_agent_id"),
    }


def _dispatch_inbound_task(
    *,
    company_id: str,
    session: Dict[str, Any],
    msg: Dict[str, Any],
) -> Optional[str]:
    """F2 + W7 P0-9 — Cria task VectraClaw + promove sessão + emite WS.

    Routing 100% catalog-driven (Regra Ouro #2). Vê `_resolve_inbound_routing`.
    Best-effort: falhas individuais (insert, promote, ws) logam e seguem.
    Retorna o task_id criado, ou None se rota não resolveu OU inserção falhou.
    """
    from src.api import supabase
    from src.services import connector_bus
    from src.ws_manager import manager as ws_manager

    if not supabase:
        logger.error("_dispatch_inbound_task: supabase indisponível")
        return None

    routing = _resolve_inbound_routing(session.get("channel") or "")
    if not routing:
        return None
    op_type = routing["operation_type"]
    assigned_agent = routing["assigned_to_agent_id"]

    content = msg["content"]
    external_label = (msg.get("external_name") or msg.get("external_id") or "").strip()
    title = f"WhatsApp: {external_label[:30]} — {content[:60]}".strip()
    now_iso = datetime.now(timezone.utc).isoformat()

    task_row = {
        "company_id": company_id,
        "title": title[:200],
        "description": content[:2000],
        "operation_type": op_type,
        "status": "queued",
        # W8 (2026-05-18) — `auto` deixa decision_engine rotear via routing_score
        # do operation_types_catalog. freight-quotation tem score 80 → vai pra CMA
        # → router resolve adapter via agent_adapter_configs → ClaudeCodeCliAgentClient
        # (após Mercator config preenchido via UI W4). Substitui harness hardcoded
        # do F2. Auditor 2026-05-18: zero hardcode novo, metadata-driven puro.
        "executor_type": "auto",
        "assigned_to_agent_id": assigned_agent,
        "input_json": {
            "source": "meta_whatsapp_webhook",
            "session_id": session["id"],
            "external_id": msg["external_id"],
            "external_name": msg.get("external_name"),
            "phone_number_id": msg["phone_number_id"],
            "message": content,
            "wamid": msg.get("message_id"),
        },
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    try:
        tres = supabase.table("tasks").insert(task_row).execute()
    except Exception as e:
        logger.exception("_dispatch_inbound_task: insert task falhou: %s", e)
        return None

    if not tres.data:
        logger.error("_dispatch_inbound_task: insert task retornou vazio")
        return None

    new_task = tres.data[0]
    new_task_id = str(new_task["id"])

    try:
        connector_bus.promote_to_processing(
            session_id=session["id"],
            task_id=new_task_id,
            routed_to_agent=assigned_agent,
            routing_score=50,
        )
    except Exception as e:
        logger.warning("_dispatch_inbound_task: promote_to_processing non-fatal: %s", e)

    # WS broadcast: front-end recebe task_updated e (best-effort) connector evento custom
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(ws_manager.emit_task_updated(company_id, new_task))
            loop.create_task(ws_manager.broadcast(
                company_id,
                {
                    "type": "connector_session_updated",
                    "payload": {
                        "session_id": session["id"],
                        "task_id": new_task_id,
                        "channel": session.get("channel"),
                        "external_id": msg["external_id"],
                    },
                },
            ))
    except Exception as e:
        logger.warning("_dispatch_inbound_task: WS broadcast non-fatal: %s", e)

    logger.info(
        "%s inbound dispatched company=%s session=%s task=%s op=%s agent=%s",
        session.get("channel"), company_id, session["id"], new_task_id, op_type, assigned_agent,
    )
    return new_task_id


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


async def _do_reply(
    request: Request,
    session_id: str,
    content: str,
) -> Dict[str, Any]:
    """Handler compartilhado por /api/connector-sessions/{id}/reply e
    /api/connectors/reply. Valida JWT vs company da session, faz append role=
    'operator', e dispara outbound real via connector_bus.reply (Meta Cloud API).

    Retorna {session_id, appended, delivered, last_message_at}. delivered=False
    significa que persistiu como histórico mas o envio externo falhou (caller
    pode reenviar). Nunca levanta — retorna detalhes pro front decidir.
    """
    from src.api import supabase, validate_jwt_company_id
    from src.services import connector_bus

    if not supabase:
        raise HTTPException(503, "supabase_required")

    sess_q = (
        supabase.table("connector_sessions")
        .select("*")
        .eq("id", session_id)
        .limit(1)
        .execute()
    )
    if not sess_q.data:
        raise HTTPException(404, "connector_session_not_found")
    session_row = sess_q.data[0]

    validate_jwt_company_id(request.state.token, session_row["company_id"])

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
        logger.exception("_do_reply append_history failed")
        raise HTTPException(500, str(e))

    delivered = False
    try:
        delivered = await connector_bus.reply(session_row, content)
    except Exception as e:
        logger.warning("_do_reply connector_bus.reply non-fatal: %s", e)

    return {
        "session_id": session_id,
        "appended": True,
        "delivered": delivered,
        "last_message_at": updated.get("last_message_at"),
    }


@router.post("/api/connector-sessions/{session_id}/reply")
@router.post("/connector-sessions/{session_id}/reply")
async def reply_connector_session(
    request: Request,
    session_id: str,
    payload: Dict[str, Any] = Body(...),
):
    """Humano responde manualmente a uma sessão. Append role='operator' +
    outbound real via Meta Cloud API (connector_bus.reply)."""
    content = str(payload.get("content") or payload.get("message") or "").strip()
    return await _do_reply(request, session_id, content)


@router.post("/api/connectors/reply")
@router.post("/connectors/reply")
async def reply_connector_body(
    request: Request,
    payload: Dict[str, Any] = Body(...),
):
    """Alias body-based (PRD seção 5). Espera {session_id, message} no body."""
    session_id = str(payload.get("session_id") or "").strip()
    content = str(payload.get("message") or payload.get("content") or "").strip()
    if not session_id:
        raise HTTPException(400, "session_id_required")
    return await _do_reply(request, session_id, content)
