"""Coerce PostgREST / Supabase cell values (basedpyright-safe helpers)."""
from __future__ import annotations

from typing import Any, Dict, Optional, Set


def pg_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def pg_row(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    raise RuntimeError("postgrest_coerce: expected dict row from PostgREST")


def pg_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def pg_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def pg_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def pg_str_set(rows: Any, key: str) -> Set[str]:
    if not isinstance(rows, list):
        return set()
    out: Set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            cell = row.get(key)
            if cell is not None:
                out.add(str(cell))
    return out
