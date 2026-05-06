"""
Testes do dispatcher PROVIDER_CLIENT_MAP / get_agent_client.

Cobertura:
- Provider desconhecido → ValueError
- openai/google (slots reservados) → NotImplementedError instrutivo
- anthropic recebe `model=` (kwarg)
- ollama recebe `config=` (dict)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.managed_agents.agent_client_factory import (
    PROVIDER_CLIENT_MAP,
    get_agent_client,
)


def test_unknown_provider_raises_value_error():
    with pytest.raises(ValueError, match="desconhecido"):
        get_agent_client("xpto")


def test_reserved_openai_raises_not_implemented():
    with pytest.raises(NotImplementedError, match="reservado"):
        get_agent_client("openai")


def test_reserved_google_raises_not_implemented():
    with pytest.raises(NotImplementedError, match="reservado"):
        get_agent_client("google")


def test_anthropic_passes_model_kwarg(monkeypatch):
    """ManagedAgentClient deve receber `model=` como kwarg."""
    captured: list = []

    class FakeAnthropic:
        def __init__(self, **kw):
            captured.append(kw)

    # Substitui a classe registrada no map
    monkeypatch.setitem(PROVIDER_CLIENT_MAP, "anthropic", FakeAnthropic)
    # ATENÇÃO: get_agent_client compara `is ManagedAgentClient`. Como trocamos
    # a classe, o ramo "anthropic" cai no else e usa `config=`. Aqui validamos
    # apenas que o slot anthropic é resolvido — para validar passagem de model
    # usamos monkeypatch direto na função.
    from src.managed_agents import agent_client_factory as factory

    # Substituir também a referência usada no `is` check
    monkeypatch.setattr(factory, "ManagedAgentClient", FakeAnthropic)

    get_agent_client("anthropic", model="claude-opus-4-7-thinking-high")
    assert len(captured) == 1
    assert captured[0]["model"] == "claude-opus-4-7-thinking-high"


def test_ollama_passes_config_dict(monkeypatch):
    """OllamaAgentClient deve receber `config=` como kwarg dict."""
    captured: list = []

    class FakeOllama:
        def __init__(self, **kw):
            captured.append(kw)

    from src.managed_agents import agent_client_factory as factory

    monkeypatch.setitem(PROVIDER_CLIENT_MAP, "ollama", FakeOllama)
    # `is ManagedAgentClient` é False para FakeOllama → cai no ramo else (config=)

    get_agent_client("ollama", config={"model_id": "qwen2.5:7b", "temperature": 0.1})

    assert len(captured) == 1
    assert captured[0]["config"]["model_id"] == "qwen2.5:7b"
    assert captured[0]["config"]["temperature"] == 0.1


def test_ollama_with_none_config_uses_empty_dict(monkeypatch):
    """get_agent_client('ollama', config=None) não deve crashar."""
    captured: list = []

    class FakeOllama:
        def __init__(self, **kw):
            captured.append(kw)

    monkeypatch.setitem(PROVIDER_CLIENT_MAP, "ollama", FakeOllama)
    get_agent_client("ollama", config=None)
    assert captured[0]["config"] == {}


def test_huggingface_passes_config_dict(monkeypatch):
    """HuggingFaceAgentClient deve receber `config=` (mesmo padrão do Ollama)."""
    captured: list = []

    class FakeHF:
        def __init__(self, **kw):
            captured.append(kw)

    monkeypatch.setitem(PROVIDER_CLIENT_MAP, "huggingface", FakeHF)
    get_agent_client("huggingface", config={
        "hf_token": "hf_xxx",
        "model_id": "meta-llama/Llama-3.3-70B-Instruct",
    })
    assert captured[0]["config"]["hf_token"] == "hf_xxx"


def test_provider_map_has_expected_slots():
    """Sentinel de regressão — garante que todos os slots conhecidos existem."""
    assert set(PROVIDER_CLIENT_MAP.keys()) == {
        "anthropic", "ollama", "huggingface", "openai", "google",
    }
    assert PROVIDER_CLIENT_MAP["openai"] is None
    assert PROVIDER_CLIENT_MAP["google"] is None
    assert PROVIDER_CLIENT_MAP["anthropic"] is not None
    assert PROVIDER_CLIENT_MAP["ollama"] is not None
    assert PROVIDER_CLIENT_MAP["huggingface"] is not None
