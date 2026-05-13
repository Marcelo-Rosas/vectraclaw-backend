"""HOTFIX-5 — _coerce_sipoc_responsavel normaliza 'agente:<uuid>' da UI.

Bug: formulário Nova Etapa (/workflow) permite escolher um agente específico,
mas Zod do frontend + DB CHECK em workflow_steps.responsavel só aceitam o
enum literal 'agente'|'humano'|'sistema'. Resultado: payload tipo
'agente:9c8d7e6f-...' explodia validação.

Função extrai UUID → grava responsibleAgentId + redefine responsavel
para o enum aceito.

Roda: pytest tests/test_sipoc_responsavel_coerce.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.api import _coerce_sipoc_responsavel  # noqa: E402


class CoerceSipocResponsavelTests(unittest.TestCase):
    def test_extracts_uuid_from_agente_prefix(self) -> None:
        meta = {"responsavel": "agente:9c8d7e6f-5a4b-4321-9876-543210fedcba"}
        _coerce_sipoc_responsavel(meta)
        self.assertEqual(meta["responsavel"], "agente")
        self.assertEqual(
            meta["responsibleAgentId"], "9c8d7e6f-5a4b-4321-9876-543210fedcba"
        )

    def test_handles_humano_prefix(self) -> None:
        meta = {"responsavel": "humano:operador-fiscal"}
        _coerce_sipoc_responsavel(meta)
        self.assertEqual(meta["responsavel"], "humano")
        # humano não grava responsibleAgentId (humanos não são agents)
        self.assertNotIn("responsibleAgentId", meta)

    def test_handles_sistema_prefix(self) -> None:
        meta = {"responsavel": "sistema:cron-scheduler"}
        _coerce_sipoc_responsavel(meta)
        self.assertEqual(meta["responsavel"], "sistema")
        self.assertNotIn("responsibleAgentId", meta)

    def test_passes_through_canonical_enum(self) -> None:
        """Já no formato canônico — função é no-op."""
        for valid in ("agente", "humano", "sistema"):
            meta = {"responsavel": valid}
            _coerce_sipoc_responsavel(meta)
            self.assertEqual(meta["responsavel"], valid)
            self.assertNotIn("responsibleAgentId", meta)

    def test_noop_when_responsavel_missing(self) -> None:
        meta = {"nome": "Etapa X"}
        _coerce_sipoc_responsavel(meta)
        self.assertNotIn("responsavel", meta)
        self.assertNotIn("responsibleAgentId", meta)

    def test_noop_when_responsavel_not_string(self) -> None:
        meta = {"responsavel": 123}
        _coerce_sipoc_responsavel(meta)
        self.assertEqual(meta["responsavel"], 123)

    def test_agente_prefix_without_uuid_only_sets_enum(self) -> None:
        """Edge case: 'agente:' com tail vazio — só normaliza enum."""
        meta = {"responsavel": "agente:"}
        _coerce_sipoc_responsavel(meta)
        self.assertEqual(meta["responsavel"], "agente")
        self.assertNotIn("responsibleAgentId", meta)

    def test_uuid_is_trimmed(self) -> None:
        meta = {"responsavel": "agente:  9c8d7e6f-5a4b-4321-9876-543210fedcba  "}
        _coerce_sipoc_responsavel(meta)
        self.assertEqual(
            meta["responsibleAgentId"], "9c8d7e6f-5a4b-4321-9876-543210fedcba"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
