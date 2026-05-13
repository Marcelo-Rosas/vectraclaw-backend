"""Unit tests for ResilientHarnessDaemon._populate_resolved_specialty — VEC-XXX PR3.

O hook resolve specialty + config no início de `execute_task` e anexa em
`task["_resolved_specialty"]` / `task["_resolved_config"]`. Handlers que
ignoram esses campos continuam funcionando — back-compat 100%.

Roda: pytest tests/test_agent_daemon_specialty_hook.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.agent_daemon import ResilientHarnessDaemon  # noqa: E402
from src.services.specialty_resolver import ResolvedSpecialty  # noqa: E402


# ════════════════════════════════════════════════════════════════════════════
# FakeSupabase — só os endpoints do resolver
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
        out = [
            r
            for r in self._rows
            if all(r.get(c) == v for c, v in self._preds)
        ]
        if self._limit is not None:
            out = out[: self._limit]
        return _FakeResult(out)


class FakeSupabase:
    def __init__(self) -> None:
        self.specialties: List[Dict[str, Any]] = []
        self.configs: List[Dict[str, Any]] = []
        self.fail_on_table: Optional[str] = None

    def table(self, name: str):  # noqa: ANN201
        if self.fail_on_table == name:
            raise RuntimeError("simulated postgrest failure")
        if name == "agent_specialty_configs":
            joined = []
            for cfg in self.configs:
                spec = next(
                    (s for s in self.specialties if s["id"] == cfg["specialty_id"]),
                    None,
                )
                joined.append({**cfg, "agent_specialties": spec})
            return _FakeQuery(joined)
        raise AssertionError(f"unexpected table {name!r}")


# ════════════════════════════════════════════════════════════════════════════
# Daemon helper — instancia sem disparar lock/load_agent_config
# ════════════════════════════════════════════════════════════════════════════


def _make_daemon(
    agent_id: str = "kronos-uuid",
    company_id: Optional[str] = "vectra-cargo",
) -> ResilientHarnessDaemon:
    """Instancia daemon com defaults seguros — sem tocar Supabase real."""
    with patch.dict(
        "os.environ",
        {"AGENT_ID": agent_id, "DAEMON_POLLING_INTERVAL_SECONDS": "5"},
        clear=False,
    ):
        d = ResilientHarnessDaemon()
    d._agent_config = {"company_id": company_id} if company_id else {}
    return d


def _seed_kronos_planner(fake: FakeSupabase) -> None:
    fake.specialties = [
        {
            "id": "spec-planner-import",
            "slug": "planner-import-ofx",
            "name": "Upload OFX no Meu Planner",
            "domain": "financial",
            "system_prompt_template": "",
            "config_schema": {
                "type": "object",
                "properties": {
                    "ofx_path": {"type": "string", "default": "/tmp/x.ofx"},
                    "downloads_dir": {"type": "string"},
                },
            },
        },
        {
            "id": "spec-fin-audit",
            "slug": "financial-audit",
            "name": "Financial Audit",
            "domain": "financial",
            "system_prompt_template": "Auditor",
            "config_schema": {},
        },
    ]
    fake.configs = [
        {
            "company_id": "vectra-cargo",
            "agent_id": "kronos-uuid",
            "specialty_id": "spec-planner-import",
            "values": {"ofx_path": "/data/abril.ofx", "downloads_dir": "/downloads"},
        },
        {
            "company_id": "vectra-cargo",
            "agent_id": "kronos-uuid",
            "specialty_id": "spec-fin-audit",
            "values": {},
        },
    ]


# ════════════════════════════════════════════════════════════════════════════
# Tests
# ════════════════════════════════════════════════════════════════════════════


class PopulateResolvedSpecialtyTests(unittest.TestCase):
    def test_populates_resolved_specialty_and_config_on_match(self) -> None:
        fake = FakeSupabase()
        _seed_kronos_planner(fake)
        d = _make_daemon()

        with patch.object(d, "_get_supabase", return_value=fake):
            task = {
                "id": "task-1",
                "operation_type": "planner-import-ofx",
                "company_id": "vectra-cargo",
            }
            d._populate_resolved_specialty(task)

        spec = task.get("_resolved_specialty")
        self.assertIsInstance(spec, ResolvedSpecialty)
        assert isinstance(spec, ResolvedSpecialty)  # narrowing
        self.assertEqual(spec.slug, "planner-import-ofx")

        cfg = task.get("_resolved_config")
        self.assertEqual(cfg, {"ofx_path": "/data/abril.ofx", "downloads_dir": "/downloads"})

    def test_noop_when_no_specialty_matches(self) -> None:
        fake = FakeSupabase()
        _seed_kronos_planner(fake)
        d = _make_daemon()

        with patch.object(d, "_get_supabase", return_value=fake):
            task = {"id": "t", "operation_type": "unknown-op"}
            d._populate_resolved_specialty(task)

        self.assertNotIn("_resolved_specialty", task)
        self.assertNotIn("_resolved_config", task)

    def test_noop_when_client_unavailable(self) -> None:
        d = _make_daemon()
        with patch.object(d, "_get_supabase", return_value=None):
            task = {"id": "t", "operation_type": "planner-import-ofx"}
            d._populate_resolved_specialty(task)

        self.assertNotIn("_resolved_specialty", task)

    def test_noop_when_agent_id_missing(self) -> None:
        d = _make_daemon(agent_id="")
        d.agent_id = None  # type: ignore[assignment]
        with patch.object(d, "_get_supabase", return_value=FakeSupabase()):
            task = {"id": "t", "operation_type": "planner-import-ofx"}
            d._populate_resolved_specialty(task)

        self.assertNotIn("_resolved_specialty", task)

    def test_noop_when_operation_type_missing(self) -> None:
        d = _make_daemon()
        fake = FakeSupabase()
        _seed_kronos_planner(fake)
        with patch.object(d, "_get_supabase", return_value=fake):
            task: Dict[str, Any] = {"id": "t"}  # sem operation_type
            d._populate_resolved_specialty(task)

        self.assertNotIn("_resolved_specialty", task)

    def test_silent_failure_on_postgrest_error(self) -> None:
        """Falha do resolver → hook devolve sem mutar task. Handler usa fallback."""
        fake = FakeSupabase()
        _seed_kronos_planner(fake)
        fake.fail_on_table = "agent_specialty_configs"
        d = _make_daemon()

        with patch.object(d, "_get_supabase", return_value=fake):
            task = {"id": "t", "operation_type": "planner-import-ofx"}
            d._populate_resolved_specialty(task)

        # resolver retorna None silencioso → hook não popula
        self.assertNotIn("_resolved_specialty", task)
        self.assertNotIn("_resolved_config", task)

    def test_company_id_fallback_from_agent_config(self) -> None:
        """Quando task.company_id está ausente, usa _agent_config.company_id."""
        fake = FakeSupabase()
        _seed_kronos_planner(fake)
        d = _make_daemon(company_id="vectra-cargo")

        with patch.object(d, "_get_supabase", return_value=fake):
            task: Dict[str, Any] = {
                "id": "t",
                "operation_type": "planner-import-ofx",
                # sem company_id
            }
            d._populate_resolved_specialty(task)

        # se cair company_id errado, resolve_config não acharia a row
        self.assertEqual(
            task["_resolved_config"]["ofx_path"], "/data/abril.ofx"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
