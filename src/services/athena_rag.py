"""Athena RAG — pipeline de ingestão e retrieval para o corpus PMBOK/Heldman.

Espelho do corpus operacional (Mnemos) com tabelas isoladas
(vectraclip.athena_documents + vectraclip.athena_chunks) e bucket
próprio (athena-rag).

O pipeline de ingestão reusa ``src.services.rag.pipeline.ingest_document``;
este módulo apenas configura o prefixo "athena" e o bucket.

Operation type esperado pelo daemon: 'athena-rag-ingest'.
AGENT_ID alvo: src.agents.athena.ATHENA_AGENT_ID.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from src.services.rag.models import ChunkResult
from src.services.rag.pipeline import ingest_document

logger = logging.getLogger("Athena.RAG")

DEFAULT_BUCKET = "athena-rag"


async def entrypoint(task: dict, supabase, *, embedder=None) -> Dict[str, Any]:
    """Handler do daemon Athena para operation_type='athena-rag-ingest'.

    Args:
        task: dict da row vectraclip.tasks.
        supabase: client com service_role.
        embedder: injetável para testes.

    Returns:
        Resultado do pipeline genérico.
    """
    return await ingest_document(
        task,
        supabase,
        table_prefix="athena",
        bucket=os.getenv("ATHENA_STORAGE_BUCKET", DEFAULT_BUCKET),
        embedder=embedder,
    )


async def query_top_k(
    query_text: str,
    company_id: str,
    *,
    k: int = 5,
    min_score: float = 0.0,
    embedder: Optional[object] = None,
    supabase_client=None,
) -> List[ChunkResult]:
    """Embed pergunta + busca top-k chunks Athena via pgvector cosine.

    Espelho de ``src.services.rag.retriever.query_top_k``, apontando para
    a RPC ``vectraclip.match_athena_chunks``.

    Args:
        query_text: pergunta ou frase de busca.
        company_id: UUID da company. Obrigatório (multi-tenant).
        k: top-k chunks a retornar (default 5).
        min_score: score mínimo (0..1) para filtrar resultado ruim.
        embedder: instance reutilizável; se None, usa resolve_embedder().
        supabase_client: injetável para testes.

    Returns:
        Lista de ChunkResult ordenada por score DESC.
    """
    if not query_text or not query_text.strip():
        return []
    if not company_id:
        raise ValueError("company_id é obrigatório (multi-tenant)")

    sb = supabase_client
    if sb is None:
        from src.api import supabase as _api_supabase
        sb = _api_supabase
    if sb is None:
        raise RuntimeError("Supabase client indisponível em src.api.supabase")

    from src.services.rag.embedder import resolve_embedder
    emb = embedder or resolve_embedder()
    query_embedding = await emb.embed_one(query_text)
    if not query_embedding:
        return []

    res = sb.rpc(
        "match_athena_chunks",
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
        "Athena.RAG query='%s...' company=%s k=%d → %d chunks (top score=%.3f)",
        query_text[:50],
        company_id,
        k,
        len(out),
        out[0].score if out else 0.0,
    )
    return out
