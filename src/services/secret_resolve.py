"""Resolve secret refs (vault://, secret:NAME) usando Supabase client do caller.

Evita import circular de src.api — daemon e agentes passam o client próprio.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("SecretResolve")

VAULT_REF_PREFIX = "vault://"


def resolve_secret_value(
    client: Any,
    company_id: str,
    value: Any,
) -> str:
    """Desreferencia vault://, secret:NAME ou devolve string literal."""
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    if not client or not company_id:
        return raw

    if raw.startswith(VAULT_REF_PREFIX):
        secret_id = raw[len(VAULT_REF_PREFIX) :].strip()
        if not secret_id:
            return ""
        try:
            res = client.rpc(
                "get_vault_secret",
                {"p_vault_secret_id": secret_id, "p_company_id": company_id},
            ).execute()
            return str(res.data or "").strip()
        except Exception as exc:
            logger.warning(
                "resolve_secret_value: vault ref falhou company=%s: %s",
                company_id[:8],
                exc,
            )
            return ""

    if raw.startswith("secret:"):
        name = raw[len("secret:") :].strip()
        if not name:
            return ""
        return read_company_secret_by_name(client, company_id, name)

    return raw


def read_company_secret_by_name(
    client: Any,
    company_id: str,
    name: str,
) -> str:
    """Lê texto claro via RPC vectraclip.read_company_secret."""
    if not client or not company_id or not name:
        return ""
    try:
        res = client.rpc(
            "read_company_secret",
            {"p_company_id": company_id, "p_name": name},
        ).execute()
        return str(res.data or "").strip()
    except Exception as exc:
        logger.warning(
            "read_company_secret_by_name: %r falhou company=%s: %s",
            name,
            company_id[:8],
            exc,
        )
        return ""


def first_non_empty_from_sources(
    sources: list[dict[str, Any]],
    *keys: str,
) -> str:
    """Primeiro valor não vazio entre dicts, testando aliases de cada key."""
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            for alias in (key, key.lower(), key.upper()):
                val = source.get(alias)
                if val is not None and str(val).strip():
                    return str(val).strip()
    return ""
