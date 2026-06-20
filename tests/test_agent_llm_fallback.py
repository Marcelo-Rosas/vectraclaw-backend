"""Testa o fallback gemini seguro de generate_for_agent.

Bug latente: provider sem branch (ex.: nous_hermes) caía no gemini usando
cfg.model de outro provider ('claude-sonnet-4-5') → modelo inválido. O fix usa
fallback_model/DEFAULT_MODEL quando o provider não é google.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.services.agent_llm as al  # noqa: E402


def _patch_gemini(monkeypatch, captured):
    async def fake_gemini(model, prompt, *, system_instruction=None, response_mime_type=None):
        captured["model"] = model
        return "ok", {"provider": "google", "model": model}
    monkeypatch.setattr("src.services.gemini_client.generate", fake_gemini)


def test_unknown_provider_does_not_pass_foreign_model_to_gemini(monkeypatch):
    monkeypatch.setattr(al, "_resolve_agent_adapter", lambda aid: {
        "provider": "nous_hermes", "model": "claude-sonnet-4-5", "api_key": None, "base_url": None})
    captured = {}
    _patch_gemini(monkeypatch, captured)
    text, _ = asyncio.run(al.generate_for_agent("ag", "hi", fallback_model="gemini-2.0-flash"))
    assert text == "ok"
    assert captured["model"] == "gemini-2.0-flash"  # NÃO 'claude-sonnet-4-5'


def test_unknown_provider_without_fallback_uses_default(monkeypatch):
    monkeypatch.setattr(al, "_resolve_agent_adapter", lambda aid: {
        "provider": "nous_hermes", "model": "claude-sonnet-4-5", "api_key": None, "base_url": None})
    captured = {}
    _patch_gemini(monkeypatch, captured)
    asyncio.run(al.generate_for_agent("ag", "hi"))  # sem fallback_model
    from src.services.gemini_client import DEFAULT_MODEL
    assert captured["model"] == DEFAULT_MODEL
    assert captured["model"] != "claude-sonnet-4-5"


def test_google_provider_keeps_its_model(monkeypatch):
    monkeypatch.setattr(al, "_resolve_agent_adapter", lambda aid: {
        "provider": "google", "model": "gemini-2.5-flash", "api_key": None, "base_url": None})
    captured = {}
    _patch_gemini(monkeypatch, captured)
    asyncio.run(al.generate_for_agent("ag", "hi"))
    assert captured["model"] == "gemini-2.5-flash"  # provider google confia em cfg.model
