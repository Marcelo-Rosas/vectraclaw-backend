"""
OllamaAgentClient: executa tasks usando a API compatível com OpenAI do Ollama.

Ollama expõe `/v1/chat/completions` no formato OpenAI; reutilizamos o `openai`
SDK apontando para o servidor local. Mesma interface (`async def execute_task
-> ExecutionResult`) do `ManagedAgentClient` para que o router seja agnóstico
ao provider.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI

from .managed_agent_client import ExecutionResult
from .tool_translator import OPENAI_TOOLS, dispatch_tool_call

logger = logging.getLogger("ManagedAgents.Ollama")

# Teto absoluto de iterações no loop tool_use → tool_result.
# ManagedAgentClient (Anthropic) respeita max_turns; aqui o teto é fixo
# porque modelos Ollama sem suporte a tool calling podem entrar em loop
# infinito ignorando o tool_choice="auto" — _MAX_TURNS é a rede de proteção.
_MAX_TURNS = 20

# Capacidade de tool calling agora vem de vectraclip.llm_models.supports_tool_calling
# (catalog-driven, Regra de Ouro #2). Use src.services.llm_cost.is_tool_capable
# no decision_engine antes de rotear, em vez de checar aqui no client.


class OllamaAgentClient:
    """Cliente para servidores Ollama (API compatível com OpenAI)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        config = config or {}

        # base_url híbrido: campo do adapter > env var > default localhost.
        # Usa `or` (não `is None`) para que string vazia também caia no fallback.
        base_url = (
            config.get("base_url")
            or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        )
        self.model = config.get("model_id")
        if not self.model:
            raise ValueError(
                "OllamaAgentClient: model_id ausente no config. "
                "Configure 'model_id' em agent_adapter_configs.field_values_json "
                "(catalog-driven via adapter_field_definitions.options_json.source='llm_models')."
            )

        try:
            self.temperature = float(config.get("temperature", 0.3))
        except (TypeError, ValueError):
            self.temperature = 0.3
        try:
            self.max_tokens = int(config.get("max_tokens", 4096))
        except (TypeError, ValueError):
            self.max_tokens = 4096

        # Ollama ignora api_key, mas o SDK exige string não-vazia.
        self._client = OpenAI(base_url=base_url, api_key="ollama")
        self._base_url = base_url

    async def execute_task(
        self,
        prompt: str,
        max_turns: int = 3,
        system_prompt: Optional[str] = None,
    ) -> ExecutionResult:
        # Import local para acessar exceções do SDK; não bloqueia import do módulo
        # caso o pacote ainda não esteja instalado em algum ambiente.
        import openai

        start = time.monotonic()
        system = system_prompt or (
            "Você é um agente logístico da Vectra Cargo. "
            "Responda em português. "
            "Use as ferramentas disponíveis quando necessário e forneça uma resposta concisa."
        )

        messages: List[Any] = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        tool_calls_log: List[Dict[str, Any]] = []
        total_input = 0
        total_output = 0
        # Acumula só o tempo de inferência (chamadas chat.completions.create),
        # excluindo dispatch_tool_call. Usado para calcular tokens_per_second.
        total_eval_seconds = 0.0
        turn = 0
        final_content = ""

        def _tps() -> float:
            """Tokens de saída por segundo de inferência. Best-effort."""
            return round(total_output / max(total_eval_seconds, 0.001), 2)

        try:
            while turn < _MAX_TURNS:
                turn += 1
                eval_start = time.monotonic()
                response = await asyncio.to_thread(
                    self._client.chat.completions.create,
                    model=self.model,
                    messages=messages,
                    tools=OPENAI_TOOLS,
                    tool_choice="auto",
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                total_eval_seconds += time.monotonic() - eval_start

                # Token accounting: Ollama nem sempre devolve usage confiável.
                usage = getattr(response, "usage", None)
                if usage is not None:
                    total_input += getattr(usage, "prompt_tokens", 0) or 0
                    total_output += getattr(usage, "completion_tokens", 0) or 0

                choice = response.choices[0]
                msg = choice.message
                tool_calls = getattr(msg, "tool_calls", None)

                if not tool_calls:
                    final_content = msg.content or ""
                    break

                # Reconstrói a assistant message como dict para evitar acoplamento
                # com o tipo do SDK (e para o test helper poder iterar como dict).
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                })

                # Processa sequencialmente — não paralelizar, alguns modelos
                # Ollama rejeitam parallel_tool_calls.
                for tc in tool_calls:
                    try:
                        tool_input = json.loads(tc.function.arguments or "{}")
                    except (TypeError, ValueError, json.JSONDecodeError):
                        tool_input = {}
                    tool_name = tc.function.name
                    # dispatch_tool_call já retorna string JSON — NÃO aplicar json.dumps.
                    tool_output = dispatch_tool_call(
                        tool_name=tool_name,
                        tool_input=tool_input,
                    )
                    tool_calls_log.append({
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                        "tool_output": tool_output,
                        "turn": turn,
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_output,
                    })
                    logger.debug("tool_call tool=%s turn=%d", tool_name, turn)
            else:
                # Atingiu _MAX_TURNS com tool_use contínuo — guard contra loop infinito
                elapsed = time.monotonic() - start
                logger.warning(
                    "OllamaAgentClient: limite de turns atingido (%d) sem resposta final",
                    _MAX_TURNS,
                )
                return ExecutionResult(
                    success=False,
                    content=final_content,
                    tool_calls=tool_calls_log,
                    turn_count=turn,
                    tokens_input=total_input,
                    tokens_output=total_output,
                    execution_time_seconds=round(elapsed, 3),
                    tokens_per_second=_tps(),
                    error=f"OllamaAgentClient: limite de turns atingido ({_MAX_TURNS})",
                )

        except openai.APITimeoutError as e:
            elapsed = time.monotonic() - start
            logger.error("OllamaAgentClient: timeout — %s", e)
            return ExecutionResult(
                success=False,
                content="",
                tool_calls=tool_calls_log,
                turn_count=turn,
                tokens_input=total_input,
                tokens_output=total_output,
                execution_time_seconds=round(elapsed, 3),
                tokens_per_second=_tps(),
                error=f"Timeout ao chamar Ollama: {e}",
            )
        except openai.APIConnectionError as e:
            elapsed = time.monotonic() - start
            logger.error(
                "OllamaAgentClient: servidor inacessível em %s — %s",
                self._base_url, e,
            )
            return ExecutionResult(
                success=False,
                content="",
                tool_calls=tool_calls_log,
                turn_count=turn,
                tokens_input=total_input,
                tokens_output=total_output,
                execution_time_seconds=round(elapsed, 3),
                tokens_per_second=_tps(),
                error=(
                    f"Ollama inacessível em {self._base_url}. "
                    f"Verifique se 'ollama serve' está rodando. Detalhe: {e}"
                ),
            )
        except Exception as e:
            elapsed = time.monotonic() - start
            logger.exception("OllamaAgentClient erro inesperado: %s", e)
            return ExecutionResult(
                success=False,
                content="",
                tool_calls=tool_calls_log,
                turn_count=turn,
                tokens_input=total_input,
                tokens_output=total_output,
                execution_time_seconds=round(elapsed, 3),
                tokens_per_second=_tps(),
                error=str(e),
            )

        elapsed = time.monotonic() - start
        logger.info(
            "OllamaAgentClient done model=%s turns=%d tokens_in=%d tokens_out=%d elapsed=%.2fs",
            self.model, turn, total_input, total_output, elapsed,
        )
        return ExecutionResult(
            success=True,
            content=final_content,
            tool_calls=tool_calls_log,
            turn_count=turn,
            tokens_input=total_input,
            tokens_output=total_output,
            execution_time_seconds=round(elapsed, 3),
            tokens_per_second=_tps(),
        )
