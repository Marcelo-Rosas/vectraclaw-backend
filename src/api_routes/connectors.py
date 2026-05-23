"""
src.api_routes.connectors — W3 PRD Fundação Orchestration (W3.1 hotfix: Meta).

Endpoints de canais externos. Webhook WhatsApp roteado via **Meta Cloud API
oficial** (NÃO Evolution/Navi — decisão Marcelo 2026-05-17 + memory
adapter-catalog meta-whatsapp). Sessões persistem em vectraclip.connector_sessions;
orquestração via src/services/connector_bus.py.

Endpoints:
- GET  /api/connectors/whatsapp/webhook   meta_whatsapp_webhook_verify  (handshake hub.challenge)
- POST /api/connectors/whatsapp/webhook   meta_whatsapp_webhook         (mensagens inbound)
- GET  /api/connectors/instagram/webhook  meta_instagram_webhook_verify (handshake hub.challenge)
- POST /api/connectors/instagram/webhook  meta_instagram_webhook        (DM inbound Instagram)
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
# Wizard POST /adapters/from-profile usa _slugify_adapter_slug → snake_case (meta_instagram).
# Seeds/migrations legados podem usar kebab-case (meta-instagram). Aceitar ambos no lookup.
META_INSTAGRAM_ADAPTER_SLUGS = ("meta_instagram", "meta-instagram")

_CONNECTOR_REPLY_BLOCKED_ROLES = ["viewer"]


def _schedule_connector_session_ws(
    company_id: str,
    session_id: str,
    **extra: Any,
) -> None:
    """Best-effort WS: front invalida lista de sessões (payload mínimo)."""
    try:
        import asyncio
        from src import ws_manager

        payload: Dict[str, Any] = {"session_id": session_id, **extra}
        message = {"type": "connector_session_updated", "payload": payload}
        loop = asyncio.get_running_loop()
        loop.create_task(ws_manager.broadcast(company_id, message))
    except Exception as e:
        logger.warning("_schedule_connector_session_ws non-fatal: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# Lookup adapter config (catalog-driven, sem env)
# ─────────────────────────────────────────────────────────────────────────────

def _load_meta_adapter_targets(adapter_slug: str) -> List[Dict[str, Any]]:
    """Lista (company_id, adapter_id) de TODA company que tem adapter Meta
    ativo no catalog (slug meta-whatsapp ou meta-instagram)."""
    from src.api import supabase
    if not supabase:
        return []
    try:
        adapters = (
            supabase.table("adapter_catalog")
            .select("id,company_id")
            .eq("slug", adapter_slug)
            .eq("is_active", True)
            .execute()
        )
        return adapters.data or []  # pyright: ignore[reportReturnType]
    except Exception as e:
        logger.error("_load_meta_adapter_targets slug=%s failed: %s", adapter_slug, e)
        return []


def _load_meta_instagram_adapter_targets() -> List[Dict[str, Any]]:
    """Adapters Instagram ativos (meta_instagram do wizard ou meta-instagram legado)."""
    rows: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for slug in META_INSTAGRAM_ADAPTER_SLUGS:
        for row in _load_meta_adapter_targets(slug):
            adapter_id = str(row.get("id") or "")
            if adapter_id and adapter_id not in seen_ids:
                seen_ids.add(adapter_id)
                rows.append(row)
    return rows


def _resolve_meta_config_for_company(
    company_id: str,
    adapter_id: str,
    *,
    routing_field: str = "phone_number_id",
    require_routing_field: bool = True,
) -> Optional[Dict[str, Any]]:
    """W5 — Resolve config Meta efetiva pra (company, adapter), aplicando
    lookup híbrido em CADA field individualmente:
      1. agent_adapter_configs.field_values_json[field] (override de exceção)
      2. company_adapter_values.field_values_json[field] (PRIMARY)
    Retorna dict com routing_field (phone_number_id ou instagram_account_id),
    app_secret, webhook_verify_token, access_token, api_version.
    Retorna None se require_routing_field=True e routing_field não está setado.
    Handshake GET usa require_routing_field=False (só precisa webhook_verify_token)."""
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
            agent_values = row.get("field_values_json") or {}  # pyright: ignore[reportAssignmentType]
            agent_id_override = row.get("agent_id")  # pyright: ignore[reportAssignmentType]
    except Exception as e:
        logger.warning("agent_adapter_configs lookup failed for company=%s: %s",
                       company_id, e)

    def _r(field: str) -> Optional[str]:
        return resolve_adapter_field_value(field, agent_values, company_values, company_id)

    routing_value = _r(routing_field)
    resolved = {
        "company_id": company_id,
        "adapter_id": adapter_id,
        "agent_id_override": agent_id_override,
        routing_field: routing_value,
        "phone_number_id": _r("phone_number_id"),
        "instagram_account_id": _r("instagram_account_id"),
        "app_secret": _r("app_secret"),
        # Wizard opcional: secret do app Instagram API (produto 182784…), distinta do app pai.
        "meta_instagram": _r("meta_instagram"),
        "webhook_verify_token": _r("webhook_verify_token"),
        "access_token": _r("access_token"),
        "api_version": _r("api_version"),
    }
    if require_routing_field and not routing_value:
        return None
    return resolved


def _company_meta_hmac_secrets(company_id: str) -> List[str]:
    """Secrets 32-char em company_secrets (nomes meta/whatsapp/instagram)."""
    from src.api import supabase, resolve_secret_ref

    if not supabase or not company_id:
        return []
    out: List[str] = []
    try:
        rows = (
            supabase.schema("vectraclip")
            .table("company_secrets")
            .select("name,vault_secret_id")
            .eq("company_id", company_id)
            .execute()
        )
        for row in rows.data or []:
            name = str(row.get("name") or "").lower()
            if any(
                skip in name
                for skip in ("verify_token", "phone_number")
            ):
                continue
            # access_token no nome só entra se for 32 hex (secret Meta colado no campo errado).
            if "access_token" in name:
                ref = f"vault://{row.get('vault_secret_id')}"
                plain_at = _normalize_meta_app_secret(
                    resolve_secret_ref(ref, company_id) or ""
                )
                if plain_at and plain_at not in out:
                    out.append(plain_at)
                continue
            if not any(tok in name for tok in ("app_secret", "meta_instagram")):
                continue
            ref = f"vault://{row.get('vault_secret_id')}"
            plain = _normalize_meta_app_secret(
                resolve_secret_ref(ref, company_id) or ""
            )
            if plain and plain not in out:
                out.append(plain)
    except Exception as e:
        logger.warning("company_meta_hmac_secrets lookup failed: %s", e)
    return out


def _meta_app_secret_env_overrides() -> List[str]:
    """Override opcional (docker .env) — 32 hex, ex. secret do app pai no painel Meta."""
    import os

    out: List[str] = []
    for key in (
        "VECTRACLAW_META_APP_SECRET",
        "META_APP_SECRET",
        "META_INSTAGRAM_APP_SECRET",
    ):
        v = _normalize_meta_app_secret(os.getenv(key, ""))
        if v and v not in out:
            out.append(v)
    return out


def _instagram_hmac_secret_candidates(cfg: Dict[str, Any]) -> List[str]:
    """Secrets para validar X-Hub-Signature-256.

    Webhook configurado no app pai (ex. 699996529141137) usa ``app_secret`` do Basic
    Settings. O field ``meta_instagram`` (produto IG 182784…) só entra como fallback.
    """
    import os

    candidates: List[str] = []
    for v in _meta_app_secret_env_overrides():
        candidates.append(v)
    parent_only = os.getenv("VECTRACLAW_IG_WEBHOOK_PARENT_APP_ONLY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    keys = ("app_secret",) if parent_only else ("app_secret", "meta_instagram")
    for key in keys:
        v = _normalize_meta_app_secret(str(cfg.get(key) or ""))
        if v and v not in candidates:
            candidates.append(v)
    # Wizard legado: App Secret 32 hex colado em access_token — Meta assina com essa chave.
    at_misfiled = _normalize_meta_app_secret(str(cfg.get("access_token") or ""))
    if at_misfiled and at_misfiled not in candidates:
        candidates.append(at_misfiled)
        logger.warning(
            "meta_instagram webhook: HMAC candidate from access_token field (prefix=%s) "
            "— mova para app_secret no wizard",
            at_misfiled[:6],
        )
    company_id = str(cfg.get("company_id") or "").strip()
    if company_id:
        for row in _load_meta_adapter_targets(META_WHATSAPP_ADAPTER_SLUG):
            if str(row.get("company_id") or "") != company_id:
                continue
            wa = _resolve_meta_config_for_company(
                row["company_id"],
                row["id"],
                routing_field="phone_number_id",
                require_routing_field=False,
            )
            if wa:
                wa_sec = _normalize_meta_app_secret(str(wa.get("app_secret") or ""))
                if wa_sec and wa_sec not in candidates:
                    candidates.append(wa_sec)
            break
        for extra in _company_meta_hmac_secrets(company_id):
            if extra not in candidates:
                candidates.append(extra)
    return candidates


def _find_meta_config_by_phone_number_id(phone_number_id: str) -> Optional[Dict[str, Any]]:
    """Resolve config Meta pela chave de roteamento `phone_number_id` (vem do
    payload Meta). Itera companies com adapter meta-whatsapp e devolve a que
    bate. W5 — usa resolver híbrido company→agent."""
    if not phone_number_id:
        return None
    pid_target = phone_number_id.strip()
    for adapter_row in _load_meta_adapter_targets(META_WHATSAPP_ADAPTER_SLUG):
        resolved = _resolve_meta_config_for_company(
            adapter_row["company_id"],
            adapter_row["id"],
            routing_field="phone_number_id",
        )
        if resolved and str(resolved.get("phone_number_id") or "").strip() == pid_target:
            return resolved
    return None


def _find_instagram_config_by_account_id(instagram_account_id: str) -> Optional[Dict[str, Any]]:
    """Resolve config meta-instagram pela chave instagram_account_id (entry.id)."""
    if not instagram_account_id:
        return None
    target = instagram_account_id.strip()
    for adapter_row in _load_meta_instagram_adapter_targets():
        resolved = _resolve_meta_config_for_company(
            adapter_row["company_id"],
            adapter_row["id"],
            routing_field="instagram_account_id",
        )
        if resolved and str(resolved.get("instagram_account_id") or "").strip() == target:
            return resolved
    return None


def _resolve_instagram_webhook_cfg(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Config para validar HMAC antes de parsear messaging (entry.id ou adapter único)."""
    ig_id = ""
    for entry in payload.get("entry") or []:
        if isinstance(entry, dict):
            ig_id = str(entry.get("id") or "").strip()
            if ig_id:
                break
    if ig_id:
        cfg = _find_instagram_config_by_account_id(ig_id)
        if cfg:
            return cfg
    for adapter_row in _load_meta_instagram_adapter_targets():
        return _resolve_meta_config_for_company(
            adapter_row["company_id"],
            adapter_row["id"],
            routing_field="instagram_account_id",
            require_routing_field=False,
        )
    return None


