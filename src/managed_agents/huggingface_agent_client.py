"""
HuggingFaceAgentClient: executa tasks via HuggingFace Inference Providers,
uma API OpenAI-compatible que roteia para 15+ inference providers
(Groq, Cerebras, Together, Fireworks, etc.) através de endpoint único.

Auth:     Bearer {hf_token}
Endpoint: vem de `config["base_url"]` (adapter_field_definitions.base_url,
          padrão Ollama). NÃO existe constante HF_BASE_URL — Regra de Ouro
          #2 NO HARDCODE (docs/CODE-PATTERNS.md §P1, caso 2026-05-17).

Mesma interface (`async def execute_task -> ExecutionResult`) que
ManagedAgentClient e OllamaAgentClient — o router permanece agnóstico.

Catalog-driven: base_url, hf_token, model_id, provider (inference router),
temperature, max_tokens vêm de `agent_adapter_configs.field_values_json`.
Capacidade de tool calling vem de `llm_models.supports_tool_calling`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI

from .managed_agent_client import ExecutionResult
from .tool_translator import OPENAI_TOOLS, dispatch_tool_call

logger = logging.getLogger("ManagedAgents.HuggingFace")

# Mesmo guard contra loop infinito do Ollama.
_MAX_TURNS = 20

# Lista de inference providers do HF Router vive em
# adapter_field_definitions.options_json.values do field `provider` do adapter
# huggingface. Antiga constante HF_INFERENCE_PROVIDERS era letra morta (zero
# referências) — removida pelo hardcode-auditor (Regra de Ouro #2, PR #194).


class HuggingFaceAgentClient:
    """Cliente para HuggingFace Inference Providers (API OpenAI-compatible)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        config = config or {}

        # base_url: catalog-driven (mesmo pattern Groq/Ollama). SEM default
        # Python — UI sugere via adapter_field_definitions.options_json.default
        # https://router.huggingface.co/v1; admin pode mudar (mirror, proxy).
        base_url = config.get("base_url")
        if not base_url:
            raise ValueError(
                "HuggingFaceAgentClient: base_url ausente no config. "
                "Configure 'base_url' em agent_adapter_configs.field_values_json "
                "(default sugerido: https://router.huggingface.co/v1)."
            )

        hf_token = config.get("hf_token") or ""
        if not hf_token:
            logger.warning(
                "HuggingFaceAgentClient: hf_token ausente no config. "
                "Configure 'hf_token' em agent_adapter_configs antes de executar."
            )

        self.model = config.get("model_id") or "meta-llama/Llama-3.3-70B-Instruct"
        self._inference_provider = (config.get("provider") or "auto").strip() or "auto"

        try:
            self.temperature = float(config.get("temperature", 0.7))
        except (TypeError, ValueError):
            self.temperature = 0.7
        try:
            self.max_tokens = int(config.get("max_tokens", 2048))
        except (TypeError, ValueError):
            self.max_tokens = 2048

        # api_key="placeholder" se vazio; execute_task captura o AuthError.
        self._base_url = base_url
        self._client = OpenAI(base_url=base_url, api_key=hf_token or "missing")
        self._has_token = bool(hf_token)

    async def execute_task(
        self,
        prompt: str,
        max_turns: int = 3,
        system_prompt: Optional[str] = None,
    ) -> ExecutionResult:
        import openai

        start = time.monotonic()

        if not self._has_token:
            return ExecutionResult(
                success=False,
                content="",
                error=(
                    "HuggingFace Inference falhou: hf_token ausente. "
                    "Configure o campo 'hf_token' em agent_adapter_configs."
                ),
                execution_time_seconds=round(time.monotonic() - start, 3),
            )

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
        # Eval-only seconds — exclui dispatch_tool_call para tps fiel à inferência.
        total_eval_seconds = 0.0
        turn = 0
        final_content = ""

        def _tps() -> float:
            return round(total_output / max(total_eval_seconds, 0.001), 2)

        # Provider routing opcional via extra_body. 'auto' (default) deixa o HF roteador decidir.
        extra_body: Dict[str, Any] = {}
        if self._inference_provider and self._inference_provider != "auto":
            extra_body["provider"] = self._inference_provider

        try:
            while turn < _MAX_TURNS:
                turn += 1
                eval_start = time.monotonic()
                kwargs: Dict[str, Any] = dict(
                    model=self.model,
                    messages=messages,
                    tools=OPENAI_TOOLS,
                    tool_choice="auto",
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                if extra_body:
                    kwargs["extra_body"] = extra_body
                response = await asyncio.to_thread(
                    self._client.chat.completions.create,
                    **kwargs,
                )
                total_eval_seconds += time.monotonic() - eval_start

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

                # Sequencial — sem parallel_tool_calls.
                for tc in tool_calls:
                    try:
                        tool_input = json.loads(tc.function.arguments or "{}")
                    except (TypeError, ValueError, json.JSONDecodeError):
                        tool_input = {}
                    tool_name = tc.function.name
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
                elapsed = time.monotonic() - start
                logger.warning(
                    "HuggingFaceAgentClient: limite de turns atingido (%d) sem resposta final",
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
                    error=(
                        f"HuggingFaceAgentClient: limite de turns atingido ({_MAX_TURNS})"
                    ),
                )

        except openai.AuthenticationError as e:
            elapsed = time.monotonic() - start
            logger.error("HuggingFaceAgentClient: auth falhou — %s", e)
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
                    "HuggingFace Inference falhou: token inválido ou expirado. "
                    "Verifique o HF_TOKEN no agente. Detalhe: "
                    f"{e}"
                ),
            )
        except openai.APIConnectionError as e:
            elapsed = time.monotonic() - start
            logger.error("HuggingFaceAgentClient: conexão falhou — %s", e)
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
                    f"HuggingFace Inference inacessível em {self._base_url}. "
                    f"Verifique conectividade e status em status.huggingface.co. Detalhe: {e}"
                ),
            )
        except openai.APITimeoutError as e:
            elapsed = time.monotonic() - start
            logger.error("HuggingFaceAgentClient: timeout — %s", e)
            return ExecutionResult(
                success=False,
                content="",
                tool_calls=tool_calls_log,
                turn_count=turn,
                tokens_input=total_input,
                tokens_output=total_output,
                execution_time_seconds=round(elapsed, 3),
                tokens_per_second=_tps(),
                error=f"Timeout ao chamar HuggingFace Inference: {e}",
            )
        except Exception as e:
            elapsed = time.monotonic() - start
            logger.exception("HuggingFaceAgentClient erro inesperado: %s", e)
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
                    f"HuggingFace Inference falhou: {e}. "
                    f"Verifique o HF_TOKEN e o modelo selecionado."
                ),
            )

        elapsed = time.monotonic() - start
        logger.info(
            "HuggingFaceAgentClient done model=%s provider=%s turns=%d tokens_in=%d tokens_out=%d elapsed=%.2fs",
            self.model, self._inference_provider, turn, total_input, total_output, elapsed,
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
