"""
Testes unitários do HuggingFaceAgentClient.

Mockam `openai.OpenAI` substituindo o símbolo no módulo do cliente — nenhum
teste toca rede; podem rodar em CI sem HF_TOKEN.
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
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    choice = MagicMock(message=msg)
    usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return MagicMock(choices=[choice], usage=usage)


def _mk_tool_call(id_, name, args):
    function = MagicMock()
    function.name = name
    function.arguments = json.dumps(args)
    tc = MagicMock()
    tc.id = id_
    tc.function = function
    return tc


@pytest.fixture
def mock_openai(monkeypatch):
    mock_client = MagicMock()
    monkeypatch.setattr(
        "src.managed_agents.huggingface_agent_client.OpenAI",
        lambda **kw: mock_client,
    )
    return mock_client


# ---------------------------------------------------------------------------
# 1. Resposta direta — caminho feliz
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_task_direct_response(mock_openai):
    from src.managed_agents.huggingface_agent_client import HuggingFaceAgentClient

    mock_openai.chat.completions.create.return_value = _mk_response(content="ok")

    client = HuggingFaceAgentClient(config={
        "hf_token": "hf_test_xxx",
        "model_id": "meta-llama/Llama-3.3-70B-Instruct",
    })
    result = await client.execute_task("teste")

    assert result.success is True
    assert result.content == "ok"
    assert result.tokens_input == 10
    assert result.tokens_output == 5


# ---------------------------------------------------------------------------
# 2. Loop tool_use sem double-encode no role=tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_task_with_tool_call(mock_openai):
    from src.managed_agents.huggingface_agent_client import HuggingFaceAgentClient

    tc = _mk_tool_call(id_="tc1", name="calculate_cbm", args={"length_cm": 50})
    mock_openai.chat.completions.create.side_effect = [
        _mk_response(tool_calls=[tc]),
        _mk_response(content="ok"),
    ]

    with patch(
        "src.managed_agents.huggingface_agent_client.dispatch_tool_call",
        return_value='{"cbm": 0.001}',
    ) as mock_dispatch:
        client = HuggingFaceAgentClient(config={
            "hf_token": "hf_test",
            "model_id": "meta-llama/Llama-3.3-70B-Instruct",
        })
        result = await client.execute_task("calcule")

    mock_dispatch.assert_called_once_with(
        tool_name="calculate_cbm",
        tool_input={"length_cm": 50},
    )
    msgs = mock_openai.chat.completions.create.call_args_list[1].kwargs["messages"]
    tool_msg = next(m for m in msgs if isinstance(m, dict) and m.get("role") == "tool")
    assert tool_msg["content"] == '{"cbm": 0.001}'  # NÃO json.dumps disso
    assert result.success is True
    assert result.turn_count == 2


# ---------------------------------------------------------------------------
# 3. _MAX_TURNS guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_max_turns_guard(mock_openai):
    from src.managed_agents.huggingface_agent_client import (
        HuggingFaceAgentClient,
        _MAX_TURNS,
    )

    tc = _mk_tool_call(id_="tc1", name="calculate_cbm", args={})
    mock_openai.chat.completions.create.return_value = _mk_response(tool_calls=[tc])

    with patch(
        "src.managed_agents.huggingface_agent_client.dispatch_tool_call",
        return_value="{}",
    ):
        client = HuggingFaceAgentClient(config={
            "hf_token": "hf_test",
            "model_id": "meta-llama/Llama-3.3-70B-Instruct",
        })
        result = await client.execute_task("loop")

    assert result.success is False
    assert "limite" in (result.error or "").lower()
    assert mock_openai.chat.completions.create.call_count == _MAX_TURNS


# ---------------------------------------------------------------------------
# 4. Token ausente → erro claro sem chamar API
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_token_returns_clear_error(mock_openai):
    from src.managed_agents.huggingface_agent_client import HuggingFaceAgentClient

    client = HuggingFaceAgentClient(config={
        "model_id": "meta-llama/Llama-3.3-70B-Instruct",
        # sem hf_token
    })
    result = await client.execute_task("teste")

    assert result.success is False
    assert "hf_token" in (result.error or "").lower()
    # Não pode ter chamado a API com token vazio
    assert mock_openai.chat.completions.create.call_count == 0


# ---------------------------------------------------------------------------
# 5. AuthenticationError → mensagem orientando o operador
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auth_error_returns_clear_message(mock_openai):
    import openai
    from src.managed_agents.huggingface_agent_client import HuggingFaceAgentClient

    mock_openai.chat.completions.create.side_effect = openai.AuthenticationError(
        message="invalid token",
        response=MagicMock(),
        body=None,
    )

    client = HuggingFaceAgentClient(config={
        "hf_token": "hf_invalid",
        "model_id": "meta-llama/Llama-3.3-70B-Instruct",
    })
    result = await client.execute_task("teste")

    assert result.success is False
    assert "token" in (result.error or "").lower()
    assert "hf_token" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# 6. APIConnectionError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connection_error_returns_clear_message(mock_openai):
    import openai
    from src.managed_agents.huggingface_agent_client import HuggingFaceAgentClient

    mock_openai.chat.completions.create.side_effect = openai.APIConnectionError(
        request=MagicMock(),
    )

    client = HuggingFaceAgentClient(config={
        "hf_token": "hf_test",
        "model_id": "meta-llama/Llama-3.3-70B-Instruct",
    })
    result = await client.execute_task("teste")

    assert result.success is False
    assert "inacess" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# 7. usage None / token counting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_counting_handles_none_usage(mock_openai):
    from src.managed_agents.huggingface_agent_client import HuggingFaceAgentClient

    resp = _mk_response(content="ok")
    resp.usage = None
    mock_openai.chat.completions.create.return_value = resp

    client = HuggingFaceAgentClient(config={
        "hf_token": "hf_test",
        "model_id": "meta-llama/Llama-3.3-70B-Instruct",
    })
    result = await client.execute_task("teste")

    assert result.success is True
    assert result.tokens_input == 0
    assert result.tokens_output == 0


# ---------------------------------------------------------------------------
# 8. tokens_per_second populado
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tokens_per_second_calculated(mock_openai):
    from src.managed_agents.huggingface_agent_client import HuggingFaceAgentClient

    mock_openai.chat.completions.create.return_value = _mk_response(
        content="ok",
        prompt_tokens=20,
        completion_tokens=40,
    )

    client = HuggingFaceAgentClient(config={
        "hf_token": "hf_test",
        "model_id": "meta-llama/Llama-3.3-70B-Instruct",
    })
    result = await client.execute_task("teste")

    assert result.success is True
    assert result.tokens_output == 40
    assert result.tokens_per_second > 0


# ---------------------------------------------------------------------------
# 9. base_url SEMPRE fixo (não vem do config)
# ---------------------------------------------------------------------------

def test_base_url_is_fixed(mock_openai):
    from src.managed_agents.huggingface_agent_client import (
        HF_BASE_URL,
        HuggingFaceAgentClient,
    )

    # Mesmo que o usuário passe base_url no config, é IGNORADO.
    HuggingFaceAgentClient(config={
        "hf_token": "hf_test",
        "model_id": "meta-llama/Llama-3.3-70B-Instruct",
        "base_url": "http://hacker.example.com/",  # tentativa de override
    })

    assert HF_BASE_URL == "https://router.huggingface.co/v1"


# ---------------------------------------------------------------------------
# 10. Inference provider routing via extra_body quando != 'auto'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inference_provider_routed_via_extra_body(mock_openai):
    from src.managed_agents.huggingface_agent_client import HuggingFaceAgentClient

    mock_openai.chat.completions.create.return_value = _mk_response(content="ok")

    client = HuggingFaceAgentClient(config={
        "hf_token": "hf_test",
        "model_id": "meta-llama/Llama-3.3-70B-Instruct",
        "provider": "groq",
    })
    await client.execute_task("teste")

    kwargs = mock_openai.chat.completions.create.call_args.kwargs
    assert kwargs.get("extra_body") == {"provider": "groq"}


@pytest.mark.asyncio
async def test_inference_provider_auto_omits_extra_body(mock_openai):
    from src.managed_agents.huggingface_agent_client import HuggingFaceAgentClient

    mock_openai.chat.completions.create.return_value = _mk_response(content="ok")

    client = HuggingFaceAgentClient(config={
        "hf_token": "hf_test",
        "model_id": "meta-llama/Llama-3.3-70B-Instruct",
        "provider": "auto",
    })
    await client.execute_task("teste")

    kwargs = mock_openai.chat.completions.create.call_args.kwargs
    assert "extra_body" not in kwargs


# ---------------------------------------------------------------------------
# 11. Warning de tool support para modelo fora da allowlist
# ---------------------------------------------------------------------------

def test_warn_for_non_tool_capable_model(caplog, mock_openai):
    from src.managed_agents.huggingface_agent_client import HuggingFaceAgentClient

    caplog.set_level(logging.WARNING, logger="ManagedAgents.HuggingFace")
    HuggingFaceAgentClient(config={
        "hf_token": "hf_test",
        "model_id": "google/gemma-2b",  # fora da allowlist
    })

    messages = [r.getMessage() for r in caplog.records]
    assert any("pode não suportar tool calling" in m for m in messages)


def test_no_warn_for_tool_capable_model(caplog, mock_openai):
    from src.managed_agents.huggingface_agent_client import HuggingFaceAgentClient

    caplog.set_level(logging.WARNING, logger="ManagedAgents.HuggingFace")
    HuggingFaceAgentClient(config={
        "hf_token": "hf_test",
        "model_id": "meta-llama/Llama-3.3-70B-Instruct",
    })

    messages = [r.getMessage() for r in caplog.records]
    assert not any("pode não suportar tool calling" in m for m in messages)
