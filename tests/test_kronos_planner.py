"""Tests for `src.agents.kronos_planner` (VEC-419 / sub-PR2 of VEC-416).

Unit tests with mocked KronosPlannerSession — sempre rodam. Sem live smoke
aqui (depende de OFX real + UI ativa; vai pro VEC-420 quando categorização
estiver implementada).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest  # pyright: ignore[reportMissingImports]


# ── Helpers ──────────────────────────────────────────────────────────


def _mock_routines_select(metadata):
    """Mock do supabase_client.table('routines').select(...).eq(...).limit(...).execute()."""
    mock_client = MagicMock()
    chain = (
        mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value
    )
    chain.execute.return_value.data = [{"metadata": metadata}]
    return mock_client


def _make_task(*, ofx_path: str, routine_id: str = "rtn-1") -> dict:
    return {
        "id": "task-1",
        "company_id": "co-1",
        "operation_type": "planner-import-ofx",
        "description": "",
        "input_json": {
            "OFX_PATH": ofx_path,
            "routine_id": routine_id,
        },
    }


# ── No-op flow (sem arquivo novo) ────────────────────────────────────


def test_returns_done_no_new_files_when_directory_empty(tmp_path):
    from src.agents.kronos_planner import entrypoint_planner_import

    task = _make_task(ofx_path=str(tmp_path), routine_id="rtn-empty")
    client = _mock_routines_select({"lastProcessedOfx": "semana-1-maio-26.ofx"})

    result = entrypoint_planner_import(task, client)

    assert result["status"] == "done"
    assert result["output_json"]["reason"] == "no_new_files"
    assert result["output_json"]["cursor"] == "semana-1-maio-26.ofx"


def test_returns_done_no_new_files_when_cursor_caught_up(tmp_path):
    from src.agents.kronos_planner import entrypoint_planner_import

    (tmp_path / "semana-1-maio-26.ofx").write_text("")
    (tmp_path / "semana-2-maio-26.ofx").write_text("")

    task = _make_task(ofx_path=str(tmp_path), routine_id="rtn-caught")
    client = _mock_routines_select({"lastProcessedOfx": "semana-2-maio-26.ofx"})

    result = entrypoint_planner_import(task, client)

    assert result["status"] == "done"
    assert result["output_json"]["reason"] == "no_new_files"


# ── Erro de configuração ─────────────────────────────────────────────


def test_returns_errored_when_ofx_path_missing(monkeypatch):
    from src.agents.kronos_planner import entrypoint_planner_import

    # Sem OFX_PATH em input_json, description ou env
    monkeypatch.delenv("OFX_PATH", raising=False)
    monkeypatch.delenv("KRONOS_OFX_PATH", raising=False)
    task = {
        "id": "task-x",
        "description": "",
        "input_json": {"routine_id": "rtn-1"},
    }

    result = entrypoint_planner_import(task, _mock_routines_select(None))

    assert result["status"] == "errored"
    assert "OFX_PATH" in result["output_json"]["error_detail"]["message"]


def test_returns_errored_when_ofx_path_does_not_exist():
    from src.agents.kronos_planner import entrypoint_planner_import

    task = _make_task(
        ofx_path=r"C:\path\que\nao\existe\semana-1-maio-26.ofx",
        routine_id="rtn-1",
    )
    result = entrypoint_planner_import(task, _mock_routines_select(None))

    assert result["status"] == "errored"
    assert "não existe" in result["output_json"]["error_detail"]["message"]


# ── Pick file logic (sem session) ────────────────────────────────────


def test_picks_first_file_when_no_cursor(tmp_path):
    from src.agents.kronos_planner import _pick_target_file

    (tmp_path / "semana-1-maio-26.ofx").write_text("")
    (tmp_path / "semana-2-maio-26.ofx").write_text("")

    picked = _pick_target_file(tmp_path, None)
    assert picked is not None
    assert picked.name == "semana-1-maio-26.ofx"


def test_picks_file_directly_when_path_is_file(tmp_path):
    from src.agents.kronos_planner import _pick_target_file

    target = tmp_path / "extrato-arbitrario.ofx"
    target.write_text("")

    picked = _pick_target_file(target, None)
    assert picked == target


def test_picks_next_file_after_cursor(tmp_path):
    from src.agents.kronos_planner import _pick_target_file

    (tmp_path / "semana-1-maio-26.ofx").write_text("")
    (tmp_path / "semana-2-maio-26.ofx").write_text("")
    (tmp_path / "semana-3-maio-26.ofx").write_text("")

    picked = _pick_target_file(tmp_path, "semana-2-maio-26.ofx")
    assert picked is not None
    assert picked.name == "semana-3-maio-26.ofx"


# ── Cursor read/write paths ──────────────────────────────────────────


def test_read_cursor_returns_none_without_routine_id(tmp_path):
    from src.agents.kronos_planner import _read_cursor

    assert _read_cursor(_mock_routines_select({}), None) is None
    assert _read_cursor(None, "rtn-1") is None


def test_write_cursor_noop_without_routine_id():
    from src.agents.kronos_planner import _write_cursor

    client = MagicMock()
    _write_cursor(client, None, "semana-3-maio-26.ofx")
    client.table.assert_not_called()


# ── Errored mapping ──────────────────────────────────────────────────


def test_errored_helper_shape():
    from src.agents.kronos_planner import _errored

    result = _errored("boom", exception="KronosSaveTimeout", extra={"file": "x.ofx"})

    assert result["status"] == "errored"
    assert result["error"] == "boom"
    assert result["output_json"]["error_detail"]["message"] == "boom"
    assert result["output_json"]["error_detail"]["exception"] == "KronosSaveTimeout"
    assert result["output_json"]["error_detail"]["file"] == "x.ofx"


# ── Session integration (mocked) ─────────────────────────────────────


def _make_mock_session():
    """Cria um async-context-manager mock que simula KronosPlannerSession."""
    session = MagicMock()
    session.page = MagicMock()

    async def aenter(*_a, **_kw):
        return session

    async def aexit(*_a, **_kw):
        return False

    session.__aenter__ = aenter
    session.__aexit__ = aexit
    session.dismiss_known_modals = AsyncMock(return_value=None)
    session.wait_for_loading_overlay = AsyncMock(return_value=None)
    session.wait_for_save_toast = AsyncMock(return_value="Importado com sucesso.")
    session.screenshot = AsyncMock(return_value=Path("audit-results/fake.png"))

    # Page.locator(...).first.click / wait_for / select_option / set_input_files
    page_locator = MagicMock()
    locator_first = MagicMock()
    locator_first.click = AsyncMock(return_value=None)
    locator_first.wait_for = AsyncMock(return_value=None)
    locator_first.count = AsyncMock(return_value=1)
    locator_first.select_option = AsyncMock(return_value=None)
    locator_first.set_input_files = AsyncMock(return_value=None)
    page_locator.first = locator_first
    page_locator.wait_for = AsyncMock(return_value=None)
    session.page.locator = MagicMock(return_value=page_locator)
    session.page.goto = AsyncMock(return_value=None)

    return session


def test_successful_import_updates_cursor(tmp_path):
    from src.agents import kronos_planner

    (tmp_path / "semana-1-maio-26.ofx").write_text("dummy")

    task = _make_task(ofx_path=str(tmp_path), routine_id="rtn-OK")
    client = _mock_routines_select(None)  # sem cursor → pega primeiro

    fake_session = _make_mock_session()

    with patch.object(
        kronos_planner, "KronosPlannerSession", return_value=fake_session
    ):
        result = kronos_planner.entrypoint_planner_import(task, client)

    assert result["status"] == "done"
    assert result["output_json"]["file_processed"] == "semana-1-maio-26.ofx"
    assert result["output_json"]["next_cursor"] == "semana-1-maio-26.ofx"

    # Confirma que update foi chamado no metadata
    update_call = client.table.return_value.update.call_args[0][0]
    assert update_call["metadata"]["lastProcessedOfx"] == "semana-1-maio-26.ofx"


def test_save_timeout_propagates_to_errored(tmp_path):
    from src.agents import kronos_planner
    from src.agents.kronos_browser import KronosSaveTimeout

    (tmp_path / "semana-1-maio-26.ofx").write_text("dummy")
    task = _make_task(ofx_path=str(tmp_path), routine_id="rtn-fail")
    client = _mock_routines_select(None)

    fake_session = _make_mock_session()

    # Faz _do_import_flow levantar KronosSaveTimeout
    async def fail(*_a, **_kw):
        raise KronosSaveTimeout("modal não fechou")

    with patch.object(
        kronos_planner, "KronosPlannerSession", return_value=fake_session
    ), patch.object(kronos_planner, "_do_import_flow", side_effect=fail):
        result = kronos_planner.entrypoint_planner_import(task, client)

    assert result["status"] == "errored"
    detail = result["output_json"]["error_detail"]
    assert detail["exception"] == "KronosSaveTimeout"
    assert "não fechou" in detail["message"]
    assert detail["file"] == "semana-1-maio-26.ofx"
    # Cursor NÃO foi atualizado em falha
    client.table.return_value.update.assert_not_called()
