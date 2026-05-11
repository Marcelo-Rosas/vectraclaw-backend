"""
Retriever: query_top_k via Supabase RPC `match_rag_chunks`.

Pipeline:
1. Embed da pergunta (OpenAIEmbedder)
2. RPC com query_embedding + p_company_id + p_match_count
3. Retorna ChunkResult[] ordenado por score DESC (1.0 = idêntico, 0.0 = oposto)

Multi-tenancy: company_id é obrigatório no RPC. Função tem SECURITY DEFINER
+ filtro WHERE c.company_id = p_company_id, garantindo isolamento mesmo se
chamada pelo service_role.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from .embedder import FallbackEmbedder, GeminiEmbedder, OpenAIEmbedder
from .models import ChunkResult

logger = logging.getLogger("rag.retriever")


async def query_top_k(
    query_text: str,
    company_id: str,
    *,
    k: int = 5,
    min_score: float = 0.0,
    embedder: Optional[OpenAIEmbedder] = None,
    supabase_client=None,
) -> List[ChunkResult]:
    """Embed pergunta + busca top-k chunks da company via pgvector cosine.

    Args:
        query_text: pergunta ou frase de busca.
        company_id: UUID da company. Obrigatório (multi-tenant).
        k: top-k chunks a retornar (default 5).
        min_score: score mínimo (0..1) para filtrar resultado ruim.
        embedder: instance reutilizável; se None, cria nova OpenAIEmbedder.
        supabase_client: injetável para testes; default usa src.api.supabase.

    Returns:
        Lista de ChunkResult ordenada por score DESC.
    """
    if not query_text or not query_text.strip():
        return []
    if not company_id:
        raise ValueError("company_id é obrigatório (multi-tenant)")

    sb = supabase_client
    if sb is None:
        # Lazy import (evita ciclo). Daemon e api.py já têm supabase global.
        from src.api import supabase as _api_supabase
        sb = _api_supabase
    if sb is None:
        raise RuntimeError("Supabase client indisponível em src.api.supabase")

    # VEC-397: default vira FallbackEmbedder (Gemini primário, OpenAI fallback).
    # Antes era OpenAIEmbedder direto e qualquer 429 derrubava o /rag/query.
    emb = embedder or FallbackEmbedder(
        primary=GeminiEmbedder(),
        fallbacks=[OpenAIEmbedder()],
    )
    query_embedding = await emb.embed_one(query_text)
    if not query_embedding:
        return []

    res = sb.rpc(
        "match_rag_chunks",
        {
            "query_embedding": query_embedding,
            "p_company_id": company_id,
            "p_match_count": int(k),
            "p_min_score": float(min_score),
        },
    ).execute()

    rows = res.data or []
    out = [
        ChunkResult(
            id=str(r["id"]),
            document_id=str(r["document_id"]),
            chunk_index=int(r["chunk_index"]),
            page_number=r.get("page_number"),
            content=r["content"],
            score=float(r["score"]),
            metadata=r.get("metadata") or {},
            document_filename=r.get("document_filename"),
        )
        for r in rows
    ]
    logger.info(
        "rag.retriever: query='%s...' company=%s k=%d → %d chunks (top score=%.3f)",
        query_text[:50], company_id, k, len(out),
        out[0].score if out else 0.0,
    )
    return out
