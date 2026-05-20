"""Smoke tests for src/services/skillforge_adapter.py — PR M Skillforge.

Roda: pytest tests/test_skillforge_adapter.py -q
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.services import skillforge_adapter as sf  # noqa: E402


class TestSkillforgeAdapterRegistry(unittest.TestCase):
    def test_ten_skills_registered(self) -> None:
        self.assertEqual(len(sf.SKILL_REGISTRY), 10)
        self.assertIn("sf-lector-documental", sf.SKILL_REGISTRY)
        self.assertIn("sf-puerta-aprobacion-humana", sf.SKILL_REGISTRY)

    def test_operation_type_prefix(self) -> None:
        self.assertTrue(sf.is_skillforge_operation("skillforge:sf-radar-anomalias"))
        self.assertFalse(sf.is_skillforge_operation("oracle-research"))
        self.assertEqual(
            sf.operation_type_for_skill("sf-radar-anomalias"),
            "skillforge:sf-radar-anomalias",
        )
        self.assertEqual(
            sf.skill_id_from_operation_type("skillforge:sf-radar-anomalias"),
            "sf-radar-anomalias",
        )


class TestSkillforgeAdapterRun(unittest.TestCase):
    def test_run_skill_unknown_id(self) -> None:
        out = sf.run_skill("sf-does-not-exist", {})
        self.assertFalse(out["ok"])
        self.assertIn("known_skills", out)

    def test_run_skill_radar_local_fallback(self) -> None:
        out = sf.run_skill(
            "sf-radar-anomalias",
            {
                "accion": "test",
                "descripcion": "unit",
                "solicitante": "pytest",
                "serie": [1.0, 1.0, 1.0, 1.0, 50.0],
                "umbral_desviaciones": 1.5,
            },
        )
        self.assertIn(out["mode"], ("skillforge", "local_fallback"))
        self.assertIn("result", out)
        self.assertEqual(out["result"]["nombre_skill"], "radar_anomalias")
        self.assertEqual(out["result"]["estado"], "ok")
        self.assertGreaterEqual(out["result"]["salida"].get("total_anomalias", 0), 1)

    def test_run_skill_lector_local_fallback(self) -> None:
        out = sf.run_skill(
            "sf-lector-documental",
            {
                "accion": "test",
                "descripcion": "unit",
                "solicitante": "pytest",
                "texto_documento": "Intro\n\nBody paragraph one.\n\nBody two.",
            },
        )
        self.assertTrue(out.get("ok") or out["result"]["estado"] == "ok")
        self.assertGreaterEqual(out["result"]["salida"].get("total_secciones", 0), 1)

    def test_run_skill_uses_package_when_available(self) -> None:
        def _fake_eval(_entrada):  # noqa: ANN001
            return {
                "nombre_skill": "radar_anomalias",
                "estado": "ok",
                "salida": {"mensaje": "from package"},
                "trazas": [],
                "advertencias": [],
            }

        fake_mod = type(
            "FakeMod",
            (),
            {"SolicitudRadarAnomalias": type("SolicitudRadarAnomalias", (), {})},
        )()

        with patch.object(sf, "_try_load_skillforge_eval", return_value=_fake_eval):
            with patch.object(sf, "_load_skill_module", return_value=fake_mod):
                with patch.object(sf, "_build_solicitud", return_value=object()):
                    out = sf.run_skill("sf-radar-anomalias", {"serie": [1, 2, 3, 4, 5]})

        self.assertTrue(out["ok"])
        self.assertEqual(out["mode"], "skillforge")
        self.assertEqual(out["result"]["salida"]["mensaje"], "from package")


class TestSkillforgeDaemonHook(unittest.TestCase):
    def test_execute_task_skillforge_branch(self) -> None:
        from src.agent_daemon import ResilientHarnessDaemon  # noqa: E402

        daemon = ResilientHarnessDaemon()
        task = {
            "id": "task-sf-1",
            "operation_type": "skillforge:sf-radar-anomalias",
            "title": "Radar test",
            "input_json": {"serie": [1.0, 1.1, 1.0, 9.0, 1.05]},
        }
        raw = daemon.execute_task(task)
        parsed = json.loads(raw)
        self.assertIn("skill_id", parsed)
        self.assertEqual(parsed["skill_id"], "sf-radar-anomalias")
        self.assertIn("result", parsed)

    def test_skillforge_disabled_env(self) -> None:
        with patch.dict("os.environ", {"SKILLFORGE_ENABLED": "0"}):
            self.assertFalse(sf.skillforge_enabled())


if __name__ == "__main__":
    unittest.main()
