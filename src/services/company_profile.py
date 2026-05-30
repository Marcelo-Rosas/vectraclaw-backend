"""RBAC helpers for company list / portfolio scope (VEC-168)."""
from __future__ import annotations

from typing import Optional


def should_list_all_companies(role: Optional[str]) -> bool:
    """True when role may see all tenants (mirrors get_companies portfolio view)."""
    return (role or "").lower() in ("platform_admin", "consultant")
