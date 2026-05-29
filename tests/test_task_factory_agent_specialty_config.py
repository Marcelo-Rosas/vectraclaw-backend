"""P0-BE-3 — TaskFactory resolve assigned_to_agent_id via agent_specialty_config_id.

Roda: pytest tests/test_task_factory_agent_specialty_config.py -q
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.agent_ids import ORACLE_AGENT_ID  # noqa: E402
from src.services.task_factory import TaskFactory  # noqa: E402

KRONOS_ID = "9c8d7e6f-5a4b-4321-9876-543210fedcba"
CONFIG_ID = "11111111-1111-1111-1111-111111111111"
COMPANY_ID = "01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2"


class _FakeTable:
    def __init__(self, handler):
        self._handler = handler
        self._filters: Dict[str, Any] = {}

    def select(self, *_cols):
        return self

    def eq(self, key: str, val: Any):
        self._filters[key] = val
        return self

    def limit(self, _n: int):
        return self

    def execute(self):
        return self._handler(self._filters)


class _FakeClient:
    def __init__(self, config_rows: Optional[List[Dict[str, Any]]] = None):
        self._config_rows = config_rows or []

    def table(self, name: str):
        if name == "agent_specialty_configs":

            def handler(filters: Dict[str, Any]):
                data = [
                    r
                    for r in self._config_rows
                    if r.get("id") == filters.get("id")
                    and r.get("company_id") == filters.get("company_id")
                ]
                return MagicMock(data=data[:1])

            return _FakeTable(handler)
        raise AssertionError(f"unexpected table {name}")


class ResolveAssignedAgentTests(unittest.TestCase):
    def test_prefers_agent_specialty_config_id(self) -> None:
        client = _FakeClient(
            [{"id": CONFIG_ID, "company_id": COMPANY_ID, "agent_id": KRONOS_ID}]
        )
        factory = TaskFactory(client)
        row = {
            "agent_specialty_config_id": CONFIG_ID,
            "specialty_slug": "wrong-slug",
        }
        agent_id = factory._resolve_assigned_agent_id(COMPANY_ID, row, "conciliacao-backlog")
        self.assertEqual(agent_id, KRONOS_ID)

    def test_falls_back_to_specialty_slug(self) -> None:
        client = _FakeClient()
        factory = TaskFactory(client)
        factory._dispatcher._find_agent = MagicMock(return_value=KRONOS_ID)  # type: ignore[method-assign]
        row = {"specialty_slug": "financial-audit"}
        agent_id = factory._resolve_assigned_agent_id(COMPANY_ID, row, "audit")
        self.assertEqual(agent_id, KRONOS_ID)
        factory._dispatcher._find_agent.assert_called_once_with(  # type: ignore[attr-defined]
            COMPANY_ID, "financial-audit", operation_type="audit"
        )

    def test_oracle_operation_without_config(self) -> None:
        client = _FakeClient()
        factory = TaskFactory(client)
        agent_id = factory._resolve_assigned_agent_id(COMPANY_ID, {}, "oracle-research")
        self.assertEqual(agent_id, ORACLE_AGENT_ID)


if __name__ == "__main__":
    unittest.main()
