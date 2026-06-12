import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("OracleSession")


class _OracleSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: List[Dict[str, Any]] = []
        self.sipoc_snapshot: Dict[str, Any] = {}
        self.collected_5w2h: Dict[str, Dict[str, str]] = {}
        self.current_stage: str = "idle"
        self.last_active: float = time.time()

        # Metadados do último turno maker-checker.
        # Permitem que turnos futuros acessem o histórico de validação
        # sem depender exclusivamente do histórico de mensagens.
        self.last_checker_verdict: str = "accept"
        self.last_checker_feedback: str = ""
        self.last_checker_corrections: List[Dict[str, Any]] = []
        self.last_maker_structured: Dict[str, Any] = {}
        self.last_iteration_count: int = 0


_SESSIONS: Dict[str, _OracleSession] = {}
_STREAM_QUEUES: Dict[str, "asyncio.Queue[Dict[str, Any]]"] = {}


def get_or_create_session(session_id: str) -> _OracleSession:
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = _OracleSession(session_id)
    session = _SESSIONS[session_id]
    session.last_active = time.time()
    return session


def register_stream_queue(session_id: str, q: "asyncio.Queue[Dict[str, Any]]") -> None:
    _STREAM_QUEUES[session_id] = q


def get_stream_queue(session_id: str) -> "Optional[asyncio.Queue[Dict[str, Any]]]":
    return _STREAM_QUEUES.get(session_id)


def unregister_stream_queue(session_id: str) -> None:
    _STREAM_QUEUES.pop(session_id, None)


def gc_inactive_sessions(max_age_hours: float = 2.0) -> int:
    cutoff = time.time() - max_age_hours * 3600
    stale = [sid for sid, s in list(_SESSIONS.items()) if s.last_active < cutoff]
    for sid in stale:
        _SESSIONS.pop(sid, None)
        _STREAM_QUEUES.pop(sid, None)
    if stale:
        logger.info("oracle_session.gc removed=%d sessions", len(stale))
    return len(stale)
