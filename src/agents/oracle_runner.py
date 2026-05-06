import asyncio
import json as _json
import logging
from typing import Any, AsyncIterator, Dict, Optional

from langchain_core.messages import HumanMessage

from src.services.flow_orchestrator import FlowState, get_orchestrator
from src.services.oracle_session import (
    get_or_create_session,
    register_stream_queue,
    unregister_stream_queue,
)

logger = logging.getLogger("OracleRunner")


def _build_pending_activity(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    ctx = payload.get("context") or {}
    activity_name = ctx.get("activity_name")
    if not activity_name:
        return None
    return {
        "id": ctx.get("activity_id"),
        "name": activity_name,
        "w2h_data": ctx.get("w2h_data") or {},
    }


async def stream_oracle_chat_v2(payload: Dict[str, Any], session_id: str) -> AsyncIterator[str]:
    """Streams Oracle SIPOC chat with Maker-Checker validation."""
    session = get_or_create_session(session_id)
    q: asyncio.Queue = asyncio.Queue()
    register_stream_queue(session_id, q)

    ctx = payload.get("context") or {}
    user_message = payload.get("user_message") or ctx.get("value") or ""

    state: FlowState = {
        "session_id": session_id,
        "process_id": payload.get("process_id"),
        "domain": payload.get("domain", "Processo"),
        "user_profile": payload.get("user_profile", "advanced"),
        "messages": [HumanMessage(content=user_message)],
        "sipoc_snapshot": session.sipoc_snapshot,
        "collected_5w2h": session.collected_5w2h,
        "current_stage": payload.get("stage", "idle"),
        "current_event": payload.get("event", "meta_input"),
        "current_w2h_field": ctx.get("w2h_field"),
        "pending_activity": _build_pending_activity(payload),
        "last_user_message": user_message,
        "maker_response_text": "",
        "maker_structured": {},
        "checker_verdict": "accept",
        "checker_feedback": "",
        "checker_corrections": [],
        "iteration_count": 0,
        "current_node": "supervisor",
    }

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
        for corr in (final_state or {}).get("checker_corrections", []):
            yield f"data: {_json.dumps(corr)}\n\n"

        yield f"data: {_json.dumps({'type': 'done'})}\n\n"

        # Persist last turn to session
        maker_text = (final_state or {}).get("maker_response_text", "")
        if maker_text:
            session.messages.append({"role": "user", "content": user_message})
            session.messages.append({"role": "assistant", "content": maker_text})
            session.current_stage = payload.get("stage", session.current_stage)

    except Exception as exc:
        logger.error("oracle_runner failed session=%s: %s", session_id, exc)
        yield f"data: {_json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        yield f"data: {_json.dumps({'type': 'done'})}\n\n"
    finally:
        unregister_stream_queue(session_id)


async def _run_graph(orch: Any, state: FlowState) -> Optional[Dict[str, Any]]:
    try:
        return await orch.ainvoke(state)
    except Exception as exc:
        logger.error("oracle_runner._run_graph failed: %s", exc)
        return None
