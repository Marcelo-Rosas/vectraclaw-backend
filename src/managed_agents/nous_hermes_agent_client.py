"""
NousHermesAgentClient — executa tasks via HTTP no container nous-hermes-runtime.

Config catalog-driven: backend resolve field_values antes de chamar o runtime.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from src.services import nous_hermes as nh

from .managed_agent_client import ExecutionResult

logger = logging.getLogger("ManagedAgents.NousHermes")

class NousHermesAgentClient:
    """Cliente CMA para provider `nous_hermes`."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}

    async def execute_task(
        self,
        prompt: str,
        max_turns: int = 3,
        system_prompt: Optional[str] = None,
        *,
        company_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> ExecutionResult:
        start = time.monotonic()
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt.strip()}\n\n{prompt}"
        if task_id:
            full_prompt = f"[TASK_ID: {task_id}]\n\n{full_prompt}"

        if not company_id:
            return ExecutionResult(
                success=False,
                content="",
                error="NousHermesAgentClient: company_id ausente no contexto CMA",
                execution_time_seconds=time.monotonic() - start,
            )

        try:
            from src.api import supabase

            if not supabase or not nh.is_adapter_active(supabase, company_id):
                return ExecutionResult(
                    success=False,
                    content="",
                    error="adapter nous-hermes inativo ou Supabase indisponível",
                    execution_time_seconds=time.monotonic() - start,
                )

            hermes_config, api_key = nh.resolve_nous_hermes_config(
                supabase, company_id, agent_id=agent_id
            )
            timeout_seconds = int(hermes_config["timeout_seconds"])
            cfg_turns = hermes_config.get("max_turns") or max_turns
            payload_cfg = {k: v for k, v in hermes_config.items() if k != "timeout_seconds"}
            data = await nh.runtime_exec(
                prompt=full_prompt,
                hermes_config=payload_cfg,
                api_key=api_key,
                max_turns=int(cfg_turns),
                timeout_seconds=timeout_seconds,
            )
        except nh.NousHermesConfigError as exc:
            return ExecutionResult(
                success=False,
                content="",
                error=str(exc),
                execution_time_seconds=time.monotonic() - start,
            )
        except Exception as exc:
            logger.exception("NousHermes execute_task failed")
            return ExecutionResult(
                success=False,
                content="",
                error=str(exc),
                execution_time_seconds=time.monotonic() - start,
            )

        elapsed = time.monotonic() - start
        return ExecutionResult(
            success=bool(data.get("success")),
            content=str(data.get("content") or ""),
            tool_calls=[],
            turn_count=0,
            tokens_input=0,
            tokens_output=0,
            execution_time_seconds=elapsed,
            tokens_per_second=0.0,
            error=data.get("error"),
        )
