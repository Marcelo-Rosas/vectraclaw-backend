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

    # Engine v2 (Task #42 PoC split-if) — interpretadores dos logic_patterns
    # consomem estes campos. Mantidos opcionais para não quebrar steps SIMPLE
    # do engine v1.
    logic_pattern: str | None = None              # 'simple' | 'split-if' | ...
    decisions: list[dict] | None = None           # jsonb — só relevante p/ SPLIT/SWITCH


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
    def fetch_tasks_for_step(self, step_id: UUID) -> list[dict]: ...


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

    def fetch_tasks_for_step(self, step_id: UUID) -> list[dict]:
        """Busca tasks associadas a um step (via workflow_step_id).

        Retorna lista vazia se schema não conectar ou erro.
        """
        try:
            res = (
                self._client.table("tasks")
                .select("id, status, output_json")
                .eq("workflow_step_id", str(step_id))
                .execute()
            )
            return list(res.data or [])
        except Exception as exc:
            logger.warning("fetch_tasks_for_step(%s) failed: %s", step_id, exc)
            return []


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


# ════════════════════════════════════════════════════════════════════════════
# Engine v2 — PoC do interpretador split-if (Task #42)
#
# Permite que workflow_steps com logic_pattern='split-if' resolvam
# dinamicamente o próximo step baseado em uma condição contra o output_json
# da task atual (task_context).
#
# Estrutura esperada de `decisions[0]`:
#
#     {
#       "condition": {"field": "score", "op": "gt", "value": 80},
#       "true_step_id":  "uuid-do-step-aprovado",
#       "false_step_id": "uuid-do-step-reprovado"
#     }
#
# `field` aceita dot notation: "score" ou "metadata.priority" ou
# "categorization.lines_categorized".
#
# Ops suportados: eq, neq, gt, lt, gte, lte, in, not_in, exists.
#
# Demais patterns (SPLIT-SWITCH, MERGE, LOOP-BATCH, WAIT-EVENT, SUBFLOW,
# ERROR-HANDLER) retornam NotImplementedError("pending") — task #42 escalará
# para os demais após este PoC validar a abordagem.
# ════════════════════════════════════════════════════════════════════════════


class ConditionEvaluationError(WorkflowEngineError):
    """Decision condition mal-formada ou field inacessível."""


def _resolve_field(context: dict, path: str) -> object:
    """Lê `context[a][b][c]` a partir de path com dot notation 'a.b.c'.

    Retorna o sentinela `_MISSING` se algum nível não existe — caller decide
    se isso é erro ou fallback.
    """
    parts = path.split(".") if path else []
    cur: object = context
    for p in parts:
        if not isinstance(cur, dict):
            return _MISSING
        if p not in cur:
            return _MISSING
        cur = cur[p]
    return cur


_MISSING = object()


def _evaluate_condition(condition: dict, context: dict) -> bool:
    """Avalia uma condição contra um dict de contexto.

    Suporta ops: eq, neq, gt, lt, gte, lte, in, not_in, exists.
    Levanta ConditionEvaluationError se field ausente em ops que precisam
    de valor (exceto `exists`/`not_in` que toleram).
    """
    if not isinstance(condition, dict):
        raise ConditionEvaluationError(f"condition must be dict, got {type(condition).__name__}")

    field = condition.get("field")
    op = condition.get("op")
    expected = condition.get("value")

    if not field or not op:
        raise ConditionEvaluationError(f"condition missing field/op: {condition!r}")

    actual = _resolve_field(context, field)

    if op == "exists":
        return actual is not _MISSING
    if op == "not_exists":
        return actual is _MISSING

    if actual is _MISSING:
        raise ConditionEvaluationError(f"field {field!r} not found in context")

    if op == "eq":
        return actual == expected
    if op == "neq":
        return actual != expected
    if op == "gt":
        return _safe_compare(actual, expected, lambda a, b: a > b)
    if op == "lt":
        return _safe_compare(actual, expected, lambda a, b: a < b)
    if op == "gte":
        return _safe_compare(actual, expected, lambda a, b: a >= b)
    if op == "lte":
        return _safe_compare(actual, expected, lambda a, b: a <= b)
    if op == "in":
        if not isinstance(expected, (list, tuple, set)):
            raise ConditionEvaluationError(f"op=in requires list value, got {type(expected).__name__}")
        return actual in expected
    if op == "not_in":
        if not isinstance(expected, (list, tuple, set)):
            raise ConditionEvaluationError(f"op=not_in requires list value, got {type(expected).__name__}")
        return actual not in expected

    raise ConditionEvaluationError(f"unsupported op: {op!r}")


