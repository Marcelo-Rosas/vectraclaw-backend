"""Coerção de células PostgREST/Supabase para tipos Python (basedpyright-safe).

PostgREST tipa `res.data` como `JSON` (str | int | float | dict | list | …).
Nunca atribua `row["col"]` direto a `str`, `dict` ou `set[str]` — use os helpers
deste módulo (Regra de Ouro #9, docs/CODE-PATTERNS.md P12).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def pg_dict(value: Any) -> Dict[str, Any]:
    """JSONB / objeto de row → dict; qualquer outro tipo → {}."""
    return value if isinstance(value, dict) else {}


def pg_list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    """res.data (list of rows) → List[Dict[str, Any]]; filtra não-dicts."""
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def pg_str(value: Any) -> str:
    """Célula escalar → str (UUID, texto, número como string)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def pg_optional_str(value: Any) -> Optional[str]:
    """Célula opcional → str | None (string vazia vira None)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    return str(value)


def pg_row(value: Any) -> Optional[Dict[str, Any]]:
    """Primeiro elemento de res.data → dict | None."""
    return value if isinstance(value, dict) else None


def pg_int(value: Any, default: int = 0) -> int:
    """Inteiro de coluna numérica (ex.: step_order)."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def pg_str_set(rows: Any, key: str = "id") -> set[str]:
    """Conjunto de strings hasháveis a partir de res.data (ex.: ids de catálogo)."""
    out: set[str] = set()
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        v = row.get(key)
        if isinstance(v, str) and v:
            out.add(v)
    return out
