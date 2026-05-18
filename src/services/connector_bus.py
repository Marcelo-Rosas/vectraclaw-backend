"""W3 — Connector Bus: orquestra sessões de canais externos (WhatsApp via Navi,
email via Hermes, etc.) sobre vectraclip.connector_sessions.

Side-effects: DB writes (connector_sessions INSERT/UPDATE).

Responsabilidades:
- get_or_open_session: encontra session aberta pra (company, channel, external_id)
  ou cria uma nova. Único INSERT racing-safe via uq_connector_sessions_open_per_contact.
- append_history: faz append truncado ao ring buffer JSONB (size via env).
- promote_to_processing: atribui task ativa quando sessão vira task VectraClaw.
- close_session: marca closed + opcionalmente closed_at agora.

Não acopla ao adapter de canal específico (Evolution API, Cloud API, IMAP, etc).
Recebe payloads já normalizados {role, content, ts}.

Status/channel são strings validadas contra catalog (regra #2 NO HARDCODE):
- vectraclip.connector_session_statuses (5 slugs: open/waiting_agent/processing/closed/errored)
- vectraclip.connector_channels (5 slugs: whatsapp/email/telegram/api/other)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Vectra.connector_bus")

# Ring buffer cap para history. Configurável via env pra evitar magic number.
# P6 do CODE-PATTERNS: aceito porque vectraclip.system_settings não existe ainda.
# Quando criar, migrar pra catalog-driven via VEC futura.
CONNECTOR_HISTORY_RING_SIZE = int(os.getenv("CONNECTOR_HISTORY_RING_SIZE", "50"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_or_open_session(
    *,
    company_id: str,
    channel: str,
    connector_id: str,
    external_id: str,
    external_name: Optional[str] = None,
    external_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Encontra sessão aberta (status in open/waiting_agent/processing) ou cria
    nova. Levanta RuntimeError se supabase indisponível (chamada de daemon/API
    real precisa de DB)."""
    from src.api import supabase
    if not supabase:
        raise RuntimeError("supabase_unavailable")

    open_statuses = ("open", "waiting_agent", "processing")
    existing = (
        supabase.table("connector_sessions")
        .select("*")
        .eq("company_id", company_id)
        .eq("channel", channel)
        .eq("external_id", external_id)
        .in_("status", list(open_statuses))
        .limit(1)
        .execute()
    )
    if existing.data:
        row = existing.data[0]
        # Atualiza external_name/meta se vierem novos (refresh barato).
        updates: Dict[str, Any] = {}
        if external_name and external_name != row.get("external_name"):
            updates["external_name"] = external_name
        if external_meta:
            updates["external_meta"] = {**(row.get("external_meta") or {}), **external_meta}
        if updates:
            updates["updated_at"] = _now_iso()
            supabase.table("connector_sessions").update(updates).eq("id", row["id"]).execute()
            row.update(updates)
        return row

    row = {
        "company_id": company_id,
        "channel": channel,
        "connector_id": connector_id,
        "external_id": external_id,
        "external_name": external_name,
        "external_meta": external_meta or {},
        "status": "open",
        "history": [],
        "opened_at": _now_iso(),
    }
    res = supabase.table("connector_sessions").insert(row).execute()
    if not res.data:
        raise RuntimeError("connector_session_insert_failed")
    logger.info(
        "connector_session opened company=%s channel=%s external=%s id=%s",
        company_id, channel, external_id, res.data[0]["id"],
    )
    return res.data[0]


