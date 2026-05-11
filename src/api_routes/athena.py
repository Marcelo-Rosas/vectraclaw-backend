"""
src.api_routes.athena — endpoints REST do corpus RAG dedicado da Athena.

Espelho de src/api_routes/rag.py, com schema isolado:
  - vectraclip.athena_documents / athena_chunks (corpus PMBOK/Heldman)
  - Bucket Storage: 'athena-rag' (override ATHENA_STORAGE_BUCKET)
  - operation_type: 'athena-rag-ingest' (despachado pelo daemon Athena)
  - assigned_to_agent_id: ATHENA_AGENT_ID

Endpoints:
- POST   /api/companies/{company_id}/athena/upload      upload + dispatch ingestão
- GET    /api/companies/{company_id}/athena/documents   list (filter por status)
- GET    /api/athena/documents/{document_id}             get single doc
- POST   /api/companies/{company_id}/athena/query       top-k chunks (cosine via RPC)
- DELETE /api/athena/documents/{document_id}             cascade chunks + storage cleanup

Isolamento de corpus garantido pela RPC `match_athena_chunks` (SECURITY DEFINER
+ filtro WHERE c.company_id), pelas tabelas separadas e pelo bucket próprio.
Razão arquitetural: ver `src/services/athena_rag.py` (docstring) e VEC-394.
"""
from __future__ import annotations

import hashlib
import json as _json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("api.athena")
router = APIRouter(tags=["athena"])

# Mesma whitelist de extensões do Mnemos (mesmo extractor).
_ATHENA_ALLOWED_EXT = {".pdf", ".txt", ".html", ".htm", ".json", ".xlsx"}
_ATHENA_DEFAULT_BUCKET = "athena-rag"


def _detect_ext(filename: str) -> str:
    return Path(filename).suffix.lower()


