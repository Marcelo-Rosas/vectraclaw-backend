"""PR-B (Modelo C) — Pydantic AgentSharedConfig + payload PUT.

Roda: pytest tests/test_agent_shared_config.py -q
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.models import AgentSharedConfig  # noqa: E402


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AgentSharedConfigModelTests(unittest.TestCase):
    def test_basic_construction_with_schema(self) -> None:
        c = AgentSharedConfig(
            id="00000000-0000-0000-0000-0000000000aa",
            company_id="01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2",
            agent_id="9c8d7e6f-5a4b-4321-9876-543210fedcba",
            values={"ofx_path": "/data/abril.ofx"},
            schema=[
                {"key": "ofx_path", "label": "Caminho do OFX", "type": "text"}
            ],
            created_at=_now(),
            updated_at=_now(),
        )
        self.assertEqual(c.agent_id, "9c8d7e6f-5a4b-4321-9876-543210fedcba")
        self.assertEqual(c.values["ofx_path"], "/data/abril.ofx")
        self.assertEqual(len(c.schema_), 1)

    def test_schema_alias_pythonic_underscore(self) -> None:
        """schema_ é o nome Python (evita colisão com BaseModel.schema()),
        mas mapeia para o jsonb column `schema` no DB."""
        c = AgentSharedConfig(
            id="x", company_id="x", agent_id="x",
            values={}, schema_=[{"key": "a"}],
            created_at=_now(), updated_at=_now(),
        )
        self.assertEqual(c.schema_, [{"key": "a"}])

    def test_to_zod_dict_emits_camelcase(self) -> None:
        c = AgentSharedConfig(
            id="x", company_id="c1", agent_id="a1",
            values={"k": "v"}, schema=[{"key": "k", "type": "text"}],
            created_at=_now(), updated_at=_now(),
        )
        z = c.to_zod_dict()
        self.assertIn("companyId", z)
        self.assertIn("agentId", z)
        self.assertIn("schema", z)        # alias preservado
        self.assertEqual(z["values"], {"k": "v"})
        self.assertEqual(z["schema"], [{"key": "k", "type": "text"}])

    def test_empty_schema_and_values_defaults(self) -> None:
        """values e schema vazios devem virar {} e [] no JSON (não None)."""
        c = AgentSharedConfig(
            id="x", company_id="c1", agent_id="a1",
            values={}, schema=[],
            created_at=_now(), updated_at=_now(),
        )
        z = c.to_zod_dict()
        self.assertEqual(z["values"], {})
        self.assertEqual(z["schema"], [])

    def test_no_collision_with_basemodel_schema_method(self) -> None:
        """Pydantic BaseModel tem .schema() — confirmamos que schema_ funciona
        sem mascarar isso."""
        c = AgentSharedConfig(
            id="x", company_id="c1", agent_id="a1",
            values={}, schema=[{"key": "a"}],
            created_at=_now(), updated_at=_now(),
        )
        # BaseModel.schema() ainda chamável (retorna JSON Schema do model)
        json_schema = type(c).schema()
        self.assertIsInstance(json_schema, dict)
        self.assertEqual(c.schema_, [{"key": "a"}])

    def test_kronos_seed_shape_constructs(self) -> None:
        """Reproduz a forma do que PR-A seedou para Kronos × Vectra Cargo."""
        kronos_schema: List[Dict[str, Any]] = [
            {"key": "ofx_path", "label": "Caminho do OFX (compartilhado)",
             "type": "text", "required": False,
             "description": "Diretório ou arquivo .ofx usado por todas as specialties do Kronos."},
            {"key": "planner_instituicao", "label": "Instituição financeira",
             "type": "text", "required": False,
             "description": "Nome no combobox partitionId do Meu Planner."},
            {"key": "pdf_path", "label": "PDF do extrato (opcional)",
             "type": "text", "required": False,
             "description": "PDF C6 para enrichment de descrições genéricas (PIX)."},
            {"key": "recipient", "label": "Email destinatário do relatório",
             "type": "text", "required": False,
             "default": "marcelo.rosas@vectracargo.com.br",
             "description": "Email para onde os relatórios do Kronos são enviados."},
        ]
        c = AgentSharedConfig(
            id="some-uuid",
            company_id="01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2",
            agent_id="9c8d7e6f-5a4b-4321-9876-543210fedcba",
            values={},          # vazio inicialmente, user preenche
            schema=kronos_schema,
            created_at=_now(),
            updated_at=_now(),
        )
        self.assertEqual(len(c.schema_), 4)
        keys = {f["key"] for f in c.schema_}
        self.assertEqual(
            keys, {"ofx_path", "planner_instituicao", "pdf_path", "recipient"}
        )


class SaveAgentSharedConfigInputTests(unittest.TestCase):
    """Sanidade do payload PUT — só `values` é editável via API."""

    def test_payload_accepts_values_only(self) -> None:
        # Import inline para não inflar topo do arquivo de teste
        from src.api import SaveAgentSharedConfigInput

        payload = SaveAgentSharedConfigInput(values={"ofx_path": "/x.ofx"})
        self.assertEqual(payload.values, {"ofx_path": "/x.ofx"})

    def test_payload_defaults_to_empty_dict(self) -> None:
        from src.api import SaveAgentSharedConfigInput

        payload = SaveAgentSharedConfigInput()
        self.assertEqual(payload.values, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