def _safe_compare(a: object, b: object, fn) -> bool:
    """Aplica fn(a, b) coercendo numérico quando possível."""
    try:
        return fn(a, b)
    except TypeError:
        # tenta coerção numérica
        try:
            return fn(float(a), float(b))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ConditionEvaluationError(f"cannot compare {a!r} {fn.__name__} {b!r}")


def advance_v2(
    engine: WorkflowEngine,
    current: WorkflowStep,
    outcome: StepOutcome,
    task_context: dict | None = None,
) -> WorkflowStep | None:
    """Engine v2 PoC: interpreta logic_pattern do step para resolver próximo.

    - SIMPLE (ou None): delega para `engine.advance(current, outcome)`.
    - split-if: avalia `current.decisions[0].condition` contra `task_context`,
      retorna step apontado por `true_step_id` ou `false_step_id`.
    - Outros patterns: NotImplementedError("pending") — task #42 escalará.

    `task_context` é o `output_json` da task que executou o step atual
    (ou input_json em casos especiais). Vem do daemon após `_complete_task`.
    """
    pattern = current.logic_pattern

    # Failure: sempre usa fluxo legado (handler de exceção ou block)
    if outcome is StepOutcome.FAILURE:
        return engine.advance(current, outcome)

    # simple ou ausente: comportamento engine v1
    if pattern in (None, "simple"):
        return engine.advance(current, outcome)

    if pattern == "split-if":
        decisions = current.decisions or []
        if not decisions:
            raise ConditionEvaluationError(
                f"step {current.step_code} é split-if mas decisions[] vazio"
            )
        decision = decisions[0]
        condition = decision.get("condition")
        if not condition:
            raise ConditionEvaluationError(
                f"step {current.step_code} split-if sem condition em decisions[0]"
            )
        outcome_bool = _evaluate_condition(condition, task_context or {})

        target_id_str = decision.get("true_step_id" if outcome_bool else "false_step_id")
        if not target_id_str:
            logger.info(
                "step %s split-if outcome=%s sem target — workflow termina",
                current.step_code, outcome_bool,
            )
            return None

        return engine.get_step(UUID(target_id_str))

    # P1-BE-5 — split-parallel stub (fork não tem step único)
    if pattern == "split-parallel":
        logger.info(
            "step %s split-parallel: fork sem step único — "
            "TaskFactory/daemon deve usar proximo_step_codes para gerar múltiplas tasks",
            current.step_code,
        )
        return None

    # P1-BE-6 — merge-by-key handler (join)
    if pattern == "merge-by-key":
        steps = engine.get_steps(current.workflow_id)
        predecessors = [s for s in steps if s.on_success_step_id == current.id]
        if not predecessors:
            # Sem predecessors conhecidos — trata como linear
            return engine.advance(current, outcome)

        all_done = True
        for pred in predecessors:
            tasks = engine._repo.fetch_tasks_for_step(pred.id)
            if not tasks:
                all_done = False
                break
            if not any(t.get("status") == "done" for t in tasks):
                all_done = False
                break

        if all_done:
            return engine.advance(current, outcome)

        logger.info(
            "step %s merge-by-key: aguardando predecessors %s",
            current.step_code,
            [p.step_code for p in predecessors],
        )
        return None

    # Patterns ainda não implementados (task #42 escala depois)
    raise NotImplementedError(
        f"logic_pattern={pattern!r} ainda não tem handler (engine_handler='pending'). "
        f"Veja task #42 e workflow_logic_patterns."
    )
