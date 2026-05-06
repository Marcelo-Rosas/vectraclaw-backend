"""
Factory para clientes de execução de agentes.

`PROVIDER_CLIENT_MAP` declara providers conhecidos. `None` marca slots
reservados (ainda não implementados) — `get_agent_client` levanta
`NotImplementedError` instrutivo nesses casos para evitar refactor quando
OpenAI/Google forem implementados.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .huggingface_agent_client import HuggingFaceAgentClient
from .managed_agent_client import ManagedAgentClient
from .ollama_agent_client import OllamaAgentClient

# Slots `None` são reservados (provider conhecido mas cliente não implementado).
PROVIDER_CLIENT_MAP: Dict[str, Optional[type]] = {
    "anthropic": ManagedAgentClient,
    "ollama": OllamaAgentClient,
    "huggingface": HuggingFaceAgentClient,
    "openai": None,
    "google": None,
}


def get_agent_client(
    provider: str,
    model: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
):
    """Instancia o cliente de execução adequado para o provider.

    - `anthropic`   → `ManagedAgentClient(model=model)`
    - `ollama`      → `OllamaAgentClient(config=config or {})`
    - `huggingface` → `HuggingFaceAgentClient(config=config or {})`
    - `openai`/`google` → `NotImplementedError` (slot reservado)
    - desconhecido → `ValueError`
    """
    if provider not in PROVIDER_CLIENT_MAP:
        raise ValueError(
            f"Provider '{provider}' desconhecido. "
            f"Suportados: {list(PROVIDER_CLIENT_MAP.keys())}"
        )

    cls = PROVIDER_CLIENT_MAP[provider]
    if cls is None:
        raise NotImplementedError(
            f"Provider '{provider}' está reservado mas ainda não foi implementado. "
            f"Adicione o cliente em src/managed_agents/{provider}_agent_client.py "
            f"e registre em PROVIDER_CLIENT_MAP."
        )

    if cls is ManagedAgentClient:
        return cls(model=model)
    return cls(config=config or {})