def _verify_instagram_webhook_hmac(
    request: Request,
    body_bytes: bytes,
    payload: Dict[str, Any],
    cfg: Dict[str, Any],
    x_hub_signature_256: Optional[str],
    x_hub_signature: Optional[str] = None,
) -> None:
    """Valida X-Hub-Signature-256 (e sha1 legado) ou levanta HTTPException (401/503)."""
    hmac_secrets = _instagram_hmac_secret_candidates(cfg)
    if not hmac_secrets and not _meta_signature_skip_enabled():
        raise HTTPException(503, "app_secret_not_configured_for_company")
    if _meta_signature_skip_enabled():
        logger.warning(
            "meta_instagram webhook: HMAC skipped (VECTRACLAW_IG_WEBHOOK_SKIP_HMAC) "
            "company_id=%s",
            cfg.get("company_id"),
        )
        return
    sig_headers: List[tuple[str, str]] = []
    if x_hub_signature_256:
        sig_headers.append(("sha256", x_hub_signature_256))
    if x_hub_signature:
        sig_headers.append(("sha1", x_hub_signature))
    if not sig_headers:
        logger.warning(
            "meta_instagram webhook: missing X-Hub-Signature-256 company_id=%s",
            cfg.get("company_id"),
        )
        raise HTTPException(401, "invalid_meta_signature")
    for idx, secret in enumerate(hmac_secrets):
        for algo, header_val in sig_headers:
            if algo == "sha256" and _verify_meta_signature_with_payload(
                body_bytes, payload, header_val, secret
            ):
                logger.info(
                    "meta_instagram webhook: HMAC ok candidate=%s/%s prefix=%s "
                    "algo=sha256 company_id=%s",
                    idx + 1,
                    len(hmac_secrets),
                    secret[:6],
                    cfg.get("company_id"),
                )
                return
            if algo == "sha1" and _verify_meta_signature(
                body_bytes, header_val, secret, algorithm="sha1"
            ):
                logger.info(
                    "meta_instagram webhook: HMAC ok candidate=%s/%s prefix=%s "
                    "algo=sha1 company_id=%s",
                    idx + 1,
                    len(hmac_secrets),
                    secret[:6],
                    cfg.get("company_id"),
                )
                return
    header = (x_hub_signature_256 or "").strip()
    expected = header.split("=", 1)[1].strip().lower() if "sha256=" in header else ""
    digests: List[str] = []
    for secret in hmac_secrets:
        dig = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest().lower()
        digests.append(f"{secret[:6]}:{dig[:16]}")
    try:
        from pathlib import Path

        body_tag = hashlib.sha256(body_bytes).hexdigest()[:16]
        Path(f"/tmp/meta_ig_{body_tag}.bin").write_bytes(body_bytes)
        Path(f"/tmp/meta_ig_{body_tag}.sig").write_text(header, encoding="utf-8")
        Path("/tmp/meta_ig_webhook_last.bin").write_bytes(body_bytes)
        Path("/tmp/meta_ig_webhook_last.sig").write_text(header, encoding="utf-8")
    except Exception as e:
        logger.warning("meta_instagram webhook: body capture failed: %s", e)
    logger.warning(
        "meta_instagram webhook: HMAC mismatch company_id=%s "
        "candidates=%s tried=%s body_len=%s body_sha256=%s expected_sig=%s "
        "content_encoding=%s",
        cfg.get("company_id"),
        len(hmac_secrets),
        digests,
        len(body_bytes),
        hashlib.sha256(body_bytes).hexdigest()[:16],
        expected[:16],
        request.headers.get("content-encoding"),
    )
    raise HTTPException(401, "invalid_meta_signature")


