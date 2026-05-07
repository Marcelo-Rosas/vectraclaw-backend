"""Testes do retriever. Mocks de embedder + supabase RPC."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_query_top_k_calls_rpc_with_correct_args():
    from src.services.rag.retriever import query_top_k

    embedder = MagicMock()
    embedder.embed_one = AsyncMock(return_value=[0.1] * 1536)

    sb = MagicMock()
    rpc_call = MagicMock()
    rpc_call.execute.return_value = MagicMock(data=[
        {
            "id": "chunk-1", "document_id": "doc-1", "chunk_index": 0,
            "page_number": 1, "content": "trecho relevante",
            "score": 0.92, "metadata": {}, "document_filename": "manual.pdf",
        },
    ])
    sb.rpc.return_value = rpc_call

    results = await query_top_k(
        "qual o procedimento de garantia?",
        company_id="cid-123",
        k=5,
        embedder=embedder,
        supabase_client=sb,
    )

    # Verifica chamada RPC
    sb.rpc.assert_called_once()
    args = sb.rpc.call_args
    assert args.args[0] == "match_rag_chunks"
    payload = args.args[1]
    assert payload["p_company_id"] == "cid-123"
    assert payload["p_match_count"] == 5
    assert len(payload["query_embedding"]) == 1536

    # Resultado mapeado corretamente
    assert len(results) == 1
    assert results[0].id == "chunk-1"
    assert results[0].score == 0.92
    assert results[0].document_filename == "manual.pdf"


@pytest.mark.asyncio
async def test_query_top_k_empty_query_returns_empty():
    from src.services.rag.retriever import query_top_k

    sb = MagicMock()
    results = await query_top_k("", "cid", supabase_client=sb)
    assert results == []
    sb.rpc.assert_not_called()


@pytest.mark.asyncio
async def test_query_top_k_missing_company_id_raises():
    from src.services.rag.retriever import query_top_k

    with pytest.raises(ValueError, match="company_id"):
        await query_top_k("pergunta", company_id="", supabase_client=MagicMock())


@pytest.mark.asyncio
async def test_query_top_k_no_supabase_raises():
    from src.services.rag import retriever as ret_mod

    embedder = MagicMock()
    embedder.embed_one = AsyncMock(return_value=[0.0] * 1536)

    # Forçar fallback para src.api.supabase = None via monkeypatch direto no módulo
    import importlib
    import src.api as api_mod
    original = api_mod.supabase
    api_mod.supabase = None
    try:
        with pytest.raises(RuntimeError, match="Supabase client indispon"):
            await ret_mod.query_top_k("pergunta", "cid", embedder=embedder)
    finally:
        api_mod.supabase = original


@pytest.mark.asyncio
async def test_query_top_k_passes_min_score():
    from src.services.rag.retriever import query_top_k

    embedder = MagicMock()
    embedder.embed_one = AsyncMock(return_value=[0.1] * 1536)
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value = MagicMock(data=[])

    await query_top_k(
        "x", "cid", k=10, min_score=0.7,
        embedder=embedder, supabase_client=sb,
    )
    payload = sb.rpc.call_args.args[1]
    assert payload["p_min_score"] == 0.7
    assert payload["p_match_count"] == 10
