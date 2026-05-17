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
