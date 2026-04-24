"""Cliente Anthropic para Managed Agents - wrapper da Anthropic SDK."""

from __future__ import annotations

import os
import json
import logging
import asyncio
from datetime import datetime
from typing import Optional, Any, Callable
from dataclasses import dataclass, asdict

from anthropic import Anthropic

from .tool_translator import translate_tools_to_anthropic, validate_tool_input, load_tool_schemas
from src.m3_tools import calculate_cbm, extract_bl_pl, send_whatsapp_webhook

logger = logging.getLogger("ManagedAgentClient")

TOOL_REGISTRY: dict[str, Callable] = {
    "calculate_cbm": calculate_cbm,
    "extract_bl_pl": extract_bl_pl,
    "send_whatsapp_webhook": send_whatsapp_webhook,
}


@dataclass(frozen=True)
class ExecutionResult:
    """Resultado da execução de uma tarefa."""
    success: bool
    content: str
    tool_calls: list[dict[str, Any]]
    turn_count: int
    tokens_input: int
    tokens_output: int
    execution_time_seconds: float
    error: Optional[str] = None


@dataclass(frozen=True)
class TurnResult:
    """Resultado de um turno de execução."""
    turn_number: int
    tool_used: Optional[str]
    tool_input: Optional[dict[str, Any]]
    output: str
    stop_reason: str


