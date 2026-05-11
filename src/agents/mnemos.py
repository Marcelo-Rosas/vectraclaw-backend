"""
Mnemos — agente curador da memória corporativa (RAG ingestor).

operation_type='rag-ingest' (despachado por agent_daemon).

Pipeline:
  1. Carrega rag_documents pelo input_json.document_id
  2. status='processing'
  3. Download do Supabase Storage (bucket rag-documents, path = {company_id}/{sha256}.{ext})
  4. extract_text → ExtractedDocument
  5. chunk_text → list[ChunkInput]
  6. embedder.embed_batch (OpenAI text-embedding-3-small primário,
     fallback Gemini gemini-embedding-001 se OpenAI retornar 429/401;
     ambos em 1536 dim — schema vector(1536) intacto)
  7. Bulk insert em rag_chunks (trigger sync_chunk_company_id valida)
  8. status='indexed', indexed_at, page_count
  9. Erro: status='failed', error_detail (truncado a 500 chars)

AGENT_ID: 00000000-0000-0000-0000-000000000003 (registrado por migration vec_rag_seed_mnemos).
adapter_type='internal' (não usa LLM de chat; só embedding API).
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("Mnemos")

MNEMOS_AGENT_ID = "00000000-0000-0000-0000-000000000003"
DEFAULT_BUCKET = "rag-documents"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mark_failed(supabase, document_id: str, error_msg: str) -> None:
    """Best-effort: marca rag_documents.status='failed' com error_detail."""
    try:
        supabase.table("rag_documents").update({
            "status": "failed",
            "error_detail": error_msg[:500],
        }).eq("id", document_id).execute()
    except Exception as e:
        logger.error("Mnemos: falha ao marcar doc=%s como failed: %s", document_id, e)


def entrypoint(task: dict, supabase, *, embedder=None) -> Dict[str, Any]:
    """Handler do daemon para operation_type='rag-ingest'.

    Args:
        task: dict da row vectraclip.tasks (id, input_json, company_id, ...).
        supabase: client com service_role (do daemon).
        embedder: injetável para testes; default cria OpenAIEmbedder.

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
        # 1. Load rag_documents row
        doc_res = (
            supabase.table("rag_documents")
            .select("*")
            .eq("id", document_id)
            .limit(1)
            .execute()
        )
        if not doc_res.data:
            return {
                "status": "errored",
                "error": f"rag_document not found: {document_id}",
            }
        doc = doc_res.data[0]
        company_id = doc["company_id"]
        storage_path = doc["storage_path"]
        filename = doc["filename"]
        mime_type = doc.get("mime_type")

        # 2. status='processing'
        supabase.table("rag_documents").update({
            "status": "processing",
        }).eq("id", document_id).execute()

        # 3. Download do Storage
        bucket = os.getenv("RAG_STORAGE_BUCKET", DEFAULT_BUCKET)
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

            # Caso documento vazio: marca indexed com 0 chunks (não é erro)
            if not chunks:
                supabase.table("rag_documents").update({
                    "status": "indexed",
                    "indexed_at": _now_iso(),
                    "page_count": extracted.page_count,
                }).eq("id", document_id).execute()
                logger.warning(
                    "Mnemos: doc=%s indexado vazio (0 chunks, %d pages)",
                    document_id, extracted.page_count,
                )
                return {
                    "status": "done",
                    "chunks_inserted": 0,
                    "page_count": extracted.page_count,
                }

            # 7. Embed (async run inside sync entrypoint do daemon)
            # Default: OpenAI primário; Gemini fallback se OpenAI dá 429/401
            # (quota zerada ou key inválida). FallbackEmbedder.model é
            # atualizado dinamicamente para refletir qual provider entregou.
            if embedder is None:
                from src.services.rag.embedder import (
                    FallbackEmbedder,
                    GeminiEmbedder,
                    OpenAIEmbedder,
                )
                embedder = FallbackEmbedder(
                    primary=OpenAIEmbedder(),
                    fallbacks=[GeminiEmbedder()],
                )

            texts = [c.content for c in chunks]
            embeddings = asyncio.run(embedder.embed_batch(texts))

            # 8. Bulk insert chunks. company_id é DENORMALIZADO de rag_documents
            # via trigger sync_chunk_company_id; populamos explicitamente para
            # belt-and-suspenders (trigger overwrite = no-op se valor coincidir).
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
            supabase.table("rag_chunks").insert(rows).execute()

            # 9. status='indexed'
            supabase.table("rag_documents").update({
                "status": "indexed",
                "indexed_at": _now_iso(),
                "page_count": extracted.page_count,
            }).eq("id", document_id).execute()

            logger.info(
                "Mnemos.entrypoint indexed doc=%s filename=%s chunks=%d pages=%d company=%s",
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
        logger.exception("Mnemos.entrypoint failed doc=%s: %s", document_id, e)
        _mark_failed(supabase, document_id, str(e))
        return {
            "status": "errored",
            "error": str(e),
            "document_id": document_id,
        }
