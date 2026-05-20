"""
ManagedAgentClient: executa tasks usando a Anthropic Messages API com tool_use loop.

Fluxo:
  1. Envia prompt ao Claude com ANTHROPIC_TOOLS disponíveis
  2. Se stop_reason == "tool_use", executa as tools e envia tool_result
  3. Repete até stop_reason == "end_turn" ou max_turns atingido
  4. Retorna ExecutionResult com todo o histórico de tokens e tool calls
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ManagedAgents.Client")


@dataclass
class ExecutionResult:
    success: bool
    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    execution_time_seconds: float = 0.0
    # Tokens de saída por segundo de inferência (eval-only, exclui dispatch de tools).
    # Preenchido por OllamaAgentClient e ManagedAgentClient (Anthropic).
    tokens_per_second: float = 0.0
    error: Optional[str] = None


class ManagedAgentClient:
    def __init__(
        self,
        model: Optional[str] = None,
        anthropic_client=None,
    ) -> None:
        self.model = model or os.getenv("CMA_MODEL", "claude-haiku-4-5-20251001")
        self._client = anthropic_client  # injetado em testes; lazy-loaded em produção

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(
                    api_key=os.getenv("ANTHROPIC_API_KEY", ""),
                    timeout=60.0,
                )
            except ImportError:
                raise RuntimeError("Pacote 'anthropic' não instalado. Execute: pip install anthropic")
        return self._client

    async def execute_task(
        self,
        prompt: str,
        max_turns: int = 3,
        system_prompt: Optional[str] = None,
        agent_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> ExecutionResult:
        from .tool_translator import ANTHROPIC_TOOLS, dispatch_tool_call

        start = time.monotonic()
        client = self._get_client()

        # Parte 2 MCP: se agent_id+company_id vierem, injeta tools MCP dos bindings
        # ativos (prefixadas mcp__<server>__<tool>) + roteia tool_use prefixado
        # pro mcp_tool_runner. Sem agent_id → comportamento legado (só ANTHROPIC_TOOLS).
        mcp_tools: List[Dict[str, Any]] = []
        _supabase = None
        if agent_id and company_id:
            try:
                from src.api import supabase as _supabase
                from src.services.mcp_tool_runner import list_agent_mcp_tools
                if _supabase:
                    mcp_tools = list_agent_mcp_tools(_supabase, agent_id)
            except Exception as e:
                logger.warning("MCP tools lookup falhou (segue sem MCP): %s", e)

        tools = ANTHROPIC_TOOLS + mcp_tools

        def _dispatch(name: str, tool_input: Dict[str, Any]) -> str:
            """Roteia: mcp__ → mcp_tool_runner; senão → tool_translator legado."""
            if name.startswith("mcp__") and _supabase and agent_id and company_id:
                from src.services.mcp_tool_runner import execute_mcp_tool
                import json as _json
                out = execute_mcp_tool(_supabase, company_id, agent_id, name, tool_input)
                return _json.dumps(out, ensure_ascii=False)
            return dispatch_tool_call(name, tool_input)

        system = system_prompt or (
            "Você é um agente logístico da Vectra Cargo. "
            "Responda em português. "
            "Use as ferramentas disponíveis quando necessário e forneça uma resposta concisa."
        )

        messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]
        tool_calls_log: List[Dict[str, Any]] = []
        total_input = 0
        total_output = 0
        # Acumula só o tempo de inferência (chamadas messages.create), excluindo
        # dispatch_tool_call. Usado para calcular tokens_per_second.
        total_eval_seconds = 0.0
        turn = 0
        final_content = ""

        def _tps() -> float:
            """Tokens de saída por segundo de inferência. Best-effort."""
            return round(total_output / max(total_eval_seconds, 0.001), 2)

        try:
            while turn < max_turns:
                turn += 1
                eval_start = time.monotonic()
                response = await asyncio.to_thread(
                    client.messages.create,
                    model=self.model,
                    max_tokens=1024,
                    system=system,
                    tools=tools,
                    messages=messages,
                )
                total_eval_seconds += time.monotonic() - eval_start

                total_input += response.usage.input_tokens
                total_output += response.usage.output_tokens

                # Extrai texto final apenas de blocks type="text"
                text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
                if text_blocks:
                    final_content = " ".join(text_blocks)

                if response.stop_reason != "tool_use":
                    break

                # Processa tool_use blocks
                tool_uses = [b for b in response.content if b.type == "tool_use"]
                tool_results = []
                for tu in tool_uses:
                    tool_output = _dispatch(tu.name, tu.input)
                    tool_calls_log.append({
                        "tool_name": tu.name,
                        "tool_input": tu.input,
                        "tool_output": tool_output,
                        "turn": turn,
                    })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": tool_output,
                    })
                    logger.debug("tool_use tool=%s turn=%d", tu.name, turn)

                # Adiciona resposta do assistente + resultados ao histórico
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

        except Exception as e:
            elapsed = time.monotonic() - start
            logger.error(f"ManagedAgentClient.execute_task error: {e}")
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
            "ManagedAgentClient done turns=%d tokens_in=%d tokens_out=%d elapsed=%.2fs",
            turn, total_input, total_output, elapsed,
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
