"""VEC-168 — intelligence dashboard service + route RBAC."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.services.intelligence_dashboard import (  # noqa: E402
    _trend,
    assert_intelligence_access,
    build_intelligence_dashboard,
    resolve_company_scope,
)


class RbacTests(unittest.TestCase):
    def test_assert_blocks_viewer(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            assert_intelligence_access("viewer")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_assert_allows_platform_admin(self) -> None:
        assert_intelligence_access("platform_admin")

    def test_resolve_scope_global(self) -> None:
        self.assertIsNone(resolve_company_scope("platform_admin", "any"))

    def test_resolve_scope_single_tenant(self) -> None:
        self.assertEqual(
            resolve_company_scope("company_admin", "cmp-1"),
            ["cmp-1"],
        )


class TrendTests(unittest.TestCase):
    def test_up(self) -> None:
        self.assertEqual(_trend(20, 10), "up")

    def test_down(self) -> None:
        self.assertEqual(_trend(5, 20), "down")

    def test_stable(self) -> None:
        self.assertEqual(_trend(10, 10), "stable")


class BuildDashboardTests(unittest.TestCase):
    def _mock_client(
        self,
        *,
        companies: list,
        tasks: list,
        agents: list,
        heartbeats: list,
        runs: list | None = None,
    ) -> MagicMock:
        client = MagicMock()

        def table_side(name: str) -> MagicMock:
            chain = MagicMock()
            data = {
                "companies": companies,
                "tasks": tasks,
                "agents": agents,
                "heartbeats": heartbeats,
                "runs": runs or [],
            }.get(name, [])
            chain.select.return_value = chain
            chain.gte.return_value = chain
            chain.in_.return_value = chain
            chain.execute.return_value = MagicMock(data=data)
            return chain

        client.table.side_effect = table_side
        return client

    def test_empty_companies(self) -> None:
        client = self._mock_client(
            companies=[],
            tasks=[],
            agents=[],
            heartbeats=[],
        )
        out = build_intelligence_dashboard(
            client,
            caller_role="platform_admin",
            caller_company_id=None,
            weeks=4,
        )
        self.assertEqual(out["totals"]["companies"], 0)

    def test_aggregates_kpis(self) -> None:
        now = datetime.now(timezone.utc)
        cid = "11111111-1111-1111-1111-111111111111"
        client = self._mock_client(
            companies=[{"company_id": cid, "name": "Acme"}],
            agents=[
                {
                    "id": "a1",
                    "company_id": cid,
                    "name": "Hermes",
                    "status": "working",
                }
            ],
            tasks=[
                {
                    "id": "t1",
                    "company_id": cid,
                    "status": "done",
                    "created_at": now.isoformat(),
                    "cost_usd": 0.5,
                    "assigned_to_agent_id": "a1",
                },
                {
                    "id": "t2",
                    "company_id": cid,
                    "status": "errored",
                    "created_at": (now - timedelta(days=2)).isoformat(),
                    "cost_usd": 0,
                    "assigned_to_agent_id": "a1",
                },
            ],
            heartbeats=[
                {
                    "company_id": cid,
                    "agent_id": "a1",
                    "tokens_used": 1000,
                    "created_at": now.isoformat(),
                }
            ],
            runs=[
                {
                    "company_id": cid,
                    "agent_id": "a1",
                    "duration_ms": 45000,
                    "cost_usd": 1.25,
                    "started_at": now.isoformat(),
                }
            ],
        )
        out = build_intelligence_dashboard(
            client,
            caller_role="admin",
            caller_company_id=None,
            weeks=4,
        )
        self.assertEqual(out["totals"]["companies"], 1)
        self.assertEqual(out["totals"]["activeAgents"], 1)
        self.assertGreaterEqual(out["totals"]["tasksThisWeek"], 1)
        self.assertEqual(out["totals"]["tokensThisMonth"], 1000)
        self.assertEqual(out["totals"]["successRate"], 0.5)
        self.assertEqual(len(out["companies"]), 1)
        self.assertEqual(out["companies"][0]["name"], "Acme")
        self.assertEqual(len(out["topAgentsByProductivity"]), 1)
        self.assertEqual(out["topAgentsByCost"][0]["costUsd"], 1.75)


if __name__ == "__main__":
    unittest.main()
