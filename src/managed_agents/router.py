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

from .agent_client_factory import get_agent_client
from .decision_engine import should_use_managed_agent, RoutingDecision
from .managed_agent_client import ManagedAgentClient, ExecutionResult
from .nous_hermes_agent_client import NousHermesAgentClient
from .session_bridge import SessionBridge

logger = logging.getLogger("ManagedAgents.Router")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _emit_run_heartbeat(
    *,
    agent_id: str,
    task_id: str,
    provider: str,
    model: str,
    result: ExecutionResult,
    supabase_client,
    ws_manager_inst,
) -> None:
    """
    Emite heartbeat sintético após uma execução CMA, alimentando o burn rate
    e o painel de tokens. Só dispara para providers efetivamente suportados
    (anthropic, ollama) — slots reservados (openai, google) ou desconhecidos
    são ignorados.

    Falha silenciosa: um problema na emissão de heartbeat não pode reverter
    o resultado da task que já foi persistida.
    """
    # W8 — `claude_cli_subscription` adicionado (auditor 2026-05-18).
    # `nous_hermes` omitido de propósito (PRD §8.5 / R15): tokens=0 polui burn rate
    # até trajectory ingest existir.
    if provider not in ("anthropic", "ollama", "huggingface", "groq", "claude_cli_subscription"):
        return
    if not agent_id:
        return
    try:
        # Import lazy para evitar circular import (api.py importa este módulo).
        from src.api import _emit_heartbeat_internal, NewHeartbeatInput

        provider_label = {
            "ollama": "Ollama",
            "anthropic": "Anthropic",
            "huggingface": "HuggingFace",
            "groq": "Groq",
            "claude_cli_subscription": "Claude CLI",
        }.get(provider, provider.title())
        log_excerpt = (
            f"{provider_label}: {result.tokens_output} tokens em "
            f"{result.tokens_per_second} tok/s"
        )
        payload = NewHeartbeatInput(
            agentId=agent_id,
            status="idle" if result.success else "error",
            tokensUsed=result.tokens_input + result.tokens_output,
            inputTokens=result.tokens_input,
            outputTokens=result.tokens_output,
            modelId=model,
            logExcerpt=log_excerpt,
            taskId=task_id,
        )
        await _emit_heartbeat_internal(
            payload,
            supabase_client=supabase_client,
            ws_manager_inst=ws_manager_inst,
        )
    except Exception as e:
        logger.warning("Router: emit heartbeat after CMA falhou: %s", e)


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

    agent_id_hint = f"\n\nAGENT_ID para read_hermes_inbox: {agent_id}" if agent_id else ""
    company_id_for_hint = task.get("company_id") or ""
    company_hint = (
        f"\nCOMPANY_ID para query_rag (consulta da memória corporativa): {company_id_for_hint}"
        if company_id_for_hint else ""
    )
    prompt = f"[{task.get('operation_type','other')}] {task['title']}\n\n{task.get('description','')}{agent_id_hint}{company_hint}"

    # Resolve o provider do adapter associado ao agente. Fallback retrocompat:
    # agentes sem agent_adapter_configs usam Anthropic (comportamento antigo).
    provider = "anthropic"
    field_values: Dict[str, Any] = {}
    if supabase_client and agent_id:
        try:
            res = (
                supabase_client.table("agent_adapter_configs")
                .select("field_values_json, adapter_catalog!inner(provider)")
                .eq("agent_id", agent_id)
                .limit(1)
                .execute()
            )
            if res.data:
                row = res.data[0]
                field_values = row.get("field_values_json") or {}
                provider = (row.get("adapter_catalog") or {}).get("provider") or "anthropic"
                # W5 hybrid resolve: company_adapter_values é PRIMARY, agent override
                # por cima. O router antes lia só o agent config — creds salvas no
                # company-level (/admin/connectors) não chegavam ao client. Mescla aqui.
                adapter_id = None
                try:
                    ac_row = (
                        supabase_client.table("agent_adapter_configs")
                        .select("adapter_id")
                        .eq("agent_id", agent_id)
                        .limit(1)
                        .execute()
                    )
                    adapter_id = ac_row.data[0].get("adapter_id") if ac_row.data else None
                    if adapter_id and company_id:
                        cv = (
                            supabase_client.table("company_adapter_values")
                            .select("field_values_json")
                            .eq("company_id", company_id)
                            .eq("adapter_id", adapter_id)
                            .limit(1)
                            .execute()
                        )
                        if cv.data:
                            company_vals = cv.data[0].get("field_values_json") or {}
                            # company primary, agent override (só sobrescreve não-vazios)
                            merged = dict(company_vals)
                            merged.update({k: v for k, v in field_values.items() if v not in (None, "")})
                            field_values = merged
                    # Resolve vault:// refs → texto claro (groq/hf leem key do config;
                    # anthropic usa env). resolve_secret_ref em src.api (lazy).
                    if company_id and field_values:
                        try:
                            from src.api import resolve_secret_ref
                            field_values = {
                                k: (resolve_secret_ref(v, company_id) if isinstance(v, str) and v.startswith("vault://") else v)
                                for k, v in field_values.items()
                            }
                        except Exception as e:
                            logger.warning(f"Router: resolve vault refs falhou agent_id={agent_id}: {e}")
                except Exception as e:
                    logger.warning(f"Router: company_adapter_values merge falhou agent_id={agent_id}: {e}")
        except Exception as e:
            logger.warning(f"Router: provider lookup falhou agent_id={agent_id}: {e}")

    client = get_agent_client(provider, model=model, config=field_values)
    if provider == "nous_hermes":
        if not isinstance(client, NousHermesAgentClient):
            raise RuntimeError(
                f"factory retornou {type(client).__name__}, esperado NousHermesAgentClient"
            )
        result = await client.execute_task(
            prompt,
            max_turns=3,
            system_prompt=field_values.get("system_prompt"),
            company_id=company_id,
            agent_id=agent_id,
            task_id=task_id,
        )
    elif provider in ("anthropic", "huggingface", "groq"):
        # Parte 2 MCP: estes clients aceitam agent_id/company_id → injetam tools MCP
        # dos bindings ativos + roteiam tool call prefixado mcp__ pro runner.
        result = await client.execute_task(
            prompt,
            max_turns=3,
            agent_id=agent_id,
            company_id=company_id,
        )
    else:
        # ollama — assinatura legada (sem MCP ainda; parte 2.x futura)
        result = await client.execute_task(prompt, max_turns=3)

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

    # Heartbeat sintético: alimenta burn rate, painel de tokens e WS `heartbeat`.
    # Função interna lida com providers não suportados e falha silenciosa.
    await _emit_run_heartbeat(
        agent_id=agent_id,
        task_id=task_id,
        provider=provider,
        model=model,
        result=result,
        supabase_client=supabase_client,
        ws_manager_inst=ws_manager,
    )

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
