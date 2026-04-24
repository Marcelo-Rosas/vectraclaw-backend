"""Ponte de sessão para persistência em Supabase."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Any, TYPE_CHECKING
from dataclasses import dataclass, field, asdict

if TYPE_CHECKING:
    from src.models import Task

logger = logging.getLogger("SessionBridge")


@dataclass(frozen=True)
class ManagedAgentSession:
    """Representação de uma sessão de Managed Agent."""
    session_id: str
    task_id: str
    agent_id: str
    model: str
    status: str  # "in_progress", "completed", "failed", "paused"
    executor_type: str = "managed_agent"
    messages: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    tools_used: tuple[str, ...] = field(default_factory=tuple)
    turn_logs: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    final_output: Optional[str] = None
    error_message: Optional[str] = None
    tokens_input: int = 0
    tokens_output: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Converte para dicionário para persistência."""
        data = asdict(self)
        # Serializar timestamps
        data["created_at"] = self.created_at.isoformat()
        if self.started_at:
            data["started_at"] = self.started_at.isoformat()
        if self.completed_at:
            data["completed_at"] = self.completed_at.isoformat()
        return data


class SessionBridge:
    """Gerencia sessões de Managed Agents no Supabase."""

    def __init__(self, supabase_client: Optional[Any] = None):
        """
        Inicializa o SessionBridge.

        Args:
            supabase_client: Cliente Supabase (se None, tenta importar do contexto global)
        """
        self.supabase = supabase_client
        self._in_memory_sessions: dict[str, ManagedAgentSession] = {}

    def _get_supabase_client(self):
        """Obtém cliente Supabase (fallback para in-memory se não disponível)."""
        if self.supabase is None:
            try:
                # Tentar importar cliente global (será inicializado em api.py)
                from src.api import supabase_client
                self.supabase = supabase_client
            except (ImportError, AttributeError):
                logger.warning("Supabase client não disponível, usando in-memory storage")
                return None
        return self.supabase

    def create_session(
        self,
        task_id: str,
        agent_id: str,
        model: str = "claude-3-5-sonnet-20241022",
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Cria nova sessão de Managed Agent.

        Args:
            task_id: ID da tarefa
            agent_id: ID do agent
            model: Modelo Claude a usar
            metadata: Metadados adicionais

        Returns:
            ID da sessão criada
        """
        session_id = f"mas_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        session = ManagedAgentSession(
            session_id=session_id,
            task_id=task_id,
            agent_id=agent_id,
            model=model,
            status="in_progress",
            started_at=now,
            metadata=metadata or {},
        )

        # Armazenar em memória
        self._in_memory_sessions[session_id] = session

        # Tentar persistir em Supabase
        try:
            supabase = self._get_supabase_client()
            if supabase:
                supabase.table("managed_agent_sessions").insert({
                    "session_id": session_id,
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "model": model,
                    "status": "in_progress",
                    "executor_type": "managed_agent",
                    "created_at": now.isoformat(),
                    "started_at": now.isoformat(),
                    "tokens_input": 0,
                    "tokens_output": 0,
                    "metadata": json.dumps(metadata or {}),
                }).execute()
                logger.info(f"Sessão criada no Supabase: {session_id}")
        except Exception as e:
            logger.warning(f"Falha ao persistir sessão no Supabase: {e}. Continuando com in-memory.")

        return session_id

    def save_turn(
        self,
        session_id: str,
        turn_number: int,
        input_text: str,
        tool_used: Optional[str],
        tool_input: Optional[dict[str, Any]],
        output_text: str,
        stop_reason: str,
    ) -> None:
        """
        Salva resultado de um turno de execução.

        Args:
            session_id: ID da sessão
            turn_number: Número do turno
            input_text: Texto de entrada
            tool_used: Ferramenta usada (ou None)
            tool_input: Input da ferramenta
            output_text: Texto de saída
            stop_reason: Razão da parada (end_turn, tool_use, etc)
        """
        turn_log = {
            "session_id": session_id,
            "turn_number": turn_number,
            "input_text": input_text,
            "tool_used": tool_used,
            "tool_input": json.dumps(tool_input) if tool_input else None,
            "output_text": output_text,
            "stop_reason": stop_reason,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Atualizar sessão em memória
        if session_id in self._in_memory_sessions:
            session = self._in_memory_sessions[session_id]
            new_turn_logs = tuple(list(session.turn_logs) + [turn_log])
            if tool_used:
                new_tools = tuple(set(list(session.tools_used) + [tool_used]))
            else:
                new_tools = session.tools_used

            # Criar nova sessão (frozen dataclass)
            updated_session = ManagedAgentSession(
                session_id=session.session_id,
                task_id=session.task_id,
                agent_id=session.agent_id,
                model=session.model,
                status=session.status,
                executor_type=session.executor_type,
                messages=session.messages,
                tools_used=new_tools,
                turn_logs=new_turn_logs,
                final_output=session.final_output,
                error_message=session.error_message,
                tokens_input=session.tokens_input,
                tokens_output=session.tokens_output,
                created_at=session.created_at,
                started_at=session.started_at,
                completed_at=session.completed_at,
                metadata=session.metadata,
            )
            self._in_memory_sessions[session_id] = updated_session

        # Tentar persistir em Supabase
        try:
            supabase = self._get_supabase_client()
            if supabase:
                supabase.table("managed_agent_turn_logs").insert(turn_log).execute()
                logger.info(f"Turn {turn_number} persistido para sessão {session_id}")
        except Exception as e:
            logger.warning(f"Falha ao salvar turn no Supabase: {e}")

    def complete_session(
        self,
        session_id: str,
        final_output: str,
        tokens_input: int = 0,
        tokens_output: int = 0,
    ) -> None:
        """
        Marca sessão como completada.

        Args:
            session_id: ID da sessão
            final_output: Saída final
            tokens_input: Total de tokens de entrada
            tokens_output: Total de tokens de saída
        """
        now = datetime.now(timezone.utc)

        # Atualizar em memória
        if session_id in self._in_memory_sessions:
            session = self._in_memory_sessions[session_id]
            updated_session = ManagedAgentSession(
                session_id=session.session_id,
                task_id=session.task_id,
                agent_id=session.agent_id,
                model=session.model,
                status="completed",
                executor_type=session.executor_type,
                messages=session.messages,
                tools_used=session.tools_used,
                turn_logs=session.turn_logs,
                final_output=final_output,
                error_message=session.error_message,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                created_at=session.created_at,
                started_at=session.started_at,
                completed_at=now,
                metadata=session.metadata,
            )
            self._in_memory_sessions[session_id] = updated_session

        # Tentar persistir em Supabase
        try:
            supabase = self._get_supabase_client()
            if supabase:
                supabase.table("managed_agent_sessions").update({
                    "status": "completed",
                    "final_output": final_output,
                    "completed_at": now.isoformat(),
                    "tokens_input": tokens_input,
                    "tokens_output": tokens_output,
                }).eq("session_id", session_id).execute()
                logger.info(f"Sessão completada: {session_id}")
        except Exception as e:
            logger.warning(f"Falha ao completar sessão no Supabase: {e}")

    def fail_session(
        self,
        session_id: str,
        error_message: str,
    ) -> None:
        """
        Marca sessão como falhada.

        Args:
            session_id: ID da sessão
            error_message: Mensagem de erro
        """
        now = datetime.now(timezone.utc)

        # Atualizar em memória
        if session_id in self._in_memory_sessions:
            session = self._in_memory_sessions[session_id]
            updated_session = ManagedAgentSession(
                session_id=session.session_id,
                task_id=session.task_id,
                agent_id=session.agent_id,
                model=session.model,
                status="failed",
                executor_type=session.executor_type,
                messages=session.messages,
                tools_used=session.tools_used,
                turn_logs=session.turn_logs,
                final_output=session.final_output,
                error_message=error_message,
                tokens_input=session.tokens_input,
                tokens_output=session.tokens_output,
                created_at=session.created_at,
                started_at=session.started_at,
                completed_at=now,
                metadata=session.metadata,
            )
            self._in_memory_sessions[session_id] = updated_session

        # Tentar persistir em Supabase
        try:
            supabase = self._get_supabase_client()
            if supabase:
                supabase.table("managed_agent_sessions").update({
                    "status": "failed",
                    "error_message": error_message,
                    "completed_at": now.isoformat(),
                }).eq("session_id", session_id).execute()
                logger.info(f"Sessão marcada como falhada: {session_id}")
        except Exception as e:
            logger.warning(f"Falha ao marcar sessão como falha no Supabase: {e}")

    def load_session(self, session_id: str) -> Optional[ManagedAgentSession]:
        """
        Carrega uma sessão pelo ID.

        Args:
            session_id: ID da sessão

        Returns:
            ManagedAgentSession ou None se não encontrada
        """
        # Verificar memória primeiro
        if session_id in self._in_memory_sessions:
            return self._in_memory_sessions[session_id]

        # Tentar Supabase
        try:
            supabase = self._get_supabase_client()
            if supabase:
                response = supabase.table("managed_agent_sessions").select(
                    "*"
                ).eq("session_id", session_id).execute()

                if response.data:
                    session_data = response.data[0]
                    # Carregar turn logs
                    turns_response = supabase.table("managed_agent_turn_logs").select(
                        "*"
                    ).eq("session_id", session_id).order("turn_number").execute()

                    turn_logs = tuple(turns_response.data) if turns_response.data else ()

                    session = ManagedAgentSession(
                        session_id=session_data["session_id"],
                        task_id=session_data["task_id"],
                        agent_id=session_data["agent_id"],
                        model=session_data["model"],
                        status=session_data["status"],
                        executor_type=session_data.get("executor_type", "managed_agent"),
                        messages=tuple(),  # Reconstruir do turn_logs se necessário
                        tools_used=tuple(session_data.get("tools_used", [])),
                        turn_logs=turn_logs,
                        final_output=session_data.get("final_output"),
                        error_message=session_data.get("error_message"),
                        tokens_input=session_data.get("tokens_input", 0),
                        tokens_output=session_data.get("tokens_output", 0),
                    )
                    self._in_memory_sessions[session_id] = session
                    return session
        except Exception as e:
            logger.warning(f"Falha ao carregar sessão do Supabase: {e}")

        return None

    def list_sessions_by_task(self, task_id: str) -> list[ManagedAgentSession]:
        """
        Lista todas as sessões de uma tarefa.

        Args:
            task_id: ID da tarefa

        Returns:
            Lista de sessões
        """
        try:
            supabase = self._get_supabase_client()
            if supabase:
                response = supabase.table("managed_agent_sessions").select(
                    "*"
                ).eq("task_id", task_id).execute()

                sessions = []
                for session_data in response.data or []:
                    session = ManagedAgentSession(
                        session_id=session_data["session_id"],
                        task_id=session_data["task_id"],
                        agent_id=session_data["agent_id"],
                        model=session_data["model"],
                        status=session_data["status"],
                        final_output=session_data.get("final_output"),
                    )
                    sessions.append(session)
                return sessions
        except Exception as e:
            logger.warning(f"Falha ao listar sessões: {e}")

        return []
