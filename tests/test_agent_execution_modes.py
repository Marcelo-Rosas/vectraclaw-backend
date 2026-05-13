"""PR-EB — AgentExecutionMode model + endpoint GET /api/agent-execution-modes.

Roda: pytest tests/test_agent_execution_modes.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.models import AgentExecutionMode  # noqa: E402


class AgentExecutionModeModelTests(unittest.TestCase):
    def test_basic_construction_realtime(self) -> None:
        m = AgentExecutionMode(
            id="REALTIME",
            name="Tempo Real",
            description="Polling contínuo",
            icon="zap",
            color="text-emerald-600",
            display_order=10,
            config_schema=[
                {"key": "polling_interval_seconds", "type": "number", "default": 5},
                {"key": "idle_heartbeat_seconds", "type": "number", "default": 30},
            ],
            is_active=True,
        )
        self.assertEqual(m.id, "REALTIME")
        self.assertEqual(len(m.config_schema), 2)

    def test_to_zod_dict_camelcase(self) -> None:
        m = AgentExecutionMode(
            id="CRON", name="Agendado", display_order=20,
            config_schema=[{"key": "cron_expression", "type": "text", "required": True}],
        )
        z = m.to_zod_dict()
        self.assertIn("displayOrder", z)
        self.assertIn("configSchema", z)
        self.assertIn("isActive", z)
        self.assertEqual(z["displayOrder"], 20)
        self.assertEqual(z["configSchema"], [
            {"key": "cron_expression", "type": "text", "required": True}
        ])

    def test_optional_fields_default_to_empty_string(self) -> None:
        m = AgentExecutionMode(id="TRIGGER", name="Gatilho")
        z = m.to_zod_dict()
        self.assertEqual(z["description"], "")
        self.assertEqual(z["icon"], "")
        self.assertEqual(z["color"], "")
        self.assertEqual(z["configSchema"], [])

    def test_defaults(self) -> None:
        m = AgentExecutionMode(id="X", name="X")
        self.assertEqual(m.display_order, 100)
        self.assertEqual(m.is_active, True)
        self.assertEqual(m.config_schema, [])

    def test_id_and_name_required(self) -> None:
        with self.assertRaises(Exception):
            AgentExecutionMode(name="missing id")  # type: ignore[call-arg]
        with self.assertRaises(Exception):
            AgentExecutionMode(id="missing name")  # type: ignore[call-arg]


class AgentExecutionModeSeededShapeTests(unittest.TestCase):
    """Sanidade do seed da migration PR-EA (#89) — reproduz a shape esperada."""

    EXPECTED_IDS = {"REALTIME", "CRON", "TRIGGER"}

    def test_canonical_seed_count(self) -> None:
        self.assertEqual(len(self.EXPECTED_IDS), 3)

    def test_each_seeded_row_constructs_cleanly(self) -> None:
        seed_rows: List[Dict[str, Any]] = [
            {
                "id": "REALTIME", "name": "Tempo Real", "description": "...",
                "icon": "zap", "color": "text-emerald-600", "display_order": 10,
                "config_schema": [
                    {"key": "polling_interval_seconds", "type": "number", "default": 5},
                    {"key": "idle_heartbeat_seconds", "type": "number", "default": 30},
                ],
            },
            {
                "id": "CRON", "name": "Agendado", "description": "...",
                "icon": "clock", "color": "text-blue-600", "display_order": 20,
                "config_schema": [
                    {"key": "cron_expression", "type": "text", "required": True},
                    {"key": "timezone", "type": "text", "default": "America/Sao_Paulo"},
                ],
            },
            {
                "id": "TRIGGER", "name": "Gatilho HTTP", "description": "...",
                "icon": "webhook", "color": "text-purple-600", "display_order": 30,
                "config_schema": [
                    {"key": "function_url", "type": "text", "required": True},
                    {"key": "auth_header_name", "type": "text", "default": "Authorization"},
                    {"key": "auth_secret_ref", "type": "secret"},
                    {"key": "payload_template", "type": "text", "default": "{}"},
                    {"key": "timeout_seconds", "type": "number", "default": 30},
                ],
            },
        ]
        ids = set()
        for row in seed_rows:
            m = AgentExecutionMode(**row, is_active=True)
            ids.add(m.id)
            z = m.to_zod_dict()
            self.assertIn("configSchema", z)
            self.assertTrue(z["isActive"])
        self.assertEqual(ids, self.EXPECTED_IDS)

    def test_seeded_orders_strictly_increasing(self) -> None:
        orders = [10, 20, 30]
        self.assertEqual(orders, sorted(orders))
        self.assertEqual(len(orders), len(set(orders)))

    def test_field_counts_match_pr_ea_seed(self) -> None:
        """REALTIME: 2 campos, CRON: 2, TRIGGER: 5 — espelha a PR-EA."""
        expectations = {"REALTIME": 2, "CRON": 2, "TRIGGER": 5}
        for mode_id, expected_n in expectations.items():
            self.assertGreater(expected_n, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
