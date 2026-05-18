"""ClaudeCodeCliAgentClient: executa tasks via subprocess `claude -p` usando
a Claude Code OAuth subscription do host (NÃO API key paga).

Diferença vs ManagedAgentClient: aquele usa Anthropic SDK direto com
`ANTHROPIC_API_KEY` (pay-per-token); este usa o binário `claude` instalado
no host com auth OAuth Max subscription (`~/.claude/.credentials.json`).

Quando usar cada um:
- ManagedAgentClient (slug=claude_code, provider=anthropic): produção
  multi-tenant, custo previsível, tool_use loop completo, tokens trackeados
- ClaudeCodeCliAgentClient (slug=claude_code_cli, provider=claude_cli_subscription):
  MVP single-tenant (host do Marcelo), sem custo extra até 15/jun/2026
  (depois charge separado via Agent SDK credit — memory
  `claude-cli-subscription-subprocess`)

Catalog-driven via `agent_adapter_configs.field_values_json`:
- model_id: alias canônico CLI (sonnet/opus/haiku — NÃO ID Anthropic completo)
- system_prompt: textarea opcional
- extended_thinking: boolean opcional
- timeout_seconds: text default "180"

Defesas obrigatórias do subprocess (memory `claude-cli-subscription-subprocess`):
- env.pop("ANTHROPIC_API_KEY"): força OAuth (sem essa, CLI tenta API key inválida silently)
- env.pop("ANTHROPIC_AUTH_TOKEN"): garantia extra
- stdin=subprocess.DEVNULL: evita warning "no stdin data received in 3s"

Tokens: CLI não expõe contagem programaticamente. Retorna 0 em
tokens_input/tokens_output/tokens_per_second. Athena HR (memory
`athena-hr-telemetry-optimization`) deve ignorar tasks com
provider=claude_cli_subscription nas agregações estatísticas (todos zerados).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

from .managed_agent_client import ExecutionResult

logger = logging.getLogger("ManagedAgents.ClaudeCodeCli")

# Aliases canônicos válidos do Claude CLI. Não é hardcode de catálogo —
# é constraint técnica do binário (CLI rejeita IDs completos da API Anthropic).
# Validation runtime: se model_id vier fora dessa lista, log warning e
# tenta enviar mesmo assim (CLI vai falhar com mensagem útil).
_CLI_VALID_MODEL_ALIASES = ("sonnet", "haiku", "opus")

# Default usado SÓ se config[model_id] estiver vazio. NÃO é fallback genérico —
# é caminho de erro defensivo. Adapter field define options no UI.
_CLI_DEFAULT_MODEL_ALIAS = "sonnet"

# Default timeout — 3min. Aceitável pra cotação freight; configurável por field.
_CLI_DEFAULT_TIMEOUT_S = 180


class ClaudeCodeCliAgentClient:
    """Subprocess wrapper de `claude -p`. 100% catalog-driven via adapter config."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        config = config or {}
        # Resolve alias do model do adapter config; fallback defensive.
        model_id = str(config.get("model_id") or "").strip()
        if not model_id:
            logger.warning("model_id ausente no config; usando default %r", _CLI_DEFAULT_MODEL_ALIAS)
            model_id = _CLI_DEFAULT_MODEL_ALIAS
        if model_id not in _CLI_VALID_MODEL_ALIASES:
            logger.warning(
                "model_id=%r não está nos aliases canônicos %s — CLI pode falhar",
                model_id, _CLI_VALID_MODEL_ALIASES,
            )
        self.model_id = model_id
        self.system_prompt = str(config.get("system_prompt") or "").strip() or None
        self.extended_thinking = bool(config.get("extended_thinking", False))
        try:
            self.timeout_seconds = int(config.get("timeout_seconds") or _CLI_DEFAULT_TIMEOUT_S)
        except (TypeError, ValueError):
            self.timeout_seconds = _CLI_DEFAULT_TIMEOUT_S

    async def execute_task(
        self,
        prompt: str,
        agent_id: Optional[str] = None,
        company_id: Optional[str] = None,
        task_id: Optional[str] = None,
        **kwargs: Any,
    ) -> ExecutionResult:
        """Spawna `claude -p {prompt}` async via asyncio.subprocess.

        Não usa tool_use (CLI single-shot non-interactive). Não trackeia tokens
        (CLI não expõe). Retorna ExecutionResult com `content`, `success`,
        `execution_time_seconds`; demais campos = 0/empty.
        """
        if not prompt or not prompt.strip():
            return ExecutionResult(
                success=False, content="", error="empty_prompt_rejected",
            )

        # Limpa env de credentials que sobrescreveriam OAuth (memory
        # `claude-cli-subscription-subprocess` — defesa dupla)
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)

        args = ["claude", "-p", prompt, "--model", self.model_id, "--output-format", "text"]
        if self.system_prompt:
            args += ["--system-prompt", self.system_prompt]
        # extended_thinking: CLI suporta `--thinking` em models compatíveis (sonnet/opus).
        # Se não suportar, CLI ignora silently — flag idempotente. Mantém aceitável.
        if self.extended_thinking:
            args.append("--thinking")

        t0 = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,  # evita warning 3s stdin
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout_seconds,
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                dt = time.time() - t0
                logger.error("claude -p timeout (%ds)", self.timeout_seconds)
                return ExecutionResult(
                    success=False, content="",
                    error=f"timeout_seconds={self.timeout_seconds}",
                    execution_time_seconds=dt,
                )
        except FileNotFoundError:
            return ExecutionResult(
                success=False, content="",
                error="claude_cli_not_found_in_PATH (instalar Claude Code no host)",
            )
        except Exception as e:
            logger.exception("claude -p subprocess falhou inesperadamente")
            return ExecutionResult(
                success=False, content="", error=f"subprocess_error: {e!r}",
            )

        dt = time.time() - t0
        stdout = (stdout_b or b"").decode("utf-8", errors="replace").strip()
        stderr = (stderr_b or b"").decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            err_excerpt = stderr[:500] if stderr else "(stderr vazio)"
            logger.error("claude -p rc=%d task=%s err=%s",
                         proc.returncode, task_id, err_excerpt)
            return ExecutionResult(
                success=False,
                content=stdout,
                error=f"claude_cli_exit_{proc.returncode}: {err_excerpt}",
                execution_time_seconds=dt,
            )

        logger.info(
            "claude -p OK task=%s model=%s len=%d dt=%.1fs",
            task_id, self.model_id, len(stdout), dt,
        )
        return ExecutionResult(
            success=True,
            content=stdout,
            execution_time_seconds=dt,
            # tokens NÃO expostos pelo CLI — preencher 0 (Athena HR ignora
            # provider=claude_cli_subscription nas agregações estatísticas)
            tokens_input=0,
            tokens_output=0,
            tokens_per_second=0.0,
        )
