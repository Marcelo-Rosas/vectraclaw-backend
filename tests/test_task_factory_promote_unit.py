"""
TaskFactory.promote_successors_after_completion + rollup_parent — cliente Supabase fake.

Roda: python tests/test_task_factory_promote_unit.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import unittest
import uuid
from typing import Any, Dict, List, Optional


class _FakeResult:
    __slots__ = ("data",)

    def __init__(self, data: Any) -> None:
        self.data = data


class _FakeQuery:
    def __init__(self, root: "FakeSupabase", table: str) -> None:
        self.root = root
        self.table = table
        self._op: Optional[str] = None
        self._cols: Optional[str] = None
        self._patch: Optional[Dict[str, Any]] = None
        self._insert_row: Optional[Dict[str, Any]] = None
        self._preds: List[Any] = []

    def select(self, cols: str = "*") -> "_FakeQuery":
        self._op = "select"
        self._cols = cols
        return self

    def update(self, patch: Dict[str, Any]) -> "_FakeQuery":
        self._op = "update"
        self._patch = patch
        return self

    def insert(self, row: Dict[str, Any]) -> "_FakeQuery":
        self._op = "insert"
        self._insert_row = dict(row)
        return self

    def delete(self) -> "_FakeQuery":
        self._op = "delete"
        return self

    def eq(self, col: str, val: Any) -> "_FakeQuery":
        self._preds.append(("eq", col, val))
        return self

    def limit(self, n: int) -> "_FakeQuery":
        self._preds.append(("limit", n))
        return self

    def maybe_single(self) -> "_FakeQuery":
        self._preds.append(("maybe_single",))
        return self

    def order(self, _col: str) -> "_FakeQuery":
        return self

    def execute(self) -> _FakeResult:
        if self.table == "tasks":
            return self._exec_tasks()
        if self.table == "task_tree_status":
            return self._exec_tree_status()
        if self.table == "workflow_definitions":
            return _FakeResult([])
        raise AssertionError(f"tabela nao suportada no fake: {self.table}")

    def _match(self, row: Dict[str, Any]) -> bool:
        for p in self._preds:
            if p[0] == "eq":
                _, col, val = p
                if str(row.get(col)) != str(val):
                    return False
        return True

    def _exec_tasks(self) -> _FakeResult:
        rows = list(self.root.tasks.values())
        if self._op == "select":
            out = [r for r in rows if self._match(r)]
            for p in self._preds:
                if p[0] == "limit":
                    out = out[: int(p[1])]
            if ("maybe_single",) in self._preds:
                return _FakeResult(out[0] if out else None)
            return _FakeResult(out)
        if self._op == "update":
            hits = [r for r in rows if self._match(r)]
            for r in hits:
                r.update(self._patch or {})
            return _FakeResult(hits[:1] if hits else [])
        if self._op == "insert":
            rid = self._insert_row.get("id") or str(uuid.uuid4())
            row = dict(self._insert_row)
            row["id"] = rid
            self.root.tasks[rid] = row
            return _FakeResult([row])
        if self._op == "delete":
            to_del = [rid for rid, r in self.root.tasks.items() if self._match(r)]
            for rid in to_del:
                del self.root.tasks[rid]
            return _FakeResult([])
        raise AssertionError(f"op desconhecida: {self._op}")

    def _exec_tree_status(self) -> _FakeResult:
        if self._op != "select":
            raise AssertionError("task_tree_status: apenas select")
        out = [r for r in self.root.task_tree_status if self._match(r)]
        if ("maybe_single",) in self._preds:
            return _FakeResult(out[0] if out else None)
        return _FakeResult(out)


class FakeSupabase:
    def __init__(self) -> None:
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.task_tree_status: List[Dict[str, Any]] = []

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self, name)


class TestTaskFactoryPromote(unittest.TestCase):
    def test_promotes_backlog_when_deps_done(self):
        from src.services.task_factory import TaskFactory

        sb = FakeSupabase()
        pid = str(uuid.uuid4())
        aid = str(uuid.uuid4())
        bid = str(uuid.uuid4())
        sb.tasks[aid] = {
            "id": aid,
            "parent_task_id": pid,
            "status": "done",
            "successor_step_codes": ["b"],
            "dependency_step_codes": [],
            "input_json": {"workflowStepSlug": "a"},
        }
        sb.tasks[bid] = {
            "id": bid,
            "parent_task_id": pid,
            "status": "backlog",
            "successor_step_codes": [],
            "dependency_step_codes": ["a"],
            "input_json": {"workflowStepSlug": "b"},
        }
        sb.tasks[pid] = {
            "id": pid,
            "parent_task_id": None,
            "status": "in_progress",
            "input_json": {},
        }

        TaskFactory(sb).promote_successors_after_completion(aid)
        self.assertEqual(sb.tasks[bid]["status"], "queued")

    def test_rollup_marks_parent_done(self):
        from src.services.task_factory import TaskFactory

        sb = FakeSupabase()
        pid = str(uuid.uuid4())
        sb.task_tree_status.append(
            {
                "parent_id": pid,
                "children_total": 2,
                "children_done": 2,
                "children_blocked": 0,
                "children_skipped": 0,
                "children_pending": 0,
            }
        )
        sb.tasks[pid] = {"id": pid, "parent_task_id": None, "status": "in_progress"}

        TaskFactory(sb).rollup_parent(pid)
        self.assertEqual(sb.tasks[pid]["status"], "done")


if __name__ == "__main__":
    unittest.main()
