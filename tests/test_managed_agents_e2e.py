"""
Testes E2E para execução CMA com mocks de Anthropic API e Supabase.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.managed_agents.managed_agent_client import ManagedAgentClient, ExecutionResult
from src.managed_agents.session_bridge import SessionBridge
from src.managed_agents.router import route_task_execution


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_task(operation_type="research", description="Pesquise frete aéreo"):
    return {
        "id": "task-e2e-001",
        "title": "Pesquisa logística",
        "description": description,
        "operation_type": operation_type,
        "budget_limit": 500,
        "company_id": "company-abc",
        "assigned_to_agent_id": "agent-xyz",
        "status": "queued",
        "executor_type": "auto",
    }


def _mock_anthropic_response(text="Resultado de teste", stop_reason="end_turn"):
    """Cria um mock de response da Anthropic Messages API."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = stop_reason
    response.usage = MagicMock(input_tokens=50, output_tokens=30)
    return response


# ---------------------------------------------------------------------------
# ManagedAgentClient unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_client_executes_simple_task():
    mock_response = _mock_anthropic_response("CBM: 0.15 m³")
    mock_anthropic = MagicMock()
    mock_anthropic.messages.create.return_value = mock_response

    client = ManagedAgentClient(anthropic_client=mock_anthropic)
    result = await client.execute_task("Calcule CBM de 50x30x20cm", max_turns=3)

    assert result.success is True
    assert result.content == "CBM: 0.15 m³"
    assert result.turn_count == 1
    assert result.tokens_input == 50
    assert result.tokens_output == 30


@pytest.mark.asyncio
async def test_client_handles_tool_use_turn():
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "calculate_cbm"
    tool_block.id = "tu-001"
    tool_block.input = {"length_cm": 50, "width_cm": 30, "height_cm": 20, "quantity": 1}

    turn1 = MagicMock()
    turn1.content = [tool_block]
    turn1.stop_reason = "tool_use"
    turn1.usage = MagicMock(input_tokens=40, output_tokens=10)

    final_block = MagicMock()
    final_block.type = "text"
    final_block.text = "CBM: 0.03 m³"
    turn2 = MagicMock()
    turn2.content = [final_block]
    turn2.stop_reason = "end_turn"
    turn2.usage = MagicMock(input_tokens=60, output_tokens=20)

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create.side_effect = [turn1, turn2]

    client = ManagedAgentClient(anthropic_client=mock_anthropic)
    result = await client.execute_task("Calcule CBM", max_turns=3)

    assert result.success is True
    assert result.turn_count == 2
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool_name"] == "calculate_cbm"
    assert result.tokens_input == 100
    assert result.tokens_output == 30


@pytest.mark.asyncio
async def test_client_handles_api_error():
    mock_anthropic = MagicMock()
    mock_anthropic.messages.create.side_effect = Exception("API timeout")

    client = ManagedAgentClient(anthropic_client=mock_anthropic)
    result = await client.execute_task("Faça X", max_turns=3)

    assert result.success is False
    assert result.error == "API timeout"


@pytest.mark.asyncio
async def test_client_respects_max_turns():
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "calculate_cbm"
    tool_block.id = "tu-loop"
    tool_block.input = {"length_cm": 10, "width_cm": 10, "height_cm": 10}

    looping_turn = MagicMock()
    looping_turn.content = [tool_block]
    looping_turn.stop_reason = "tool_use"
    looping_turn.usage = MagicMock(input_tokens=10, output_tokens=5)

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create.return_value = looping_turn

    client = ManagedAgentClient(anthropic_client=mock_anthropic)
    result = await client.execute_task("Loop infinito", max_turns=2)

    assert result.turn_count <= 2


# ---------------------------------------------------------------------------
# SessionBridge tests
# ---------------------------------------------------------------------------

def test_session_bridge_creates_and_loads_in_memory():
    bridge = SessionBridge(supabase_client=None)
    session_id = bridge.create_session("task-1", "agent-1", "claude-haiku-4-5-20251001")
    session = bridge.load_session(session_id)

    assert session is not None
    assert session["task_id"] == "task-1"
    assert session["status"] == "in_progress"


def test_session_bridge_completes_session():
    bridge = SessionBridge(supabase_client=None)
    session_id = bridge.create_session("task-2", "agent-2", "claude-haiku-4-5-20251001")
    bridge.complete_session(session_id, "Resultado final", tokens_input=50, tokens_output=30, success=True)
    session = bridge.load_session(session_id)

    assert session["status"] == "completed"
    assert session["final_output"] == "Resultado final"
    assert session["tokens_input"] == 50


def test_session_bridge_saves_turns():
    bridge = SessionBridge(supabase_client=None)
    session_id = bridge.create_session("task-3", "agent-3", "claude-haiku-4-5-20251001")
    bridge.save_turn(session_id, 1, "input text", "output text", "tool_use", "calculate_cbm", {})
    turns = bridge.list_turns(session_id)

    assert len(turns) >= 1
    assert turns[0]["turn_number"] == 1
    assert turns[0]["tool_used"] == "calculate_cbm"


# ---------------------------------------------------------------------------
# Router E2E test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cma_task_end_to_end():
    mock_response = _mock_anthropic_response("Frete aéreo custa R$2.500")
    mock_anthropic = MagicMock()
    mock_anthropic.messages.create.return_value = mock_response

    task = _make_task(operation_type="research")

    with patch("src.managed_agents.managed_agent_client.ManagedAgentClient._get_client", return_value=mock_anthropic):
        with patch("src.managed_agents.router.ManagedAgentClient") as MockClient:
            mock_client_instance = MagicMock()
            mock_client_instance.execute_task = AsyncMock(return_value=ExecutionResult(
                success=True,
                content="Frete aéreo custa R$2.500",
                tool_calls=[],
                turn_count=1,
                tokens_input=50,
                tokens_output=30,
                execution_time_seconds=1.2,
            ))
            MockClient.return_value = mock_client_instance

            result = await route_task_execution(
                task=task,
                force_mode="managed_agent",
                supabase_client=None,
                ws_manager=None,
            )

    assert result["executor_type"] == "managed_agent"
    assert result["status"] == "done"
    assert result["result"] == "Frete aéreo custa R$2.500"
    assert "session_id" in result


@pytest.mark.asyncio
async def test_harness_task_returns_queued():
    task = _make_task(operation_type="code_generation")

    result = await route_task_execution(
        task=task,
        force_mode="harness",
        supabase_client=None,
        ws_manager=None,
    )

    assert result["executor_type"] == "harness"
    assert result["status"] == "queued"


@pytest.mark.asyncio
async def test_websocket_events_emitted():
    mock_ws = MagicMock()
    mock_ws.emit_managed_agent_event = AsyncMock()

    task = _make_task(operation_type="research")

    with patch("src.managed_agents.router.ManagedAgentClient") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.execute_task = AsyncMock(return_value=ExecutionResult(
            success=True,
            content="Resultado",
            tool_calls=[],
            turn_count=1,
            tokens_input=10,
            tokens_output=10,
            execution_time_seconds=0.5,
        ))
        MockClient.return_value = mock_client_instance

        await route_task_execution(
            task=task,
            force_mode="managed_agent",
            supabase_client=None,
            ws_manager=mock_ws,
        )

    # Deve ter emitido pelo menos start + complete
    assert mock_ws.emit_managed_agent_event.call_count >= 2
    call_types = [c.kwargs.get("event_type") or c.args[1] for c in mock_ws.emit_managed_agent_event.call_args_list]
    assert "managed_agent_start" in call_types
    assert "managed_agent_complete" in call_types
