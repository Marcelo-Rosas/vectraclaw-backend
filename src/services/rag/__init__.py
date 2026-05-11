"""
src.services.rag — Pipeline RAG do VectraClaw.

Substitui o RAG PHP standalone por uma stack Python integrada:
- Extract: PDF/TXT/HTML/JSON/XLSX → texto + páginas
- Chunk: split em segmentos (default 500 tokens, 100 overlap)
- Embed: OpenAI text-embedding-3-small (1536 dim — locked pelo schema)
- Retrieve: pgvector HNSW cosine via Supabase RPC

Schema: vectraclip.rag_documents + vectraclip.rag_chunks (PR #18).
Tool externa para o CMA: query_rag em src/m3_tools.py (PR 5/5).
Daemon ingestor: Mnemos (PR 3/5).

Athena (9º daemon) reusa o pipeline com corpus paralelo
(vectraclip.athena_documents + vectraclip.athena_chunks) — ver VEC-394.
"""
import logging
import os
from typing import Any

from .models import (
    ChunkInput,
    ChunkResult,
    ExtractedDocument,
    PageText,
)
from .extractor import extract_text
from .chunker import chunk_text
from .embedder import OpenAIEmbedder
from .retriever import query_top_k

logger = logging.getLogger("rag")


def _rag_auto_provision_enabled() -> bool:
    """RAG_AUTO_PROVISION=true habilita criação automática de bucket no /upload."""
    return os.getenv("RAG_AUTO_PROVISION", "").strip().lower() in ("1", "true", "yes", "on")


def ensure_bucket_exists(supabase: Any, bucket: str) -> bool:
    """Verifica se o bucket existe; se não, cria (idempotente) sob env RAG_AUTO_PROVISION.

    Compartilhado por src/api_routes/rag.py (corpus Mnemos) e
    src/api_routes/athena.py (corpus Athena) — ambos reusam o mesmo flag de
    auto-provision para evitar drift entre features RAG.

    Retorna True se o bucket existe (já existia ou acabou de ser criado).
    Retorna False se não existe e auto-provision está desligado — caller decide
    como reportar (404/503 com mensagem instrutiva).
    """
    try:
        existing = supabase.storage.list_buckets()
        # supabase-py 2.x retorna list de objects com .name
        names = {(b.name if hasattr(b, "name") else b.get("name")) for b in existing}
        if bucket in names:
            return True
    except Exception as e:
        logger.warning("rag.bucket: list_buckets falhou (%s) — tentando criar mesmo assim", e)

    if not _rag_auto_provision_enabled():
        logger.info(
            "rag.bucket: '%s' não existe e RAG_AUTO_PROVISION=false. Crie via dashboard.",
            bucket,
        )
        return False

    try:
        supabase.storage.create_bucket(bucket, options={"public": False})
        logger.info("rag.bucket: '%s' criado (auto-provision)", bucket)
        return True
    except Exception as e:
        # Pode falhar com "already exists" se outra request criou simultaneamente
        msg = str(e).lower()
        if "already" in msg or "exists" in msg or "duplicate" in msg:
            return True
        logger.error("rag.bucket: create_bucket falhou: %s", e)
        return False


__all__ = [
    "ChunkInput",
    "ChunkResult",
    "ExtractedDocument",
    "PageText",
    "extract_text",
    "chunk_text",
    "OpenAIEmbedder",
    "query_top_k",
    "ensure_bucket_exists",
]