def _find_any_meta_config_with_verify_token(verify_token: str) -> Optional[Dict[str, Any]]:
    """Handshake GET: aceita verify_token de meta-whatsapp OU meta-instagram."""
    if not verify_token:
        return None
    vt = verify_token.strip()
    instagram_rows = _load_meta_instagram_adapter_targets()
    for slug, routing_field, rows in (
        (META_WHATSAPP_ADAPTER_SLUG, "phone_number_id", _load_meta_adapter_targets(META_WHATSAPP_ADAPTER_SLUG)),
        (META_INSTAGRAM_ADAPTER_SLUGS[0], "instagram_account_id", instagram_rows),
    ):
        for adapter_row in rows:
            resolved = _resolve_meta_config_for_company(
                adapter_row["company_id"],
                adapter_row["id"],
                routing_field=routing_field,
                require_routing_field=False,
            )
            if not resolved:
                continue
            cfg_token = (resolved.get("webhook_verify_token") or "").strip()
            if not cfg_token:
                logger.warning(
                    "meta webhook verify: adapter slug=%s company=%s sem webhook_verify_token resolvido",
                    slug, adapter_row.get("company_id"),
                )
                continue
            if hmac.compare_digest(cfg_token, vt):
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


def _normalize_meta_app_secret(value: str) -> str:
    """App Secret Meta: 32 chars hex; remove espaços/BOM de cópia do painel."""
    v = (value or "").strip().replace("\r", "").replace("\n", "")
    if len(v) != 32:
        return ""
    try:
        int(v, 16)
    except ValueError:
        return ""
    return v.lower()


