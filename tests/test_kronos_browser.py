"""Tests for `src.agents.kronos_browser` (VEC-418 / sub-PR1 of VEC-416).

Two layers:

- **Unit tests** — sempre rodam. Validam configuração, leitura de env, paths.
- **Live smoke** — gated pelo env `KRONOS_PLANNER_LIVE_SMOKE=true`.
  Faz login real no Meu Planner Financeiro e tira screenshot da `/inicio`.
  Read-only — não modifica dados.

Para rodar tudo localmente com playwright instalado e Chromium baixado::

    pip install playwright>=1.40.0
    playwright install chromium
    pytest tests/test_kronos_browser.py -q

Para incluir o smoke real (precisa de PLANNER_EMAIL/PLANNER_PASSWORD no .env)::

    KRONOS_PLANNER_LIVE_SMOKE=true pytest tests/test_kronos_browser.py -q -s
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]


# ── Unit tests ───────────────────────────────────────────────────────


def test_session_raises_when_creds_missing(monkeypatch):
    monkeypatch.delenv("PLANNER_EMAIL", raising=False)
    monkeypatch.delenv("PLANNER_PASSWORD", raising=False)
    from src.agents.kronos_browser import (
        KronosBrowserConfigError,
        KronosPlannerSession,
    )

    with pytest.raises(KronosBrowserConfigError):
        KronosPlannerSession()


def test_session_accepts_explicit_creds(monkeypatch):
    monkeypatch.delenv("PLANNER_EMAIL", raising=False)
    monkeypatch.delenv("PLANNER_PASSWORD", raising=False)
    from src.agents.kronos_browser import KronosPlannerSession

    session = KronosPlannerSession(email="foo@bar.com", password="secret")
    assert session.email == "foo@bar.com"
    assert session.password == "secret"


def test_session_reads_creds_from_env(monkeypatch):
    monkeypatch.setenv("PLANNER_EMAIL", "env@example.com")
    monkeypatch.setenv("PLANNER_PASSWORD", "env-secret")
    from src.agents.kronos_browser import KronosPlannerSession

    session = KronosPlannerSession()
    assert session.email == "env@example.com"
    assert session.password == "env-secret"


def test_session_default_storage_state_path():
    from src.agents.kronos_browser import KronosPlannerSession

    session = KronosPlannerSession(email="x", password="y")
    assert session.storage_state_path.name == "state.json"
    assert session.storage_state_path.parent.name == ".kronos-browser-storage"


def test_session_accepts_custom_storage_path(tmp_path: Path):
    from src.agents.kronos_browser import KronosPlannerSession

    custom = tmp_path / "custom-state.json"
    session = KronosPlannerSession(
        email="x", password="y", storage_state_path=custom
    )
    assert session.storage_state_path == custom


def test_session_default_headless_when_env_unset(monkeypatch):
    monkeypatch.delenv("KRONOS_PLAYWRIGHT_HEADED", raising=False)
    from src.agents.kronos_browser import KronosPlannerSession

    session = KronosPlannerSession(email="x", password="y")
    assert session.headless is True


def test_session_headed_when_env_truthy(monkeypatch):
    monkeypatch.setenv("KRONOS_PLAYWRIGHT_HEADED", "true")
    from src.agents.kronos_browser import KronosPlannerSession

    session = KronosPlannerSession(email="x", password="y")
    assert session.headless is False


def test_session_headed_explicit_overrides_env(monkeypatch):
    monkeypatch.setenv("KRONOS_PLAYWRIGHT_HEADED", "true")
    from src.agents.kronos_browser import KronosPlannerSession

    session = KronosPlannerSession(email="x", password="y", headless=True)
    assert session.headless is True


def test_require_page_raises_outside_context_manager():
    from src.agents.kronos_browser import (
        KronosBrowserError,
        KronosPlannerSession,
    )

    session = KronosPlannerSession(email="x", password="y")
    with pytest.raises(KronosBrowserError):
        session._require_page()  # type: ignore[attr-defined]


# ── Live smoke (gated) ───────────────────────────────────────────────


@pytest.mark.skipif(
    os.getenv("KRONOS_PLANNER_LIVE_SMOKE", "").lower()
    not in ("true", "1", "yes", "on"),
    reason="KRONOS_PLANNER_LIVE_SMOKE não setado — smoke real do Meu Planner pulado",
)
def test_session_live_smoke():
    """Login real + screenshot de `/inicio`. Read-only, não modifica dados."""
    from src.agents.kronos_browser import (
        PLANNER_HOME_URL,
        KronosPlannerSession,
    )

    async def _run():
        async with KronosPlannerSession() as session:
            assert session.page is not None
            assert "/inicio" in session.page.url
            await session.dismiss_known_modals()
            screenshot = await session.screenshot("live-smoke")
            assert screenshot.exists()
            assert screenshot.stat().st_size > 0
            return screenshot

    path = asyncio.run(_run())
    assert path.exists()
    # cleanup opcional — deixa o artifact pra inspeção manual
