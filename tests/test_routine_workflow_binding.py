"""Task #44 — Routine vinculada a workflow propaga workflow_step_id na task.

Antes: run_routine_now (api.py:3406) criava task sem workflow_step_id, mesmo
quando a routine pertencia a um workflow. Resultado: TaskFactory não tinha
ancora pra promover DAG, /flow-logic não mostrava execução, engine_v2 não
era invocado.

Agora: se routine.workflow_definition_id está preenchido, fetch first step
(step_order=1, active=true) e seta task.workflow_step_id.

Roda: pytest tests/test_routine_workflow_binding.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ════════════════════════════════════════════════════════════════════════════
# FakeSupabase — minimal só pra testar a lógica do propagador
# ════════════════════════════════════════════════════════════════════════════


class _FakeResult:
    def __init__(self, data: Any) -> None:
        self.data = data


class _FakeQuery:
    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = list(rows)

    def select(self, *args, **kwargs) -> "_FakeQuery":
        return self

    def eq(self, col: str, val: Any) -> "_FakeQuery":
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def order(self, col: str) -> "_FakeQuery":
        self._rows = sorted(self._rows, key=lambda r: r.get(col, 0))
        return self

    def limit(self, n: int) -> "_FakeQuery":
        self._rows = self._rows[:n]
        return self

    def execute(self) -> _FakeResult:
        return _FakeResult(self._rows)


class FakeSupabase:
    """Sim mínima — só workflow_steps."""

    def __init__(self, steps: List[Dict[str, Any]]) -> None:
        self.steps = steps

    def table(self, name: str):  # noqa: ANN201
        if name == "workflow_steps":
            return _FakeQuery(self.steps)
        raise AssertionError(f"unexpected table {name!r}")


# ════════════════════════════════════════════════════════════════════════════
# Helper que reproduz a lógica de propagação (extraída de api.py:3406+)
# ════════════════════════════════════════════════════════════════════════════


def _resolve_first_step_id(supabase, wf_def_id: Optional[str]) -> Optional[str]:
    """Reproduz a lógica do PR #44 — resolve first step de um workflow."""
    if not wf_def_id:
        return None
    try:
        step_res = (
            supabase.table("workflow_steps")
            .select("id")
            .eq("workflow_id", wf_def_id)
            .eq("active", True)
            .order("step_order")
            .limit(1)
            .execute()
        )
        return step_res.data[0]["id"] if step_res.data else None
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════════════
# Tests
# ════════════════════════════════════════════════════════════════════════════


class ResolveFirstStepTests(unittest.TestCase):
    def test_returns_none_when_no_workflow(self) -> None:
        fake = FakeSupabase([])
        self.assertIsNone(_resolve_first_step_id(fake, None))

    def test_returns_none_when_empty_string(self) -> None:
        fake = FakeSupabase([])
        self.assertIsNone(_resolve_first_step_id(fake, ""))

    def test_returns_first_step_by_order(self) -> None:
        fake = FakeSupabase([
            {"id": "step-3", "workflow_id": "wf-1", "step_order": 3, "active": True},
            {"id": "step-1", "workflow_id": "wf-1", "step_order": 1, "active": True},
            {"id": "step-2", "workflow_id": "wf-1", "step_order": 2, "active": True},
        ])
        result = _resolve_first_step_id(fake, "wf-1")
        self.assertEqual(result, "step-1")

    def test_ignores_inactive_steps(self) -> None:
        """Mesmo se step_order=1 está inativo, busca o primeiro ativo."""
        fake = FakeSupabase([
            {"id": "step-1-inactive", "workflow_id": "wf-1", "step_order": 1, "active": False},
            {"id": "step-2", "workflow_id": "wf-1", "step_order": 2, "active": True},
        ])
        result = _resolve_first_step_id(fake, "wf-1")
        self.assertEqual(result, "step-2")

    def test_returns_none_when_workflow_has_no_steps(self) -> None:
        fake = FakeSupabase([
            {"id": "step-other", "workflow_id": "outro-wf", "step_order": 1, "active": True},
        ])
        result = _resolve_first_step_id(fake, "wf-vazio")
        self.assertIsNone(result)


class TaskPayloadIntegrationTests(unittest.TestCase):
    """Reproduz o fluxo completo: routine + step lookup → task_payload."""

    def test_task_gets_workflow_step_id_when_routine_linked(self) -> None:
        # Setup: routine com workflow_definition_id apontando pro wf-kronos
        routine_row = {
            "id": "routine-1",
            "company_id": "vectra-cargo",
            "agent_id": "kronos-uuid",
            "operation_type": "planner-import-ofx",
            "workflow_definition_id": "wf-kronos",
            "name": "Lançamentos - Meu Planner",
        }
        fake = FakeSupabase([
            {"id": "step-import", "workflow_id": "wf-kronos", "step_order": 1, "active": True},
            {"id": "step-categorize", "workflow_id": "wf-kronos", "step_order": 2, "active": True},
        ])

        # Lógica do api.py:run_routine_now:
        task_payload: Dict[str, Any] = {
            "company_id": routine_row["company_id"],
            "assigned_to_agent_id": routine_row["agent_id"],
            "operation_type": routine_row["operation_type"],
            "status": "queued",
        }
        wf_def_id = routine_row.get("workflow_definition_id")
        first_step_id = _resolve_first_step_id(fake, wf_def_id)
        if first_step_id:
            task_payload["workflow_step_id"] = first_step_id

        # Assert: task vinculada
        self.assertEqual(task_payload["workflow_step_id"], "step-import")
        self.assertEqual(task_payload["operation_type"], "planner-import-ofx")

    def test_task_legacy_when_no_workflow_definition(self) -> None:
        """Backcompat: routine sem workflow_definition_id continua criando
        task standalone (sem workflow_step_id)."""
        routine_row = {
            "id": "routine-legacy",
            "company_id": "vectra-cargo",
            "agent_id": "kronos-uuid",
            "operation_type": "financial-audit",
            "workflow_definition_id": None,  # legacy
        }
        fake = FakeSupabase([])

        task_payload: Dict[str, Any] = {
            "company_id": routine_row["company_id"],
            "assigned_to_agent_id": routine_row["agent_id"],
            "operation_type": routine_row["operation_type"],
            "status": "queued",
        }
        wf_def_id = routine_row.get("workflow_definition_id")
        first_step_id = _resolve_first_step_id(fake, wf_def_id)
        if first_step_id:
            task_payload["workflow_step_id"] = first_step_id

        # Assert: task standalone (sem workflow_step_id)
        self.assertNotIn("workflow_step_id", task_payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
