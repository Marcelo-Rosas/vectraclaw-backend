"""
src.api_routes.rag — endpoints REST do RAG corpus.

Endpoints:
- POST   /api/companies/{company_id}/rag/upload         upload + dispatch ingestion
- GET    /api/companies/{company_id}/rag/documents      list (filter por status)
- GET    /api/rag/documents/{document_id}                get single doc
- POST   /api/companies/{company_id}/rag/query          top-k chunks (cosine via RPC)
- DELETE /api/rag/documents/{document_id}                cascade chunks + storage cleanup

Pipeline upload:
  1. Recebe arquivo multipart
  2. Calcula sha256 do conteúdo
  3. Idempotência: se (company_id, sha256) existe → retorna doc existente
  4. Upload Storage: {company_id}/{sha256}.{ext} (bucket RAG_STORAGE_BUCKET)
  5. INSERT rag_documents (status='uploaded')
  6. Cria task rag-ingest assigned_to_agent_id=Mnemos
  7. Retorna document_id + task_id

Daemon Mnemos polla a task e processa pipeline (PR #20).
Tool query_rag em m3_tools.py expõe query para o CMA (PR 5/5).
"""
from __future__ import annotations

import hashlib
import json as _json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger("api.rag")
router = APIRouter(tags=["rag"])

# Extensões aceitas pelo extractor (espelha src/services/rag/extractor.py).
# `.xls` (formato BIFF antigo) NÃO é suportado: openpyxl só lê `.xlsx`. Aceitar
# `.xls` resultava em upload OK + status='failed' downstream — pior UX que
# rejeitar no upload com mensagem clara. Suporte real exigiria adicionar
# `xlrd` ao requirements e handler dedicado em extractor.py.
_RAG_ALLOWED_EXT = {".pdf", ".txt", ".html", ".htm", ".json", ".xlsx"}
_RAG_DEFAULT_BUCKET = "rag-documents"


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
# Bucket auto-provisioning
# ─────────────────────────────────────────────────────────────────────────────

def _rag_auto_provision_enabled() -> bool:
    """RAG_AUTO_PROVISION=true habilita criação automática de bucket no /upload."""
    return os.getenv("RAG_AUTO_PROVISION", "").strip().lower() in ("1", "true", "yes", "on")


