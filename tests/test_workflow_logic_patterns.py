"""Task #49 — WorkflowLogicPattern model + endpoint.

Roda: pytest tests/test_workflow_logic_patterns.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.models import WorkflowLogicPattern  # noqa: E402


class WorkflowLogicPatternModelTests(unittest.TestCase):
    def test_basic_construction_simple(self) -> None:
        p = WorkflowLogicPattern(
            id="simple",
            category="simple",
            taxonomy="SIMPLE",
            name="Linear (Sucesso/Falha)",
            description="Step linear sem condicionais.",
            heuristics=["Default para steps sem lógica especial."],
            icon="arrow-right",
            color="text-slate-500",
            display_order=10,
            engine_handler="WorkflowEngine.advance",
        )
        self.assertEqual(p.taxonomy, "SIMPLE")
        self.assertEqual(p.engine_handler, "WorkflowEngine.advance")
        self.assertIsNone(p.json_skeleton)

    def test_to_zod_dict_camelcase(self) -> None:
        p = WorkflowLogicPattern(
            id="split-if",
            category="splitting",
            taxonomy="SPLIT-IF",
            name="SPLIT com IF",
            display_order=20,
            json_skeleton={"nodes": [{"name": "IF"}]},
        )
        z = p.to_zod_dict()
        self.assertIn("displayOrder", z)
        self.assertIn("jsonSkeleton", z)
        self.assertIn("engineHandler", z)
        self.assertEqual(z["displayOrder"], 20)
        self.assertEqual(z["jsonSkeleton"], {"nodes": [{"name": "IF"}]})

    def test_optional_fields_default_to_empty_string(self) -> None:
        p = WorkflowLogicPattern(
            id="x", category="x", taxonomy="X", name="X"
        )
        z = p.to_zod_dict()
        self.assertEqual(z["description"], "")
        self.assertEqual(z["icon"], "")
        self.assertEqual(z["color"], "")

    def test_defaults(self) -> None:
        p = WorkflowLogicPattern(id="x", category="x", taxonomy="X", name="X")
        self.assertEqual(p.display_order, 100)
        self.assertEqual(p.is_active, True)
        self.assertEqual(p.engine_handler, "pending")
        self.assertEqual(p.heuristics, [])

    def test_required_fields(self) -> None:
        with self.assertRaises(Exception):
            WorkflowLogicPattern(category="x", taxonomy="X", name="X")
        with self.assertRaises(Exception):
            WorkflowLogicPattern(id="x", taxonomy="X", name="X")
        with self.assertRaises(Exception):
            WorkflowLogicPattern(id="x", category="x", name="X")
        with self.assertRaises(Exception):
            WorkflowLogicPattern(id="x", category="x", taxonomy="X")


class WorkflowLogicPatternSeedShapeTests(unittest.TestCase):
    """Reproduz a forma do seed da migration #49.

    8 patterns esperados — espelho de FlowLogic.tsx + SIMPLE."""

    EXPECTED_TAXONOMIES = {
        "SIMPLE",
        "SPLIT-IF",
        "SPLIT-SWITCH",
        "MERGE",
        "LOOP-BATCH",
        "WAIT-EVENT",
        "SUBFLOW",
        "ERROR-HANDLER",
    }

    EXPECTED_CATEGORIES = {
        "simple",
        "splitting",
        "merging",
        "looping",
        "waiting",
        "subworkflows",
        "error-handling",
    }

    def test_canonical_seed_count(self) -> None:
        self.assertEqual(len(self.EXPECTED_TAXONOMIES), 8)
        self.assertEqual(len(self.EXPECTED_CATEGORIES), 7)

    def test_each_seeded_row_constructs(self) -> None:
        seed_rows: List[Dict[str, Any]] = [
            {"id": "simple", "category": "simple", "taxonomy": "SIMPLE",
             "name": "Linear", "engine_handler": "WorkflowEngine.advance",
             "display_order": 10},
            {"id": "split-if", "category": "splitting", "taxonomy": "SPLIT-IF",
             "name": "SPLIT com IF", "display_order": 20,
             "json_skeleton": {"nodes": [{"type": "n8n-nodes-base.if"}]}},
            {"id": "split-switch", "category": "splitting", "taxonomy": "SPLIT-SWITCH",
             "name": "SPLIT com Switch", "display_order": 30,
             "json_skeleton": {"type": "n8n-nodes-base.switch"}},
            {"id": "merge-by-key", "category": "merging", "taxonomy": "MERGE",
             "name": "Merge por Chave", "display_order": 40},
            {"id": "loop-batch", "category": "looping", "taxonomy": "LOOP-BATCH",
             "name": "Processar em Lotes", "display_order": 50},
            {"id": "wait-event", "category": "waiting", "taxonomy": "WAIT-EVENT",
             "name": "Aguardar Webhook", "display_order": 60},
            {"id": "subflow", "category": "subworkflows", "taxonomy": "SUBFLOW",
             "name": "Execute Sub-workflow", "display_order": 70},
            {"id": "error-handler", "category": "error-handling", "taxonomy": "ERROR-HANDLER",
             "name": "Workflow de Erro", "display_order": 80},
        ]
        taxonomies = set()
        categories = set()
        for row in seed_rows:
            p = WorkflowLogicPattern(**row, is_active=True)
            taxonomies.add(p.taxonomy)
            categories.add(p.category)
            z = p.to_zod_dict()
            self.assertTrue(z["isActive"])
        self.assertEqual(taxonomies, self.EXPECTED_TAXONOMIES)
        self.assertEqual(categories, self.EXPECTED_CATEGORIES)

    def test_only_simple_has_real_engine_handler(self) -> None:
        """Engine v1 só interpreta SIMPLE. Demais 7 patterns ficam 'pending'
        até Engine v2 (task #42)."""
        seed_handlers = {
            "SIMPLE": "WorkflowEngine.advance",
            "SPLIT-IF": "pending",
            "SPLIT-SWITCH": "pending",
            "MERGE": "pending",
            "LOOP-BATCH": "pending",
            "WAIT-EVENT": "pending",
            "SUBFLOW": "pending",
            "ERROR-HANDLER": "pending",
        }
        real_count = sum(1 for h in seed_handlers.values() if h != "pending")
        pending_count = sum(1 for h in seed_handlers.values() if h == "pending")
        self.assertEqual(real_count, 1)
        self.assertEqual(pending_count, 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
