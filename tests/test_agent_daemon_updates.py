"""
Testes para as modificações no ResilientHarnessDaemon:
- should_skip_task() retorna True para tasks CMA
- fetch_next_task() não retorna tasks com executor_type=managed_agent
- Funcionalidade existente não quebrada
"""
import pytest
from unittest.mock import MagicMock, patch
from src.agent_daemon import ResilientHarnessDaemon


def _make_daemon():
    with patch.dict("os.environ", {"AGENT_ID": "agent-test-001"}):
        d = ResilientHarnessDaemon(polling_interval=1)
    return d


# ---------------------------------------------------------------------------
# should_skip_task
# ---------------------------------------------------------------------------

def test_daemon_skips_cma_tasks():
    daemon = _make_daemon()
    task = {"id": "t1", "executor_type": "managed_agent"}
    assert daemon.should_skip_task(task) is True


def test_daemon_does_not_skip_harness_tasks():
    daemon = _make_daemon()
    task = {"id": "t2", "executor_type": "harness"}
    assert daemon.should_skip_task(task) is False


def test_daemon_does_not_skip_auto_tasks():
    daemon = _make_daemon()
    task = {"id": "t3", "executor_type": "auto"}
    assert daemon.should_skip_task(task) is False


def test_daemon_does_not_skip_task_without_executor_type():
    daemon = _make_daemon()
    task = {"id": "t4"}  # campo ausente → default auto
    assert daemon.should_skip_task(task) is False


# ---------------------------------------------------------------------------
# fetch_next_task (com mock Supabase)
# ---------------------------------------------------------------------------

def test_daemon_processes_harness_tasks():
    daemon = _make_daemon()

    mock_res = MagicMock()
    mock_res.data = [{"id": "t-harness", "executor_type": "harness", "title": "Do X"}]

    mock_supabase = MagicMock()
    (
        mock_supabase.table.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .neq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ) = mock_res

    daemon._supabase = mock_supabase
    result = daemon.fetch_next_task()

    assert result is not None
    assert result["id"] == "t-harness"


def test_fetch_next_task_returns_none_when_no_tasks():
    daemon = _make_daemon()

    mock_res = MagicMock()
    mock_res.data = []

    mock_supabase = MagicMock()
    (
        mock_supabase.table.return_value
        .select.return_value
        .eq.return_value
        .eq.return_value
        .neq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ) = mock_res

    daemon._supabase = mock_supabase
    result = daemon.fetch_next_task()

    assert result is None


def test_fetch_next_task_applies_neq_executor_type_filter():
    """Verifica que fetch_next_task chama .neq('executor_type', 'managed_agent')."""
    daemon = _make_daemon()

    mock_table = MagicMock()
    mock_res = MagicMock()
    mock_res.data = []

    chain = mock_table.select.return_value.eq.return_value.eq.return_value.neq.return_value
    chain.order.return_value.limit.return_value.execute.return_value = mock_res

    mock_supabase = MagicMock()
    mock_supabase.table.return_value = mock_table
    daemon._supabase = mock_supabase

    daemon.fetch_next_task()

    # neq() deve ter sido chamado com ("executor_type", "managed_agent")
    neq_call = chain.order.return_value.limit.return_value.execute
    mock_table.select.return_value.eq.return_value.eq.return_value.neq.assert_called_once_with(
        "executor_type", "managed_agent"
    )


# ---------------------------------------------------------------------------
# Garantia de retrocompatibilidade
# ---------------------------------------------------------------------------

def test_existing_claim_task_unaffected():
    daemon = _make_daemon()

    mock_res = MagicMock()
    mock_res.data = [{"id": "t-claimed"}]

    mock_supabase = MagicMock()
    (
        mock_supabase.table.return_value
        .update.return_value
        .eq.return_value
        .eq.return_value
        .execute.return_value
    ) = mock_res

    daemon._supabase = mock_supabase
    result = daemon._claim_task("t-claimed")
    assert result is True


def test_existing_complete_task_unaffected():
    daemon = _make_daemon()
    mock_supabase = MagicMock()
    daemon._supabase = mock_supabase
    # Não deve lançar exceção
    daemon._complete_task("t-done", success=True)
    mock_supabase.table.return_value.update.assert_called()
