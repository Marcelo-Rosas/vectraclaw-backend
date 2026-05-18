"""W11 PR1 — WhatsApp Templates Sync Service.

Espelha localmente os templates aprovados pela Meta WABA em
`vectraclip.whatsapp_templates`. Catálogo serve options dinâmicas pro
DynamicFieldRenderer (adapter_field_definitions.options_json.source).

Fluxo do sync:
  1. Resolve config Meta da company (access_token + waba_id + api_version)
     via _resolve_meta_config_for_company (catalog-driven, vault:// resolvido)
  2. GET https://graph.facebook.com/<api_version>/<waba_id>/message_templates
     (paginação ?after se houver)
  3. Upsert em whatsapp_templates por (waba_id, name, language)
  4. Marca is_active=false pros que sumiram da Meta (soft-delete)
  5. Log em whatsapp_template_sync_log

NÃO duplica `_META_GRAPH_BASE` — importa de connector_bus (P0.2 auditor).
NÃO hardcoda WABA_ID — vem do company_adapter_values (P0.1 auditor).

Side-effects: DB writes (whatsapp_templates, whatsapp_template_sync_log),
HTTP externo (Graph API).

Sync chamado por:
  - POST /api/connectors/whatsapp/templates/sync (admin, force refresh)
  - Cron diário (a configurar via scheduler — W13)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("Vectra.whatsapp_template_sync")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def sync_company_templates(
    company_id: str,
    adapter_id: str,
    triggered_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Sync templates WABA pra uma company. Retorna dict com status+counts.

    Best-effort: erros parciais (ex: 1 template malformado) não param o sync.
    Erro fatal (auth, network, sem waba_id) retorna status='error' + log.
    """
    from src.api import supabase
    from src.api_routes.connectors import _resolve_meta_config_for_company
    from src.services.connector_bus import _META_GRAPH_BASE

    if not supabase:
        return _error_result(company_id, adapter_id, triggered_by_user_id,
                             "supabase_unavailable")

    log_id = _start_sync_log(supabase, company_id, adapter_id, triggered_by_user_id)

    cfg = _resolve_meta_config_for_company(company_id, adapter_id)
    if not cfg:
        return _finish_sync_log(supabase, log_id, status="error",
                                error="meta_config_unresolved_for_company")

    # waba_id + session_window_hours não estão no shape antigo do resolver.
    # Resolvo via mesma rota: company_adapter_values (com fallback agent override).
    waba_id, _ = _resolve_field(supabase, company_id, adapter_id, "waba_id")
    if not waba_id:
        return _finish_sync_log(supabase, log_id, status="error",
                                error="waba_id_not_configured")

    access_token = (cfg.get("access_token") or "").strip()
    api_version = (cfg.get("api_version") or "v22.0").strip()
    if not access_token:
        return _finish_sync_log(supabase, log_id, status="error",
                                error="access_token_empty")

    # Fetch (com paginação simples)
    try:
        templates_raw, raw_snapshot = await _fetch_all_templates(
            base_url=_META_GRAPH_BASE,
            api_version=api_version,
            waba_id=waba_id,
            access_token=access_token,
        )
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text[:500]
        except Exception:
            pass
        return _finish_sync_log(
            supabase, log_id, status="error",
            error=f"meta_graph_error_{e.response.status_code}: {body}",
        )
    except Exception as e:
        return _finish_sync_log(supabase, log_id, status="error",
                                error=f"meta_fetch_failed: {e}")

    if not templates_raw:
        return _finish_sync_log(supabase, log_id, status="success",
                                fetched=0, upserted=0,
                                snapshot={"empty": True})

    # Upsert em batch
    upserted, partial_errors = _upsert_templates(
        supabase, company_id, waba_id, templates_raw,
    )

    # Soft-delete dos que sumiram da Meta (is_active=false)
    _soft_delete_missing(supabase, company_id, waba_id, templates_raw)

    status = "success" if not partial_errors else "partial"
    return _finish_sync_log(
        supabase, log_id, status=status,
        fetched=len(templates_raw), upserted=upserted,
        snapshot=raw_snapshot,
        error=("; ".join(partial_errors)[:500] if partial_errors else None),
    )


