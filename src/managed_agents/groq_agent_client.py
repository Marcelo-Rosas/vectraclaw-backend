"""GroqAgentClient: executa tasks via Groq Cloud (API compatível OpenAI).

Groq oferece free tier generoso (Llama 3.3 70B, Qwen 32B, etc.) com latência
extremamente baixa (~500-1000 tokens/s). API é compatível OpenAI — endpoint
único, mesmo SDK.

Auth:     Bearer {api_key}
Endpoint: vem de `config["base_url"]` (adapter_field_definitions.base_url,
          padrão Ollama). NÃO existe constante GROQ_BASE_URL — Regra de Ouro
          #2 NO HARDCODE (docs/CODE-PATTERNS.md §P1, caso 2026-05-17).

Mesma interface (`async def execute_task -> ExecutionResult`) que
ManagedAgentClient / OllamaAgentClient / HuggingFaceAgentClient — o router
permanece agnóstico.

Diferença vs HuggingFaceAgentClient: este chama Groq DIRETO (sem router HF).
Mais simples, sem dependência intermediária. Use este quando tiver
API key Groq dedicada; use HF Router quando quiser rotear por múltiplos
providers (Groq + Cerebras + Together) com 1 token só.

Catalog-driven: base_url, api_key, model_id, temperature, max_tokens vêm de
`agent_adapter_configs.field_values_json` (preenchido pela UI). Capacidade
de tool calling vem de `llm_models.supports_tool_calling` — quem checa é o
`decision_engine` (via `src.services.llm_cost.is_tool_capable`), não o client.
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

logger = logging.getLogger("ManagedAgents.Groq")

# Mesmo guard contra loop infinito dos outros clients.
_MAX_TURNS = 20


class GroqAgentClient:
    """Cliente para Groq Cloud (API compatível OpenAI). 100% catalog-driven."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        config = config or {}

        # base_url: catalog-driven. SEM default Python — admin preenche na UI
        # (adapter_field_definitions.options_json.default sugere o valor canônico
        # https://api.groq.com/openai/v1, mas o cliente exige config).
        base_url = config.get("base_url")
        if not base_url:
            raise ValueError(
                "GroqAgentClient: base_url ausente no config. "
                "Configure 'base_url' em agent_adapter_configs.field_values_json "
                "(default sugerido: https://api.groq.com/openai/v1)."
            )

        # api_key híbrido: campo do adapter > env var > fail.
        api_key = (
            config.get("api_key")
            or os.getenv("GROQ_API_KEY", "")
        )
        if not api_key:
            logger.warning(
                "GroqAgentClient: api_key ausente no config E no env GROQ_API_KEY. "
                "execute_task vai retornar erro claro até que seja configurado."
            )

        self.model = config.get("model_id")
        if not self.model:
            raise ValueError(
                "GroqAgentClient: model_id ausente no config. "
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

        self._base_url = base_url
        self._client = OpenAI(base_url=base_url, api_key=api_key or "missing")
        self._has_key = bool(api_key)

    async def execute_task(
        self,
        prompt: str,
        max_turns: int = 3,
        system_prompt: Optional[str] = None,
    ) -> ExecutionResult:
        import openai

        start = time.monotonic()

        if not self._has_key:
            return ExecutionResult(
                success=False,
                content="",
                error=(
                    "Groq falhou: api_key ausente. "
                    "Configure 'api_key' em agent_adapter_configs.field_values_json "
                    "ou exporte GROQ_API_KEY no ambiente."
                ),
                execution_time_seconds=time.monotonic() - start,
            )

        system = system_prompt or (
            "Você é um agente logístico da Vectra Cargo. "
            "Responda em português. "
            "Use as ferramentas disponíveis quando necessário e forneça uma resposta concisa."
        )

        messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]
        tool_calls_log: List[Dict[str, Any]] = []
        total_input = 0
        total_output = 0
        total_eval_seconds = 0.0
        turn = 0
        final_content = ""
        effective_max_turns = min(max_turns, _MAX_TURNS)

        def _tps() -> float:
            return round(total_output / max(total_eval_seconds, 0.001), 2)

        try:
            while turn < effective_max_turns:
                turn += 1
                eval_start = time.monotonic()
                response = await asyncio.to_thread(
                    self._client.chat.completions.create,
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    messages=messages,
                    tools=OPENAI_TOOLS,
                )
                total_eval_seconds += time.monotonic() - eval_start

                if response.usage:
                    total_input += response.usage.prompt_tokens or 0
                    total_output += response.usage.completion_tokens or 0

                choice = response.choices[0]
                msg = choice.message
                final_content = (msg.content or "").strip()

                tool_calls = getattr(msg, "tool_calls", None) or []
                if not tool_calls:
                    return ExecutionResult(
                        success=True,
                        content=final_content,
                        tool_calls=tool_calls_log,
                        turn_count=turn,
                        tokens_input=total_input,
                        tokens_output=total_output,
                        execution_time_seconds=time.monotonic() - start,
                        tokens_per_second=_tps(),
                    )

                # Echo assistant message (com tool_calls) pra contexto
                messages.append({
                    "role": "assistant",
                    "content": msg.content,
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

                # Executar cada tool call e injetar resultado
                for tc in tool_calls:
                    name = tc.function.name
                    raw_args = tc.function.arguments or "{}"
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {"_raw": raw_args}
                    tool_result = dispatch_tool_call(name, args)
                    tool_calls_log.append({"name": name, "args": args, "result": tool_result})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": name,
                        "content": tool_result if isinstance(tool_result, str) else json.dumps(tool_result),
                    })

            # max_turns atingido
            return ExecutionResult(
                success=True,
                content=final_content or "[max_turns atingido]",
                tool_calls=tool_calls_log,
                turn_count=turn,
                tokens_input=total_input,
                tokens_output=total_output,
                execution_time_seconds=time.monotonic() - start,
                tokens_per_second=_tps(),
                error=f"max_turns {effective_max_turns} atingido sem resposta final",
            )

        except openai.APIError as e:
            return ExecutionResult(
                success=False,
                content=final_content,
                tool_calls=tool_calls_log,
                turn_count=turn,
                tokens_input=total_input,
                tokens_output=total_output,
                execution_time_seconds=time.monotonic() - start,
                tokens_per_second=_tps(),
                error=f"Groq API error: {e}",
            )
        except Exception as e:
            logger.exception("GroqAgentClient.execute_task fail")
            return ExecutionResult(
                success=False,
                content=final_content,
                tool_calls=tool_calls_log,
                turn_count=turn,
                tokens_input=total_input,
                tokens_output=total_output,
                execution_time_seconds=time.monotonic() - start,
                tokens_per_second=_tps(),
                error=f"GroqAgentClient unexpected: {type(e).__name__}: {e}",
            )
