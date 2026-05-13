"""Unit tests for src/services/specialty_resolver.py — VEC-XXX PR1.

Roda: pytest tests/test_specialty_resolver.py -q
   ou: python tests/test_specialty_resolver.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.services.specialty_resolver import (  # noqa: E402
    ResolvedSpecialty,
    render_system_prompt,
    resolve_config,
    resolve_specialty,
    resolve_value,
)


# ════════════════════════════════════════════════════════════════════════════
# FakeSupabase — mínimo necessário para os 2 endpoints lidos pelo resolver:
#   agent_specialty_configs.select(...).eq("agent_id", X).execute()
#   agent_specialty_configs.select(...).eq("agent_id", X).eq("specialty_id", Y)
#                          [.eq("company_id", Z)].limit(1).execute()
# ════════════════════════════════════════════════════════════════════════════


class _FakeResult:
    def __init__(self, data: Any) -> None:
        self.data = data


class _FakeQuery:
    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = rows
        self._preds: List[tuple] = []
        self._limit: Optional[int] = None

    def select(self, _cols: str = "*") -> "_FakeQuery":
        return self

    def eq(self, col: str, val: Any) -> "_FakeQuery":
        self._preds.append((col, val))
        return self

    def limit(self, n: int) -> "_FakeQuery":
        self._limit = n
        return self

    def execute(self) -> _FakeResult:
        filtered = [
            r
            for r in self._rows
            if all(r.get(col) == val for col, val in self._preds)
        ]
        if self._limit is not None:
            filtered = filtered[: self._limit]
        return _FakeResult(filtered)


class FakeSupabase:
    """Minimal fake — only the two tables the resolver touches."""

    def __init__(self) -> None:
        self.specialties: List[Dict[str, Any]] = []
        self.configs: List[Dict[str, Any]] = []
        self._raise_on_table: Optional[str] = None

    def table(self, name: str):  # noqa: ANN201
        if self._raise_on_table == name:
            raise RuntimeError("simulated postgrest failure")
        if name == "agent_specialty_configs":
            # Enriquece com join de agent_specialties para o resolve_specialty
            joined = []
            for cfg in self.configs:
                spec = next(
                    (s for s in self.specialties if s["id"] == cfg["specialty_id"]),
                    None,
                )
                row = dict(cfg)
                row["agent_specialties"] = spec  # dict (PostgREST 1:1 join)
                joined.append(row)
            return _FakeQuery(joined)
        raise AssertionError(f"FakeSupabase: unexpected table {name!r}")


# ════════════════════════════════════════════════════════════════════════════
# resolve_specialty
# ════════════════════════════════════════════════════════════════════════════


class ResolveSpecialtyTests(unittest.TestCase):
    def _setup_kronos(self) -> FakeSupabase:
        fake = FakeSupabase()
        fake.specialties = [
            {
                "id": "spec-fin-audit",
                "slug": "financial-audit",
                "name": "Financial Audit & Reconciliation",
                "domain": "financial",
                "system_prompt_template": "Você é o auditor {{ task.title }}.",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "ofx_path": {"type": "string", "default": "/tmp/default.ofx"},
                    },
                },
            },
            {
                "id": "spec-planner-import",
                "slug": "planner-import-ofx",
                "name": "Upload OFX no Meu Planner",
                "domain": "financial",
                "system_prompt_template": "",
                "config_schema": {"type": "object", "properties": {}},
            },
        ]
        fake.configs = [
            {
                "company_id": "vectra-cargo",
                "agent_id": "kronos",
                "specialty_id": "spec-fin-audit",
                "values": {"ofx_path": "/data/abril.ofx"},
            },
            {
                "company_id": "vectra-cargo",
                "agent_id": "kronos",
                "specialty_id": "spec-planner-import",
                "values": {},
            },
        ]
        return fake

    def test_returns_none_when_client_missing(self) -> None:
        self.assertIsNone(resolve_specialty(None, "kronos", "financial-audit"))

    def test_returns_none_when_agent_id_missing(self) -> None:
        self.assertIsNone(resolve_specialty(self._setup_kronos(), None, "financial-audit"))

    def test_returns_none_when_operation_type_missing(self) -> None:
        self.assertIsNone(resolve_specialty(self._setup_kronos(), "kronos", ""))

    def test_matches_by_slug(self) -> None:
        fake = self._setup_kronos()
        spec = resolve_specialty(fake, "kronos", "planner-import-ofx")
        self.assertIsNotNone(spec)
        assert spec is not None  # mypy
        self.assertEqual(spec.id, "spec-planner-import")
        self.assertEqual(spec.slug, "planner-import-ofx")

    def test_matches_by_id(self) -> None:
        fake = self._setup_kronos()
        spec = resolve_specialty(fake, "kronos", "spec-fin-audit")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.slug, "financial-audit")

    def test_returns_none_on_no_match(self) -> None:
        fake = self._setup_kronos()
        self.assertIsNone(resolve_specialty(fake, "kronos", "nonexistent-op"))

    def test_handles_join_as_list(self) -> None:
        """PostgREST pode devolver join como list em algumas inferências."""
        fake = self._setup_kronos()
        # Override: força join como lista
        joined_rows = []
        for cfg in fake.configs:
            spec = next(
                (s for s in fake.specialties if s["id"] == cfg["specialty_id"]),
                None,
            )
            row = dict(cfg)
            row["agent_specialties"] = [spec] if spec else []
            joined_rows.append(row)

        class _ListJoinFake:
            def table(self, _name: str):  # noqa: ANN201
                return _FakeQuery(joined_rows)

        spec = resolve_specialty(_ListJoinFake(), "kronos", "financial-audit")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.slug, "financial-audit")

    def test_returns_none_on_exception(self) -> None:
        fake = self._setup_kronos()
        fake._raise_on_table = "agent_specialty_configs"
        self.assertIsNone(resolve_specialty(fake, "kronos", "financial-audit"))

    def test_specialty_defaults_list_format(self) -> None:
        """Convenção VectraClaw: config_schema é lista de field descriptors."""
        spec = ResolvedSpecialty(
            id="x",
            slug="x",
            name="x",
            domain="x",
            system_prompt_template="",
            config_schema=[
                {"key": "ofx_path", "type": "text", "default": "/tmp/a.ofx"},
                {"key": "recipient", "type": "text"},  # sem default
                {"key": "categorize_after_import", "type": "boolean", "default": True},
                {"label": "sem key — ignorado"},  # sem key, deve ser pulado
            ],
        )
        self.assertEqual(
            spec.defaults,
            {"ofx_path": "/tmp/a.ofx", "categorize_after_import": True},
        )

    def test_specialty_defaults_json_schema_dict_backcompat(self) -> None:
        """Formato JSON Schema (legacy) também é aceito."""
        spec = ResolvedSpecialty(
            id="x",
            slug="x",
            name="x",
            domain="x",
            system_prompt_template="",
            config_schema={
                "type": "object",
                "properties": {
                    "ofx_path": {"type": "string", "default": "/tmp/a.ofx"},
                    "recipient": {"type": "string"},
                },
            },
        )
        self.assertEqual(spec.defaults, {"ofx_path": "/tmp/a.ofx"})

    def test_specialty_defaults_empty_when_no_schema(self) -> None:
        spec = ResolvedSpecialty(
            id="x", slug="x", name="x", domain="x", system_prompt_template=""
        )
        self.assertEqual(spec.defaults, {})


# ════════════════════════════════════════════════════════════════════════════
# resolve_config
# ════════════════════════════════════════════════════════════════════════════


class ResolveConfigTests(unittest.TestCase):
    def _setup(self) -> FakeSupabase:
        fake = FakeSupabase()
        fake.configs = [
            {
                "company_id": "vectra-cargo",
                "agent_id": "kronos",
                "specialty_id": "spec-fin-audit",
                "values": {"ofx_path": "/data/abril.ofx", "recipient": "a@b.com"},
            },
            {
                "company_id": "outra-empresa",
                "agent_id": "kronos",
                "specialty_id": "spec-fin-audit",
                "values": {"ofx_path": "/other/maio.ofx"},
            },
        ]
        return fake

    def test_returns_empty_when_client_missing(self) -> None:
        self.assertEqual(resolve_config(None, "kronos", "spec-x"), {})

    def test_returns_empty_when_args_missing(self) -> None:
        fake = self._setup()
        self.assertEqual(resolve_config(fake, None, "spec-x"), {})
        self.assertEqual(resolve_config(fake, "kronos", None), {})

    def test_returns_values_for_pair(self) -> None:
        fake = self._setup()
        # Sem company_id, pega a primeira (vectra-cargo no fake)
        out = resolve_config(fake, "kronos", "spec-fin-audit")
        self.assertEqual(out["ofx_path"], "/data/abril.ofx")
        self.assertEqual(out["recipient"], "a@b.com")

    def test_filters_by_company_id(self) -> None:
        fake = self._setup()
        out = resolve_config(fake, "kronos", "spec-fin-audit", company_id="outra-empresa")
        self.assertEqual(out["ofx_path"], "/other/maio.ofx")
        self.assertNotIn("recipient", out)

    def test_returns_empty_on_no_match(self) -> None:
        fake = self._setup()
        self.assertEqual(resolve_config(fake, "kronos", "spec-unknown"), {})

    def test_returns_empty_on_exception(self) -> None:
        fake = self._setup()
        fake._raise_on_table = "agent_specialty_configs"
        self.assertEqual(resolve_config(fake, "kronos", "spec-fin-audit"), {})


# ════════════════════════════════════════════════════════════════════════════
# render_system_prompt
# ════════════════════════════════════════════════════════════════════════════


class RenderSystemPromptTests(unittest.TestCase):
    def test_empty_template(self) -> None:
        self.assertEqual(render_system_prompt(""), "")
        self.assertEqual(render_system_prompt(None), "")

    def test_template_without_placeholders(self) -> None:
        out = render_system_prompt("Hello world", {"k": "v"})
        self.assertEqual(out, "Hello world")

    def test_no_context_returns_template_unchanged(self) -> None:
        # Sem values nem task, retorna o template como veio (placeholder não resolvido)
        self.assertEqual(render_system_prompt("Hi {{ name }}!"), "Hi {{ name }}!")

    def test_simple_values_substitution(self) -> None:
        out = render_system_prompt("Hi {{ name }}!", {"name": "Marcelo"})
        self.assertEqual(out, "Hi Marcelo!")

    def test_handles_whitespace_in_placeholder(self) -> None:
        out = render_system_prompt("X={{key}} Y={{  key  }}", {"key": "v"})
        self.assertEqual(out, "X=v Y=v")

    def test_task_field_substitution(self) -> None:
        out = render_system_prompt(
            "Task: {{ task.title }}", task={"title": "Auditar abril"}
        )
        self.assertEqual(out, "Task: Auditar abril")

    def test_nested_task_input_json(self) -> None:
        out = render_system_prompt(
            "OFX: {{ task.input_json.ofx_path }}",
            task={"input_json": {"ofx_path": "/data/a.ofx"}},
        )
        self.assertEqual(out, "OFX: /data/a.ofx")

    def test_missing_placeholder_becomes_empty(self) -> None:
        out = render_system_prompt("A={{ a }} B={{ b }}", {"a": "1"})
        self.assertEqual(out, "A=1 B=")

    def test_non_string_value_coerced(self) -> None:
        out = render_system_prompt("N={{ n }} B={{ b }}", {"n": 42, "b": True})
        self.assertEqual(out, "N=42 B=True")

    def test_combined_values_and_task(self) -> None:
        out = render_system_prompt(
            "{{ name }} executa {{ task.operation_type }}",
            values={"name": "Kronos"},
            task={"operation_type": "planner-import-ofx"},
        )
        self.assertEqual(out, "Kronos executa planner-import-ofx")


# ════════════════════════════════════════════════════════════════════════════
# resolve_value (cadeia de precedência)
# ════════════════════════════════════════════════════════════════════════════


class ResolveValueTests(unittest.TestCase):
    def test_payload_wins(self) -> None:
        out = resolve_value(
            "ofx_path",
            payload={"ofx_path": "/from-payload.ofx"},
            config_values={"ofx_path": "/from-config.ofx"},
            specialty_defaults={"ofx_path": "/from-default.ofx"},
            env_default="/from-env.ofx",
        )
        self.assertEqual(out, "/from-payload.ofx")

    def test_config_wins_when_no_payload(self) -> None:
        out = resolve_value(
            "ofx_path",
            payload={},
            config_values={"ofx_path": "/from-config.ofx"},
            specialty_defaults={"ofx_path": "/from-default.ofx"},
            env_default="/from-env.ofx",
        )
        self.assertEqual(out, "/from-config.ofx")

    def test_specialty_default_wins_when_no_config(self) -> None:
        out = resolve_value(
            "ofx_path",
            config_values={},
            specialty_defaults={"ofx_path": "/from-default.ofx"},
            env_default="/from-env.ofx",
        )
        self.assertEqual(out, "/from-default.ofx")

    def test_env_default_when_nothing_else(self) -> None:
        out = resolve_value("ofx_path", env_default="/from-env.ofx")
        self.assertEqual(out, "/from-env.ofx")

    def test_returns_none_when_nothing(self) -> None:
        self.assertIsNone(resolve_value("ofx_path"))

    def test_none_in_source_skips_to_next(self) -> None:
        # config_values["k"] = None deve cair pro specialty_defaults
        out = resolve_value(
            "k",
            config_values={"k": None},
            specialty_defaults={"k": "from-default"},
        )
        self.assertEqual(out, "from-default")

    def test_falsy_zero_is_valid(self) -> None:
        # 0 não é None, então conta como preenchido
        out = resolve_value(
            "n",
            config_values={"n": 0},
            specialty_defaults={"n": 99},
        )
        self.assertEqual(out, 0)

    def test_falsy_empty_string_is_valid(self) -> None:
        out = resolve_value(
            "s",
            config_values={"s": ""},
            specialty_defaults={"s": "fallback"},
        )
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
