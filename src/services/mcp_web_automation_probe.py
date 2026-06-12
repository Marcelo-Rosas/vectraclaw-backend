"""Smoke de login Playwright para handshake credential_only (mcp-web-automation)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger("McpWebAutomationProbe")


async def probe_planner_login_async(
    *,
    email: str,
    password: str,
    base_url: str,
    login_url: Optional[str] = None,
    nav_timeout_ms: int = 20_000,
) -> dict[str, Any]:
    """Tenta login real no Meu Planner (mesmo fluxo do Kronos)."""
    from src.agents.kronos_browser import KronosLoginFailed, KronosPlannerSession

    try:
        async with KronosPlannerSession(
            email=email,
            password=password,
            base_url=base_url,
            login_url=login_url,
            nav_timeout_ms=nav_timeout_ms,
        ):
            pass
        return {"ok": True, "message": "login_ok"}
    except KronosLoginFailed as exc:
        return {"ok": False, "message": str(exc), "errorType": "KronosLoginFailed"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("probe_planner_login falhou: %s", exc)
        return {"ok": False, "message": str(exc), "errorType": type(exc).__name__}


def probe_planner_login(
    *,
    email: str,
    password: str,
    base_url: str,
    login_url: Optional[str] = None,
) -> dict[str, Any]:
    """Wrapper síncrono para uso em endpoints FastAPI."""
    return asyncio.run(
        probe_planner_login_async(
            email=email,
            password=password,
            base_url=base_url,
            login_url=login_url,
        )
    )
