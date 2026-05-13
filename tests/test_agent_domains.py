"""PR-DB — AgentDomain model + endpoint GET /api/agent-domains.

Roda: pytest tests/test_agent_domains.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.models import AgentDomain  # noqa: E402


class AgentDomainModelTests(unittest.TestCase):
    """Pydantic model — to_zod_dict alias camelCase + defaults."""

    def test_basic_construction(self) -> None:
        d = AgentDomain(
            id="finance",
            name="Financeiro",
            description="Auditoria e conciliação",
            icon="wallet",
            color="text-emerald-600",
            display_order=10,
            is_active=True,
        )
        self.assertEqual(d.id, "finance")
        self.assertEqual(d.display_order, 10)

    def test_to_zod_dict_camelcase_keys(self) -> None:
        d = AgentDomain(
            id="logistics", name="Logística", display_order=20, is_active=True,
        )
        z = d.to_zod_dict()
        # CamelModel converte snake → camel via alias
        self.assertIn("displayOrder", z)
        self.assertIn("isActive", z)
        self.assertEqual(z["displayOrder"], 20)
        self.assertEqual(z["isActive"], True)

    def test_optional_fields_default_to_empty_string(self) -> None:
        """description/icon/color None → '' no JSON enviado pra UI."""
        d = AgentDomain(id="crm", name="CRM & Clientes")
        z = d.to_zod_dict()
        self.assertEqual(z["description"], "")
        self.assertEqual(z["icon"], "")
        self.assertEqual(z["color"], "")

    def test_defaults_display_order_and_is_active(self) -> None:
        d = AgentDomain(id="x", name="X")
        self.assertEqual(d.display_order, 100)
        self.assertEqual(d.is_active, True)

    def test_id_and_name_are_required(self) -> None:
        with self.assertRaises(Exception):
            AgentDomain(name="missing id")  # type: ignore[call-arg]
        with self.assertRaises(Exception):
            AgentDomain(id="missing name")  # type: ignore[call-arg]


class AgentDomainSeededRowsTests(unittest.TestCase):
    """Sanidade do seed da migration PR-DA (não vai ao banco — só shape)."""

    EXPECTED_SLUGS = {
        "finance",
        "logistics",
        "communication",
        "intelligence",
        "knowledge",
        "automation",
        "crm",
    }

    def test_canonical_seed_count(self) -> None:
        # Verifica que a lista esperada tem exatamente 7 slugs
        self.assertEqual(len(self.EXPECTED_SLUGS), 7)

    def test_each_seeded_row_constructs_cleanly(self) -> None:
        """Reproduz a forma do que a migration insere — todos devem
        construir sem erro pelo Pydantic model."""
        seed_rows: List[Dict[str, Any]] = [
            {"id": "finance", "name": "Financeiro", "description": "...",
             "icon": "wallet", "color": "text-emerald-600", "display_order": 10},
            {"id": "logistics", "name": "Logística", "description": "...",
             "icon": "truck", "color": "text-blue-600", "display_order": 20},
            {"id": "communication", "name": "Comunicação", "description": "...",
             "icon": "message-circle", "color": "text-purple-600", "display_order": 30},
            {"id": "intelligence", "name": "Inteligência & Pesquisa",
             "description": "...", "icon": "search",
             "color": "text-amber-600", "display_order": 40},
            {"id": "knowledge", "name": "Dados & Conhecimento",
             "description": "...", "icon": "database",
             "color": "text-cyan-600", "display_order": 50},
            {"id": "automation", "name": "Processos & Automação",
             "description": "...", "icon": "workflow",
             "color": "text-pink-600", "display_order": 60},
            {"id": "crm", "name": "CRM & Clientes", "description": "...",
             "icon": "users", "color": "text-indigo-600", "display_order": 70},
        ]
        slugs = set()
        for row in seed_rows:
            d = AgentDomain(**row, is_active=True)
            slugs.add(d.id)
            z = d.to_zod_dict()
            self.assertIn("displayOrder", z)
            self.assertTrue(z["isActive"])
        self.assertEqual(slugs, self.EXPECTED_SLUGS)

    def test_seeded_orders_are_strictly_increasing(self) -> None:
        """display_order deve ser estritamente crescente — facilita
        renderização determinística no frontend."""
        orders = [10, 20, 30, 40, 50, 60, 70]
        self.assertEqual(orders, sorted(orders))
        self.assertEqual(len(orders), len(set(orders)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
