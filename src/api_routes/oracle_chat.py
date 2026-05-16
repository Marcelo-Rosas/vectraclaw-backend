"""
src.api_routes.oracle_chat — VEC-348 Oracle Chat (Gemini SSE).

Streaming de chat SIPOC via Google Gemini com Maker-Checker (LangGraph).
Retorna Server-Sent Events: {type:'delta'}, {type:'done'},
{type:'correction'}, {type:'requires_human_review'}.

Endpoint:
- POST /api/oracle/chat                                   oracle_chat (SSE)

PR5 (Fase A): suporte a `activity_id` no body — quando presente, hidrata
automaticamente o `context` com dados da atividade SIPOC + componentes
vizinhos do process, sem o frontend precisar fazer N pre-fetches.

Depende de:
- src.agents.oracle_runner.stream_oracle_chat_v2 (PR #7)
- LangGraph + flow_orchestrator (PR #7)
- oracle_session in-memory store (PR #6)
"""
from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any, Dict, List, Optional

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
    activity_id: Optional[str] = None  # PR5: scoped chat per-activity


def _component_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    """Resumo enxuto de um sipoc_component pra injetar no contexto."""
    content = row.get("content") or {}
    if isinstance(content, dict):
        name = content.get("name") or content.get("title") or ""
        description = content.get("description") or ""
    else:
        name = str(content)[:80]
        description = ""
    return {
        "id": row["id"],
        "type": row.get("type"),
        "name": name,
        "description": description,
        "order": row.get("order"),
    }


def _fetch_activity_context(activity_id: str, client) -> Optional[Dict[str, Any]]:
    """Hidrata contexto da atividade pro Oracle.

    Retorna dict com:
      - activity:    {id, name, description, 5w2h, suggested_operation_type, automation_status}
      - process:     {id, name, sector_id}
      - neighbors:   {suppliers[], inputs[], outputs[], customers[], activities[]}
                     — outros componentes do mesmo process (resumo enxuto)
      - responsible: {position_id, title}  (NULL se sem RACI atribuído)

    Falhas silenciosas (log + None) — Oracle continua funcionando sem o enriquecimento.
    """
    try:
        # 1. Activity
        ares = (
            client.table("sipoc_components")
            .select("id, process_id, type, content, automation_status, suggested_operation_type, responsible_position_id, cloned_from_template_id")
            .eq("id", activity_id)
            .limit(1)
            .execute()
        )
        if not ares.data:
            logger.warning("oracle_chat scoped: activity %s não encontrado", activity_id)
            return None
        activity_row = ares.data[0]
        process_id = activity_row.get("process_id")
        content = activity_row.get("content") or {}
        if not isinstance(content, dict):
            content = {}

        activity_block = {
            "id": activity_row["id"],
            "type": activity_row.get("type"),
            "name": content.get("name") or content.get("title"),
            "description": content.get("description"),
            "what": content.get("what"),
            "who": content.get("who"),
            "when": content.get("when"),
            "where": content.get("where"),
            "why": content.get("why"),
            "how": content.get("how"),
            "how_much": content.get("how_much"),
            "suggested_operation_type": activity_row.get("suggested_operation_type"),
            "automation_status": activity_row.get("automation_status") or "undefined",
            "cloned_from_template_id": activity_row.get("cloned_from_template_id"),
        }

        # 2. Process
        process_block: Dict[str, Any] = {}
        if process_id:
            pres = (
                client.table("sipoc_processes")
                .select("id, name, sector_id")
                .eq("id", process_id)
                .limit(1)
                .execute()
            )
            if pres.data:
                process_block = {
                    "id": pres.data[0]["id"],
                    "name": pres.data[0].get("name"),
                    "sector_id": pres.data[0].get("sector_id"),
                }

        # 3. Neighbors — outros components do mesmo process, agrupados por type
        neighbors: Dict[str, List[Dict[str, Any]]] = {
            "suppliers": [],
            "inputs": [],
            "outputs": [],
            "customers": [],
            "activities": [],
        }
        if process_id:
            nres = (
                client.table("sipoc_components")
                .select("id, type, content, order")
                .eq("process_id", process_id)
                .neq("id", activity_id)
                .order("order")
                .execute()
            )
            for row in (nres.data or []):
                t = (row.get("type") or "").lower()
                bucket = {
                    "supplier": "suppliers",
                    "input": "inputs",
                    "output": "outputs",
                    "customer": "customers",
                    "activity": "activities",
                }.get(t)
                if bucket:
                    neighbors[bucket].append(_component_summary(row))

        # 4. Responsible position
        responsible_block: Optional[Dict[str, Any]] = None
        rp_id = activity_row.get("responsible_position_id")
        if rp_id:
            rres = (
                client.table("sipoc_positions")
                .select("id, title, sector_id")
                .eq("id", rp_id)
                .limit(1)
                .execute()
            )
            if rres.data:
                responsible_block = {
                    "position_id": rres.data[0]["id"],
                    "title": rres.data[0].get("title"),
                    "sector_id": rres.data[0].get("sector_id"),
                }

        return {
            "activity": activity_block,
            "process": process_block,
            "neighbors": neighbors,
            "responsible": responsible_block,
        }
    except Exception as e:
        logger.warning("oracle_chat scoped hidratação falhou activity=%s: %s", activity_id, e)
        return None


@router.post("/api/oracle/chat")
async def oracle_chat(body: OracleChatRequest, request: Request):
    """Streaming Oracle SIPOC via Google Gemini com Maker-Checker (LangGraph).

    PR5: se `activity_id` for passado no body, hidrata `context` com
    snapshot da atividade + neighbors + responsible. Frontend não precisa
    fazer pre-fetch separado.
    """
    session_id = body.session_id or str(_uuid.uuid4())

    # PR5: hidratação do contexto quando scoped por activity
    payload = body.dict()
    if body.activity_id:
        try:
            from src.api import get_authenticated_client
            client = get_authenticated_client(request.state.token)
            scoped = _fetch_activity_context(body.activity_id, client)
            if scoped:
                base_ctx = payload.get("context") or {}
                if not isinstance(base_ctx, dict):
                    base_ctx = {}
                # Não sobrescreve chaves que o cliente passou explicitamente.
                # Merge: scoped vai como `activity_scope` pra ficar visível mas
                # isolado de chaves arbitrárias do cliente.
                base_ctx.setdefault("activity_scope", scoped)
                payload["context"] = base_ctx
                logger.info(
                    "oracle_chat scoped session=%s activity=%s neighbors_count=%s",
                    session_id,
                    body.activity_id,
                    sum(len(v) for v in (scoped.get("neighbors") or {}).values()),
                )
        except Exception as e:
            logger.warning("oracle_chat scoped enrichment falhou (degrada gracioso): %s", e)

    async def event_gen():
        try:
            from src.agents.oracle_runner import stream_oracle_chat_v2
            async for chunk in stream_oracle_chat_v2(payload, session_id):
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
