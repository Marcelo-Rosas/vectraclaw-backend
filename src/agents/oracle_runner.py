"""Runner público do fluxo Oracle SIPOC.

Este módulo é o ponto de entrada para executar o orquestrador LangGraph
em produção. Ele:

1. Recupera (ou cria) a sessão do Oracle.
2. Constrói um ``FlowState`` válido através da factory
   ``build_initial_flow_state``.
3. Executa o grafo de forma assíncrona.
4. Transmite os deltas de streaming do LLM para o cliente via SSE.
5. Persiste o resultado final na sessão para manter contexto entre
   interações.

Importante: o runner não deve conhecer detalhes internos dos nós do
grafo. Ele é apenas um adaptador entre a API HTTP e o orquestrador.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
from typing import Any, AsyncIterator, Dict, Optional

from langchain_core.messages import HumanMessage

from src.services.flow_orchestrator import (
    FlowState,
    build_initial_flow_state,
    get_orchestrator,
)
from src.services.oracle_session import (
    get_or_create_session,
    register_stream_queue,
    unregister_stream_queue,
)

logger = logging.getLogger("OracleRunner")

# Timeout máximo para uma execução completa do grafo.
# Cloud Run containers podem ter deadlines; manter abaixo de 30s
# garante margem para overhead de rede.
GRAPH_TIMEOUT_SECONDS = 25


def _build_pending_activity(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extrai atividade pendente do payload recebido pela API."""
    ctx = payload.get("context") or {}
    activity_name = ctx.get("activity_name")
    if not activity_name:
        return None
    return {
        "id": ctx.get("activity_id"),
        "name": activity_name,
        "w2h_data": ctx.get("w2h_data") or {},
    }


async def stream_oracle_chat_v2(
    payload: Dict[str, Any], session_id: str
) -> AsyncIterator[str]:
    """Executa o fluxo Oracle e faz streaming dos eventos via SSE.

    O grafo pode realizar múltiplas iterações maker-checker internamente.
    Apenas os deltas gerados pelo maker são transmitidos em tempo real;
    o veredicto final e correções são enviados ao término.

    Args:
        payload: Payload JSON da requisição.
        session_id: Identificador da sessão Oracle.

    Yields:
        Eventos formatados como Server-Sent Events (SSE).
    """
    session = get_or_create_session(session_id)
    q: asyncio.Queue = asyncio.Queue()
    register_stream_queue(session_id, q)

    ctx = payload.get("context") or {}
    user_message = payload.get("user_message") or ctx.get("value") or ""

    # Usa a factory para garantir um FlowState completo e válido.
    state = build_initial_flow_state(
        session_id=session_id,
        user_message=user_message,
        process_id=payload.get("process_id"),
        domain=payload.get("domain", "Processo"),
        user_profile=payload.get("user_profile", "advanced"),
        current_stage=payload.get("stage", "idle"),
        current_event=payload.get("event", "meta_input"),
        current_w2h_field=ctx.get("w2h_field"),
        pending_activity=_build_pending_activity(payload),
        sipoc_snapshot=session.sipoc_snapshot,
        collected_5w2h=session.collected_5w2h,
    )

    orch = get_orchestrator()
    graph_task: asyncio.Task = asyncio.create_task(_run_graph(orch, state))

    try:
        while not graph_task.done() or not q.empty():
            try:
                ev = await asyncio.wait_for(q.get(), timeout=0.05)
                yield f"data: {_json.dumps(ev)}\n\n"
            except asyncio.TimeoutError:
                continue

        final_state = await graph_task

        # Emite correções estruturadas ao final do fluxo.
        for corr in (final_state or {}).get("checker_corrections", []):
            yield f"data: {_json.dumps(corr)}\n\n"

        yield f"data: {_json.dumps({'type': 'done'})}\n\n"

        # Persistência do turno na sessão.
        _persist_turn(session, user_message, final_state, payload)

    except Exception as exc:
        logger.error("oracle_runner failed session=%s: %s", session_id, exc, exc_info=True)
        yield f"data: {_json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        yield f"data: {_json.dumps({'type': 'done'})}\n\n"
    finally:
        unregister_stream_queue(session_id)


async def _run_graph(orch: Any, state: FlowState) -> Optional[Dict[str, Any]]:
    """Invoca o grafo com timeout para evitar execuções fantasmas.

    Args:
        orch: Orquestrador LangGraph compilado.
        state: Estado inicial do fluxo.

    Returns:
        Estado final do grafo ou ``None`` em caso de falha/timeout.
    """
    try:
        return await asyncio.wait_for(
            orch.ainvoke(state),
            timeout=GRAPH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error(
            "oracle_runner._run_graph timeout session=%s after %ds",
            state.get("session_id"),
            GRAPH_TIMEOUT_SECONDS,
        )
        return None
    except Exception as exc:
        logger.error("oracle_runner._run_graph failed: %s", exc, exc_info=True)
        return None


def _persist_turn(
    session: Any,
    user_message: str,
    final_state: Optional[Dict[str, Any]],
    payload: Dict[str, Any],
) -> None:
    """Persiste o resultado do turno na sessão Oracle.

    Além das mensagens trocadas, preserva metadados do maker-checker
    para que turnos futuros tenham acesso ao histórico de validação.
    """
    if not final_state:
        return

    maker_text = final_state.get("maker_response_text", "")
    if maker_text:
        session.messages.append({"role": "user", "content": user_message})
        session.messages.append({"role": "assistant", "content": maker_text})
        session.current_stage = payload.get("stage", session.current_stage)

    # Preserva metadados de validação para turnos futuros.
    session.last_checker_verdict = final_state.get("checker_verdict", "accept")
    session.last_checker_feedback = final_state.get("checker_feedback", "")
    session.last_checker_corrections = final_state.get("checker_corrections", []) or []
    session.last_maker_structured = final_state.get("maker_structured", {}) or {}
    session.last_iteration_count = final_state.get("iteration_count", 0)
