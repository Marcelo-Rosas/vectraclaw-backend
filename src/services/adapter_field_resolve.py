"""Resolve adapter field_values (company primary + agent override) com vault://.

SSOT alinhado a api.resolve_adapter_field_value (W5) sem import circular de src.api.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.services.secret_resolve import resolve_secret_value

logger = logging.getLogger("AdapterFieldResolve")

# adapter_catalog.slug canônico — mesmo id usado em mcp_server_catalog e Connectors UI.
MCP_IMAP_ADAPTER_SLUG = "mcp-imap"


def resolve_adapter_field(
    client: Any,
    company_id: str,
    field_key: str,
    agent_field_values: Optional[Dict[str, Any]],
    company_field_values: Optional[Dict[str, Any]],
) -> str:
    """Agent override → company primary → vazio; desreferencia vault://.

    Se o override do agente existe mas resolve vazio (ex.: ``vault://`` apontando
    para um secret inexistente/órfão), cai para o valor primário da company em
    vez de travar com string vazia. Sem esse fallback, um ref de Vault quebrado
    no layer do agente mascara um valor válido no layer da company — foi a causa
    raiz do ``send_smtp failed: 'HERMES_SMTP_SERVER'`` do Hermes (agent password
    apontando para secret órfão enquanto a company tinha o ref correto).
    """
    agent_v = (agent_field_values or {}).get(field_key)
    if agent_v is not None and str(agent_v).strip() != "":
        resolved = resolve_secret_value(client, company_id, agent_v)
        if resolved:
            return resolved
    company_v = (company_field_values or {}).get(field_key)
    if company_v is not None and str(company_v).strip() != "":
        return resolve_secret_value(client, company_id, company_v)
    return ""


def _adapter_id_for_slug(client: Any, company_id: str, adapter_slug: str) -> Optional[str]:
    try:
        res = (
            client.table("adapter_catalog")
            .select("id")
            .eq("company_id", company_id)
            .eq("slug", adapter_slug)
            .limit(1)
            .execute()
        )
        if res.data:
            return str(res.data[0]["id"])
    except Exception as exc:
        logger.warning("_adapter_id_for_slug failed slug=%s: %s", adapter_slug, exc)
    return None


def _company_field_values(
    client: Any, company_id: str, adapter_id: str
) -> Dict[str, Any]:
    try:
        res = (
            client.table("company_adapter_values")
            .select("field_values_json")
            .eq("company_id", company_id)
            .eq("adapter_id", adapter_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if res.data:
            fv = res.data[0].get("field_values_json") or {}
            return fv if isinstance(fv, dict) else {}
    except Exception as exc:
        logger.warning("_company_field_values failed: %s", exc)
    return {}


def _agent_field_values(
    client: Any,
    company_id: str,
    adapter_id: str,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        q = (
            client.table("agent_adapter_configs")
            .select("field_values_json, agent_id")
            .eq("company_id", company_id)
            .eq("adapter_id", adapter_id)
        )
        if agent_id:
            q = q.eq("agent_id", agent_id)
        res = q.limit(1).execute()
        if res.data:
            fv = res.data[0].get("field_values_json") or {}
            return fv if isinstance(fv, dict) else {}
    except Exception as exc:
        logger.warning("_agent_field_values failed: %s", exc)
    return {}


def load_mcp_imap_smtp_credentials(
    client: Any,
    company_id: str,
    *,
    agent_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """SMTP a partir de adapter_field_definitions (mcp-imap) + Vault.

    Campos obrigatórios no catálogo: email, password, smtp_host, smtp_port.
    Sem fallback de host/porta no código — configure em /admin/connectors.
    """
    if not client or not company_id:
        return None

    adapter_id = _adapter_id_for_slug(client, company_id, MCP_IMAP_ADAPTER_SLUG)
    if not adapter_id:
        logger.warning(
            "load_mcp_imap_smtp_credentials: adapter %r ausente company=%s",
            MCP_IMAP_ADAPTER_SLUG,
            company_id[:8],
        )
        return None

    company_fv = _company_field_values(client, company_id, adapter_id)
    agent_fv = _agent_field_values(client, company_id, adapter_id, agent_id)

    email = resolve_adapter_field(client, company_id, "email", agent_fv, company_fv)
    password = resolve_adapter_field(client, company_id, "password", agent_fv, company_fv)
    smtp_host = resolve_adapter_field(client, company_id, "smtp_host", agent_fv, company_fv)
    port_raw = resolve_adapter_field(client, company_id, "smtp_port", agent_fv, company_fv)

    if not email or not password or not smtp_host or not port_raw:
        logger.warning(
            "load_mcp_imap_smtp_credentials: metadata incompleta company=%s "
            "email=%s pwd=%s smtp_host=%s smtp_port=%s",
            company_id[:8],
            bool(email),
            bool(password),
            bool(smtp_host),
            bool(port_raw),
        )
        return None

    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        logger.warning(
            "load_mcp_imap_smtp_credentials: smtp_port inválido %r company=%s",
            port_raw,
            company_id[:8],
        )
        return None

    return {
        "server": smtp_host,
        "port": port,
        "user": email,
        "password": password,
    }
