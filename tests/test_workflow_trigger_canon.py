"""PR-T1+T2 — Workflow trigger canon: Pydantic + _sync_routine_for_workflow.

Roda: pytest tests/test_workflow_trigger_canon.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.api_routes.workflows import (  # noqa: E402
    _ROUTINE_OP_TYPE_WHITELIST,
    _sync_routine_for_workflow,
)
from src.models import WorkflowTriggerType  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Fake supabase mínimo para isolar _sync_routine_for_workflow do banco real
# ─────────────────────────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, data: Any) -> None:
        self.data = data


class _FakeQuery:
    def __init__(self, root: "FakeSupabase", table: str) -> None:
        self.root = root
        self.table_name = table
        self._op: Optional[str] = None
        self._patch: Optional[Dict[str, Any]] = None
        self._insert_row: Optional[Dict[str, Any]] = None
        self._preds: List[Any] = []

    def select(self, _cols: str = "*") -> "_FakeQuery":
        self._op = "select"
        return self

    def update(self, patch: Dict[str, Any]) -> "_FakeQuery":
        self._op = "update"
        self._patch = dict(patch)
        return self

    def insert(self, row: Dict[str, Any]) -> "_FakeQuery":
        self._op = "insert"
        self._insert_row = dict(row)
        return self

    def eq(self, col: str, val: Any) -> "_FakeQuery":
        self._preds.append(("eq", col, val))
        return self

    def limit(self, _n: int) -> "_FakeQuery":
        return self

    def execute(self) -> _FakeResult:
        rows = self.root.tables.get(self.table_name, [])

        if self._op == "select":
            matched = [
                r for r in rows
                if all(r.get(c) == v for op, c, v in self._preds if op == "eq")
            ]
            return _FakeResult(matched)

        if self._op == "insert":
            assert self._insert_row is not None
            inserted = dict(self._insert_row)
            inserted.setdefault("id", f"{self.table_name}-fake-{len(rows) + 1}")
            self.root.tables.setdefault(self.table_name, []).append(inserted)
            self.root.history.append(("insert", self.table_name, inserted))
            return _FakeResult([inserted])

        if self._op == "update":
            assert self._patch is not None
            matched = []
            for r in rows:
                if all(r.get(c) == v for op, c, v in self._preds if op == "eq"):
                    r.update(self._patch)
                    matched.append(r)
            self.root.history.append(("update", self.table_name, dict(self._patch)))
            return _FakeResult(matched)

        return _FakeResult([])


class FakeSupabase:
    def __init__(self, seed: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> None:
        self.tables: Dict[str, List[Dict[str, Any]]] = dict(seed or {})
        self.history: List[Any] = []

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self, name)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Pydantic WorkflowTriggerType
# ─────────────────────────────────────────────────────────────────────────────


class WorkflowTriggerTypeModelTests(unittest.TestCase):
    def test_to_zod_dict_camelcase(self) -> None:
        m = WorkflowTriggerType(
            slug="cron", name="Agendado", description="x",
            icon="clock", display_order=200,
        )
        z = m.to_zod_dict()
        self.assertEqual(z["slug"], "cron")
        self.assertIn("displayOrder", z)
        self.assertEqual(z["displayOrder"], 200)

    def test_icon_defaults_to_empty_string(self) -> None:
        m = WorkflowTriggerType(slug="event", name="Evento", description="x")
        z = m.to_zod_dict()
        self.assertEqual(z["icon"], "")
        self.assertTrue(z["isActive"])


# ─────────────────────────────────────────────────────────────────────────────
# 2. _sync_routine_for_workflow
# ─────────────────────────────────────────────────────────────────────────────


class SyncRoutineForWorkflowTests(unittest.TestCase):
    WF_ID = "wf-kronos"
    COMPANY_ID = "vectra-cargo"
    WF_NAME = "Kronos Planner Flow"

    def _step(self, op_type: str = "planner-import-ofx", spec: Optional[str] = "planner-import-ofx"):
        return {"default_operation_type": op_type, "specialty_slug": spec}

    def test_cron_active_inserts_new_routine(self) -> None:
        sb = FakeSupabase(seed={"routines": []})
        _sync_routine_for_workflow(
            sb, self.WF_ID, self.COMPANY_ID, self.WF_NAME,
            trigger_type="cron", cron_expression="0 9 * * 1-5",
            is_scheduled=True, first_step=self._step(),
        )
        ops = [h for h in sb.history if h[1] == "routines"]
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0][0], "insert")
        row = ops[0][2]
        self.assertEqual(row["workflow_definition_id"], self.WF_ID)
        self.assertEqual(row["company_id"], self.COMPANY_ID)
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["operation_type"], "planner-import-ofx")
        self.assertEqual(row["schedule"]["cron"], "0 9 * * 1-5")
        self.assertIn("timezone", row["schedule"])

    def test_cron_active_updates_existing_routine(self) -> None:
        sb = FakeSupabase(seed={
            "routines": [{
                "id": "rot-1",
                "workflow_definition_id": self.WF_ID,
                "status": "paused",
                "schedule": {"cron": "antigo"},
            }]
        })
        _sync_routine_for_workflow(
            sb, self.WF_ID, self.COMPANY_ID, self.WF_NAME,
            trigger_type="cron", cron_expression="0 9 * * 1-5",
            is_scheduled=True, first_step=self._step(),
        )
        update_ops = [h for h in sb.history if h[0] == "update" and h[1] == "routines"]
        self.assertEqual(len(update_ops), 1)
        patch = update_ops[0][2]
        self.assertEqual(patch["status"], "active")
        self.assertEqual(patch["schedule"]["cron"], "0 9 * * 1-5")

    def test_manual_pauses_existing_routine(self) -> None:
        sb = FakeSupabase(seed={
            "routines": [{
                "id": "rot-1",
                "workflow_definition_id": self.WF_ID,
                "status": "active",
            }]
        })
        _sync_routine_for_workflow(
            sb, self.WF_ID, self.COMPANY_ID, self.WF_NAME,
            trigger_type="manual", cron_expression=None,
            is_scheduled=False, first_step=self._step(),
        )
        update_ops = [h for h in sb.history if h[0] == "update" and h[1] == "routines"]
        self.assertEqual(len(update_ops), 1)
        self.assertEqual(update_ops[0][2], {"status": "paused"})
        # Não cria nova routine
        insert_ops = [h for h in sb.history if h[0] == "insert" and h[1] == "routines"]
        self.assertEqual(insert_ops, [])

    def test_manual_without_existing_routine_is_noop(self) -> None:
        sb = FakeSupabase(seed={"routines": []})
        _sync_routine_for_workflow(
            sb, self.WF_ID, self.COMPANY_ID, self.WF_NAME,
            trigger_type="manual", cron_expression=None,
            is_scheduled=False, first_step=self._step(),
        )
        write_ops = [h for h in sb.history
                     if h[1] == "routines" and h[0] in ("insert", "update")]
        self.assertEqual(write_ops, [])

    def test_cron_scheduled_false_pauses(self) -> None:
        """Toggle is_scheduled=false sem perder cron_expression do workflow."""
        sb = FakeSupabase(seed={
            "routines": [{
                "id": "rot-1",
                "workflow_definition_id": self.WF_ID,
                "status": "active",
            }]
        })
        _sync_routine_for_workflow(
            sb, self.WF_ID, self.COMPANY_ID, self.WF_NAME,
            trigger_type="cron", cron_expression="0 9 * * *",
            is_scheduled=False, first_step=self._step(),
        )
        update_ops = [h for h in sb.history if h[0] == "update" and h[1] == "routines"]
        self.assertEqual(update_ops[0][2], {"status": "paused"})

    def test_op_type_outside_whitelist_falls_to_other(self) -> None:
        sb = FakeSupabase(seed={"routines": []})
        _sync_routine_for_workflow(
            sb, self.WF_ID, self.COMPANY_ID, self.WF_NAME,
            trigger_type="cron", cron_expression="0 9 * * *",
            is_scheduled=True,
            first_step=self._step(op_type="oracle-report", spec="oracle-report"),
        )
        inserted = next(h for h in sb.history if h[0] == "insert")
        self.assertEqual(inserted[2]["operation_type"], "other")

    def test_empty_cron_expression_treated_as_inactive(self) -> None:
        sb = FakeSupabase(seed={"routines": []})
        _sync_routine_for_workflow(
            sb, self.WF_ID, self.COMPANY_ID, self.WF_NAME,
            trigger_type="cron", cron_expression="   ",
            is_scheduled=True, first_step=self._step(),
        )
        write_ops = [h for h in sb.history
                     if h[1] == "routines" and h[0] in ("insert", "update")]
        self.assertEqual(write_ops, [])

    def test_whitelist_contains_required_op_types(self) -> None:
        for op in ("planner-import-ofx", "planner-categorize-pendings", "other"):
            self.assertIn(op, _ROUTINE_OP_TYPE_WHITELIST)


if __name__ == "__main__":
    unittest.main(verbosity=2)
