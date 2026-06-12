"""Resolve credenciais Meu Planner via MCP web-automation (Admin → MCP)."""
from __future__ import annotations

import logging
import os
from typing import Any

from src.agents.kronos import _parse_env_line

logger = logging.getLogger("Kronos")

_PLANNER_EMAIL_SECRET_NAMES = ("PLANNER_EMAIL", "planner_email")
_PLANNER_PASSWORD_SECRET_NAMES = ("PLANNER_PASSWORD", "planner_password")
_PLANNER_CREDENTIALS_HINT = (
    "Configure o perfil em Admin → MCP Servers → Automação web (mcp-web-automation): "
    "URL base, usuário e senha (Vault). Perfil padrão: mcp_profile_key=meu-planner."
)


def _resolve_task_company_id(task: dict, client: Any = None) -> str:
    cid = str(task.get("company_id") or "").strip()
    if cid:
        return cid
    agent_id = str(task.get("assigned_to_agent_id") or "").strip()
    if client and agent_id:
        try:
            res = (
                client.table("agents")
                .select("company_id")
                .eq("id", agent_id)
                .limit(1)
                .execute()
            )
            if res.data:
                return str(res.data[0].get("company_id") or "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("_resolve_task_company_id falhou: %s", exc)
    return ""


def resolve_planner_credentials(
    task: dict,
    client: Any = None,
) -> tuple[str, str]:
    from src.services.mcp_web_automation import (
        resolve_web_automation_profile,
        resolve_web_automation_profile_key_from_task,
        resolve_web_automation_server_id_from_task,
    )
    from src.services.secret_resolve import (
        first_non_empty_from_sources,
        read_company_secret_by_name,
        resolve_secret_value,
    )

    company_id = _resolve_task_company_id(task, client)
    agent_id = str(task.get("assigned_to_agent_id") or "").strip() or None
    sources = [
        task.get("input_json") or {},
        task.get("_resolved_config") or {},
        task.get("_resolved_shared") or {},
    ]

    email_raw = first_non_empty_from_sources(sources, "planner_email", "PLANNER_EMAIL")
    password_raw = first_non_empty_from_sources(
        sources, "planner_password", "PLANNER_PASSWORD"
    )
    desc = task.get("description", "") or ""
    if not email_raw:
        email_raw = _parse_env_line(desc, "PLANNER_EMAIL")
    if not password_raw:
        password_raw = _parse_env_line(desc, "PLANNER_PASSWORD")

    email = ""
    password = ""

    if client and company_id and not (email_raw and password_raw):
        profile = resolve_web_automation_profile(
            client,
            company_id,
            server_id=resolve_web_automation_server_id_from_task(task),
            profile_key=resolve_web_automation_profile_key_from_task(task),
            agent_id=agent_id,
        )
        if profile:
            email = profile.username
            password = profile.password
            task["_web_automation_profile"] = {
                "base_url": profile.base_url,
                "login_url": profile.login_url,
                "engine": profile.engine,
                "institution": profile.institution,
                "profile_key": profile.profile_key,
            }

    if client and company_id:
        if email_raw:
            email = email or resolve_secret_value(client, company_id, email_raw)
        elif not email:
            for name in _PLANNER_EMAIL_SECRET_NAMES:
                email = read_company_secret_by_name(client, company_id, name)
                if email:
                    break
        if password_raw:
            password = password or resolve_secret_value(client, company_id, password_raw)
        elif not password:
            for name in _PLANNER_PASSWORD_SECRET_NAMES:
                password = read_company_secret_by_name(client, company_id, name)
                if password:
                    break
    else:
        email = email or email_raw
        password = password or password_raw

    if not email:
        email = os.getenv("PLANNER_EMAIL", "").strip()
    if not password:
        password = os.getenv("PLANNER_PASSWORD", "").strip()

    return email, password


def resolve_planner_web_context(task: dict, client: Any = None) -> dict[str, Any]:
    cached = task.get("_web_automation_profile")
    if isinstance(cached, dict):
        return cached
    company_id = _resolve_task_company_id(task, client)
    if not client or not company_id:
        return {}
    from src.services.mcp_web_automation import (
        resolve_web_automation_profile,
        resolve_web_automation_profile_key_from_task,
        resolve_web_automation_server_id_from_task,
    )

    profile = resolve_web_automation_profile(
        client,
        company_id,
        server_id=resolve_web_automation_server_id_from_task(task),
        profile_key=resolve_web_automation_profile_key_from_task(task),
        agent_id=str(task.get("assigned_to_agent_id") or "").strip() or None,
    )
    if not profile:
        return {}
    return {
        "base_url": profile.base_url,
        "login_url": profile.login_url,
        "engine": profile.engine,
        "institution": profile.institution,
        "profile_key": profile.profile_key,
    }


def planner_credentials_error_message(
    task: dict,
    client: Any = None,
    *,
    email: str = "",
    password: str = "",
) -> str:
    company_id = _resolve_task_company_id(task, client)
    return (
        f"{_PLANNER_CREDENTIALS_HINT} — task={task.get('id', '?')[:8]} "
        f"company_id={'ok' if company_id else 'ausente'} — "
        f"email={'ok' if email else 'ausente'} — password={'ok' if password else 'ausente'}"
    )
