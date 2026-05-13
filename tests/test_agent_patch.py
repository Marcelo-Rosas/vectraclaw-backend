"""Hotfix — AgentPatch aceita systemPrompt, platformUrl, requiresApproval.

Antes deste fix, PATCH /api/agents/{id} retornava 400 empty_patch quando
o frontend tentava editar a tab Instructions porque `system_prompt` não
estava declarado em AgentPatch — extra="ignore" descartava o campo.

Roda: pytest tests/test_agent_patch.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.api import AgentPatch  # noqa: E402


class AgentPatchAcceptedFieldsTests(unittest.TestCase):
    def test_system_prompt_via_camelcase_alias(self) -> None:
        """Frontend envia camelCase (systemPrompt); backend deve aceitar."""
        patch = AgentPatch(systemPrompt="# Novo prompt")  # type: ignore[call-arg]
        d = patch.dict(by_alias=False, exclude_none=True)
        self.assertEqual(d, {"system_prompt": "# Novo prompt"})

    def test_system_prompt_via_snake_case(self) -> None:
        """populate_by_name=True permite snake_case também."""
        patch = AgentPatch(system_prompt="# Novo prompt")
        d = patch.dict(by_alias=False, exclude_none=True)
        self.assertEqual(d, {"system_prompt": "# Novo prompt"})

    def test_platform_url_alias(self) -> None:
        patch = AgentPatch(platformUrl="https://web.meuplannerfinanceiro.com.br")  # type: ignore[call-arg]
        d = patch.dict(by_alias=False, exclude_none=True)
        self.assertEqual(d, {"platform_url": "https://web.meuplannerfinanceiro.com.br"})

    def test_requires_approval_alias(self) -> None:
        patch = AgentPatch(requiresApproval=True)  # type: ignore[call-arg]
        d = patch.dict(by_alias=False, exclude_none=True)
        self.assertEqual(d, {"requires_approval": True})

    def test_combined_payload_multiple_fields(self) -> None:
        """Payload típico da UI editando vários campos de uma vez."""
        patch = AgentPatch(
            systemPrompt="# Kronos governance v2",  # type: ignore[call-arg]
            tokenBudget=200_000,
            platformUrl="https://web.meuplannerfinanceiro.com.br",
        )
        d = patch.dict(by_alias=False, exclude_none=True)
        self.assertEqual(d["system_prompt"], "# Kronos governance v2")
        self.assertEqual(d["token_budget"], 200_000)
        self.assertEqual(d["platform_url"], "https://web.meuplannerfinanceiro.com.br")

    def test_partial_update_excludes_unset_fields(self) -> None:
        """Campo não enviado → None → exclude_none filtra."""
        patch = AgentPatch(systemPrompt="só prompt")  # type: ignore[call-arg]
        d = patch.dict(by_alias=False, exclude_none=True)
        self.assertEqual(set(d.keys()), {"system_prompt"})

    def test_unknown_field_silently_ignored(self) -> None:
        """extra='ignore' — campo desconhecido cai fora."""
        patch = AgentPatch(systemPrompt="x", unknownField="ignored")  # type: ignore[call-arg]
        d = patch.dict(by_alias=False, exclude_none=True)
        self.assertIn("system_prompt", d)
        self.assertNotIn("unknownField", d)
        self.assertNotIn("unknown_field", d)

    def test_empty_payload_results_in_empty_dict(self) -> None:
        """Reproduz o bug original: 0 campos válidos → dict vazio → 400 empty_patch."""
        patch = AgentPatch()
        d = patch.dict(by_alias=False, exclude_none=True)
        self.assertEqual(d, {})

    def test_existing_fields_still_work_via_aliases(self) -> None:
        """Regressão — campos pré-existentes não quebraram."""
        patch = AgentPatch(
            name="Kronos v2", role="Auditor", tokenBudget=150_000,  # type: ignore[call-arg]
            reportsToId="59b7a69e-cc53-4063-85f9-5dcc5619ac96",
        )
        d = patch.dict(by_alias=False, exclude_none=True)
        self.assertEqual(d["name"], "Kronos v2")
        self.assertEqual(d["role"], "Auditor")
        self.assertEqual(d["token_budget"], 150_000)
        self.assertEqual(d["reports_to_id"], "59b7a69e-cc53-4063-85f9-5dcc5619ac96")


if __name__ == "__main__":
    unittest.main(verbosity=2)
