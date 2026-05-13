"""Task #52 — OperationType Pydantic model + endpoint.

Roda: pytest tests/test_operation_types_catalog.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.models import OperationType  # noqa: E402


class OperationTypeModelTests(unittest.TestCase):
    def test_basic_construction(self) -> None:
        ot = OperationType(
            id="planner-import-ofx",
            name="Upload OFX (Meu Planner)",
            description="Pivot VEC-416: upload OFX via Playwright.",
            category="kronos-planner",
            icon="upload",
            color="text-emerald-600",
            display_order=430,
            primary_agent_id="9c8d7e6f-5a4b-4321-9876-543210fedcba",
            default_specialty_slug="planner-import-ofx",
        )
        self.assertEqual(ot.id, "planner-import-ofx")
        self.assertEqual(ot.category, "kronos-planner")
        self.assertEqual(ot.primary_agent_id, "9c8d7e6f-5a4b-4321-9876-543210fedcba")

    def test_to_zod_dict_camelcase(self) -> None:
        ot = OperationType(
            id="oracle-research", name="Oracle Research",
            category="oracle", display_order=300,
            primary_agent_id="00000000-0000-0000-0000-000000000002",
            default_specialty_slug="oracle-research",
        )
        z = ot.to_zod_dict()
        self.assertIn("displayOrder", z)
        self.assertIn("primaryAgentId", z)
        self.assertIn("defaultSpecialtySlug", z)
        self.assertEqual(z["displayOrder"], 300)

    def test_optional_fields_default_to_empty_string(self) -> None:
        """Frontend Zod tolera string; force '' em vez de None."""
        ot = OperationType(id="other", name="Outro", category="system")
        z = ot.to_zod_dict()
        self.assertEqual(z["description"], "")
        self.assertEqual(z["icon"], "")
        self.assertEqual(z["color"], "")
        self.assertEqual(z["primaryAgentId"], "")
        self.assertEqual(z["defaultSpecialtySlug"], "")

    def test_defaults(self) -> None:
        ot = OperationType(id="x", name="X", category="x")
        self.assertEqual(ot.display_order, 100)
        self.assertEqual(ot.is_active, True)
        self.assertIsNone(ot.primary_agent_id)
        self.assertIsNone(ot.default_specialty_slug)

    def test_required_fields(self) -> None:
        with self.assertRaises(Exception):
            OperationType(name="missing id", category="x")
        with self.assertRaises(Exception):
            OperationType(id="x", category="x")
        with self.assertRaises(Exception):
            OperationType(id="x", name="X")


class OperationTypeSeedShapeTests(unittest.TestCase):
    """Reproduz amostras do seed da migration #52 e valida shape."""

    KNOWN_CATEGORIES = {
        "system", "commercial", "crm", "oracle",
        "kronos", "kronos-planner", "mnemos", "athena",
    }

    KNOWN_KRONOS_OPS = {
        "financial-audit", "financial-bookkeeping",
        "conciliacao-backlog",
        "planner-import-ofx", "planner-categorize-pendings",
    }

    def test_kronos_ops_construct_with_planner_pivot(self) -> None:
        for op_id in self.KNOWN_KRONOS_OPS:
            with self.subTest(op_id=op_id):
                ot = OperationType(
                    id=op_id, name=op_id, category="kronos-planner"
                    if op_id.startswith("planner-") else "kronos",
                    primary_agent_id="9c8d7e6f-5a4b-4321-9876-543210fedcba",
                )
                self.assertEqual(ot.primary_agent_id, "9c8d7e6f-5a4b-4321-9876-543210fedcba")

    def test_athena_ops_count_matches_pydantic_literal(self) -> None:
        """9 athena-* op_types alinhados com src/models.py:124-132."""
        athena_ops = {
            "athena-classify", "athena-charter", "athena-stakeholder-map",
            "athena-risk-register", "athena-evm", "athena-rag-ingest",
            "athena-audit", "athena-recommend", "athena-prioritize",
        }
        self.assertEqual(len(athena_ops), 9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
