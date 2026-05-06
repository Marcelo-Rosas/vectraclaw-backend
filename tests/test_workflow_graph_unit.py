"""
Unit tests for workflow_graph (networkx) — sem DB.

Roda: python tests/test_workflow_graph_unit.py
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import unittest

from src.services.workflow_graph import (
    build_graph,
    critical_path,
    topological_generations_with_meta,
    validate_workflow_steps,
)


class TestWorkflowGraph(unittest.TestCase):
    def test_detects_cycle(self):
        steps = [
            {"step_code": "a", "proximo": ["b"], "sla_horas": 1},
            {"step_code": "b", "proximo": ["a"], "sla_horas": 1},
        ]
        errs = validate_workflow_steps(steps)
        self.assertTrue(any("cycle" in e.lower() for e in errs))

    def test_unknown_proximo_target(self):
        steps = [
            {"step_code": "a", "proximo": ["ghost"]},
        ]
        errs = validate_workflow_steps(steps)
        self.assertTrue(any("unknown proximo" in e for e in errs))

    def test_parallel_generations(self):
        steps = [
            {"step_code": "a", "proximo": ["c"], "sla_horas": 1},
            {"step_code": "b", "proximo": ["c"], "sla_horas": 2},
            {"step_code": "c", "proximo": [], "sla_horas": 1},
        ]
        errs = validate_workflow_steps(steps)
        self.assertEqual(errs, [])
        G = build_graph(steps)
        gens = topological_generations_with_meta(G)
        self.assertEqual(set(gens[0]), {"a", "b"})
        self.assertEqual(gens[1], ["c"])

    def test_critical_path_weighted(self):
        steps = [
            {"step_code": "a", "proximo": ["b", "c"], "sla_horas": 1},
            {"step_code": "b", "proximo": ["d"], "sla_horas": 10},
            {"step_code": "c", "proximo": ["d"], "sla_horas": 1},
            {"step_code": "d", "proximo": [], "sla_horas": 1},
        ]
        self.assertEqual(validate_workflow_steps(steps), [])
        G = build_graph(steps)
        path, total = critical_path(G)
        self.assertEqual(path, ["a", "b", "d"])
        self.assertEqual(total, 12)


if __name__ == "__main__":
    unittest.main()
