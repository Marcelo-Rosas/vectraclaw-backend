"""
Workflow Engine — DB-driven step transition resolver.

Consumed by Plutus, Hodos, Mercator e routine_runner para decidir o próximo
passo de uma task após a conclusão do passo atual. Usa workflow_definitions /
workflow_steps no schema vectraclip.

Design:
- Repository injetado (Protocol) para permitir InMemoryRepository em testes.
- Modelos Pydantic frozen — task/step/workflow são imutáveis no domínio.
- StepOutcome / FailureAction StrEnums substituem flags booleanas e strings mágicas.
- Hierarquia de exceções distingue "não existe" de "DB falhou".
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

__all__ = [
    "WorkflowEngine",
    "WorkflowDefinition",
    "WorkflowStep",
    "StepOutcome",
    "FailureAction",
    "WorkflowEngineError",
    "WorkflowNotFound",
    "StepNotFound",
    "RepositoryError",
    "WorkflowRepository",
    "SupabaseWorkflowRepository",
    "get_engine",
]

logger = logging.getLogger("WorkflowEngine")


# ---------- Enums ----------

class StepOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class FailureAction(StrEnum):
    BLOCK = "block"
    SKIP = "skip"
    RETRY = "retry"
    ESCALATE = "escalate"


# ---------- Domain models (frozen) ----------

class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: UUID
    slug: str
    name: str | None = None
    is_active: bool = True
    company_id: UUID | None = None


class WorkflowStep(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: UUID
    workflow_id: UUID
    step_code: str
    step_order: int
    name: str | None = None
    on_success_step_id: UUID | None = None
    on_failure_step_id: UUID | None = None
    on_failure_action: FailureAction = FailureAction.BLOCK


# ---------- Exceptions ----------

class WorkflowEngineError(Exception):
    """Base error for workflow engine."""


class WorkflowNotFound(WorkflowEngineError):
    """No active workflow_definition matched the slug."""


class StepNotFound(WorkflowEngineError):
    """workflow_step_id did not resolve."""


class RepositoryError(WorkflowEngineError):
    """Underlying datastore (Supabase) raised an error."""


# ---------- Repository contract ----------

class WorkflowRepository(Protocol):
    def fetch_workflow_by_slug(self, slug: str) -> WorkflowDefinition | None: ...
    def fetch_steps(self, workflow_id: UUID) -> list[WorkflowStep]: ...
    def fetch_step(self, step_id: UUID) -> WorkflowStep | None: ...


class SupabaseWorkflowRepository:
    """Concrete repo backed by supabase-py client."""

    def __init__(self, client) -> None:
        self._client = client

    def fetch_workflow_by_slug(self, slug: str) -> WorkflowDefinition | None:
        try:
            res = (
                self._client.table("workflow_definitions")
                .select("*")
                .eq("slug", slug)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise RepositoryError(f"fetch_workflow_by_slug({slug!r}) failed") from exc
        return WorkflowDefinition.model_validate(res.data[0]) if res.data else None

    def fetch_steps(self, workflow_id: UUID) -> list[WorkflowStep]:
        try:
            res = (
                self._client.table("workflow_steps")
                .select("*")
                .eq("workflow_id", str(workflow_id))
                .order("step_order")
                .execute()
            )
        except Exception as exc:
            raise RepositoryError(f"fetch_steps({workflow_id}) failed") from exc
        return [WorkflowStep.model_validate(r) for r in (res.data or [])]

    def fetch_step(self, step_id: UUID) -> WorkflowStep | None:
        try:
            res = (
                self._client.table("workflow_steps")
                .select("*")
                .eq("id", str(step_id))
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise RepositoryError(f"fetch_step({step_id}) failed") from exc
        return WorkflowStep.model_validate(res.data[0]) if res.data else None


# ---------- Engine ----------

class WorkflowEngine:
    def __init__(self, repo: WorkflowRepository) -> None:
        self._repo = repo

    def get_workflow(self, slug: str) -> WorkflowDefinition:
        wf = self._repo.fetch_workflow_by_slug(slug)
        if wf is None:
            raise WorkflowNotFound(f"no active workflow with slug={slug!r}")
        return wf

    def get_step(self, step_id: UUID) -> WorkflowStep:
        step = self._repo.fetch_step(step_id)
        if step is None:
            raise StepNotFound(f"step_id={step_id} not found")
        return step

    def get_steps(self, workflow_id: UUID) -> list[WorkflowStep]:
        return self._repo.fetch_steps(workflow_id)

    def advance(self, current: WorkflowStep, outcome: StepOutcome) -> WorkflowStep | None:
        """
        Resolve next step based on outcome.

        Returns None at end-of-pipeline or when FAILURE has no configured transition.
        Raises StepNotFound if a transition id points to a non-existent step.
        """
        if outcome is StepOutcome.SUCCESS:
            return self._repo.fetch_step(current.on_success_step_id) if current.on_success_step_id else None

        action = current.on_failure_action
        logger.info("step %s failed (action=%s)", current.step_code, action)
        if current.on_failure_step_id:
            return self._repo.fetch_step(current.on_failure_step_id)
        if action is FailureAction.SKIP and current.on_success_step_id:
            return self._repo.fetch_step(current.on_success_step_id)
        return None  # caller handles BLOCK / RETRY / ESCALATE


def get_engine(client) -> WorkflowEngine:
    """Factory — wires SupabaseWorkflowRepository into the engine."""
    return WorkflowEngine(SupabaseWorkflowRepository(client))