async def _fetch_all_templates(
    *, base_url: str, api_version: str, waba_id: str, access_token: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Fetch templates da Graph API com paginação ?after. Retorna lista
    achatada + snapshot raw (primeira página) pra audit log."""
    url = f"{base_url}/{api_version}/{waba_id}/message_templates"
    headers = {"Authorization": f"Bearer {access_token}"}
    params: Dict[str, Any] = {
        "fields": "id,name,status,category,language,components,quality_score,rejected_reason",
        "limit": 100,
    }

    all_templates: List[Dict[str, Any]] = []
    first_snapshot: Optional[Dict[str, Any]] = None
    pages = 0
    next_url: Optional[str] = url

    async with httpx.AsyncClient(timeout=20.0) as client:
        while next_url and pages < 20:  # safety cap (2000 templates)
            pages += 1
            resp = await client.get(next_url, params=params if pages == 1 else None,
                                    headers=headers)
            resp.raise_for_status()
            payload = resp.json() or {}
            if first_snapshot is None:
                first_snapshot = {
                    "page1_count": len(payload.get("data") or []),
                    "has_paging_next": bool(payload.get("paging", {}).get("next")),
                }
            data = payload.get("data") or []
            all_templates.extend(data)
            next_url = (payload.get("paging") or {}).get("next")

    return all_templates, (first_snapshot or {})


def _upsert_templates(
    supabase, company_id: str, waba_id: str, templates: List[Dict[str, Any]],
) -> Tuple[int, List[str]]:
    """Upsert lote em whatsapp_templates por (waba_id, name, language).

    Retorna (count_upserted, partial_errors).
    """
    upserted = 0
    errors: List[str] = []
    now = _now_iso()

    rows: List[Dict[str, Any]] = []
    for t in templates:
        try:
            row = {
                "company_id": company_id,
                "waba_id": waba_id,
                "meta_template_id": str(t.get("id") or ""),
                "name": t.get("name") or "",
                "language": t.get("language") or "und",
                "category": t.get("category") or "UNKNOWN",
                "status": t.get("status") or "UNKNOWN",
                "components": t.get("components"),
                "quality_score": t.get("quality_score"),
                "rejected_reason": t.get("rejected_reason"),
                "is_active": True,
                "last_synced_at": now,
                "updated_at": now,
            }
            if not row["name"] or not row["meta_template_id"]:
                errors.append(f"skip_invalid_template_id={t.get('id')}_name={t.get('name')}")
                continue
            rows.append(row)
        except Exception as e:
            errors.append(f"parse_error_{t.get('name', '?')}: {e}")

    if not rows:
        return 0, errors

    try:
        # on_conflict requer constraint name OU tuple de cols — Supabase Python aceita string
        res = (
            supabase.table("whatsapp_templates")
            .upsert(rows, on_conflict="waba_id,name,language")
            .execute()
        )
        upserted = len(res.data or [])
    except Exception as e:
        errors.append(f"upsert_failed: {e}")

    return upserted, errors


def _soft_delete_missing(
    supabase, company_id: str, waba_id: str, fetched: List[Dict[str, Any]],
) -> None:
    """Marca is_active=false em templates locais que NÃO vieram na fetch atual
    (provavelmente deletados na Meta ou WABA mudou). Não apaga — soft."""
    fetched_keys = {(t.get("name"), t.get("language")) for t in fetched}
    try:
        existing = (
            supabase.table("whatsapp_templates")
            .select("id,name,language")
            .eq("company_id", company_id)
            .eq("waba_id", waba_id)
            .eq("is_active", True)
            .execute()
        )
        for row in existing.data or []:
            if (row.get("name"), row.get("language")) not in fetched_keys:
                supabase.table("whatsapp_templates").update({
                    "is_active": False,
                    "updated_at": _now_iso(),
                }).eq("id", row["id"]).execute()
    except Exception as e:
        logger.warning("soft_delete_missing failed (non-fatal): %s", e)


def _resolve_field(
    supabase, company_id: str, adapter_id: str, field_key: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve um field específico via híbrido company→agent override.
    Retorna (value, source) onde source in ('agent','company',None)."""
    from src.api import (
        get_company_adapter_values,
        resolve_adapter_field_value,
    )
    company_values = get_company_adapter_values(company_id, adapter_id) or {}
    agent_values: Dict[str, Any] = {}
    try:
        agent_cfgs = (
            supabase.table("agent_adapter_configs")
            .select("field_values_json")
            .eq("company_id", company_id)
            .eq("adapter_id", adapter_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if agent_cfgs.data:
            agent_values = agent_cfgs.data[0].get("field_values_json") or {}
    except Exception:
        pass
    value = resolve_adapter_field_value(field_key, agent_values, company_values, company_id)
    if value:
        source = "agent" if (agent_values.get(field_key) and value == agent_values.get(field_key)) else "company"
        return value, source
    return None, None


def resolve_session_window_hours(
    company_id: str, adapter_id: str, default: int = 24,
) -> int:
    """Lê session_window_hours do adapter resolvido (W11 P1.1 auditor).
    Usado por connector_bus.reply pra decidir entre free text e template."""
    from src.api import supabase
    if not supabase:
        return default
    raw, _ = _resolve_field(supabase, company_id, adapter_id, "session_window_hours")
    if not raw:
        return default
    try:
        n = int(raw)
        if 1 <= n <= 168:
            return n
    except (TypeError, ValueError):
        pass
    logger.warning("session_window_hours inválido (%s) — usando default %d", raw, default)
    return default


# ─────────────────────────────────────────────────────────────────────────────
# Sync log helpers
# ─────────────────────────────────────────────────────────────────────────────

def _start_sync_log(supabase, company_id: str, adapter_id: str,
                    triggered_by: Optional[str]) -> Optional[str]:
    try:
        res = supabase.table("whatsapp_template_sync_log").insert({
            "company_id": company_id,
            "adapter_id": adapter_id,
            "triggered_by": triggered_by,
            "status": "success",  # placeholder; sobrescrito no finish
            "templates_fetched": 0,
            "templates_upserted": 0,
            "started_at": _now_iso(),
        }).execute()
        return res.data[0]["id"] if res.data else None
    except Exception as e:
        logger.warning("start_sync_log failed (non-fatal): %s", e)
        return None


def _finish_sync_log(
    supabase, log_id: Optional[str], *,
    status: str,
    fetched: int = 0,
    upserted: int = 0,
    error: Optional[str] = None,
    snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = {
        "status": status,
        "templates_fetched": fetched,
        "templates_upserted": upserted,
        "error_message": error,
    }
    if not log_id:
        return result
    try:
        supabase.table("whatsapp_template_sync_log").update({
            **result,
            "meta_response_snapshot": snapshot,
            "finished_at": _now_iso(),
        }).eq("id", log_id).execute()
    except Exception as e:
        logger.warning("finish_sync_log failed (non-fatal): %s", e)
    return result


def _error_result(company_id: str, adapter_id: str, triggered_by: Optional[str],
                  msg: str) -> Dict[str, Any]:
    return {
        "status": "error",
        "templates_fetched": 0,
        "templates_upserted": 0,
        "error_message": msg,
    }
