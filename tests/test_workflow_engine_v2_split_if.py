"""Task #42 — PoC Engine v2 com SPLIT-IF.

Valida que `advance_v2` interpreta logic_pattern='SPLIT-IF' resolvendo
dinamicamente o próximo step baseado em condição contra task_context.

Roda: pytest tests/test_workflow_engine_v2_split_if.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.services.workflow_engine import (  # noqa: E402
    ConditionEvaluationError,
    FailureAction,
    StepOutcome,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowRepository,
    WorkflowStep,
    _evaluate_condition,
    _resolve_field,
    advance_v2,
)


# ════════════════════════════════════════════════════════════════════════════
# Stub repo — controla diretamente o set de steps em memória
# ════════════════════════════════════════════════════════════════════════════


class _StubRepo:
    def __init__(self, steps: dict[UUID, WorkflowStep]) -> None:
        self._steps = steps

    def fetch_workflow_by_slug(self, slug: str) -> Optional[WorkflowDefinition]:
        return None  # não usado nos testes

    def fetch_steps(self, workflow_id: UUID) -> list[WorkflowStep]:
        return [s for s in self._steps.values() if s.workflow_id == workflow_id]

    def fetch_step(self, step_id: UUID) -> Optional[WorkflowStep]:
        return self._steps.get(step_id)


def _make_step(
    *,
    step_id: Optional[UUID] = None,
    code: str = "S",
    order: int = 1,
    on_success: Optional[UUID] = None,
    on_failure: Optional[UUID] = None,
    logic_pattern: Optional[str] = None,
    decisions: Optional[list[dict]] = None,
) -> WorkflowStep:
    return WorkflowStep(
        id=step_id or uuid4(),
        workflow_id=uuid4(),
        step_code=code,
        step_order=order,
        name=f"Step {code}",
        on_success_step_id=on_success,
        on_failure_step_id=on_failure,
        on_failure_action=FailureAction.BLOCK,
        logic_pattern=logic_pattern,
        decisions=decisions,
    )


# ════════════════════════════════════════════════════════════════════════════
# _resolve_field — dot notation
# ════════════════════════════════════════════════════════════════════════════


class ResolveFieldTests(unittest.TestCase):
    def test_simple_field(self) -> None:
        ctx = {"score": 85}
        self.assertEqual(_resolve_field(ctx, "score"), 85)

    def test_nested_field(self) -> None:
        ctx = {"categorization": {"lines_categorized": 42}}
        self.assertEqual(_resolve_field(ctx, "categorization.lines_categorized"), 42)

    def test_deep_nested(self) -> None:
        ctx = {"a": {"b": {"c": {"d": "leaf"}}}}
        self.assertEqual(_resolve_field(ctx, "a.b.c.d"), "leaf")

    def test_missing_field_returns_sentinel(self) -> None:
        from src.services.workflow_engine import _MISSING

        self.assertIs(_resolve_field({}, "x"), _MISSING)
        self.assertIs(_resolve_field({"x": 1}, "x.y"), _MISSING)


# ════════════════════════════════════════════════════════════════════════════
# _evaluate_condition — ops básicos
# ════════════════════════════════════════════════════════════════════════════


class EvaluateConditionTests(unittest.TestCase):
    def test_eq_match(self) -> None:
        self.assertTrue(_evaluate_condition(
            {"field": "status", "op": "eq", "value": "ok"},
            {"status": "ok"}
        ))

    def test_eq_no_match(self) -> None:
        self.assertFalse(_evaluate_condition(
            {"field": "status", "op": "eq", "value": "ok"},
            {"status": "error"}
        ))

    def test_neq(self) -> None:
        cond = {"field": "status", "op": "neq", "value": "ok"}
        self.assertFalse(_evaluate_condition(cond, {"status": "ok"}))
        self.assertTrue(_evaluate_condition(cond, {"status": "error"}))

    def test_gt(self) -> None:
        cond = {"field": "score", "op": "gt", "value": 80}
        self.assertTrue(_evaluate_condition(cond, {"score": 85}))
        self.assertFalse(_evaluate_condition(cond, {"score": 70}))
        self.assertFalse(_evaluate_condition(cond, {"score": 80}))  # gt strict

    def test_gte(self) -> None:
        cond = {"field": "score", "op": "gte", "value": 80}
        self.assertTrue(_evaluate_condition(cond, {"score": 80}))
        self.assertTrue(_evaluate_condition(cond, {"score": 81}))
        self.assertFalse(_evaluate_condition(cond, {"score": 79}))

    def test_lt_lte(self) -> None:
        cond_lt = {"field": "x", "op": "lt", "value": 10}
        self.assertTrue(_evaluate_condition(cond_lt, {"x": 5}))
        self.assertFalse(_evaluate_condition(cond_lt, {"x": 10}))

        cond_lte = {"field": "x", "op": "lte", "value": 10}
        self.assertTrue(_evaluate_condition(cond_lte, {"x": 10}))

    def test_in(self) -> None:
        cond = {"field": "tipo", "op": "in", "value": ["a", "b", "c"]}
        self.assertTrue(_evaluate_condition(cond, {"tipo": "a"}))
        self.assertFalse(_evaluate_condition(cond, {"tipo": "z"}))

    def test_not_in(self) -> None:
        cond = {"field": "tipo", "op": "not_in", "value": ["bad"]}
        self.assertTrue(_evaluate_condition(cond, {"tipo": "good"}))
        self.assertFalse(_evaluate_condition(cond, {"tipo": "bad"}))

    def test_exists(self) -> None:
        cond = {"field": "x", "op": "exists"}
        self.assertTrue(_evaluate_condition(cond, {"x": None}))   # presente, mesmo se None
        self.assertTrue(_evaluate_condition(cond, {"x": 1}))
        self.assertFalse(_evaluate_condition(cond, {}))

    def test_nested_field_with_op(self) -> None:
        cond = {"field": "categorization.lines_categorized", "op": "gt", "value": 0}
        self.assertTrue(_evaluate_condition(cond, {"categorization": {"lines_categorized": 5}}))
        self.assertFalse(_evaluate_condition(cond, {"categorization": {"lines_categorized": 0}}))

    def test_numeric_coercion(self) -> None:
        """gt entre string e int via coerção."""
        cond = {"field": "x", "op": "gt", "value": 5}
        self.assertTrue(_evaluate_condition(cond, {"x": "10"}))

    def test_missing_field_errors(self) -> None:
        cond = {"field": "x", "op": "eq", "value": 1}
        with self.assertRaises(ConditionEvaluationError):
            _evaluate_condition(cond, {})

    def test_missing_field_ok_for_exists(self) -> None:
        cond = {"field": "x", "op": "exists"}
        self.assertFalse(_evaluate_condition(cond, {}))

    def test_unsupported_op_raises(self) -> None:
        with self.assertRaises(ConditionEvaluationError):
            _evaluate_condition({"field": "x", "op": "fancy", "value": 1}, {"x": 1})


# ════════════════════════════════════════════════════════════════════════════
# advance_v2 — SIMPLE delega para advance() legado
# ════════════════════════════════════════════════════════════════════════════


class AdvanceV2SimpleDelegationTests(unittest.TestCase):
    def test_simple_pattern_uses_v1(self) -> None:
        next_id = uuid4()
        next_step = _make_step(step_id=next_id, code="Next")
        current = _make_step(
            code="Curr", on_success=next_id, logic_pattern="SIMPLE",
        )
        repo = _StubRepo({next_id: next_step, current.id: current})
        engine = WorkflowEngine(repo)

        result = advance_v2(engine, current, StepOutcome.SUCCESS)
        self.assertEqual(result, next_step)

    def test_null_pattern_uses_v1(self) -> None:
        next_id = uuid4()
        next_step = _make_step(step_id=next_id, code="Next")
        current = _make_step(
            code="Curr", on_success=next_id, logic_pattern=None,
        )
        repo = _StubRepo({next_id: next_step, current.id: current})
        engine = WorkflowEngine(repo)

        result = advance_v2(engine, current, StepOutcome.SUCCESS)
        self.assertEqual(result, next_step)

    def test_failure_always_uses_v1(self) -> None:
        """Mesmo com SPLIT-IF, FAILURE deve cair pro fluxo legado."""
        fail_id = uuid4()
        fail_step = _make_step(step_id=fail_id, code="Err")
        current = _make_step(
            code="SplitCurr",
            on_failure=fail_id,
            logic_pattern="SPLIT-IF",
            decisions=[
                {"condition": {"field": "x", "op": "eq", "value": 1},
                 "true_step_id": str(uuid4()), "false_step_id": str(uuid4())}
            ],
        )
        repo = _StubRepo({fail_id: fail_step, current.id: current})
        engine = WorkflowEngine(repo)

        result = advance_v2(engine, current, StepOutcome.FAILURE)
        self.assertEqual(result, fail_step)


# ════════════════════════════════════════════════════════════════════════════
# advance_v2 — SPLIT-IF resolução condicional
# ════════════════════════════════════════════════════════════════════════════


class AdvanceV2SplitIfTests(unittest.TestCase):
    def _setup_split(self, condition_value: int) -> tuple[WorkflowEngine, WorkflowStep, WorkflowStep, WorkflowStep]:
        """Workflow: Current(SPLIT-IF) → Aprovado (if score>80) | Reprovado (else)."""
        aprovado_id = uuid4()
        reprovado_id = uuid4()
        aprovado = _make_step(step_id=aprovado_id, code="Aprovado")
        reprovado = _make_step(step_id=reprovado_id, code="Reprovado")
        current = _make_step(
            code="EscoreCheck",
            logic_pattern="SPLIT-IF",
            decisions=[{
                "condition": {"field": "score", "op": "gt", "value": condition_value},
                "true_step_id": str(aprovado_id),
                "false_step_id": str(reprovado_id),
            }],
        )
        repo = _StubRepo({
            aprovado_id: aprovado,
            reprovado_id: reprovado,
            current.id: current,
        })
        return WorkflowEngine(repo), current, aprovado, reprovado

    def test_condition_true_goes_to_true_branch(self) -> None:
        engine, current, aprovado, _ = self._setup_split(condition_value=80)

        result = advance_v2(engine, current, StepOutcome.SUCCESS, {"score": 85})
        self.assertEqual(result, aprovado)

    def test_condition_false_goes_to_false_branch(self) -> None:
        engine, current, _, reprovado = self._setup_split(condition_value=80)

        result = advance_v2(engine, current, StepOutcome.SUCCESS, {"score": 70})
        self.assertEqual(result, reprovado)

    def test_split_if_without_target_returns_none(self) -> None:
        """Se decision não tem target pro outcome, workflow termina."""
        current = _make_step(
            code="EndingSplit",
            logic_pattern="SPLIT-IF",
            decisions=[{
                "condition": {"field": "x", "op": "eq", "value": True},
                "true_step_id": None,
                "false_step_id": None,
            }],
        )
        repo = _StubRepo({current.id: current})
        engine = WorkflowEngine(repo)

        result = advance_v2(engine, current, StepOutcome.SUCCESS, {"x": True})
        self.assertIsNone(result)

    def test_split_if_empty_decisions_raises(self) -> None:
        current = _make_step(code="Bad", logic_pattern="SPLIT-IF", decisions=[])
        repo = _StubRepo({current.id: current})
        engine = WorkflowEngine(repo)

        with self.assertRaises(ConditionEvaluationError):
            advance_v2(engine, current, StepOutcome.SUCCESS, {"score": 50})

    def test_split_if_missing_condition_raises(self) -> None:
        current = _make_step(
            code="Bad", logic_pattern="SPLIT-IF",
            decisions=[{"true_step_id": str(uuid4())}],  # sem 'condition'
        )
        repo = _StubRepo({current.id: current})
        engine = WorkflowEngine(repo)

        with self.assertRaises(ConditionEvaluationError):
            advance_v2(engine, current, StepOutcome.SUCCESS, {})


# ════════════════════════════════════════════════════════════════════════════
# advance_v2 — patterns ainda não implementados
# ════════════════════════════════════════════════════════════════════════════


class AdvanceV2PendingPatternsTests(unittest.TestCase):
    PENDING_PATTERNS = [
        "SPLIT-SWITCH",
        "MERGE",
        "LOOP-BATCH",
        "WAIT-EVENT",
        "SUBFLOW",
        "ERROR-HANDLER",
    ]

    def test_pending_patterns_raise_notimplemented(self) -> None:
        for pattern in self.PENDING_PATTERNS:
            with self.subTest(pattern=pattern):
                current = _make_step(code="X", logic_pattern=pattern)
                repo = _StubRepo({current.id: current})
                engine = WorkflowEngine(repo)
                with self.assertRaises(NotImplementedError) as ctx:
                    advance_v2(engine, current, StepOutcome.SUCCESS, {})
                self.assertIn("pending", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
