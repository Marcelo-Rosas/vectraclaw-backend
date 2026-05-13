"""Task #2 — Agent model aceita specialty_ids: list[str] + bug fix em api.py:1781.

Antes: api.py:1781 usava `specialty_map: Dict[str, str]` que SOBRESCREVIA
quando um agente tinha múltiplas specialties (Oracle tem 3, por exemplo).
Resultado: GET /agents só mostrava 1 specialty por agente.

Agora: lista canônica `specialty_ids: List[str]`, campo singular
`specialty_id` mantido como primeiro da lista por backcompat.

Roda: pytest tests/test_agent_specialty_ids_list.py -q
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.models import Agent  # noqa: E402


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _base_agent_kwargs(**overrides) -> dict:
    """Fields obrigatórios do Agent model."""
    base = {
        "id": "agent-uuid",
        "company_id": "company-uuid",
        "name": "Test Agent",
        "role": "Test Role",
        "status": "idle",
        "token_budget": 100000,
        "current_burn_rate": 0.0,
        "adapter_type": "claude_code",
        "created_at": _now(),
        "updated_at": _now(),
    }
    base.update(overrides)
    return base


class AgentSpecialtyIdsTests(unittest.TestCase):
    def test_default_empty_list(self) -> None:
        """specialty_ids default vazio quando agent não tem specialties."""
        agent = Agent(**_base_agent_kwargs())
        self.assertEqual(agent.specialty_ids, [])
        self.assertIsNone(agent.specialty_id)

    def test_single_specialty_in_list(self) -> None:
        """Agente com 1 specialty."""
        agent = Agent(**_base_agent_kwargs(
            specialty_id="financial-audit",
            specialty_ids=["financial-audit"],
        ))
        self.assertEqual(agent.specialty_ids, ["financial-audit"])
        self.assertEqual(agent.specialty_id, "financial-audit")

    def test_multiple_specialties_oracle_case(self) -> None:
        """Caso Oracle: 3 specialties atreladas."""
        agent = Agent(**_base_agent_kwargs(
            id="oracle-uuid",
            name="Oracle",
            role="Analysis & Research Specialist",
            specialty_id="oracle-research",  # primeira da lista (backcompat)
            specialty_ids=["oracle-research", "oracle-extract", "oracle-rag"],
        ))
        self.assertEqual(len(agent.specialty_ids), 3)
        self.assertEqual(agent.specialty_id, "oracle-research")  # primeira

    def test_to_zod_dict_emits_camelcase_ids(self) -> None:
        agent = Agent(**_base_agent_kwargs(
            specialty_id="financial-audit",
            specialty_ids=["financial-audit", "planner-import-ofx"],
        ))
        z = agent.to_zod_dict()
        self.assertIn("specialtyIds", z)
        self.assertEqual(z["specialtyIds"], ["financial-audit", "planner-import-ofx"])
        # Campo singular continua exposto (backcompat)
        self.assertIn("specialtyId", z)
        self.assertEqual(z["specialtyId"], "financial-audit")

    def test_specialty_ids_can_be_passed_via_camelcase_input(self) -> None:
        """Inbound do frontend (camelCase) também aceita."""
        agent = Agent(**_base_agent_kwargs(
            specialtyId="financial-audit",
            specialtyIds=["financial-audit", "planner-categorize-pendings"],
        ))
        self.assertEqual(agent.specialty_ids, ["financial-audit", "planner-categorize-pendings"])


class SpecialtyMapAccumulationTests(unittest.TestCase):
    """Reproduz o bug fix em api.py:1781 — acumula em lista em vez de
    sobrescrever no dict."""

    def test_old_logic_loses_specialties(self) -> None:
        """Comportamento ANTIGO (bug): dict.update() sobrescreve."""
        sc_data = [
            {"agent_id": "oracle", "specialty_id": "oracle-research"},
            {"agent_id": "oracle", "specialty_id": "oracle-extract"},
            {"agent_id": "oracle", "specialty_id": "oracle-rag"},
        ]
        # Lógica antiga reproduzida:
        old_map = {}
        for sc in sc_data:
            old_map[sc["agent_id"]] = sc["specialty_id"]
        # Resultado: só 1 (a última)
        self.assertEqual(len(old_map["oracle"]), len("oracle-rag"))  # string, não lista
        self.assertEqual(old_map["oracle"], "oracle-rag")

    def test_new_logic_accumulates(self) -> None:
        """Comportamento NOVO (fix): lista acumula todas."""
        sc_data = [
            {"agent_id": "oracle", "specialty_id": "oracle-research"},
            {"agent_id": "oracle", "specialty_id": "oracle-extract"},
            {"agent_id": "oracle", "specialty_id": "oracle-rag"},
            {"agent_id": "kronos", "specialty_id": "financial-audit"},
            {"agent_id": "kronos", "specialty_id": "planner-import-ofx"},
            {"agent_id": "kronos", "specialty_id": "planner-categorize-pendings"},
        ]
        # Lógica nova reproduzida:
        new_map: dict[str, list[str]] = {}
        for sc in sc_data:
            new_map.setdefault(sc["agent_id"], []).append(sc["specialty_id"])

        self.assertEqual(len(new_map["oracle"]), 3)
        self.assertEqual(
            sorted(new_map["oracle"]),
            sorted(["oracle-research", "oracle-extract", "oracle-rag"]),
        )
        self.assertEqual(len(new_map["kronos"]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
