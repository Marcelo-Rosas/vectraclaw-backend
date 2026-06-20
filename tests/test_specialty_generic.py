"""Testes do executor genérico de specialty (src/agents/specialty_generic.py).

Mocka generate_for_agent — não chama LLM real. Prova: render do
system_prompt_template com precedência de config, chamada provider-agnostic,
hooks input/effect e guards de erro.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.specialty_resolver import ResolvedSpecialty  # noqa: E402
import src.agents.specialty_generic as sg  # noqa: E402


def _spec(template, slug="demo", config_schema=None):
    return ResolvedSpecialty(
        id="spec-demo", slug=slug, name="Demo", domain="automation",
        system_prompt_template=template, config_schema=config_schema or [],
    )


def test_renders_template_and_calls_llm(monkeypatch):
    captured = {}

    async def fake_gen(agent_id, prompt, *, system_instruction=None,
                       response_mime_type=None, fallback_model=None):
        captured.update(agent_id=agent_id, system=system_instruction,
                        prompt=prompt, mime=response_mime_type)
        return "resposta do modelo", {"provider": "groq", "model": "x"}

    monkeypatch.setattr(sg, "generate_for_agent", fake_gen)

    spec = _spec("Você é {{AGENT_NAME}}, domínio {{DOMAIN}}. SLA {{sla}}h.",
                 config_schema=[{"key": "sla", "default": 24}])
    task = {"id": "t1", "operation_type": "demo", "assigned_to_agent_id": "ag1",
            "title": "Faz X", "description": "detalhe", "input_json": {"foo": 1},
            "_resolved_specialty": spec, "_resolved_config": {}, "_resolved_shared": {}}

    res = asyncio.run(sg.execute_specialty(task, supabase=None))
    assert res["status"] == "succeeded"
    assert res["output_text"] == "resposta do modelo"
    assert "Demo" in captured["system"]
    assert "SLA 24h" in captured["system"]
    assert captured["mime"] is None  # sem effect → modo texto
    assert captured["agent_id"] == "ag1"


def test_config_value_overrides_default(monkeypatch):
    captured = {}

    async def fake_gen(agent_id, prompt, *, system_instruction=None,
                       response_mime_type=None, fallback_model=None):
        captured["system"] = system_instruction
        return "ok", {}

    monkeypatch.setattr(sg, "generate_for_agent", fake_gen)
    spec = _spec("SLA {{sla}}h", config_schema=[{"key": "sla", "default": 24}])
    task = {"id": "t1b", "operation_type": "demo", "assigned_to_agent_id": "ag1",
            "_resolved_specialty": spec, "_resolved_config": {"sla": 8},
            "_resolved_shared": {}}
    asyncio.run(sg.execute_specialty(task, supabase=None))
    assert "SLA 8h" in captured["system"]  # config vence default


def test_effect_hook_parses_json_and_summarizes(monkeypatch):
    async def fake_gen(agent_id, prompt, *, system_instruction=None,
                       response_mime_type=None, fallback_model=None):
        assert response_mime_type == "application/json"  # effect força JSON
        return '{"steps": [{"name": "A"}]}', {"provider": "gemini"}

    monkeypatch.setattr(sg, "generate_for_agent", fake_gen)
    seen = {}

    def effect(task, supabase, parsed, values):
        seen["parsed"] = parsed
        return {"summary": f"{len(parsed['steps'])} steps escritos"}

    sg.register_effect("with-effect", effect)
    try:
        spec = _spec("gere steps", slug="with-effect")
        task = {"id": "t2", "operation_type": "with-effect", "assigned_to_agent_id": "ag1",
                "title": "build", "_resolved_specialty": spec,
                "_resolved_config": {}, "_resolved_shared": {}}
        res = asyncio.run(sg.execute_specialty(task, supabase=None))
        assert res["status"] == "succeeded"
        assert res["output_text"] == "1 steps escritos"
        assert seen["parsed"] == {"steps": [{"name": "A"}]}
        assert res["output_json"]["effect"]["summary"] == "1 steps escritos"
    finally:
        sg.EFFECTS.pop("with-effect", None)


def test_input_builder_injects_context(monkeypatch):
    captured = {}

    async def fake_gen(agent_id, prompt, *, system_instruction=None,
                       response_mime_type=None, fallback_model=None):
        captured["prompt"] = prompt
        return "ok", {}

    monkeypatch.setattr(sg, "generate_for_agent", fake_gen)
    sg.register_input_builder("with-input", lambda task, sb, values: "CONTEXTO_EXTRA_SIPOC")
    try:
        spec = _spec("prompt", slug="with-input")
        task = {"id": "t4", "operation_type": "with-input", "assigned_to_agent_id": "ag1",
                "title": "x", "_resolved_specialty": spec,
                "_resolved_config": {}, "_resolved_shared": {}}
        asyncio.run(sg.execute_specialty(task, supabase=None))
        assert "CONTEXTO_EXTRA_SIPOC" in captured["prompt"]
    finally:
        sg.INPUT_BUILDERS.pop("with-input", None)


def test_errors_without_template():
    spec = _spec("")
    task = {"id": "t3", "operation_type": "x", "assigned_to_agent_id": "ag1",
            "_resolved_specialty": spec}
    res = asyncio.run(sg.execute_specialty(task, supabase=None))
    assert res["status"] == "error"
    assert res["output_json"]["error"]["code"] == "no_specialty_template"


def test_errors_without_agent():
    spec = _spec("template ok")
    task = {"id": "t5", "operation_type": "x", "assigned_to_agent_id": None,
            "_resolved_specialty": spec}
    res = asyncio.run(sg.execute_specialty(task, supabase=None))
    assert res["status"] == "error"
    assert res["output_json"]["error"]["code"] == "no_agent"