def _detect_mime(ext: str) -> str:
    return {
        ".pdf":  "application/pdf",
        ".txt":  "text/plain",
        ".html": "text/html",
        ".htm":  "text/html",
        ".json": "application/json",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(ext, "application/octet-stream")


# ─────────────────────────────────────────────────────────────────────────────
# Models (mais enxutos que o Mnemos — Athena não tem categorização operacional
# em V1; metadata aceito como dict livre para o user passar contexto Heldman).
# ─────────────────────────────────────────────────────────────────────────────

class AthenaQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    k: int = Field(default=5, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)


class AthenaChunkOut(BaseModel):
    id: str
    document_id: str
    chunk_index: int
    page_number: Optional[int] = None
    content: str
    score: float
    document_filename: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AthenaDocumentOut(BaseModel):
    id: str
    company_id: str
    filename: str
    sha256: str
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    page_count: Optional[int] = None
    status: str
    error_detail: Optional[str] = None
    ingest_task_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    uploaded_at: str
    indexed_at: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/companies/{company_id}/athena/upload")
@router.post("/companies/{company_id}/athena/upload")
async def upload_athena_document(
    request: Request,
    company_id: str,
    arquivo: UploadFile = File(...),
    metadata: Optional[str] = Form(None),
):
    """Upload de documento PMBOK/Heldman + dispara ingestão assíncrona via Athena.

    Idempotência: re-upload do mesmo arquivo (sha256 igual) retorna a row
    existente — não duplica em athena_documents nem cria task duplicada.

    Metadata (Form field opcional, JSON string): aceito como dict livre.
    Não há closed enums em V1 — categorização Heldman fica a critério do user
    (ex: {"book":"PMBOK 6th","chapter":"4","topic":"integration"}).
    """
    from src.api import supabase, validate_jwt_company_id
    from src.agents.athena import ATHENA_AGENT_ID
    from src.services.rag import ensure_bucket_exists

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        raise HTTPException(503, "supabase_required")

    # Parse de metadata livre (dict opcional)
    metadata_dict: Dict[str, Any] = {}
    if metadata:
        try:
            metadata_dict = _json.loads(metadata)
            if not isinstance(metadata_dict, dict):
                raise HTTPException(422, "metadata: deve ser um objeto JSON")
        except _json.JSONDecodeError as e:
            raise HTTPException(422, f"metadata: JSON inválido — {e}")

    filename = arquivo.filename or "unnamed"
    ext = _detect_ext(filename)
    if ext not in _ATHENA_ALLOWED_EXT:
        raise HTTPException(
            422,
            f"extensão não suportada: '{ext}'. Permitidos: {sorted(_ATHENA_ALLOWED_EXT)}",
        )

    file_bytes = await arquivo.read()
    if not file_bytes:
        raise HTTPException(422, "arquivo vazio")

    size_bytes = len(file_bytes)
    sha256 = hashlib.sha256(file_bytes).hexdigest()
    storage_path = f"{company_id}/{sha256}{ext}"
    mime_type = _detect_mime(ext)
    bucket = os.getenv("ATHENA_STORAGE_BUCKET", _ATHENA_DEFAULT_BUCKET)

    if not ensure_bucket_exists(supabase, bucket):
        raise HTTPException(
            503,
            f"Bucket Storage '{bucket}' não existe. Crie via dashboard ou "
            f"defina RAG_AUTO_PROVISION=true no env.",
        )

    # Idempotência: já existe?
    existing = (
        supabase.table("athena_documents")
        .select("*")
        .eq("company_id", company_id)
        .eq("sha256", sha256)
        .limit(1)
        .execute()
    )
    if existing.data:
        existing_doc = existing.data[0]
        logger.info(
            "athena.upload: duplicate sha256=%s for company=%s (returning existing doc=%s status=%s)",
            sha256[:12], company_id, existing_doc["id"], existing_doc["status"],
        )
        return {
            "document_id": existing_doc["id"],
            "task_id": existing_doc.get("ingest_task_id"),
            "status": existing_doc["status"],
            "duplicate": True,
            "filename": existing_doc["filename"],
        }

    # Upload Storage. upsert=true permite re-upload caso DB e Storage divirjam.
    try:
        supabase.storage.from_(bucket).upload(
            storage_path,
            file_bytes,
            file_options={
                "content-type": mime_type,
                "upsert": "true",
            },
        )
    except Exception as e:
        logger.error("athena.upload storage failed: %s", e)
        raise HTTPException(500, f"storage_upload_failed: {e}")

    # Insert athena_documents (status='uploaded')
    now_iso = datetime.now(timezone.utc).isoformat()
    insert_doc_row: Dict[str, Any] = {
        "company_id": company_id,
        "filename": filename,
        "storage_path": storage_path,
        "sha256": sha256,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "status": "uploaded",
        "uploaded_at": now_iso,
    }
    if metadata_dict:
        insert_doc_row["metadata"] = metadata_dict
    try:
        doc_res = supabase.table("athena_documents").insert(insert_doc_row).execute()
        if not doc_res.data:
            raise HTTPException(500, "athena_documents insert returned empty")
        document_id = doc_res.data[0]["id"]
    except Exception as e:
        # Cleanup: tentar remover arquivo do bucket pra não criar lixo órfão
        try:
            supabase.storage.from_(bucket).remove([storage_path])
        except Exception:
            pass
        logger.error("athena.upload db insert failed: %s", e)
        raise HTTPException(500, f"db_insert_failed: {e}")

    # Cria task athena-rag-ingest assigned to Athena
    task_row = {
        "company_id": company_id,
        "title": f"Athena RAG ingest: {filename}",
        "description": f"Ingestão Athena do documento '{filename}' (sha256={sha256[:12]}...)",
        "operation_type": "athena-rag-ingest",
        "status": "queued",
        "budget_limit": 0,
        "spent": 0,
        "cost_usd": 0,
        "executor_type": "auto",
        "assigned_to_agent_id": ATHENA_AGENT_ID,
        "input_json": {
            "document_id": document_id,
            "filename": filename,
            "sha256": sha256,
        },
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    try:
        task_res = supabase.table("tasks").insert(task_row).execute()
        if not task_res.data:
            # Documento já inserido — não deixar órfão sem task companion.
            # Marca como failed com mensagem clara para reprocessamento manual.
            try:
                supabase.table("athena_documents").update({
                    "status": "failed",
                    "error_detail": "task_insert_returned_empty",
                }).eq("id", document_id).execute()
            except Exception:
                pass
            raise HTTPException(500, "task insert returned empty")
        task_id = task_res.data[0]["id"]
    except HTTPException:
        raise
    except Exception as e:
        # Mesmo cleanup do branch acima.
        try:
            supabase.table("athena_documents").update({
                "status": "failed",
                "error_detail": f"task_insert_failed: {str(e)[:400]}",
            }).eq("id", document_id).execute()
        except Exception:
            pass
        logger.error("athena.upload task insert failed: %s", e)
        raise HTTPException(500, f"task_insert_failed: {e}")

    # Atualiza ingest_task_id no documento (audit trail)
    try:
        supabase.table("athena_documents").update({
            "ingest_task_id": task_id,
        }).eq("id", document_id).execute()
    except Exception as e:
        logger.warning("athena.upload: failed to set ingest_task_id (non-fatal): %s", e)

    logger.info(
        "athena.upload company=%s filename=%s size=%d doc=%s task=%s",
        company_id, filename, size_bytes, document_id, task_id,
    )
    return {
        "document_id": document_id,
        "task_id": task_id,
        "status": "uploaded",
        "duplicate": False,
        "filename": filename,
        "size_bytes": size_bytes,
        "sha256": sha256,
    }


@router.get("/api/companies/{company_id}/athena/documents")
@router.get("/companies/{company_id}/athena/documents")
async def list_athena_documents(
    request: Request,
    company_id: str,
    status: Optional[str] = Query(None, pattern="^(uploaded|processing|indexed|failed)$"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Lista documents Athena da company. Filtros: status, limit."""
    from src.api import supabase, validate_jwt_company_id, get_authenticated_client

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        query = (
            client.table("athena_documents")
            .select("*")
            .eq("company_id", company_id)
            .order("uploaded_at", desc=True)
            .limit(limit)
        )
        if status:
            query = query.eq("status", status)
        res = query.execute()
        return [AthenaDocumentOut(**row).model_dump() for row in (res.data or [])]
    except Exception as e:
        logger.error("athena.list_documents failed: %s", e)
        raise HTTPException(500, str(e))


@router.get("/api/athena/documents/{document_id}")
@router.get("/athena/documents/{document_id}")
async def get_athena_document(request: Request, document_id: str):
    """Get single Athena doc. RLS valida company_id automaticamente."""
    from src.api import supabase, get_authenticated_client

    if not supabase:
        raise HTTPException(404, "athena_document_not_found")
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("athena_documents")
            .select("*")
            .eq("id", document_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(404, "athena_document_not_found")
        return AthenaDocumentOut(**res.data[0]).model_dump()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("athena.get_document failed: %s", e)
        raise HTTPException(500, str(e))


@router.post("/api/companies/{company_id}/athena/query")
@router.post("/companies/{company_id}/athena/query")
async def query_athena_corpus(
    request: Request,
    company_id: str,
    body: AthenaQueryRequest,
):
    """Top-k chunks Athena por cosine similarity. Retorna chunks com score
    + document_filename. Não gera resposta — apenas retrieval.
    """
    from src.api import supabase, validate_jwt_company_id
    from src.services.athena_rag import query_top_k as athena_query_top_k

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        raise HTTPException(503, "supabase_required")

    try:
        results = await athena_query_top_k(
            body.query,
            company_id=company_id,
            k=body.k,
            min_score=body.min_score,
            supabase_client=supabase,
        )
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error("athena.query failed: %s", e)
        raise HTTPException(500, str(e))

    return {
        "query": body.query,
        "k": body.k,
        "min_score": body.min_score,
        "matches": [
            AthenaChunkOut(
                id=r.id,
                document_id=r.document_id,
                chunk_index=r.chunk_index,
                page_number=r.page_number,
                content=r.content,
                score=r.score,
                document_filename=r.document_filename,
                metadata=r.metadata,
            ).model_dump()
            for r in results
        ],
        "total": len(results),
    }


@router.delete("/api/athena/documents/{document_id}")
@router.delete("/athena/documents/{document_id}")
async def delete_athena_document(request: Request, document_id: str):
    """Cascade delete: chunks via FK, storage file via API."""
    from src.api import supabase, get_authenticated_client

    if not supabase:
        raise HTTPException(404, "athena_document_not_found")
    try:
        client = get_authenticated_client(request.state.token)
        existing = (
            client.table("athena_documents")
            .select("id,storage_path,company_id")
            .eq("id", document_id)
            .limit(1)
            .execute()
        )
        if not existing.data:
            raise HTTPException(404, "athena_document_not_found")
        row = existing.data[0]

        bucket = os.getenv("ATHENA_STORAGE_BUCKET", _ATHENA_DEFAULT_BUCKET)
        try:
            supabase.storage.from_(bucket).remove([row["storage_path"]])
        except Exception as e:
            logger.warning("athena.delete storage cleanup failed (non-fatal): %s", e)

        supabase.table("athena_documents").delete().eq("id", document_id).execute()
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("athena.delete_document failed: %s", e)
        raise HTTPException(500, str(e))