class ManagedAgentClient:
    """Cliente para executar tarefas com Claude Managed Agents."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = 4096,
        timeout_seconds: int = 30,
        include_tools: Optional[list[str]] = None,
    ):
        """
        Inicializa o cliente Anthropic.

        Args:
            api_key: Chave de API Anthropic (ou ANTHROPIC_API_KEY env var)
            model: Modelo a usar
            max_tokens: Máximo de tokens na resposta
            timeout_seconds: Timeout para requisições
            include_tools: Lista de ferramentas a incluir (padrão: todas)
        """
        api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY não configurada. "
                "Defina a variável de ambiente ou passe api_key="
            )

        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds
        self.include_tools = include_tools or ["calculate_cbm", "extract_bl_pl", "send_whatsapp_webhook"]
        self.tools = translate_tools_to_anthropic(self.include_tools)

        logger.info(f"ManagedAgentClient inicializado: modelo={model}, tools={len(self.tools)}")

    def execute_task(
        self,
        task_prompt: str,
        max_turns: int = 3,
        system_prompt: Optional[str] = None,
    ) -> ExecutionResult:
        """
        Executa uma tarefa com até max_turns iterações.

        Args:
            task_prompt: Descrição da tarefa
            max_turns: Número máximo de turnos (default: 3)
            system_prompt: Prompt de sistema customizado

        Returns:
            ExecutionResult com resultado e histórico de ferramentas
        """
        if not task_prompt or not task_prompt.strip():
            raise ValueError("task_prompt não pode estar vazio")

        import time
        start_time = time.time()

        if system_prompt is None:
            system_prompt = self._get_default_system_prompt()

        messages: list[dict[str, str]] = [
            {"role": "user", "content": task_prompt}
        ]

        tool_calls_history: list[dict[str, Any]] = []
        turn_results: list[TurnResult] = []

        total_input_tokens = 0
        total_output_tokens = 0

        for turn_num in range(1, max_turns + 1):
            logger.info(f"Turn {turn_num}/{max_turns} iniciado")

            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system_prompt,
                    tools=self.tools,
                    messages=messages,
                    timeout=self.timeout_seconds,
                )

                total_input_tokens += response.usage.input_tokens
                total_output_tokens += response.usage.output_tokens

                # Processar resposta
                tool_used = None
                tool_input = None
                output_text = ""
                has_tool_use = False

                for block in response.content:
                    block_type = getattr(block, "type", None)

                    if block_type == "text":
                        output_text = getattr(block, "text", "")
                    elif block_type == "tool_use":
                        has_tool_use = True
                        tool_used = getattr(block, "name", "")
                        tool_input = getattr(block, "input", {})
                        block_id = getattr(block, "id", "")

                        logger.info(f"Tool call detectado: {tool_used}")

                        # Executar ferramenta localmente
                        tool_result = self._execute_tool(tool_used, tool_input)

                        # Adicionar ao histórico
                        tool_calls_history.append({
                            "turn": turn_num,
                            "tool": tool_used,
                            "input": tool_input,
                            "result": tool_result
                        })

                        # Adicionar resultado ao histórico de mensagens
                        messages.append(
                            {"role": "assistant", "content": response.content}
                        )
                        messages.append({
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block_id,
                                    "content": tool_result,
                                }
                            ]
                        })

                # Registrar turn result
                turn_result = TurnResult(
                    turn_number=turn_num,
                    tool_used=tool_used,
                    tool_input=tool_input,
                    output=output_text,
                    stop_reason=response.stop_reason
                )
                turn_results.append(turn_result)

                logger.info(f"Turn {turn_num} concluído: stop_reason={response.stop_reason}")

                # Parar se model não quer mais ferramentas
                if not has_tool_use or response.stop_reason == "end_turn":
                    break

                # Adicionar resposta final ao histórico se não houve tool use
                if not has_tool_use:
                    messages.append({"role": "assistant", "content": output_text})

            except asyncio.TimeoutError:
                logger.error(f"Timeout na turn {turn_num}")
                return ExecutionResult(
                    success=False,
                    content="",
                    tool_calls=tool_calls_history,
                    turn_count=turn_num - 1,
                    tokens_input=total_input_tokens,
                    tokens_output=total_output_tokens,
                    execution_time_seconds=time.time() - start_time,
                    error=f"Timeout após turn {turn_num}"
                )
            except Exception as e:
                logger.exception(f"Erro na turn {turn_num}")
                return ExecutionResult(
                    success=False,
                    content="",
                    tool_calls=tool_calls_history,
                    turn_count=turn_num - 1,
                    tokens_input=total_input_tokens,
                    tokens_output=total_output_tokens,
                    execution_time_seconds=time.time() - start_time,
                    error=str(e)
                )

        # Extrair conteúdo final
        final_output = turn_results[-1].output if turn_results else ""

        execution_time = time.time() - start_time

        return ExecutionResult(
            success=True,
            content=final_output,
            tool_calls=tool_calls_history,
            turn_count=len(turn_results),
            tokens_input=total_input_tokens,
            tokens_output=total_output_tokens,
            execution_time_seconds=execution_time,
        )

    def _execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """
        Executa uma ferramenta localmente.

        Args:
            tool_name: Nome da ferramenta
            tool_input: Entrada da ferramenta

        Returns:
            Resultado da execução (JSON string)
        """
        if tool_name not in TOOL_REGISTRY:
            error_msg = f"Ferramenta desconhecida: {tool_name}"
            logger.error(error_msg)
            return json.dumps({"success": False, "error": error_msg})

        try:
            # Validar entrada
            is_valid, error_msg = validate_tool_input(tool_name, tool_input)
            if not is_valid:
                logger.error(f"Validação falhou para {tool_name}: {error_msg}")
                return json.dumps({"success": False, "error": error_msg})

            # Executar ferramenta
            tool_func = TOOL_REGISTRY[tool_name]
            payload_json = json.dumps(tool_input)
            result = tool_func(payload_json)

            logger.info(f"Tool executada com sucesso: {tool_name}")
            return result

        except Exception as e:
            logger.exception(f"Erro ao executar {tool_name}")
            return json.dumps({"success": False, "error": str(e)})

    def _get_default_system_prompt(self) -> str:
        """Retorna prompt de sistema padrão para Managed Agents."""
        return """Você é um assistente especializado em processos logísticos e automação.

Seus objetivos:
1. Entender a tarefa solicitada com clareza
2. Usar as ferramentas disponíveis para resolver problemas
3. Validar resultados antes de reportar
4. Fornecer respostas estruturadas e acionáveis

Directives importantes:
- Sempre valide inputs antes de processar
- Use ferramentas quando necessário, mas não abuse
- Estruture respostas em Português
- Seja conciso e direto
- Reporte erros claramente se ocorrerem"""

    def get_schemas(self) -> dict[str, Any]:
        """Retorna schemas de ferramentas carregados."""
        return load_tool_schemas()
