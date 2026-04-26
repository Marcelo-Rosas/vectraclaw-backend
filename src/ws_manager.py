"""
VEC-183 — ConnectionManager para WebSocket em tempo real.

Mantém um dict `company_id → List[WebSocket]` e expõe helpers de broadcast.
Singleton: `manager` é importado por `api.py` e por qualquer serviço que precise
emitir eventos (Doctor loop, endpoints de mutação).

Contrato de mensagens (alinhado ao mock VectraClip `/mocks/ws.ts`):

  hello        { type: "hello",        companyId: str }
  heartbeat    { type: "heartbeat",    payload: <Heartbeat camelCase> }
  agent_updated{ type: "agent_updated",payload: <Agent camelCase> }
  task_updated { type: "task_updated", payload: <Task camelCase> }
  incident_updated { type: "incident_updated", payload: <Incident camelCase> }
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Protocol


class WebSocketLike(Protocol):
    async def send_text(self, data: str) -> None: ...

logger = logging.getLogger("VectraClawWS")


class ConnectionManager:
    def __init__(self) -> None:
        # company_id → lista de sockets ativos
        self._connections: Dict[str, List[WebSocketLike]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, websocket: WebSocketLike, company_id: str) -> None:
        # accept() já foi chamado no route handler (antes da auth)
        self._connections[company_id].append(websocket)
        logger.info(
            "WS connect company=%s total=%d",
            company_id,
            len(self._connections[company_id]),
        )

    def disconnect(self, websocket: WebSocketLike, company_id: str) -> None:
        conns = self._connections.get(company_id, [])
        try:
            conns.remove(websocket)
        except ValueError:
            pass
        logger.info(
            "WS disconnect company=%s remaining=%d",
            company_id,
            len(conns),
        )

    # ------------------------------------------------------------------
    # Emit helpers
    # ------------------------------------------------------------------

    async def broadcast(self, company_id: str, message: Dict[str, Any]) -> None:
        """Envia `message` (JSON) para todos os sockets da company. Fire-and-forget."""
        text = json.dumps(message, default=str)
        dead: List[WebSocketLike] = []
        for ws in list(self._connections.get(company_id, [])):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, company_id)

    async def emit_hello(self, company_id: str) -> None:
        await self.broadcast(company_id, {"type": "hello", "companyId": company_id})

    async def emit_heartbeat(self, company_id: str, payload: Dict[str, Any]) -> None:
        await self.broadcast(company_id, {"type": "heartbeat", "payload": payload})

    async def emit_agent_updated(
        self, company_id: str, payload: Dict[str, Any]
    ) -> None:
        await self.broadcast(
            company_id, {"type": "agent_updated", "payload": payload}
        )

    async def emit_task_updated(
        self, company_id: str, payload: Dict[str, Any]
    ) -> None:
        await self.broadcast(
            company_id, {"type": "task_updated", "payload": payload}
        )

    async def emit_incident_updated(
        self, company_id: str, payload: Dict[str, Any]
    ) -> None:
        await self.broadcast(
            company_id, {"type": "incident_updated", "payload": payload}
        )

    async def emit_managed_agent_event(
        self,
        company_id: str,
        event_type: str,
        payload: Dict[str, Any],
    ) -> None:
        """Emite evento CMA em tempo real.

        event_type: "managed_agent_start" | "managed_agent_turn"
                    | "managed_agent_complete" | "managed_agent_error"
        """
        import datetime as _dt
        await self.broadcast(
            company_id,
            {
                "type": event_type,
                "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                "data": payload,
            },
        )

    # ------------------------------------------------------------------
    # Fire-and-forget para código sync (loop.py)
    # ------------------------------------------------------------------

    def broadcast_nowait(self, company_id: str, message: Dict[str, Any]) -> None:
        """
        Agenda o broadcast no event loop do uvicorn sem bloquear.
        Seguro chamar de código sync (Doctor loop) que roda em asyncio.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.broadcast(company_id, message))
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # Diagnóstico
    # ------------------------------------------------------------------

    def connection_count(self, company_id: str) -> int:
        return len(self._connections.get(company_id, []))

    def all_counts(self) -> Dict[str, int]:
        return {cid: len(ws) for cid, ws in self._connections.items() if ws}


# Singleton global importado por api.py e loop.py
manager = ConnectionManager()