def _ensure_rag_bucket_exists(supabase, bucket: str) -> bool:
    """Verifica se o bucket existe; se não, cria (idempotente) sob env RAG_AUTO_PROVISION.

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


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────

# Closed enums alinhados a docs/PRD-RAG-categorization (Step 11)
RagCategoria = Literal["manual", "procedimento", "contrato", "tabela", "email", "outro"]
RagDepartamento = Literal["operacao", "comercial", "financeiro", "rh", "juridico", "ti"]
RagConfidencialidade = Literal["publica", "interna", "restrita"]


class RagUploadMetadata(BaseModel):
    """Categorização opcional anexada ao upload. Persiste em rag_documents.metadata."""
    categoria: Optional[RagCategoria] = None
    tags: List[str] = Field(default_factory=list, max_length=20)
    departamento: Optional[RagDepartamento] = None
    confidencialidade: Optional[RagConfidencialidade] = None
    data_referencia: Optional[str] = None  # 'YYYY-MM'
    vinculo_processo_id: Optional[str] = None  # uuid

    @field_validator("data_referencia")
    @classmethod
    def _validate_data_referencia(cls, v):
        if v is None or v == "":
            return None
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", v):
            raise ValueError("data_referencia deve seguir 'YYYY-MM' (ex: 2026-05)")
        return v

    @field_validator("vinculo_processo_id")
    @classmethod
    def _validate_uuid(cls, v):
        if v is None or v == "":
            return None
        if not re.match(r"^[0-9a-fA-F-]{36}$", v):
            raise ValueError("vinculo_processo_id deve ser UUID")
        return v

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, v):
        # Trim + dedupe + lowercase, descarta vazias
        seen = set()
        out = []
        for t in v:
            t2 = (t or "").strip().lower()
            if t2 and t2 not in seen:
                seen.add(t2)
                out.append(t2)
        return out


class RagQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    k: int = Field(default=5, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)


class RagChunkOut(BaseModel):
    id: str
    document_id: str
    chunk_index: int
    page_number: Optional[int] = None
    content: str
    score: float
    document_filename: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RagDocumentOut(BaseModel):
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

@router.post("/api/companies/{company_id}/rag/upload")
@router.post("/companies/{company_id}/rag/upload")
async def upload_rag_document(
    request: Request,
    company_id: str,
    arquivo: UploadFile = File(...),
    metadata: Optional[str] = Form(None),
):
    """Upload de documento + dispara ingestão assíncrona via Mnemos.

    Idempotência: re-upload do mesmo arquivo (sha256 igual) retorna a row
    existente — não duplica em rag_documents nem cria task duplicada.

    Metadata (Form field opcional, JSON string): categoria, tags,
    departamento, confidencialidade, data_referencia, vinculo_processo_id.
    Validado via RagUploadMetadata; persiste em `rag_documents.metadata`.
    """
    from src.api import supabase, validate_jwt_company_id
    from src.agents.mnemos import MNEMOS_AGENT_ID

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        raise HTTPException(503, "supabase_required")

    # Parse + valida metadata se fornecido
    metadata_dict: Dict[str, Any] = {}
    if metadata:
        try:
            raw = _json.loads(metadata)
            metadata_dict = RagUploadMetadata(**raw).model_dump(exclude_none=True)
        except _json.JSONDecodeError as e:
            raise HTTPException(422, f"metadata: JSON inválido — {e}")
        except ValidationError as e:
            raise HTTPException(422, f"metadata: {e.errors()}")

    filename = arquivo.filename or "unnamed"
    ext = _detect_ext(filename)
    if ext not in _RAG_ALLOWED_EXT:
        raise HTTPException(
            422,
            f"extensão não suportada: '{ext}'. Permitidos: {sorted(_RAG_ALLOWED_EXT)}",
        )

    file_bytes = await arquivo.read()
    if not file_bytes:
        raise HTTPException(422, "arquivo vazio")

    size_bytes = len(file_bytes)
    sha256 = hashlib.sha256(file_bytes).hexdigest()
    storage_path = f"{company_id}/{sha256}{ext}"
    mime_type = _detect_mime(ext)
    bucket = os.getenv("RAG_STORAGE_BUCKET", _RAG_DEFAULT_BUCKET)

    # Garante que o bucket existe (auto-provision se RAG_AUTO_PROVISION=true)
    if not _ensure_rag_bucket_exists(supabase, bucket):
        raise HTTPException(
            503,
            f"Bucket Storage '{bucket}' não existe. Crie via dashboard ou "
            f"defina RAG_AUTO_PROVISION=true no env.",
        )

    # Idempotência: já existe?
    existing = (
        supabase.table("rag_documents")
        .select("*")
        .eq("company_id", company_id)
        .eq("sha256", sha256)
        .limit(1)
        .execute()
    )
    if existing.data:
        existing_doc = existing.data[0]
        logger.info(
            "rag.upload: duplicate sha256=%s for company=%s (returning existing doc=%s status=%s)",
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
        logger.error("rag.upload storage failed: %s", e)
        raise HTTPException(500, f"storage_upload_failed: {e}")

    # Insert rag_documents (status='uploaded')
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
        doc_res = supabase.table("rag_documents").insert(insert_doc_row).execute()
        if not doc_res.data:
            raise HTTPException(500, "rag_documents insert returned empty")
        document_id = doc_res.data[0]["id"]
    except Exception as e:
        # Cleanup: tentar remover arquivo do bucket pra não criar lixo órfão
        try:
            supabase.storage.from_(bucket).remove([storage_path])
        except Exception:
            pass
        logger.error("rag.upload db insert failed: %s", e)
        raise HTTPException(500, f"db_insert_failed: {e}")

    # Cria task rag-ingest assigned to Mnemos
    task_row = {
        "company_id": company_id,
        "title": f"RAG ingest: {filename}",
        "description": f"Ingestão do documento '{filename}' (sha256={sha256[:12]}...)",
        "operation_type": "rag-ingest",
        "status": "queued",
        "budget_limit": 0,
        "spent": 0,
        "cost_usd": 0,
        "executor_type": "auto",
        "assigned_to_agent_id": MNEMOS_AGENT_ID,
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
            raise HTTPException(500, "task insert returned empty")
        task_id = task_res.data[0]["id"]
    except Exception as e:
        logger.error("rag.upload task insert failed: %s", e)
        raise HTTPException(500, f"task_insert_failed: {e}")

    # Atualiza ingest_task_id no documento (audit trail)
    try:
        supabase.table("rag_documents").update({
            "ingest_task_id": task_id,
        }).eq("id", document_id).execute()
    except Exception as e:
        logger.warning("rag.upload: failed to set ingest_task_id (non-fatal): %s", e)

    logger.info(
        "rag.upload company=%s filename=%s size=%d doc=%s task=%s",
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


@router.get("/api/companies/{company_id}/rag/documents")
@router.get("/companies/{company_id}/rag/documents")
async def list_rag_documents(
    request: Request,
    company_id: str,
    status: Optional[str] = Query(None, pattern="^(uploaded|processing|indexed|failed)$"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Lista documents da company. Filtros: status, limit."""
    from src.api import supabase, validate_jwt_company_id, get_authenticated_client

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        query = (
            client.table("rag_documents")
            .select("*")
            .eq("company_id", company_id)
            .order("uploaded_at", desc=True)
            .limit(limit)
        )
        if status:
            query = query.eq("status", status)
        res = query.execute()
        return [RagDocumentOut(**row).model_dump() for row in (res.data or [])]
    except Exception as e:
        logger.error("rag.list_documents failed: %s", e)
        raise HTTPException(500, str(e))