def _verify_meta_signature(
    body_bytes: bytes,
    signature_header: str,
    app_secret: str,
    *,
    algorithm: str = "sha256",
) -> bool:
    """Valida ``sha256=<hex>`` ou ``sha1=<hex>`` (legado) sobre body bruto."""
    secret = _normalize_meta_app_secret(app_secret)
    if not signature_header or not secret:
        return False
    header = signature_header.strip()
    prefix = f"{algorithm}="
    if not header.lower().startswith(prefix):
        return False
    expected = header.split("=", 1)[1].strip().lower()
    hash_fn = hashlib.sha256 if algorithm == "sha256" else hashlib.sha1
    digest = hmac.new(secret.encode("utf-8"), body_bytes, hash_fn).hexdigest().lower()
    return hmac.compare_digest(expected, digest)


def _verify_meta_signature_with_payload(
    body_bytes: bytes,
    payload: Dict[str, Any],
    signature_header: str,
    app_secret: str,
) -> bool:
    """Valida HMAC no body bruto; fallbacks se proxy reformatar JSON."""
    if _verify_meta_signature(body_bytes, signature_header, app_secret):
        return True
    import json

    candidates: list[bytes] = []
    try:
        candidates.append(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )
        candidates.append(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        )
        candidates.append(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        candidates.append(json.dumps(payload, sort_keys=True).encode("utf-8"))
    except Exception:
        pass
    for alt in candidates:
        if alt != body_bytes and _verify_meta_signature(alt, signature_header, app_secret):
            logger.info("meta_instagram webhook: HMAC ok on JSON re-encode variant")
            return True
    return False


def _meta_signature_debug_enabled() -> bool:
    import os
    return os.getenv("VECTRACLAW_IG_WEBHOOK_DEBUG", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _meta_signature_skip_enabled() -> bool:
    import os
    return os.getenv("VECTRACLAW_IG_WEBHOOK_SKIP_HMAC", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _parse_meta_message(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extrai a primeira mensagem útil do payload Meta Cloud API.
    Schema: entry[].changes[].value.messages[] + value.metadata.phone_number_id
    + value.contacts[].profile.name. Retorna None se não houver mensagem (eg
    status/delivery updates).

    W9 (auditor 2026-05-18 ajuste P1): extrai também `interactive.button_reply.id`
    pra `button_id_hint` — Morpheus inbound triage usa pra match exato em
    inbound_intent_rules.button_id. Sem isso o classifier perde o sinal mais
    forte de detecção de origem."""
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

            # W9 — extração de interactive.button_reply (Meta interactive messages).
            # NULL se mensagem é texto normal ou não-interactive.
            interactive = msg.get("interactive") or {}
            button_reply = interactive.get("button_reply") or {}
            list_reply = interactive.get("list_reply") or {}
            button_id_hint = (
                str(button_reply.get("id") or "").strip()
                or str(list_reply.get("id") or "").strip()
                or None
            )

            return {
                "phone_number_id": phone_number_id,
                "external_id": str(msg.get("from") or "").strip(),
                "external_name": external_name,
                "content": content,
                "message_id": msg.get("id"),
                "msg_type": msg.get("type") or "text",
                "timestamp": msg.get("timestamp"),
                "button_id_hint": button_id_hint,  # W9 — pode ser None
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
            _schedule_connector_session_ws(
                company_id,
                str(session["id"]),
                channel=session.get("channel"),
                external_id=msg["external_id"],
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


# ─────────────────────────────────────────────────────────────────────────────
# Meta Instagram — GET (handshake) e POST (DM inbound)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/connectors/instagram/webhook")
@router.get("/connectors/instagram/webhook")
async def meta_instagram_webhook_verify(
    hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
):
    """Handshake Meta para Instagram (mesmo fluxo hub.challenge do WhatsApp)."""
    if hub_mode != "subscribe":
        raise HTTPException(400, "invalid_hub_mode")
    if not hub_verify_token or not hub_challenge:
        raise HTTPException(400, "missing_hub_params")
    cfg = _find_any_meta_config_with_verify_token(hub_verify_token)
    if not cfg:
        logger.warning(
            "meta_instagram verify token mismatch (token first 4 chars: %s)",
            hub_verify_token[:4],
        )
        raise HTTPException(403, "verify_token_mismatch")
    logger.info("meta_instagram webhook verified for company_id=%s", cfg.get("company_id"))
    return Response(content=hub_challenge, media_type="text/plain")


@router.post("/api/connectors/instagram/webhook")
@router.post("/connectors/instagram/webhook")
async def meta_instagram_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None, alias="X-Hub-Signature-256"),
    x_hub_signature: Optional[str] = Header(default=None, alias="X-Hub-Signature"),
):
    """Recebe payload Meta Instagram (object=instagram). Mesmo pipeline W3:
    connector_session + inbound-triage via connector_channels."""
    from src.services import connector_bus
    from src.services.instagram_parser import (
        instagram_message_to_bus_dict,
        parse_instagram_payload,
    )

    body_bytes = await request.body()
    if not body_bytes:
        raise HTTPException(400, "empty_body")
    try:
        import json
        payload = json.loads(body_bytes)
    except Exception:
        raise HTTPException(400, "invalid_json")

    if payload.get("object") != "instagram":
        logger.info("meta_instagram webhook: object=%s ignored", payload.get("object"))
        return {"received": True, "had_message": False}

    cfg = _resolve_instagram_webhook_cfg(payload)
    if not cfg:
        logger.warning("meta_instagram webhook: no adapter config for HMAC")
        raise HTTPException(404, "no_adapter_config_for_instagram_webhook")
    _verify_instagram_webhook_hmac(
        request,
        body_bytes,
        payload,
        cfg,
        x_hub_signature_256,
        x_hub_signature,
    )

    parsed = parse_instagram_payload(payload)
    if not parsed:
        return {"received": True, "had_message": False}

    last_session: Optional[Dict[str, Any]] = None
    last_msg: Optional[Dict[str, Any]] = None
    last_task_id: Optional[str] = None

    for ig_msg in parsed:
        msg = instagram_message_to_bus_dict(ig_msg)
        if not msg["instagram_account_id"]:
            continue
        if not msg["external_id"]:
            continue

        msg_cfg = _find_instagram_config_by_account_id(msg["instagram_account_id"])
        if not msg_cfg:
            logger.warning(
                "meta_instagram webhook: skip unknown instagram_account_id=%s",
                msg["instagram_account_id"],
            )
            continue

        company_id = str(msg_cfg.get("company_id") or "").strip()
        if not company_id:
            continue

        try:
            session = connector_bus.get_or_open_session(
                company_id=company_id,
                channel="instagram",
                connector_id=msg["instagram_account_id"],
                external_id=msg["external_id"],
                external_name=msg.get("external_name"),
                external_meta={"mid": msg["message_id"], "msg_type": msg["msg_type"]},
            )
            if msg["content"]:
                connector_bus.append_history(
                    session_id=session["id"],
                    role="user",
                    content=msg["content"],
                    extra={"mid": msg["message_id"], "timestamp": msg["timestamp"]},
                )
                _schedule_connector_session_ws(
                    company_id,
                    str(session["id"]),
                    channel=session.get("channel"),
                    external_id=msg["external_id"],
                )
        except RuntimeError as e:
            logger.error("meta_instagram_webhook bus failure: %s", e)
            raise HTTPException(503, str(e))
        except Exception:
            logger.exception("meta_instagram_webhook unexpected failure")
            raise HTTPException(500, "instagram_webhook_failed")

        task_id: Optional[str] = None
        if msg["content"]:
            task_id = _dispatch_inbound_task(
                company_id=company_id,
                session=session,
                msg=msg,
            )
        last_session = session
        last_msg = msg
        last_task_id = task_id

    if not last_session or not last_msg:
        return {"received": True, "had_message": False}

    delivered = False
    if last_msg.get("content"):
        delivered = await _instagram_inline_triage_and_reply(
            session_id=str(last_session["id"]),
            task_id=last_task_id,
        )

    return {
        "session_id": last_session["id"],
        "status": last_session.get("status"),
        "external_id": last_msg["external_id"],
        "had_content": bool(last_msg["content"]),
        "task_id": last_task_id,
        "reply_delivered": delivered,
    }


async def _instagram_inline_triage_and_reply(
    *,
    session_id: str,
    task_id: Optional[str],
) -> bool:
    """Triage Morpheus + reply DM no webhook (daemon pode estar parado)."""
    import os

    if os.getenv("VECTRACLAW_IG_INLINE_TRIAGE", "true").strip().lower() in (
        "0",
        "false",
        "no",
    ):
        return False

    from src.api import supabase
    from src.services import connector_bus

    if not supabase or not session_id:
        return False

    reply_text = (
        "Recebi sua mensagem! 👋 Já encaminhei pro time e respondemos em breve."
    )
    if task_id:
        try:
            tres = (
                supabase.table("tasks")
                .select("*")
                .eq("id", task_id)
                .limit(1)
                .execute()
            )
            if tres.data:
                from src.agents.morpheus_inbound_triage import entrypoint as triage_entry

                result = triage_entry(tres.data[0], supabase)
                if isinstance(result, dict):
                    candidate = str(result.get("output_text") or "").strip()
                    if candidate:
                        reply_text = candidate
                    if str(result.get("status") or "").strip() == "done":
                        patch: Dict[str, Any] = {
                            "status": "done",
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                        if result.get("output_json") is not None:
                            patch["output_json"] = result["output_json"]
                        (
                            supabase.table("tasks")
                            .update(patch)
                            .eq("id", task_id)
                            .eq("status", "queued")
                            .execute()
                        )
        except Exception as e:
            logger.warning(
                "meta_instagram inline triage failed task=%s: %s", task_id, e
            )

    try:
        sres = (
            supabase.table("connector_sessions")
            .select("*")
            .eq("id", session_id)
            .limit(1)
            .execute()
        )
        if not sres.data:
            return False
        session_row = sres.data[0]
    except Exception as e:
        logger.warning("meta_instagram inline reply: session load failed: %s", e)
        return False

    try:
        delivered = await connector_bus.reply(session_row, reply_text)
        if delivered:
            logger.info(
                "meta_instagram inline reply sent session=%s task=%s len=%d",
                session_id,
                task_id,
                len(reply_text),
            )
        else:
            logger.warning(
                "meta_instagram inline reply NOT delivered session=%s task=%s",
                session_id,
                task_id,
            )
        return bool(delivered)
    except Exception as e:
        logger.exception(
            "meta_instagram inline reply failed session=%s: %s", session_id, e
        )
        return False


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

    from src.services.connector_inbound_policy import (
        inbound_auto_dispatch_skip_reason,
        is_meta_inbound_channel,
    )

    channel_slug = (session.get("channel") or "").strip().lower()
    if not is_meta_inbound_channel(channel_slug):
        logger.warning(
            "_dispatch_inbound_task: canal %r não é Meta implementado — skip",
            channel_slug,
        )
        return None

    skip = inbound_auto_dispatch_skip_reason(channel_slug)
    if skip:
        logger.info(
            "_dispatch_inbound_task: auto-dispatch bloqueado (%s) session=%s — "
            "sessão/histórico OK; task só via humano ou fluxo explícito",
            skip,
            session.get("id"),
        )
        return None

    routing = _resolve_inbound_routing(channel_slug)
    if not routing:
        return None
    op_type = routing["operation_type"]
    assigned_agent = routing["assigned_to_agent_id"]

    content = msg["content"]
    external_label = (msg.get("external_name") or msg.get("external_id") or "").strip()
    channel = (session.get("channel") or "connector").strip()
    channel_labels = {"whatsapp": "WhatsApp", "instagram": "Instagram"}
    prefix = channel_labels.get(channel, channel.title() or "Connector")
    title = f"{prefix}: {external_label[:30]} — {content[:60]}".strip()
    now_iso = datetime.now(timezone.utc).isoformat()

    input_json: Dict[str, Any] = {
        "source": f"meta_{channel}_webhook",
        "session_id": session["id"],
        "external_id": msg["external_id"],
        "external_name": msg.get("external_name"),
        "message": content,
        "channel": channel,
        "button_id_hint": msg.get("button_id_hint"),
    }
    if msg.get("phone_number_id"):
        input_json["phone_number_id"] = msg["phone_number_id"]
        input_json["wamid"] = msg.get("message_id")
    if msg.get("instagram_account_id"):
        input_json["instagram_account_id"] = msg["instagram_account_id"]
        input_json["mid"] = msg.get("message_id")

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
        "input_json": input_json,
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
    from src.api import supabase, validate_jwt_company_id, require_role_not
    from src.services import connector_bus

    if not supabase:
        raise HTTPException(503, "supabase_required")

    scope = {"role": getattr(request.state, "role", None)}
    require_role_not(scope, _CONNECTOR_REPLY_BLOCKED_ROLES, "responder sessão de canal")

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
        # PR2 fix Bug #2: append_role=None — caller já gravou history role='operator'
        # acima (linha ~626). Sem o None, _reply_whatsapp_meta duplicaria como
        # 'assistant', criando os pares operator+assistant que apareciam como eco.
        delivered = await connector_bus.reply(session_row, content, append_role=None)
    except Exception as e:
        logger.warning("_do_reply connector_bus.reply non-fatal: %s", e)

    company_id = str(session_row.get("company_id") or "")
    if company_id:
        _schedule_connector_session_ws(company_id, session_id)

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
