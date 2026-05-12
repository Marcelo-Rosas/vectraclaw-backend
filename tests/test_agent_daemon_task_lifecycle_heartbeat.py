"""Testes do _emit_task_lifecycle_heartbeat (VEC-429 Fase 1)."""
from __future__ import annotations

from unittest.mock import MagicMock


def _build_daemon(monkeypatch, agent_id="9c8d7e6f-5a4b-4321-9876-543210fedcba"):
    monkeypatch.setenv("AGENT_ID", agent_id)
    from src.agent_daemon import ResilientHarnessDaemon
    return ResilientHarnessDaemon()


def _mock_supabase(company_id="cid-vec"):
    sb = MagicMock()
    agents_table = MagicMock()
    agents_table.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"company_id": company_id},
    )
    heartbeats_table = MagicMock()
    heartbeats_table.insert.return_value.execute.return_value = MagicMock(data=[{"id": "hb-X"}])
    tasks_table = MagicMock()
    # PATCH retornar data (claim ok)
    tasks_table.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "t-1"}]
    )
    tasks_table.update.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "t-1"}]
    )

    def _route(name):
        return {"agents": agents_table, "heartbeats": heartbeats_table, "tasks": tasks_table}.get(name, MagicMock())

    sb.table.side_effect = _route
    return sb, heartbeats_table, tasks_table


def test_emit_task_lifecycle_heartbeat_working(monkeypatch):
    """Emite heartbeat com task_id, agent_id, status=working e log_excerpt customizado."""
    d = _build_daemon(monkeypatch)
    sb, hb_table, _ = _mock_supabase()
    d._supabase = sb

    d._emit_task_lifecycle_heartbeat(
        task_id="task-aaa",
        status="working",
        company_id="cid-vec",
        operation_type="planner-import-ofx",
        log_excerpt="executing planner-import-ofx",
    )

    hb_table.insert.assert_called_once()
    row = hb_table.insert.call_args.args[0]
    assert row["task_id"] == "task-aaa"
    assert row["agent_id"] == "9c8d7e6f-5a4b-4321-9876-543210fedcba"
    assert row["status"] == "working"
    assert row["company_id"] == "cid-vec"
    assert row["log_excerpt"] == "executing planner-import-ofx"
    assert row["cost_usd"] == 0


def test_emit_task_lifecycle_heartbeat_terminal_working(monkeypatch):
    """Heartbeat terminal de sucesso é status='working' (CHECK constraint
    do schema só aceita working|idle|paused|errored|offline). Distinção
    claim vs end fica em log_excerpt."""
    d = _build_daemon(monkeypatch)
    sb, hb_table, _ = _mock_supabase()
    d._supabase = sb

    d._emit_task_lifecycle_heartbeat(
        task_id="task-bbb",
        status="working",
        company_id="cid-vec",
        operation_type="oracle-report",
        log_excerpt="task done: oracle-report",
        cost_usd=0.0042,
    )

    row = hb_table.insert.call_args.args[0]
    assert row["status"] == "working"
    assert row["task_id"] == "task-bbb"
    assert row["log_excerpt"] == "task done: oracle-report"
    assert abs(row["cost_usd"] - 0.0042) < 1e-9


def test_emit_task_lifecycle_heartbeat_fetches_company_when_missing(monkeypatch):
    """Se company_id não vier, faz fetch via agents.select()."""
    d = _build_daemon(monkeypatch)
    sb, hb_table, _ = _mock_supabase(company_id="cid-fetched")
    d._supabase = sb
    # garante que cache do agent_config está vazio
    d._agent_config = {}

    d._emit_task_lifecycle_heartbeat(
        task_id="task-ccc",
        status="working",
    )

    row = hb_table.insert.call_args.args[0]
    assert row["company_id"] == "cid-fetched"
    # cache deve ter sido populado
    assert d._agent_config.get("company_id") == "cid-fetched"


def test_emit_task_lifecycle_heartbeat_skips_when_no_task_id(monkeypatch):
    """Sem task_id ou agent_id, não emite."""
    d = _build_daemon(monkeypatch)
    sb, hb_table, _ = _mock_supabase()
    d._supabase = sb

    d._emit_task_lifecycle_heartbeat(task_id="", status="working")
    hb_table.insert.assert_not_called()


def test_complete_task_emits_lifecycle_heartbeat(monkeypatch):
    """_complete_task chama _emit_task_lifecycle_heartbeat com status compatível
    com o CHECK constraint do schema: working (sucesso) / errored (falha)."""
    d = _build_daemon(monkeypatch)
    sb, hb_table, tasks_table = _mock_supabase()
    d._supabase = sb

    # Sucesso → status='working' + log diferenciado
    d._complete_task(
        "task-OK",
        success=True,
        cost_usd=0.01,
        task_meta={"company_id": "cid-vec", "operation_type": "planner-import-ofx"},
    )
    success_row = hb_table.insert.call_args_list[-1].args[0]
    assert success_row["status"] == "working"
    assert success_row["task_id"] == "task-OK"
    assert success_row["company_id"] == "cid-vec"
    assert "task done" in success_row["log_excerpt"]
    assert abs(success_row["cost_usd"] - 0.01) < 1e-9

    # Falha → status='errored'
    d._complete_task(
        "task-FAIL",
        success=False,
        task_meta={"company_id": "cid-vec", "operation_type": "planner-import-ofx"},
    )
    fail_row = hb_table.insert.call_args_list[-1].args[0]
    assert fail_row["status"] == "errored"
    assert fail_row["task_id"] == "task-FAIL"
    assert "task blocked" in fail_row["log_excerpt"]
