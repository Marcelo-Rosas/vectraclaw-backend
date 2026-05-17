"""
Testes unitários do OllamaAgentClient.

Mockam `openai.OpenAI` substituindo o símbolo no módulo do cliente — nenhum
teste toca rede; podem rodar em CI sem servidor Ollama local.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_response(content=None, tool_calls=None, prompt_tokens=10, completion_tokens=5):
    """Constrói um objeto compatível com `openai.types.ChatCompletion`."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    choice = MagicMock(message=msg)
    usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    response = MagicMock(choices=[choice], usage=usage)
    return response


def _mk_tool_call(id_, name, args):
    """Constrói um tool_call (formato OpenAI). NÃO usar `MagicMock(name=...)`
    no construtor — `name` é reservado pelo MagicMock. Atribuir após criar."""
    function = MagicMock()
    function.name = name
    function.arguments = json.dumps(args)
    tc = MagicMock()
    tc.id = id_
    tc.function = function
    return tc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_openai(monkeypatch):
    """Substitui `OpenAI` no módulo do cliente — nenhum teste cria HTTP real."""
    mock_client = MagicMock()
    monkeypatch.setattr(
        "src.managed_agents.ollama_agent_client.OpenAI",
        lambda **kw: mock_client,
    )
    return mock_client


# ---------------------------------------------------------------------------
# 1. Resposta direta sem tool calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_task_direct_response(mock_openai):
    from src.managed_agents.ollama_agent_client import OllamaAgentClient

    mock_openai.chat.completions.create.return_value = _mk_response(content="ok")

    client = OllamaAgentClient(config={"model_id": "llama3.2"})
    result = await client.execute_task("olá")

    assert result.success is True
    assert result.content == "ok"
    assert result.turn_count == 1
    assert result.tokens_input == 10
    assert result.tokens_output == 5


# ---------------------------------------------------------------------------
# 2. Loop tool_use → tool_result → resposta. Verifica que NÃO há double-encode.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_task_with_tool_call(mock_openai):
    from src.managed_agents.ollama_agent_client import OllamaAgentClient

    tc = _mk_tool_call(id_="tc1", name="calculate_cbm", args={"length_cm": 10})
    mock_openai.chat.completions.create.side_effect = [
        _mk_response(tool_calls=[tc]),
        _mk_response(content="resultado"),
    ]

    with patch(
        "src.managed_agents.ollama_agent_client.dispatch_tool_call",
        return_value='{"cbm": 0.001}',
    ) as mock_dispatch:
        client = OllamaAgentClient(config={"model_id": "llama3.2"})
        result = await client.execute_task("calcule")

    mock_dispatch.assert_called_once_with(
        tool_name="calculate_cbm",
        tool_input={"length_cm": 10},
    )

    # Verifica que o content da role=tool é a string crua de dispatch_tool_call
    second_call_kwargs = mock_openai.chat.completions.create.call_args_list[1].kwargs
    msgs = second_call_kwargs["messages"]
    tool_msg = next(m for m in msgs if isinstance(m, dict) and m.get("role") == "tool")
    assert tool_msg["content"] == '{"cbm": 0.001}'  # NÃO json.dumps disso

    assert result.success is True
    assert result.turn_count == 2
    assert result.content == "resultado"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["tool_name"] == "calculate_cbm"
    assert result.tool_calls[0]["tool_output"] == '{"cbm": 0.001}'


# ---------------------------------------------------------------------------
# 3. _MAX_TURNS guard — modelo sem tool support entraria em loop infinito
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_max_turns_guard(mock_openai):
    from src.managed_agents.ollama_agent_client import OllamaAgentClient, _MAX_TURNS

    tc = _mk_tool_call(id_="tc1", name="calculate_cbm", args={})
    mock_openai.chat.completions.create.return_value = _mk_response(tool_calls=[tc])

    with patch(
        "src.managed_agents.ollama_agent_client.dispatch_tool_call",
        return_value="{}",
    ):
        client = OllamaAgentClient(config={"model_id": "llama3.2"})
        result = await client.execute_task("loop")

    assert result.success is False
    assert "limite" in (result.error or "").lower()
    assert mock_openai.chat.completions.create.call_count == _MAX_TURNS


# ---------------------------------------------------------------------------
# 4. Ollama offline → APIConnectionError → mensagem clara ao operador
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ollama_offline_returns_clear_error(mock_openai):
    import openai
    from src.managed_agents.ollama_agent_client import OllamaAgentClient

    mock_openai.chat.completions.create.side_effect = openai.APIConnectionError(
        request=MagicMock(),
    )

    client = OllamaAgentClient(config={"model_id": "llama3.2", "base_url": "http://localhost:11434/v1"})
    result = await client.execute_task("teste")

    assert result.success is False
    assert "inacessível" in result.error.lower()
    assert "ollama serve" in result.error.lower()


# ---------------------------------------------------------------------------
# 5. usage=None ou tokens=None — não pode lançar TypeError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_counting_handles_none_usage(mock_openai):
    from src.managed_agents.ollama_agent_client import OllamaAgentClient

    resp = _mk_response(content="ok")
    resp.usage = None
    mock_openai.chat.completions.create.return_value = resp

    client = OllamaAgentClient(config={"model_id": "llama3.2"})
    result = await client.execute_task("teste")

    assert result.success is True
    assert result.tokens_input == 0
    assert result.tokens_output == 0


# ---------------------------------------------------------------------------
# 6. Tool capability — capacidade saiu do client (PR #194).
# Agora vem de vectraclip.llm_models.supports_tool_calling, lido por
# src.services.llm_cost.is_tool_capable. Tests dessa lógica vivem em
# tests/test_llm_cost.py.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Comportamento de fallback do base_url (decisão híbrida)
# ---------------------------------------------------------------------------

def test_base_url_falls_back_to_env_when_config_empty(mock_openai, monkeypatch):
    from src.managed_agents.ollama_agent_client import OllamaAgentClient

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://remote-ollama:11434/v1")
    client = OllamaAgentClient(config={"model_id": "llama3.2"})
    assert client._base_url == "http://remote-ollama:11434/v1"


def test_base_url_uses_config_when_provided(mock_openai, monkeypatch):
    from src.managed_agents.ollama_agent_client import OllamaAgentClient

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://should-be-overridden:11434/v1")
    client = OllamaAgentClient(config={"model_id": "llama3.2", "base_url": "http://my-ollama:9000/v1"})
    assert client._base_url == "http://my-ollama:9000/v1"


def test_base_url_default_localhost_when_no_config_and_no_env(mock_openai, monkeypatch):
    from src.managed_agents.ollama_agent_client import OllamaAgentClient

    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    client = OllamaAgentClient(config={"model_id": "llama3.2"})
    assert client._base_url == "http://localhost:11434/v1"


# ---------------------------------------------------------------------------
# tokens_per_second populado a partir de eval time + completion_tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tokens_per_second_calculated(mock_openai):
    from src.managed_agents.ollama_agent_client import OllamaAgentClient

    mock_openai.chat.completions.create.return_value = _mk_response(
        content="ok",
        prompt_tokens=20,
        completion_tokens=40,
    )

    client = OllamaAgentClient(config={"model_id": "llama3.2"})
    result = await client.execute_task("teste")

    # Mock retorna instantâneo, mas o `max(total_eval_seconds, 0.001)` garante
    # que tps seja sempre finito e positivo (40 / 0.001 = 40000 no pior caso).
    assert result.success is True
    assert result.tokens_output == 40
    assert result.tokens_per_second > 0
    assert isinstance(result.tokens_per_second, float)
