"""PR-B1 / PR-B2 — wire de routine.workflowDefinitionId e goal pós-classify."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.models import Goal, Routine  # noqa: E402


class RoutineWorkflowWireTests(unittest.TestCase):
    def test_routine_wire_includes_workflow_definition_id(self) -> None:
        row = {
            "id": "rot-1",
            "company_id": "01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2",
            "name": "Cadência IG",
            "status": "active",
            "schedule": {
                "cron": "0 9 * * *",
                "timezone": "America/Sao_Paulo",
                "human": "Diário 9h",
            },
            "workflow_definition_id": "wf-eros-spin",
            "created_at": datetime.now(timezone.utc),
        }
        wire = Routine(**row).to_zod_dict()
        self.assertEqual(wire["workflowDefinitionId"], "wf-eros-spin")

    def test_routine_wire_without_workflow_is_nullable(self) -> None:
        row = {
            "id": "rot-2",
            "company_id": "01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2",
            "name": "Legacy",
            "status": "active",
            "schedule": {
                "cron": "0 9 * * *",
                "timezone": "America/Sao_Paulo",
                "human": "Diário 9h",
            },
            "created_at": datetime.now(timezone.utc),
        }
        wire = Routine(**row).to_zod_dict()
        self.assertIsNone(wire.get("workflowDefinitionId"))


class GoalClassifyWireTests(unittest.TestCase):
    def test_goal_wire_includes_classify_fields(self) -> None:
        row = {
            "id": "gol-1",
            "company_id": "01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2",
            "title": "Prospecção academias IG",
            "metric": "leads",
            "target": 50.0,
            "current": 0.0,
            "kind": "operation",
            "confidence": 0.91,
            "business_case_strength": "adequate",
            "classified_at": datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
            "pmoia_metadata": {
                "classification_rationale": "Rotina comercial recorrente",
                "next_handler_suggested": "mercator",
            },
        }
        wire = Goal(**row).to_zod_dict()
        self.assertEqual(wire["kind"], "operation")
        self.assertAlmostEqual(wire["confidence"], 0.91)
        self.assertEqual(wire["businessCaseStrength"], "adequate")
        self.assertIn("classifiedAt", wire)
        self.assertEqual(
            wire["classificationRationale"], "Rotina comercial recorrente"
        )
        self.assertEqual(wire["nextHandlerSuggested"], "mercator")

    def test_unclassified_goal_fields_nullable(self) -> None:
        row = {
            "id": "gol-2",
            "company_id": "01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2",
            "title": "Novo goal",
            "metric": "revenue",
            "target": 100.0,
            "current": 0.0,
        }
        wire = Goal(**row).to_zod_dict()
        self.assertIsNone(wire.get("kind"))
        self.assertIsNone(wire.get("classifiedAt"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
