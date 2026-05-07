"""
src.api_routes.oracle_chat — VEC-348 Oracle Chat (Gemini SSE).

Streaming de chat SIPOC via Google Gemini com Maker-Checker (LangGraph).
Retorna Server-Sent Events: {type:'delta'}, {type:'done'},
{type:'correction'}, {type:'requires_human_review'}.

Endpoint:
- POST /api/oracle/chat                                   oracle_chat (SSE)

Depende de:
- src.agents.oracle_runner.stream_oracle_chat_v2 (PR #7)
- LangGraph + flow_orchestrator (PR #7)
- oracle_session in-memory store (PR #6)
"""
from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger("api.oracle_chat")
router = APIRouter(tags=["oracle_chat"])


class OracleChatRequest(BaseModel):
    session_id: Optional[str] = None  # gerado no cliente; fallback uuid4
    event: str  # stage_intro | component_ack | w2h_question | w2h_analysis | meta_input
    stage: str
    user_profile: str  # beginner | advanced | pmo
    domain: str
    user_message: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    process_id: Optional[str] = None


@router.post("/api/oracle/chat")
async def oracle_chat(body: OracleChatRequest, request: Request):
    """Streaming Oracle SIPOC via Google Gemini com Maker-Checker (LangGraph)."""
    session_id = body.session_id or str(_uuid.uuid4())

    async def event_gen():
        try:
            from src.agents.oracle_runner import stream_oracle_chat_v2
            async for chunk in stream_oracle_chat_v2(body.dict(), session_id):
                yield chunk
        except Exception as e:
            import json as _json
            logger.error("oracle_chat stream error session=%s: %s", session_id, e)
            yield f"data: {_json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            yield f"data: {_json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
