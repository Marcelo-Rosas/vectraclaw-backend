"""
Athena RAG — pipeline de ingestão e retrieval para o corpus PMBOK/Heldman.

Espelho de src/agents/mnemos.py + src/services/rag/retriever.py, com tabelas
isoladas (vectraclip.athena_documents + vectraclip.athena_chunks) e bucket
Storage próprio (athena-rag). Pipeline ext./chunk./embed./retrieval é
o mesmo do Mnemos — apenas o schema de destino muda.

Razão da separação (ADR-002): corpus Heldman/PMBOK tem natureza distinta
do corpus operacional Vectra (contratos, manuais, e-mails). Misturá-los
no `rag_documents` degradaria recall em ambos os agentes.

Operation type esperado pelo daemon: 'athena-rag-ingest'.
AGENT_ID alvo: src.agents.athena.ATHENA_AGENT_ID.

Bucket Storage: 'athena-rag' (override via env ATHENA_STORAGE_BUCKET).
Path convention: {company_id}/{sha256}.{ext} (igual Mnemos).
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.services.rag.models import ChunkResult

logger = logging.getLogger("Athena.RAG")

DEFAULT_BUCKET = "athena-rag"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mark_failed(supabase, document_id: str, error_msg: str) -> None:
    """Best-effort: marca athena_documents.status='failed' com error_detail."""
    try:
        supabase.table("athena_documents").update({
            "status": "failed",
            "error_detail": error_msg[:500],
        }).eq("id", document_id).execute()
    except Exception as e:
        logger.error("Athena.RAG: falha ao marcar doc=%s como failed: %s", document_id, e)


def entrypoint(task: dict, supabase, *, embedder=None) -> Dict[str, Any]:
    """Handler do daemon Athena para operation_type='athena-rag-ingest'.

    Args:
        task: dict da row vectraclip.tasks (id, input_json, company_id, ...).
        supabase: client com service_role (do daemon).
        embedder: injetável para testes; default resolve_embedder()
                  (catalog-driven, Ollama nomic 768-dim) igual ao Mnemos.

    Returns:
        dict com status ('done' | 'errored'), chunks_inserted, page_count, error.
    """
    document_id: Optional[str] = (task.get("input_json") or {}).get("document_id")
    if not document_id:
        return {
            "status": "errored",
            "error": "missing input_json.document_id",
        }

    try:
        # 1. Load athena_documents row
        doc_res = (
            supabase.table("athena_documents")
            .select("*")
            .eq("id", document_id)
            .limit(1)
            .execute()
        )
        if not doc_res.data:
            return {
                "status": "errored",
                "error": f"athena_document not found: {document_id}",
            }
        doc = doc_res.data[0]
        company_id = doc["company_id"]
        storage_path = doc["storage_path"]
        filename = doc["filename"]
        mime_type = doc.get("mime_type")

        # 2. status='processing'
        supabase.table("athena_documents").update({
            "status": "processing",
        }).eq("id", document_id).execute()

        # 3. Download do Storage
        bucket = os.getenv("ATHENA_STORAGE_BUCKET", DEFAULT_BUCKET)
        try:
            file_bytes = supabase.storage.from_(bucket).download(storage_path)
        except Exception as e:
            raise RuntimeError(f"storage download falhou (bucket={bucket}, path={storage_path}): {e}")

        if not file_bytes:
            raise RuntimeError(f"storage retornou bytes vazios para {storage_path}")

        # 4. Tempfile com extensão preservada
        ext = Path(filename).suffix or ".bin"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
            tf.write(file_bytes)
            tmp_path = tf.name

        try:
            # 5. Extract
            from src.services.rag.extractor import extract_text
            extracted = extract_text(tmp_path, mime_type=mime_type)

            # 6. Chunk
            from src.services.rag.chunker import chunk_text
            chunks = chunk_text(
                extracted.pages or [],
                max_tokens=int(os.getenv("RAG_CHUNK_MAX_TOKENS", "500")),
                overlap=int(os.getenv("RAG_CHUNK_OVERLAP", "100")),
            )

            if not chunks:
                supabase.table("athena_documents").update({
                    "status": "indexed",
                    "indexed_at": _now_iso(),
                    "page_count": extracted.page_count,
                }).eq("id", document_id).execute()
                logger.warning(
                    "Athena.RAG: doc=%s indexado vazio (0 chunks, %d pages)",
                    document_id, extracted.page_count,
                )
                return {
                    "status": "done",
                    "chunks_inserted": 0,
                    "page_count": extracted.page_count,
                }

            # 7. Embed — catalog-driven (Regra de Ouro #2). Mesmo embedder do
            # Mnemos (Ollama nomic-embed-text 768-dim local), resolvido via
            # adapter. Mantém athena_chunks na MESMA dimensão de rag_chunks.
            if embedder is None:
                from src.services.rag.embedder import resolve_embedder
                embedder = resolve_embedder()

            texts = [c.content for c in chunks]
            embeddings = asyncio.run(embedder.embed_batch(texts))

            # 8. Bulk insert chunks (trigger sync_athena_chunk_company_id valida)
            rows = [
                {
                    "document_id": document_id,
                    "company_id": company_id,
                    "chunk_index": c.chunk_index,
                    "page_number": c.page_number,
                    "content": c.content,
                    "token_count": c.token_count,
                    "embedding": embeddings[i],
                    "embedding_model": embedder.model,
                    "metadata": c.metadata,
                }
                for i, c in enumerate(chunks)
            ]
            supabase.table("athena_chunks").insert(rows).execute()

            # 9. status='indexed'
            supabase.table("athena_documents").update({
                "status": "indexed",
                "indexed_at": _now_iso(),
                "page_count": extracted.page_count,
            }).eq("id", document_id).execute()

            logger.info(
                "Athena.RAG indexed doc=%s filename=%s chunks=%d pages=%d company=%s",
                document_id, filename, len(rows), extracted.page_count, company_id,
            )
            return {
                "status": "done",
                "chunks_inserted": len(rows),
                "page_count": extracted.page_count,
                "document_id": document_id,
            }
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    except Exception as e:
        logger.exception("Athena.RAG entrypoint failed doc=%s: %s", document_id, e)
        _mark_failed(supabase, document_id, str(e))
        return {
            "status": "errored",
            "error": str(e),
            "document_id": document_id,
        }


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

    Espelho de src/services/rag/retriever.py:query_top_k, apontando para
    a RPC `vectraclip.match_athena_chunks`.

    Args:
        query_text: pergunta ou frase de busca.
        company_id: UUID da company. Obrigatório (multi-tenant).
        k: top-k chunks a retornar (default 5).
        min_score: score mínimo (0..1) para filtrar resultado ruim.
        embedder: instance reutilizável; se None, usa resolve_embedder().
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
        from src.api import supabase as _api_supabase
        sb = _api_supabase
    if sb is None:
        raise RuntimeError("Supabase client indisponível em src.api.supabase")

    # Catalog-driven (Regra de Ouro #2): embedder da query DEVE ser o mesmo do
    # ingest (Ollama nomic 768-dim), senão a dimensão do vetor de busca não bate
    # com athena_chunks e o RPC falha. resolve_embedder lê o adapter do Mnemos.
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
        query_text[:50], company_id, k, len(out),
        out[0].score if out else 0.0,
    )
    return out
