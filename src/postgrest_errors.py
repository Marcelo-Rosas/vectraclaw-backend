"""Re-export PostgREST APIError for Supabase handler exception handling.

Supabase installs `postgrest` as a transitive dependency. Several routes catch
`APIError` to map PostgREST failures (constraints, missing tables, etc.) to
HTTP responses. Import from here instead of `postgrest.exceptions` directly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:

    class PostgrestAPIError(Exception):
        """Stub for basedpyright when postgrest is not installed in the venv."""

        code: str | None
        message: str | None
        hint: str | None
        details: str | None

else:
    from postgrest.exceptions import APIError as PostgrestAPIError

__all__ = ["PostgrestAPIError"]
