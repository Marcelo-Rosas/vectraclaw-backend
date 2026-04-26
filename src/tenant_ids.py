"""Helpers para IDs multi-tenant (PostgREST / API compat)."""
from __future__ import annotations

from typing import Any, Dict, Optional


def company_row_public_id(row: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    UUID público da empresa para JSON da API (Fase 1).

    No Postgres após vec_249 a PK é `company_id`; antes era `id`.
    Retorna o valor estável para expor como `id` no contrato HTTP.
    """
    if not row:
        return None
    v = row.get("company_id") or row.get("id")
    return str(v) if v is not None else None