def append_history(
    *,
    session_id: str,
    role: str,
    content: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Faz append ao ring buffer JSONB de history. Trunca pra
    CONNECTOR_HISTORY_RING_SIZE últimas trocas. Atualiza last_message + last_message_at.
    Best-effort: loga warning se falhar mas não levanta (caller já tem msg)."""
    from src.api import supabase
    if not supabase:
        raise RuntimeError("supabase_unavailable")

    current = (
        supabase.table("connector_sessions")
        .select("history")
        .eq("id", session_id)
        .limit(1)
        .execute()
    )
    if not current.data:
        raise RuntimeError(f"connector_session_not_found: {session_id}")

    history: List[Dict[str, Any]] = current.data[0].get("history") or []
    entry = {"role": role, "content": content, "ts": _now_iso()}
    if extra:
        entry.update(extra)
    history.append(entry)
    if len(history) > CONNECTOR_HISTORY_RING_SIZE:
        history = history[-CONNECTOR_HISTORY_RING_SIZE:]

    update_row = {
        "history": history,
        "last_message": content[:500],
        "last_message_at": entry["ts"],
        "updated_at": entry["ts"],
    }
    res = supabase.table("connector_sessions").update(update_row).eq("id", session_id).execute()
    if not res.data:
        logger.warning("connector_session append_history returned empty for %s", session_id)
        return {"id": session_id, **update_row}
    return res.data[0]


def promote_to_processing(
    *,
    session_id: str,
    task_id: str,
    routed_to_agent: Optional[str] = None,
    routing_score: Optional[int] = None,
) -> Dict[str, Any]:
    """Atribui task ativa + status='processing' + opcionalmente agente roteado."""
    from src.api import supabase
    if not supabase:
        raise RuntimeError("supabase_unavailable")

    update_row: Dict[str, Any] = {
        "active_task_id": task_id,
        "status": "processing",
        "updated_at": _now_iso(),
    }
    if routed_to_agent:
        update_row["routed_to_agent"] = routed_to_agent
    if routing_score is not None:
        update_row["routing_score"] = max(0, min(100, int(routing_score)))

    res = supabase.table("connector_sessions").update(update_row).eq("id", session_id).execute()
    if not res.data:
        raise RuntimeError(f"connector_session_promote_failed: {session_id}")
    logger.info("connector_session promoted id=%s task=%s agent=%s",
                session_id, task_id, routed_to_agent)
    return res.data[0]


def close_session(*, session_id: str, status: str = "closed") -> Dict[str, Any]:
    """Fecha sessão (status default 'closed', alternativa: 'errored')."""
    from src.api import supabase
    if not supabase:
        raise RuntimeError("supabase_unavailable")
    now = _now_iso()
    update_row = {
        "status": status,
        "closed_at": now,
        "updated_at": now,
    }
    res = supabase.table("connector_sessions").update(update_row).eq("id", session_id).execute()
    if not res.data:
        raise RuntimeError(f"connector_session_close_failed: {session_id}")
    return res.data[0]


# ─────────────────────────────────────────────────────────────────────────────
# Outbound (reply) — F2 do PRD Fundação Orchestration
# ─────────────────────────────────────────────────────────────────────────────

_META_GRAPH_BASE = "https://graph.facebook.com"


async def reply(session: Dict[str, Any], message: str) -> bool:
    """Envia `message` de volta ao contato externo da `session`.

    Best-effort: loga e devolve False em falha; nunca re-raise. Caller decide
    o que fazer com False (manter aberta, marcar errored, etc.).

    Roteamento por session.channel:
      - 'whatsapp' → Meta Cloud API (resolve creds via adapter_catalog)
      - outros     → log + False (delega ao caller criar task pro canal certo)
    """
    channel = (session.get("channel") or "").strip()
    if channel == "whatsapp":
        return await _reply_whatsapp_meta(session, message)
    logger.warning("connector_bus.reply: canal '%s' não suportado", channel)
    return False


async def _reply_whatsapp_meta(session: Dict[str, Any], message: str) -> bool:
    """Envia texto via Meta Cloud API.

    Resolve credenciais via _find_meta_config_by_phone_number_id (catalog-driven,
    com vault:// desreferenciado). connector_id da session deve ser o
    phone_number_id Meta (set no webhook inbound).
    """
    phone_number_id = (session.get("connector_id") or "").strip()
    to_digits = (session.get("external_id") or "").strip()
    if not phone_number_id or not to_digits or not message.strip():
        logger.warning(
            "connector_bus._reply_whatsapp_meta: missing fields phone=%s to=%s msg_empty=%s",
            bool(phone_number_id), bool(to_digits), not message.strip(),
        )
        return False

    try:
        from src.api_routes.connectors import _find_meta_config_by_phone_number_id
    except Exception as e:
        logger.error("connector_bus: import resolver falhou: %s", e)
        return False

    cfg = _find_meta_config_by_phone_number_id(phone_number_id)
    if not cfg:
        logger.warning(
            "connector_bus._reply_whatsapp_meta: no adapter config for phone_number_id=%s",
            phone_number_id,
        )
        return False

    access_token = (cfg.get("access_token") or "").strip()
    api_version = (cfg.get("api_version") or "v25.0").strip()
    if not access_token:
        logger.warning("connector_bus._reply_whatsapp_meta: access_token vazio para phone=%s", phone_number_id)
        return False

    url = f"{_META_GRAPH_BASE}/{api_version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_digits,
        "type": "text",
        "text": {"preview_url": False, "body": message[:4096]},
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            logger.error(
                "connector_bus: Meta API %s para phone=%s body=%s",
                resp.status_code, phone_number_id, resp.text[:500],
            )
            return False
    except Exception as e:
        logger.exception("connector_bus._reply_whatsapp_meta HTTP falhou: %s", e)
        return False

    # Append da resposta no history pra trilha completa
    try:
        append_history(
            session_id=session["id"],
            role="assistant",
            content=message,
            extra={"channel": "whatsapp", "delivery": "meta_cloud_api"},
        )
    except Exception as e:
        logger.warning("connector_bus.reply append_history non-fatal: %s", e)

    logger.info(
        "connector_bus._reply_whatsapp_meta: sent session=%s to=%s len=%d",
        session.get("id"), to_digits, len(message),
    )
    return True
