"""
Session Bridge: persiste sessões CMA e turn logs no Supabase.

Tabelas esperadas:
  - managed_agent_sessions
  - managed_agent_turn_logs

Fallback em memória quando Supabase não está disponível (dev/testes).
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ManagedAgents.SessionBridge")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# Fallback em memória para dev/testes
_mem_sessions: Dict[str, Dict[str, Any]] = {}
_mem_turns: List[Dict[str, Any]] = []


class SessionBridge:
    def __init__(self, supabase_client=None) -> None:
        self._sb = supabase_client

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def create_session(
        self,
        task_id: str,
        agent_id: str,
        model: str,
        executor_rationale: str = "",
    ) -> str:
        session_id = str(uuid.uuid4())
        now = _now_iso()
        row = {
            "session_id": session_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "model": model,
            "status": "in_progress",
            "executor_type": "managed_agent",
            "created_at": now,
            "started_at": now,
            "completed_at": None,
            "final_output": None,
            "error_message": None,
            "tokens_input": 0,
            "tokens_output": 0,
            "metadata": {"executor_rationale": executor_rationale},
        }
        if self._sb:
            try:
                self._sb.table("managed_agent_sessions").insert(row).execute()
            except Exception as e:
                logger.warning(f"create_session Supabase error: {e} — using memory fallback")
                _mem_sessions[session_id] = row
        else:
            _mem_sessions[session_id] = row
        logger.info("SessionBridge create session_id=%s task_id=%s", session_id, task_id)
        return session_id

    def complete_session(
        self,
        session_id: str,
        final_output: str,
        tokens_input: int,
        tokens_output: int,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        now = _now_iso()
        status = "completed" if success else "failed"
        patch = {
            "status": status,
            "completed_at": now,
            "final_output": final_output,
            "error_message": error_message,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
        }
        if self._sb:
            try:
                self._sb.table("managed_agent_sessions").update(patch).eq("session_id", session_id).execute()
                return
            except Exception as e:
                logger.warning(f"complete_session Supabase error: {e}")
        if session_id in _mem_sessions:
            _mem_sessions[session_id].update(patch)

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        if self._sb:
            try:
                res = self._sb.table("managed_agent_sessions").select("*").eq("session_id", session_id).execute()
                if res.data:
                    return res.data[0]
            except Exception as e:
                logger.warning(f"load_session Supabase error: {e}")
        return _mem_sessions.get(session_id)

    # ------------------------------------------------------------------
    # Turns
    # ------------------------------------------------------------------

    def save_turn(
        self,
        session_id: str,
        turn_number: int,
        input_text: str,
        output_text: str,
        stop_reason: str,
        tool_used: Optional[str] = None,
        tool_input: Optional[Dict[str, Any]] = None,
    ) -> None:
        row = {
            "session_id": session_id,
            "turn_number": turn_number,
            "input_text": input_text,
            "output_text": output_text,
            "stop_reason": stop_reason,
            "tool_used": tool_used,
            "tool_input": tool_input,
            "created_at": _now_iso(),
        }
        if self._sb:
            try:
                self._sb.table("managed_agent_turn_logs").insert(row).execute()
                return
            except Exception as e:
                logger.warning(f"save_turn Supabase error: {e}")
        _mem_turns.append(row)

    def list_turns(self, session_id: str) -> List[Dict[str, Any]]:
        if self._sb:
            try:
                res = (
                    self._sb.table("managed_agent_turn_logs")
                    .select("*")
                    .eq("session_id", session_id)
                    .order("turn_number")
                    .execute()
                )
                return res.data or []
            except Exception as e:
                logger.warning(f"list_turns Supabase error: {e}")
        return [t for t in _mem_turns if t["session_id"] == session_id]
