"""Montagem de payload companies — create/patch + shape de resposta HTTP."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

# Listagem segura antes/depois de 20260521110000_companies_cnpj_profile.sql (Regra Ouro #8).
COMPANIES_LIST_COLUMNS = "company_id,name,updated_at,tier,owner_user_id,mission"
COMPANIES_LIST_COLUMNS_WITH_CNPJ = (
    f"{COMPANIES_LIST_COLUMNS},cnpj,trade_name,cnpj_lookup_data"
)

_CNPJ_RE = re.compile(r"\D")


def _wire_iso_z(value: Union[None, str, datetime]) -> str:
    """Serializa timestamptz do Postgres para ISO-8601 com Z (contrato VectraClip)."""
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    s = str(value).strip()
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    if s.endswith("+00") and not s.endswith("+00:00"):
        s = f"{s}:00"
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sanitize_cnpj_digits(raw: Optional[str]) -> Optional[str]:
    """14 dígitos ou None."""
    if not raw:
        return None
    digits = _CNPJ_RE.sub("", str(raw))
    return digits if len(digits) == 14 else None


def pick_trade_name(cnpj_data: Optional[Dict[str, Any]], fallback_name: str) -> Optional[str]:
    if not cnpj_data:
        return None
    tn = (cnpj_data.get("trade_name") or "").strip()
    return tn or None


def build_company_insert_row(
    *,
    name: str,
    mission: Optional[str] = None,
    tier: str = "trial",
    owner_user_id: Optional[str] = None,
    cnpj: Optional[str] = None,
    cnpj_data: Optional[Dict[str, Any]] = None,
    updated_at: str,
) -> Dict[str, Any]:
    """Linha para INSERT em vectraclip.companies."""
    row: Dict[str, Any] = {
        "name": name.strip(),
        "tier": tier,
        "updated_at": updated_at,
    }
    if owner_user_id:
        row["owner_user_id"] = owner_user_id
    if mission and str(mission).strip():
        row["mission"] = str(mission).strip()

    digits = sanitize_cnpj_digits(cnpj)
    if not digits and cnpj_data:
        digits = sanitize_cnpj_digits(cnpj_data.get("cnpj"))
    if digits:
        row["cnpj"] = digits
    if cnpj_data:
        row["cnpj_lookup_data"] = cnpj_data
        trade = pick_trade_name(cnpj_data, name)
        if trade:
            row["trade_name"] = trade

    return row


def strip_cnpj_columns_for_insert(row: Dict[str, Any]) -> Dict[str, Any]:
    """Remove campos CNPJ se migration ainda não aplicada (insert não quebra)."""
    return {
        k: v
        for k, v in row.items()
        if k not in ("cnpj", "trade_name", "cnpj_lookup_data")
    }


def company_row_to_api(
    row: Dict[str, Any],
    *,
    owner_fallback: Optional[str] = None,
    members: Optional[list] = None,
    slug: Optional[str] = None,
) -> Dict[str, Any]:
    """DB row → contrato Zod do frontend (Company)."""
    from src.tenant_ids import company_row_public_id

    cid = company_row_public_id(row)
    name = row.get("name") or ""
    owner_id = row.get("owner_user_id") or owner_fallback or ""
    created_raw = row.get("created_at") or row.get("updated_at")
    created_iso = _wire_iso_z(created_raw)

    out: Dict[str, Any] = {
        "id": cid,
        "name": name,
        "mission": row.get("mission") or "",
        "ownerUserId": owner_id,
        "slug": slug or _slugify(name),
        "members": members
        or [{"userId": owner_id, "role": "admin", "joinedAt": created_iso}],
        "createdAt": created_iso,
        "tier": row.get("tier") or "trial",
    }
    if row.get("cnpj"):
        out["cnpj"] = row["cnpj"]
    if row.get("trade_name"):
        out["tradeName"] = row["trade_name"]
    if row.get("cnpj_lookup_data"):
        out["cnpjLookupData"] = row["cnpj_lookup_data"]
    return out


def _slugify(name: str) -> str:
    import re as _re

    return _re.sub(r"-{2,}", "-", _re.sub(r"[^a-z0-9]+", "-", (name or "").lower())).strip("-") or "company"


_PLATFORM_PROVISION_ROLES = frozenset({"platform_admin", "consultant"})


def assert_can_provision_company(role: Optional[str]) -> None:
    """Console de plataforma: só roles globais criam tenant novo."""
    from fastapi import HTTPException

    if (role or "").lower() not in _PLATFORM_PROVISION_ROLES:
        raise HTTPException(
            status_code=403,
            detail="provision_company_requires_platform_admin_or_consultant",
        )


def should_list_all_companies(role: Optional[str]) -> bool:
    return (role or "").lower() in _PLATFORM_PROVISION_ROLES
