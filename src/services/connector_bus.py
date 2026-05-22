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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Vectra.connector_bus")

# Ring buffer cap para history. Configurável via env pra evitar magic number.
# P6 do CODE-PATTERNS: aceito porque vectraclip.system_settings não existe ainda.
# Quando criar, migrar pra catalog-driven via VEC futura.
CONNECTOR_HISTORY_RING_SIZE = int(os.getenv("CONNECTOR_HISTORY_RING_SIZE", "50"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pg_dict(value: Any) -> Dict[str, Any]:
    """Coerce PostgREST JSON cell to dict (basedpyright-safe)."""
    if isinstance(value, dict):
        return value
    return {}


def _pg_row(value: Any) -> Dict[str, Any]:
    """Coerce PostgREST table row to dict."""
    if isinstance(value, dict):
        return value
    raise RuntimeError("connector_bus: expected dict row from PostgREST")


def _pg_history(value: Any) -> List[Dict[str, Any]]:
    """Coerce JSONB history ring buffer to list of message dicts."""
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            out.append(item)
    return out


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
        row = _pg_row(existing.data[0])
        # Atualiza external_name/meta se vierem novos (refresh barato).
        updates: Dict[str, Any] = {}
        if external_name and external_name != row.get("external_name"):
            updates["external_name"] = external_name
        if external_meta:
            updates["external_meta"] = {**_pg_dict(row.get("external_meta")), **external_meta}
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
    return _pg_row(res.data[0])


def append_history(
    *,
    session_id: str,
    role: str,
    content: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Faz append ao ring buffer JSONB de history. Trunca pra
    CONNECTOR_HISTORY_RING_SIZE últimas trocas. Atualiza last_message + last_message_at.
    Mensagens do usuário (`role=user`) também atualizam last_inbound_at (janela Meta 24h).
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

    history = _pg_history(current.data[0].get("history"))
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
    if role == "user":
        update_row["last_inbound_at"] = entry["ts"]
    res = supabase.table("connector_sessions").update(update_row).eq("id", session_id).execute()
    if not res.data:
        logger.warning("connector_session append_history returned empty for %s", session_id)
        return {"id": session_id, **update_row}
    return _pg_row(res.data[0])


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
    return _pg_row(res.data[0])


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
    return _pg_row(res.data[0])


# ─────────────────────────────────────────────────────────────────────────────
# Outbound (reply) — F2 do PRD Fundação Orchestration
# ─────────────────────────────────────────────────────────────────────────────

_META_GRAPH_BASE = "https://graph.facebook.com"
_INSTAGRAM_GRAPH_BASE = "https://graph.instagram.com"


def _build_instagram_messages_url(
    access_token: str,
    api_version: str,
    instagram_account_id: str,
) -> str:
    """URL de envio DM Instagram.

    - Token ``IGAA…`` (Instagram API com Instagram Login): ``graph.instagram.com/.../me/messages``
    - Token ``EAA…`` / Page (Messenger legado): ``graph.facebook.com/.../{ig_account_id}/messages``
    """
    ver = (api_version or "v21.0").strip()
    if not ver.startswith("v"):
        ver = f"v{ver}"
    if access_token.strip().upper().startswith("IG"):
        return f"{_INSTAGRAM_GRAPH_BASE}/{ver}/me/messages"
    ig_id = instagram_account_id.strip()
    return f"{_META_GRAPH_BASE}/{ver}/{ig_id}/messages"


async def reply(
    session: Dict[str, Any],
    message: str,
    *,
    template_name: Optional[str] = None,
    template_params: Optional[List[str]] = None,
    append_role: Optional[str] = "agent",
) -> bool:
    """Envia `message` de volta ao contato externo da `session`.

    Best-effort: loga e devolve False em falha; nunca re-raise. Caller decide
    o que fazer com False (manter aberta, marcar errored, etc.).

    Args:
        append_role: role pra append_history pós-envio. Default 'agent' (contrato
            Clip — handoff CONNECTOR-SESSIONS-AGENT-DISPATCH 2026-05-18).
            **Passe `None` se o caller já gravou a entry no history** (evita
            duplicação operator+assistant — Bug #2 do handoff). Caller típico
            que passa None: POST /reply manual em api_routes/connectors.py:_do_reply
            (já fez append role='operator' antes de chamar reply).

    Roteamento por session.channel:
      - 'whatsapp' → Meta Cloud API (resolve creds via adapter_catalog).
                     Se fora da janela conversacional (session_window_hours do
                     adapter), envia TEMPLATE em vez de free text. Template
                     resolvido em ordem: arg template_name → agent_adapter_configs.
                     template_id → fail (W11).
      - outros     → log + False (delega ao caller criar task pro canal certo).
                     Dispatch table por channel virá em W12.
    """
    channel = (session.get("channel") or "").strip()
    if channel == "whatsapp":
        return await _reply_whatsapp_meta(
            session, message,
            template_name_override=template_name,
            template_params=template_params,
            append_role=append_role,
        )
    if channel == "instagram":
        return await _reply_instagram_meta(session, message, append_role=append_role)
    logger.warning("connector_bus.reply: canal '%s' não suportado (W12: dispatch table)", channel)
    return False


async def _reply_whatsapp_meta(
    session: Dict[str, Any],
    message: str,
    *,
    template_name_override: Optional[str] = None,
    template_params: Optional[List[str]] = None,
    append_role: Optional[str] = "agent",
) -> bool:
    """Envia mensagem via Meta Cloud API. W11 PR1: decisão free text vs template
    baseada em janela conversacional (session_window_hours do adapter).

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

    # W11 PR1 — janela conversacional check (auditor P1.1 + P2.1)
    # W11 fix (2026-05-18) — análise NAVI driver-qualification revelou que
    # templates pertencem ao workflow_step (W14), não ao agente. E templates
    # Vectra são todos MARKETING — sem opt-in registrado, Meta penaliza/rejeita
    # reply emergencial via template. Estratégia:
    #   - DENTRO janela: free text (continua igual)
    #   - FORA janela SEM override explícito: NÃO tenta auto-template; log warning
    #     e retorna False. Caller decide (criar task humana / usar W14 cadence_dispatcher
    #     com binding explícito em workflow_steps.ferramentas + opt-in registrado).
    company_id = session.get("company_id")
    adapter_id = cfg.get("adapter_id")
    in_window = _is_in_session_window(session, company_id, adapter_id)

    if not in_window and not template_name_override:
        window_h = resolve_session_window_hours_safe(company_id, adapter_id)
        logger.warning(
            "connector_bus._reply_whatsapp_meta: FORA janela %dh — reply automático "
            "bloqueado (templates MARKETING sem opt-in seriam rejeitados pela Meta). "
            "session=%s. Caminho correto: criar task humana OU W14 cadence_dispatcher "
            "com event_key + binding explícito em workflow_steps.ferramentas.",
            window_h, session.get("id"),
        )
        return False

    use_template = bool(template_name_override)
    if use_template:
        # Placeholders do template são dados estruturados — nunca reutilizar body free-text.
        params = template_params if template_params is not None else []
        payload = _build_template_payload(to_digits, template_name_override, params)
    else:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_digits,
            "type": "text",
            "text": {"preview_url": False, "body": message[:4096]},
        }

    url = f"{_META_GRAPH_BASE}/{api_version}/{phone_number_id}/messages"
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

    # Append da resposta no history pra trilha completa.
    # PR2 fix Bug #2 (2026-05-18): role hardcoded 'assistant' era anti-padrão
    # — contrato Clip (VectraClip/src/types/api.ts) espera 'agent' pra resposta
    # de executor. Quando append_role=None, caller já fez append (ex: _do_reply
    # gravou 'operator' antes); skipar evita duplicação operator+assistant
    # (era o eco visível no histórico antes do fix).
    if append_role is None:
        logger.debug(
            "connector_bus._reply_whatsapp_meta: append_role=None — caller já gravou history, skip"
        )
    else:
        try:
            delivery_kind = "meta_template" if use_template else "meta_cloud_api"
            history_extra: Dict[str, Any] = {
                "channel": "whatsapp",
                "delivery": delivery_kind,
            }
            if use_template:
                # W11 fix: só template_name_override (W14 vai expandir via workflow_steps.ferramentas)
                history_extra["template_name"] = template_name_override
            append_history(
                session_id=session["id"],
                role=append_role,
                content=message,
                extra=history_extra,
            )
        except Exception as e:
            logger.warning("connector_bus.reply append_history non-fatal: %s", e)

    logger.info(
        "connector_bus._reply_whatsapp_meta: sent session=%s to=%s len=%d kind=%s",
        session.get("id"), to_digits, len(message),
        ("template" if use_template else "text"),
    )
    return True


async def _reply_instagram_meta(
    session: Dict[str, Any],
    message: str,
    *,
    append_role: Optional[str] = "agent",
) -> bool:
    """Envia DM via Instagram Messaging API (Graph). connector_id da session =
    instagram_account_id (set no webhook inbound)."""
    instagram_account_id = (session.get("connector_id") or "").strip()
    recipient_id = (session.get("external_id") or "").strip()
    if not instagram_account_id or not recipient_id or not message.strip():
        logger.warning(
            "connector_bus._reply_instagram_meta: missing fields ig=%s to=%s",
            bool(instagram_account_id), bool(recipient_id),
        )
        return False

    try:
        from src.api_routes.connectors import _find_instagram_config_by_account_id
    except Exception as e:
        logger.error("connector_bus: import instagram resolver falhou: %s", e)
        return False

    cfg = _find_instagram_config_by_account_id(instagram_account_id)
    if not cfg:
        logger.warning(
            "connector_bus._reply_instagram_meta: no adapter for instagram_account_id=%s",
            instagram_account_id,
        )
        return False

    access_token = (cfg.get("access_token") or "").strip()
    api_version = (cfg.get("api_version") or "v21.0").strip()
    if not access_token:
        logger.warning(
            "connector_bus._reply_instagram_meta: access_token vazio ig=%s",
            instagram_account_id,
        )
        return False

    company_id = session.get("company_id")
    adapter_id = cfg.get("adapter_id")
    if not _is_in_session_window(session, company_id, adapter_id):
        window_h = resolve_session_window_hours_safe(company_id, adapter_id)
        logger.warning(
            "connector_bus._reply_instagram_meta: FORA janela %dh — reply bloqueado session=%s",
            window_h, session.get("id"),
        )
        return False

    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message[:1000]},
    }
    url = _build_instagram_messages_url(access_token, api_version, instagram_account_id)
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
                "connector_bus._reply_instagram_meta: API %s url=%s ig=%s body=%s",
                resp.status_code, url, instagram_account_id, resp.text[:500],
            )
            return False
    except Exception as e:
        logger.exception("connector_bus._reply_instagram_meta HTTP falhou: %s", e)
        return False

    if append_role is not None:
        try:
            append_history(
                session_id=session["id"],
                role=append_role,
                content=message,
                extra={"channel": "instagram", "delivery": "instagram_graph_api"},
            )
        except Exception as e:
            logger.warning("connector_bus._reply_instagram_meta append_history: %s", e)

    logger.info(
        "connector_bus._reply_instagram_meta: sent session=%s url=%s to=%s len=%d",
        session.get("id"), url, recipient_id, len(message),
    )
    return True


# ─────────────────────────────────────────────────────────────────────────────
# W11 PR1 helpers — janela conversacional Meta + template fallback
# ─────────────────────────────────────────────────────────────────────────────

def _is_in_session_window(
    session: Dict[str, Any],
    company_id: Optional[str],
    adapter_id: Optional[str],
) -> bool:
    """True se NOW < last_inbound_at + session_window_hours do adapter.

    last_inbound_at vazio (sessão sem inbound do user) ⇒ FORA da janela
    (Meta exige template message pra iniciar conversa).
    """
    last_inbound_raw = session.get("last_inbound_at")
    if not last_inbound_raw:
        return False
    try:
        # tolera string ISO ou datetime
        if isinstance(last_inbound_raw, str):
            # remove possíveis "Z" → +00:00 pro fromisoformat
            iso = last_inbound_raw.replace("Z", "+00:00")
            last_inbound = datetime.fromisoformat(iso)
        else:
            last_inbound = last_inbound_raw
        if last_inbound.tzinfo is None:
            last_inbound = last_inbound.replace(tzinfo=timezone.utc)
    except Exception:
        logger.warning("last_inbound_at malformed (%s) — assumindo fora janela",
                       last_inbound_raw)
        return False

    window_h = resolve_session_window_hours_safe(company_id, adapter_id)
    return datetime.now(timezone.utc) < (last_inbound + timedelta(hours=window_h))


def resolve_session_window_hours_safe(
    company_id: Optional[str], adapter_id: Optional[str], default: int = 24,
) -> int:
    """Wrapper safe pra service.whatsapp_template_sync.resolve_session_window_hours."""
    if not company_id or not adapter_id:
        return default
    try:
        from src.services.whatsapp_template_sync import resolve_session_window_hours
        return resolve_session_window_hours(company_id, adapter_id, default=default)
    except Exception as e:
        logger.warning("resolve_session_window_hours failed (using default %d): %s",
                       default, e)
        return default


def _build_template_payload(
    to_digits: str, template_name: str, params: List[str],
) -> Dict[str, Any]:
    """Payload Meta API type=template. Body params como text components.
    Header/footer custom não suportados aqui (W12 vai estender)."""
    body_components: List[Dict[str, Any]] = []
    if params:
        body_components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": str(p)} for p in params],
        })
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_digits,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "pt_BR"},  # W12: resolver via whatsapp_templates.language
            "components": body_components,
        },
    }