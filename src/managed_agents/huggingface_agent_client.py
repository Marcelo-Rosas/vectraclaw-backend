"""
HuggingFaceAgentClient: executa tasks via HuggingFace Inference Providers,
uma API OpenAI-compatible que roteia para 15+ inference providers
(Groq, Cerebras, Together, Fireworks, etc.) através de endpoint único.

Endpoint: https://router.huggingface.co/v1
Auth:     Bearer {HF_TOKEN}

Mesma interface (`async def execute_task -> ExecutionResult`) que
ManagedAgentClient e OllamaAgentClient — o router permanece agnóstico.
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

# Endpoint fixo do roteador HF — não vem do config (intencional).
HF_BASE_URL = "https://router.huggingface.co/v1"

# Mesmo guard contra loop infinito do Ollama.
_MAX_TURNS = 20

# Allowlist best-effort de modelos com suporte a tool calling no roteador HF.
# Verifica-se pelo prefixo (split("/")[0] + "/" + ...) — formato "owner/repo".
# Lista pode ficar desatualizada; usado só para warning, não bloqueia.
HF_TOOL_CAPABLE_MODELS = {
    "meta-llama/Llama-3.3-70B-Instruct",
    "meta-llama/Llama-3.1-8B-Instruct",
    "meta-llama/Llama-3.1-70B-Instruct",
    "meta-llama/Llama-3.1-405B-Instruct",
    "Qwen/Qwen2.5-72B-Instruct",
    "Qwen/Qwen2.5-32B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "Qwen/Qwen3-235B-A22B",
    "moonshotai/Kimi-K2-Instruct-0905",
    "deepseek-ai/DeepSeek-R1",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "mistralai/Mixtral-8x7B-Instruct-v0.1",
    "mistralai/Mixtral-8x22B-Instruct-v0.1",
}

# Providers aceitos pelo campo `provider` (inference router). 'auto' deixa o HF decidir.
HF_INFERENCE_PROVIDERS = {
    "auto", "groq", "cerebras", "together", "fireworks",
    "sambanova", "novita", "deepinfra",
}


class HuggingFaceAgentClient:
    """Cliente para HuggingFace Inference Providers (API OpenAI-compatible)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        config = config or {}

        hf_token = config.get("hf_token") or ""
        if not hf_token:
            # Em vez de crashar no __init__, deixa execute_task retornar erro
            # claro. Útil pra que o factory possa ser chamado em testes que não
            # exercitam a chamada real.
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

        # Cliente OpenAI síncrono apontando para o roteador HF; chamadas
        # vão por asyncio.to_thread (mesmo padrão do OllamaAgentClient).
        # api_key="placeholder" se vazio; execute_task captura o AuthError.
        self._client = OpenAI(base_url=HF_BASE_URL, api_key=hf_token or "missing")
        self._has_token = bool(hf_token)
        self._warn_if_no_tool_support()

    def _warn_if_no_tool_support(self) -> None:
        if self.model not in HF_TOOL_CAPABLE_MODELS:
            logger.warning(
                "HuggingFaceAgentClient: modelo '%s' pode não suportar tool calling. "
                "Modelos confirmados: %s. "
                "Se o agente entrar em loop ou retornar vazio, troque para um da lista.",
                self.model,
                sorted(HF_TOOL_CAPABLE_MODELS),
            )

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
                    f"HuggingFace Inference inacessível em {HF_BASE_URL}. "
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
