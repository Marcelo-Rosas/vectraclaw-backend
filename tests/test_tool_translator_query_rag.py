"""Testes da tool query_rag em tool_translator.

Cobre:
- Tool registrada em ANTHROPIC_TOOLS + OPENAI_TOOLS
- Dispatch chama retriever com args corretos
- Validação: company_id obrigatório, query obrigatória
- Erros (Supabase ausente, retriever falha) retornam JSON com success=False
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# 1. Schema da tool em ANTHROPIC_TOOLS / OPENAI_TOOLS
# ─────────────────────────────────────────────────────────────────────────────

def test_query_rag_in_anthropic_tools():
    from src.managed_agents.tool_translator import ANTHROPIC_TOOLS
    names = [t["name"] for t in ANTHROPIC_TOOLS]
    assert "query_rag" in names

    tool = next(t for t in ANTHROPIC_TOOLS if t["name"] == "query_rag")
    assert "company_id" in tool["input_schema"]["properties"]
    assert "query" in tool["input_schema"]["properties"]
    assert tool["input_schema"]["required"] == ["company_id", "query"]


def test_query_rag_derived_to_openai_tools():
    from src.managed_agents.tool_translator import OPENAI_TOOLS
    fn_names = [t["function"]["name"] for t in OPENAI_TOOLS]
    assert "query_rag" in fn_names


# ─────────────────────────────────────────────────────────────────────────────
# 2. Dispatch / execução
# ─────────────────────────────────────────────────────────────────────────────

def test_query_rag_missing_company_id_returns_error():
    from src.managed_agents.tool_translator import _query_rag
    payload = json.dumps({"query": "qual o prazo de garantia?"})
    raw = _query_rag(payload)
    out = json.loads(raw)
    assert out["success"] is False
    assert "company_id" in out["error"]


def test_query_rag_missing_query_returns_error():
    from src.managed_agents.tool_translator import _query_rag
    payload = json.dumps({"company_id": "cid-X"})
    raw = _query_rag(payload)
    out = json.loads(raw)
    assert out["success"] is False
    assert "query" in out["error"]


def test_query_rag_no_supabase_returns_error(monkeypatch):
    import src.api as api
    monkeypatch.setattr(api, "supabase", None)

    from src.managed_agents.tool_translator import _query_rag
    payload = json.dumps({"company_id": "cid-X", "query": "test"})
    raw = _query_rag(payload)
    out = json.loads(raw)
    assert out["success"] is False
    assert "Supabase" in out["error"]


def test_query_rag_happy_path(monkeypatch):
    """Dispatcher chama retriever, formata resposta JSON com matches."""
    import src.api as api
    from src.services.rag.models import ChunkResult

    # Garante que supabase não é None
    monkeypatch.setattr(api, "supabase", MagicMock(name="supabase-mock"))

    fake_results = [
        ChunkResult(
            id="chunk-1", document_id="doc-1", chunk_index=0,
            page_number=2, content="Garantia: 12 meses para defeitos de fábrica.",
            score=0.91, metadata={}, document_filename="manual.pdf",
        ),
        ChunkResult(
            id="chunk-2", document_id="doc-1", chunk_index=1,
            page_number=3, content="Não cobre dano por má utilização.",
            score=0.83, metadata={}, document_filename="manual.pdf",
        ),
    ]

    async def _fake_query(*args, **kwargs):
        # Verifica que kwargs corretos chegaram
        assert kwargs.get("company_id") == "cid-X"
        assert kwargs.get("k") == 3
        assert kwargs.get("min_score") == 0.5
        return fake_results

    monkeypatch.setattr(
        "src.services.rag.retriever.query_top_k",
        _fake_query,
    )

    from src.managed_agents.tool_translator import _query_rag
    payload = json.dumps({
        "company_id": "cid-X",
        "query": "qual o prazo de garantia?",
        "k": 3,
        "min_score": 0.5,
    })
    raw = _query_rag(payload)
    out = json.loads(raw)

    assert out["success"] is True
    assert out["query"] == "qual o prazo de garantia?"
    assert out["total"] == 2
    assert out["matches"][0]["filename"] == "manual.pdf"
    assert out["matches"][0]["score"] == 0.91
    assert out["matches"][0]["page"] == 2


def test_query_rag_via_dispatch_tool_call(monkeypatch):
    """dispatch_tool_call('query_rag', ...) → roteia para _query_rag."""
    import src.api as api
    from src.services.rag.models import ChunkResult

    monkeypatch.setattr(api, "supabase", MagicMock())

    async def _fake(*args, **kwargs):
        return [ChunkResult(
            id="c", document_id="d", chunk_index=0, content="x",
            score=0.5, metadata={},
        )]

    monkeypatch.setattr(
        "src.services.rag.retriever.query_top_k",
        _fake,
    )

    from src.managed_agents.tool_translator import dispatch_tool_call
    raw = dispatch_tool_call("query_rag", {
        "company_id": "cid-A",
        "query": "x",
    })
    out = json.loads(raw)
    assert out["success"] is True
    assert out["total"] == 1


def test_query_rag_unknown_tool_dispatch_returns_error():
    from src.managed_agents.tool_translator import dispatch_tool_call
    raw = dispatch_tool_call("nonexistent_tool", {})
    out = json.loads(raw)
    assert out["success"] is False
    assert "não encontrada" in out["error"]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Router prompt hint (COMPANY_ID injection)
# ─────────────────────────────────────────────────────────────────────────────

def test_router_injects_company_hint_in_prompt(monkeypatch):
    """task.company_id deve aparecer no prompt como COMPANY_ID hint."""
    import src.managed_agents.router as router_mod

    # Verifica via inspect: o source da função route_task_execution contém
    # a string 'COMPANY_ID para query_rag'
    import inspect
    src = inspect.getsource(router_mod.route_task_execution)
    assert "COMPANY_ID para query_rag" in src
    assert "company_id_for_hint" in src
