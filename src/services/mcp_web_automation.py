"""Resolve perfis MCP de automação web (URL + secrets) para Playwright/fetch.

SSOT: vectraclip.company_mcp_values + vault refs em field_values_json.
Configurado em Admin → MCP (`mcp-web-automation`). Ver migration
20260523120000_mcp_web_automation_catalog.sql.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal, Optional

from src.services.secret_resolve import first_non_empty_from_sources, resolve_secret_value

logger = logging.getLogger("McpWebAutomation")

MCP_WEB_AUTOMATION_SERVER_ID = "mcp-web-automation"
DEFAULT_WEB_AUTOMATION_PROFILE_KEY = "meu-planner"
WebAutomationEngine = Literal["playwright", "fetch"]


@dataclass(frozen=True)
class WebAutomationProfile:
    base_url: str
    engine: WebAutomationEngine
    username: str
    password: str
    login_url: Optional[str] = None
    institution: Optional[str] = None
    profile_key: str = DEFAULT_WEB_AUTOMATION_PROFILE_KEY
    mcp_server_id: str = MCP_WEB_AUTOMATION_SERVER_ID


def _str_field(values: dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = values.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def resolve_web_automation_profile(
    client: Any,
    company_id: str,
    *,
    server_id: str = MCP_WEB_AUTOMATION_SERVER_ID,
    profile_key: str = DEFAULT_WEB_AUTOMATION_PROFILE_KEY,
    agent_id: Optional[str] = None,
    binding_override: Optional[dict[str, Any]] = None,
) -> Optional[WebAutomationProfile]:
    """Lê perfil company-level + override de binding do agente; resolve vault://."""
    if not client or not company_id:
        return None

    from src.api_routes.agent_mcp_bindings import _resolve_effective_field_values

    override = dict(binding_override or {})
    if agent_id and not binding_override:
        try:
            bind = (
                client.table("agent_mcp_bindings")
                .select("field_values_json")
                .eq("company_id", company_id)
                .eq("agent_id", agent_id)
                .eq("mcp_server_id", server_id)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            rows = getattr(bind, "data", None) or []
            if rows:
                override = rows[0].get("field_values_json") or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "resolve_web_automation_profile: binding lookup falhou agent=%s: %s",
                agent_id[:8],
                exc,
            )

    raw = _resolve_effective_field_values(
        client, company_id, server_id, override, profile_key=profile_key
    )
    if not raw and profile_key != "default":
        raw = _resolve_effective_field_values(
            client, company_id, server_id, override, profile_key="default"
        )
    if not raw:
        return None

    base_url = _str_field(raw, "base_url", "url", "site_url")
    username_raw = _str_field(raw, "username", "email", "user", "login")
    password_raw = _str_field(raw, "password", "secret")
    if not base_url or not username_raw or not password_raw:
        return None

    username = resolve_secret_value(client, company_id, username_raw)
    password = resolve_secret_value(client, company_id, password_raw)
    if not username or not password:
        return None

    engine_raw = _str_field(raw, "engine") or "playwright"
    engine: WebAutomationEngine = "fetch" if engine_raw.lower() == "fetch" else "playwright"

    login_url = _str_field(raw, "login_url") or None
    institution = _str_field(raw, "institution", "instituicao", "planner_instituicao") or None

    return WebAutomationProfile(
        base_url=base_url.rstrip("/"),
        engine=engine,
        username=username,
        password=password,
        login_url=login_url.rstrip("/") if login_url else None,
        institution=institution,
        profile_key=profile_key,
        mcp_server_id=server_id,
    )


def resolve_web_automation_profile_key_from_task(
    task: dict,
    *,
    default: str = DEFAULT_WEB_AUTOMATION_PROFILE_KEY,
) -> str:
    """profile_key em input_json, specialty config ou shared config."""
    sources = [
        task.get("input_json") or {},
        task.get("_resolved_config") or {},
        task.get("_resolved_shared") or {},
    ]
    key = first_non_empty_from_sources(
        sources, "mcp_profile_key", "web_automation_profile_key", "profile_key"
    )
    return key or default


def resolve_web_automation_server_id_from_task(
    task: dict,
    *,
    default: str = MCP_WEB_AUTOMATION_SERVER_ID,
) -> str:
    sources = [
        task.get("input_json") or {},
        task.get("_resolved_config") or {},
        task.get("_resolved_shared") or {},
    ]
    sid = first_non_empty_from_sources(
        sources, "mcp_web_automation_server_id", "web_automation_mcp_server_id"
    )
    return sid or default