@router.get("/api/rag/documents/{document_id}")
@router.get("/rag/documents/{document_id}")
async def get_rag_document(request: Request, document_id: str):
    """Get single doc. RLS valida company_id automaticamente."""
    from src.api import supabase, get_authenticated_client

    if not supabase:
        raise HTTPException(404, "rag_document_not_found")
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("rag_documents")
            .select("*")
            .eq("id", document_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(404, "rag_document_not_found")
        return RagDocumentOut(**res.data[0]).model_dump()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("rag.get_document failed: %s", e)
        raise HTTPException(500, str(e))


@router.post("/api/companies/{company_id}/rag/query")
@router.post("/companies/{company_id}/rag/query")
async def query_rag_corpus(
    request: Request,
    company_id: str,
    body: RagQueryRequest,
):
    """Top-k chunks por cosine similarity. Retorna chunks com score + document_filename.

    Não inclui LLM augmentation aqui (resposta gerada). Para isso, use a tool
    `query_rag` do CMA (PR 5/5) ou agregue no cliente.
    """
    from src.api import supabase, validate_jwt_company_id
    from src.services.rag.retriever import query_top_k

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        raise HTTPException(503, "supabase_required")

    try:
        results = await query_top_k(
            body.query,
            company_id=company_id,
            k=body.k,
            min_score=body.min_score,
            supabase_client=supabase,
        )
    except RuntimeError as e:
        # OPENAI_KEY ausente, supabase indisponível, etc.
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error("rag.query failed: %s", e)
        raise HTTPException(500, str(e))

    return {
        "query": body.query,
        "k": body.k,
        "min_score": body.min_score,
        "matches": [
            RagChunkOut(
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


@router.delete("/api/rag/documents/{document_id}")
@router.delete("/rag/documents/{document_id}")
async def delete_rag_document(request: Request, document_id: str):
    """Cascade delete: chunks via FK, storage file via API.

    RLS em rag_documents permite DELETE apenas authenticated da própria
    company OU service_role. service_role aqui via cliente raiz.
    """
    from src.api import supabase, get_authenticated_client

    if not supabase:
        raise HTTPException(404, "rag_document_not_found")
    try:
        # Verificar acesso via cliente authenticated (RLS)
        client = get_authenticated_client(request.state.token)
        existing = (
            client.table("rag_documents")
            .select("id,storage_path,company_id")
            .eq("id", document_id)
            .limit(1)
            .execute()
        )
        if not existing.data:
            raise HTTPException(404, "rag_document_not_found")
        row = existing.data[0]

        # Storage cleanup (best-effort; FK CASCADE cuida dos chunks)
        bucket = os.getenv("RAG_STORAGE_BUCKET", _RAG_DEFAULT_BUCKET)
        try:
            supabase.storage.from_(bucket).remove([row["storage_path"]])
        except Exception as e:
            logger.warning("rag.delete storage cleanup failed (non-fatal): %s", e)

        # DELETE (CASCADE em rag_chunks via FK)
        supabase.table("rag_documents").delete().eq("id", document_id).execute()
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("rag.delete_document failed: %s", e)
        raise HTTPException(500, str(e))
