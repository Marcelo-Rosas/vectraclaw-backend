"""Testes das folhas de prospecção (enrich-phone / outbound-wa) + spine effect-only.

Fake NAVI client chainable — sem rede. Prova: enrich reconcilia mobile;
outbound-wa é dry-run por padrão (NÃO enfileira) e só insere no send_queue com
confirm_send=true; o executor genérico pula o LLM pra effect-only.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.agents.prospect_leaves as leaves  # noqa: E402
import src.agents.specialty_generic as sg  # noqa: E402
from src.services.specialty_resolver import ResolvedSpecialty  # noqa: E402


class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, table, store):
        self.table, self.store, self.f = table, store, {}

    def select(self, *a, **k):
        return self

    def ilike(self, col, val):
        self.f["ilike"] = (col, val)
        return self

    def eq(self, col, val):
        self.f[col] = val
        return self

    def limit(self, *a, **k):
        return self

    def insert(self, row):
        self.store["inserts"].setdefault(self.table, []).append(row)
        self._inserted = row
        return self

    def update(self, patch):
        self.store["updates"].setdefault(self.table, []).append(patch)
        return self

    def execute(self):
        if getattr(self, "_inserted", None) is not None:
            return _Resp([{"id": f"new-{self.table}"}])
        return _Resp(self.store["data"].get(self.table, []))


class FakeNavi:
    def __init__(self, data=None):
        self.store = {"data": data or {}, "inserts": {}, "updates": {}}

    def table(self, name):
        return _Q(name, self.store)


def test_enrich_phone_reconciles_by_hint(monkeypatch):
    navi = FakeNavi({"contacts": [{"id": "c1", "phone_number": "+55 47 99888-7766", "name": "Arena Fit"}]})
    monkeypatch.setattr(leaves, "get_navi_client", lambda: navi)
    out = leaves.enrich_phone({}, None, {"phone": "47998887766"}, {})
    assert out["needs_enrichment"] is False
    assert out["tier"] == "A"
    assert out["navi_contact_id"] == "c1"


def test_enrich_phone_needs_enrichment_when_absent(monkeypatch):
    navi = FakeNavi({"contacts": []})
    monkeypatch.setattr(leaves, "get_navi_client", lambda: navi)
    out = leaves.enrich_phone({}, None, {"name": "Inexistente"}, {})
    assert out["needs_enrichment"] is True
    assert out["mobile"] is None


def test_outbound_wa_dry_run_does_not_enqueue(monkeypatch):
    navi = FakeNavi({"contacts": [{"id": "c1", "phone_number": "+5521975602969"}]})
    monkeypatch.setattr(leaves, "get_navi_client", lambda: navi)
    out = leaves.outbound_wa({}, None, {"to": "5521975602969"}, {})
    assert out["dry_run"] is True
    assert out["sent"] is False
    assert "send_queue" not in navi.store["inserts"]  # nada enfileirado


def test_outbound_wa_enqueues_with_confirm(monkeypatch):
    navi = FakeNavi({"contacts": [{"id": "c1", "phone_number": "+5521975602969"}]})
    monkeypatch.setattr(leaves, "get_navi_client", lambda: navi)
    out = leaves.outbound_wa(
        {"id": "t1"}, None,
        {"to": "5521975602969", "confirm_send": True, "template_params": ["Arena Fit"]}, {})
    assert out["queued"] is True
    rows = navi.store["inserts"]["send_queue"]
    assert rows and rows[0]["status"] == "pending"
    assert rows[0]["message_type"] == "template"
    assert rows[0]["contact_id"] == "c1"
    assert rows[0]["template_data"]["name"] == "vectra_prospeccao_academia"


def test_outbound_wa_requires_navi(monkeypatch):
    monkeypatch.setattr(leaves, "get_navi_client", lambda: None)
    try:
        leaves.outbound_wa({}, None, {"to": "5521975602969"}, {})
        assert False
    except RuntimeError as e:
        assert "NAVI" in str(e)


def test_generic_executor_skips_llm_for_effect_only(monkeypatch):
    # se cair no LLM, falha (effect-only não deve chamar generate_for_agent)
    async def boom(*a, **k):
        raise AssertionError("LLM não deveria ser chamado em effect-only")
    monkeypatch.setattr(sg, "generate_for_agent", boom)

    seen = {}
    sg.register_effect("leaf-x", lambda task, sb, parsed, values: seen.update(parsed=parsed) or {"summary": "feito"}, llm=False)
    try:
        spec = ResolvedSpecialty(id="leaf-x", slug="leaf-x", name="X", domain="automation",
                                 system_prompt_template="ignorado", config_schema=[])
        task = {"id": "t9", "operation_type": "leaf-x", "assigned_to_agent_id": "ag1",
                "input_json": {"k": "v"}, "_resolved_specialty": spec,
                "_resolved_config": {}, "_resolved_shared": {}}
        res = asyncio.run(sg.execute_specialty(task, supabase=None))
        assert res["status"] == "succeeded"
        assert res["output_text"] == "feito"
        assert res["output_json"]["metadata"]["mode"] == "effect_only"
        assert seen["parsed"] == {"k": "v"}
    finally:
        sg.EFFECTS.pop("leaf-x", None)
        sg.EFFECT_ONLY.discard("leaf-x")
