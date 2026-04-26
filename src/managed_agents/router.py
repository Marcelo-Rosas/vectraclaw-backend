"""
Router: integra DecisionEngine ao fluxo de execução principal.

route_task_execution() é chamado pelo endpoint /api/tasks/{id}/execute
e retorna o resultado completo da execução (CMA) ou enfileira para o daemon (Harness).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .decision_engine import should_use_managed_agent, RoutingDecision
from .managed_agent_client import ManagedAgentClient, ExecutionResult
from .session_bridge import SessionBridge

logger = logging.getLogger("ManagedAgents.Router")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def route_task_execution(
    task: Dict[str, Any],
    force_mode: Optional[str],
    supabase_client=None,
    ws_manager=None,
) -> Dict[str, Any]:
    """
    Recebe a task e retorna o resultado de execução.

    force_mode: "managed_agent" | "harness" | "auto" | None
    ws_manager: instância do ConnectionManager para eventos em tempo real
    """
    task_id: str = task["id"]
    company_id: str = task.get("company_id", "")
    agent_id: str = task.get("assigned_to_agent_id") or ""

    # Determina executor
    if force_mode and force_mode != "auto":
        executor = force_mode
        decision = RoutingDecision(
            executor_type=executor,
            score=-1,
            rationale=f"force_mode={force_mode}",
            operation_type=task.get("operation_type", "other"),
        )
    else:
        decision = should_use_managed_agent(task)
        executor = decision.executor_type

    logger.info(
        "Router task_id=%s executor=%s score=%d rationale=%s",
        task_id, executor, decision.score, decision.rationale,
    )

    # Persiste decisão na task
    if supabase_client:
        try:
            supabase_client.table("tasks").update({
                "executor_type": executor,
                "executor_selected_at": _now_iso(),
                "executor_rationale": decision.rationale,
            }).eq("id", task_id).execute()
        except Exception as e:
            logger.warning(f"Router: persisting executor_type failed: {e}")

    if executor == "harness":
        # Apenas enfileira para o daemon — sem execução aqui
        if supabase_client:
            try:
                supabase_client.table("tasks").update({
                    "status": "queued",
                    "executor_type": "harness",
                }).eq("id", task_id).execute()
            except Exception as e:
                logger.warning(f"Router: enqueue harness failed: {e}")
        return {
            "executor_type": "harness",
            "status": "queued",
            "task_id": task_id,
            "rationale": decision.rationale,
        }

    # ---- CMA path ----
    bridge = SessionBridge(supabase_client)
    model = os.getenv("CMA_MODEL", "claude-haiku-4-5-20251001")
    session_id = bridge.create_session(
        task_id=task_id,
        agent_id=agent_id,
        model=model,
        executor_rationale=decision.rationale,
    )

    # Emite evento de início
    if ws_manager and company_id:
        try:
            await ws_manager.emit_managed_agent_event(
                company_id=company_id,
                event_type="managed_agent_start",
                payload={"session_id": session_id, "task_id": task_id, "model": model},
            )
        except Exception:
            pass

    prompt = f"[{task.get('operation_type','other')}] {task['title']}\n\n{task.get('description','')}"
    client = ManagedAgentClient(model=model)
    result: ExecutionResult = await client.execute_task(prompt, max_turns=3)

    # Persiste turns
    for tc in result.tool_calls:
        bridge.save_turn(
            session_id=session_id,
            turn_number=tc["turn"],
            input_text=str(tc.get("tool_input", "")),
            output_text=tc.get("tool_output", ""),
            stop_reason="tool_use",
            tool_used=tc["tool_name"],
            tool_input=tc.get("tool_input"),
        )

        if ws_manager and company_id:
            try:
                await ws_manager.emit_managed_agent_event(
                    company_id=company_id,
                    event_type="managed_agent_turn",
                    payload={
                        "session_id": session_id,
                        "task_id": task_id,
                        "turn_number": tc["turn"],
                        "tool_used": tc["tool_name"],
                        "output_preview": tc.get("tool_output", "")[:200],
                        "stop_reason": "tool_use",
                    },
                )
            except Exception:
                pass

    # Fecha sessão
    bridge.complete_session(
        session_id=session_id,
        final_output=result.content,
        tokens_input=result.tokens_input,
        tokens_output=result.tokens_output,
        success=result.success,
        error_message=result.error,
    )

    # Atualiza task no banco
    final_status = "done" if result.success else "blocked"
    if supabase_client:
        try:
            supabase_client.table("tasks").update({
                "status": final_status,
                "executor_type": "managed_agent",
                "managed_agent_session_id": session_id,
            }).eq("id", task_id).execute()
        except Exception as e:
            logger.warning(f"Router: update task post-CMA failed: {e}")

    # Emite evento de conclusão ou erro
    if ws_manager and company_id:
        event_type = "managed_agent_complete" if result.success else "managed_agent_error"
        try:
            await ws_manager.emit_managed_agent_event(
                company_id=company_id,
                event_type=event_type,
                payload={
                    "session_id": session_id,
                    "task_id": task_id,
                    "status": final_status,
                    "turn_count": result.turn_count,
                    "tokens_input": result.tokens_input,
                    "tokens_output": result.tokens_output,
                    "execution_time_seconds": result.execution_time_seconds,
                    "error": result.error,
                },
            )
        except Exception:
            pass

    return {
        "executor_type": "managed_agent",
        "session_id": session_id,
        "status": final_status,
        "result": result.content,
        "task_id": task_id,
        "turn_count": result.turn_count,
        "tokens_input": result.tokens_input,
        "tokens_output": result.tokens_output,
        "execution_time_seconds": result.execution_time_seconds,
        "rationale": decision.rationale,
    }
