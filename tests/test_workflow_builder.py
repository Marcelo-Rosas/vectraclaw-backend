"""Testes do cliente workflow-builder (src/agents/workflow_builder.py).

Fake supabase chainable — sem LLM/DB real. Prova: input-builder monta o JSON
do processo + availableOperationTypes; effect mapeia o array do LLM em
workflow_definition + workflow_steps ricos, com contagem needs_handler (path B).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.agents.workflow_builder as wb  # noqa: E402


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, store):
        self.table = table
        self.store = store
        self.filters = {}

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def insert(self, rows):
        self.store["inserts"].setdefault(self.table, []).append(rows)
        return self

    def update(self, patch):
        self.store["updates"].setdefault(self.table, []).append(patch)
        return self

    def execute(self):
        return _Resp(self.store["data"].get(self.table, lambda f: [])(self.filters))


class FakeSupabase:
    def __init__(self, data):
        self.store = {"data": data, "inserts": {}, "updates": {}}

    def table(self, name):
        return _Query(name, self.store)


def _data():
    return {
        "sipoc_processes": lambda f: [{"name": "Prospecção Outbound", "sector_id": "sec1"}],
        "sipoc_sectors": lambda f: [{"name": "Comercial"}],
        "sipoc_components": lambda f: [
            {"type": "activity", "order": 0,
             "content": {"name": "Enriquecimento de Telefone", "what": "achar mobile", "logicPattern": "SIMPLE"},
             "diagnostic_metadata": {"automationScore": 89}},
            {"type": "activity", "order": 1,
             "content": {"name": "Disparo WhatsApp", "what": "mandar template", "logicPattern": "SIMPLE"},
             "diagnostic_metadata": {"automationScore": 70}},
        ],
        "operation_types_catalog": lambda f: (
            [{"primary_agent_id": "agent-enrich", "default_specialty_slug": "enrich-phone"}]
            if f.get("id") == "enrich-phone" else
            [{"id": "enrich-phone", "description": "enriquece telefone", "default_specialty_slug": "enrich-phone",
              "primary_agent_id": "agent-enrich"}]
        ),
        "agent_specialties": lambda f: [{"id": "spec-enrich"}],
        "agent_specialty_configs": lambda f: [{"id": "cfg-enrich"}],
    }


def test_build_input_assembles_process_and_catalog():
    sb = FakeSupabase(_data())
    task = {"id": "t1", "input_json": {"source_id": "proc1"}}
    out = wb.build_input(task, sb, {})
    # remove o prefixo markdown antes do JSON
    payload = json.loads(out[out.index("{"):])
    assert payload["processName"] == "Prospecção Outbound"
    assert payload["sector"] == "Comercial"
    assert len(payload["activities"]) == 2
    assert payload["activities"][0]["automationScore"] == 89
    assert payload["availableOperationTypes"][0]["operationType"] == "enrich-phone"
    assert task["_wb"]["process_id"] == "proc1"


def test_build_input_raises_without_activities():
    data = _data()
    data["sipoc_components"] = lambda f: []
    sb = FakeSupabase(data)
    task = {"id": "t1", "input_json": {"source_id": "proc1"}}
    try:
        wb.build_input(task, sb, {})
        assert False, "deveria ter levantado"
    except ValueError as e:
        assert "sem activities" in str(e)


def test_write_steps_maps_llm_array_to_rows():
    sb = FakeSupabase(_data())
    task = {"id": "t2", "company_id": "co1", "_wb": {"process_id": "proc1"}}
    parsed = {"_list": [
        {"stepCode": "W1", "nome": "Enriquecimento de Telefone", "operationType": "enrich-phone",
         "specialtySlug": "enrich-phone", "responsavel": "agente", "slaHoras": 2,
         "fiveW2H": {"what": "achar mobile"}, "proximo": ["W2"], "logicPattern": "SIMPLE"},
        {"stepCode": "W2", "nome": "Disparo WhatsApp", "operationType": None,
         "responsavel": "agente", "slaHoras": 1, "logicPattern": "SIMPLE"},
    ]}
    res = wb.write_steps(task, sb, parsed, {"responsavel_default": "agente"})

    assert res["steps_created"] == 2
    assert res["needs_handler"] == 1  # W2 sem op_type → placeholder
    # workflow_definition criado
    assert sb.store["inserts"]["workflow_definitions"]
    # steps inseridos
    rows = sb.store["inserts"]["workflow_steps"][0]
    assert len(rows) == 2
    w1 = rows[0]
    assert w1["default_operation_type"] == "enrich-phone"
    assert w1["assigned_to_agent_id"] == "agent-enrich"
    assert w1["agent_specialty_config_id"] == "cfg-enrich"
    assert w1["five_w2h"] == {"what": "achar mobile"}
    assert w1["step_order"] == 0
    assert w1["proximo_step_codes"] == ["W2"]
    w2 = rows[1]
    assert w2["default_operation_type"] is None
    assert w2["assigned_to_agent_id"] is None
    assert w2["sipoc_meta"]["needs_handler"] is True
    # processo religado ao novo workflow
    assert sb.store["updates"]["sipoc_processes"]


def test_write_steps_raises_without_steps():
    sb = FakeSupabase(_data())
    task = {"id": "t3", "company_id": "co1", "_wb": {"process_id": "proc1"}}
    try:
        wb.write_steps(task, sb, {"foo": "bar"}, {})
        assert False, "deveria ter levantado"
    except ValueError as e:
        assert "sem steps" in str(e)
