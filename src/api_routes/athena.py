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


# ════════════════════════════════════════════════════════════════════════════
# VEC-408 sub-PR 3 — endpoints REST de approval de athena_recommendations
# ════════════════════════════════════════════════════════════════════════════

# Status válidos no DB (CHECK constraint criado no sub-PR 1)
_REC_DB_STATUSES = {"pending", "approved", "applied", "rejected", "superseded"}

# Catalog canônico de kind alinhado com:
#   - DB CHECK: migration 20260516150000_athena_kind_catalog_canonical.sql
#   - Frontend Zod: src/types/api.ts (VectraClip)
#   - Documentação: docs/ATHENA-RECOMMENDATIONS.md
# 8 valores divididos em 2 categorias:
#   - 5 EXECUTÁVEIS: POST .../apply após PATCH approved (AC-2)
#   - 3 INFORMATIVOS: apenas relatório/insight (humano lê + decide)
_REC_VALID_KINDS = {
    # Executáveis (Athena auto-aplica)
    "hire_new_agent", "add_specialty", "rewrite_system_prompt",
    "create_specialty", "consolidate_agents",
    # Informativos (Athena só reporta)
    "diagnose_gap", "suggest_automation", "suggest_hire_agent",
    "prompt_adjust",
}


class AthenaRecommendationOut(BaseModel):
    """Schema de resposta para athena_recommendations row."""
    id: str
    company_id: str
    kind: str
    status: str
    target_agent_id: Optional[str] = None
    target_specialty_id: Optional[str] = None
    triggered_by_goal_id: Optional[str] = None
    triggered_by_task_id: Optional[str] = None
    title: str
    rationale: str
    proposed_changes_json: Dict[str, Any]
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: float
    estimated_effort: str
    reviewed_by_user_id: Optional[str] = None
    reviewed_at: Optional[str] = None
    review_notes: Optional[str] = None
    applied_history_id: Optional[str] = None
    created_at: str
    updated_at: str


class AthenaRecommendationPatchBody(BaseModel):
    """Payload de PATCH /api/athena/recommendations/{id}.

    Workflow:
      - status='approved': humano aprovou; em seguida POST .../apply (AC-2) ou mark-applied manual
      - status='rejected': humano rejeitou; review_notes obrigatório se confidence>=0.85
      - status='superseded': recommendation mais nova substitui esta (raro, manual)
    """
    status: str = Field(pattern="^(approved|rejected|superseded)$")
    review_notes: Optional[str] = None


class AthenaRecommendationMarkAppliedBody(BaseModel):
    """Payload de POST /api/athena/recommendations/{id}/mark-applied.

    Humano marca após copiar manualmente o prompt da recommendation aprovada
    e aplicar via /agents/:id/edit. applied_history_id é opcional — se vier,
    linka pra row de agent_prompt_history criada pelo trigger.
    """
    applied_history_id: Optional[str] = None
    notes: Optional[str] = None


class ApplyRecommendationBody(BaseModel):
    """POST /api/athena/recommendations/{id}/apply — AC-2 v1."""

    dry_run: bool = False
    run_mcp_handshake: bool = True  # reservado bundle v2; ignorado em v1
    decisions: Optional[List[Dict[str, Any]]] = None  # reservado bundle v2


class ApplyRecommendationResult(BaseModel):
    status: str
    recommendation_id: str
    agent_id: Optional[str] = None
    created: Dict[str, Any] = Field(default_factory=dict)
    errors: Dict[str, str] = Field(default_factory=dict)


@router.get("/api/athena/recommendations")
@router.get("/athena/recommendations")
async def list_athena_recommendations(
    request: Request,
    status: Optional[str] = Query(None),
    target_agent_id: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Lista recommendations da company. RLS filtra cross-tenant automaticamente.

    Filtros opcionais via query string:
    - status: pending|approved|applied|rejected|superseded
    - target_agent_id: UUID
    - kind: ver docs/ATHENA-RECOMMENDATIONS.md (8 valores: 5 executáveis + 3 informativos)

    Ordenação: created_at DESC (mais recentes primeiro).
    """
    from src.api import supabase, get_authenticated_client

    if not supabase:
        return []
    if status and status not in _REC_DB_STATUSES:
        raise HTTPException(
            422,
            f"status inválido. Esperado: {sorted(_REC_DB_STATUSES)}",
        )
    if kind and kind not in _REC_VALID_KINDS:
        raise HTTPException(
            422,
            f"kind inválido. Esperado: {sorted(_REC_VALID_KINDS)}",
        )

    try:
        client = get_authenticated_client(request.state.token)
        q = (
            client.table("athena_recommendations")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if status:
            q = q.eq("status", status)
        if target_agent_id:
            q = q.eq("target_agent_id", target_agent_id)
        if kind:
            q = q.eq("kind", kind)
        res = q.execute()
        return [AthenaRecommendationOut(**row).model_dump() for row in (res.data or [])]
    except Exception as e:
        logger.error("athena.list_recommendations failed: %s", e)
        raise HTTPException(500, str(e))


@router.get("/api/athena/recommendations/{recommendation_id}")
@router.get("/athena/recommendations/{recommendation_id}")
async def get_athena_recommendation(request: Request, recommendation_id: str):
    """Get single recommendation. RLS valida company_id."""
    from src.api import supabase, get_authenticated_client

    if not supabase:
        raise HTTPException(404, "recommendation_not_found")
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("athena_recommendations")
            .select("*")
            .eq("id", recommendation_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(404, "recommendation_not_found")
        return AthenaRecommendationOut(**res.data[0]).model_dump()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("athena.get_recommendation failed: %s", e)
        raise HTTPException(500, str(e))


@router.patch("/api/athena/recommendations/{recommendation_id}")
@router.patch("/athena/recommendations/{recommendation_id}")
async def patch_athena_recommendation(
    request: Request,
    recommendation_id: str,
    body: AthenaRecommendationPatchBody,
):
    """Approve/reject/supersede recommendation.

    Workflow validations:
    - Só permite transições legais a partir do status atual:
      pending → approved | rejected | superseded
      approved → rejected | superseded | (mark-applied via outro endpoint)
      applied → (terminal — não muda mais)
      rejected → superseded
      superseded → (terminal)
    - status='rejected' com confidence>=0.85 exige review_notes (proteção contra
      rejeição leviana de recommendation de alta confiança)
    - Set automático: reviewed_at=now(), reviewed_by_user_id do JWT sub
    """
    from src.api import supabase, get_authenticated_client
    from datetime import datetime as _dt, timezone as _tz

    if not supabase:
        raise HTTPException(503, "supabase_required")

    try:
        client = get_authenticated_client(request.state.token)

        # 1) Pega estado atual (RLS valida acesso cross-tenant)
        existing = (
            client.table("athena_recommendations")
            .select("id,status,confidence,target_agent_id,kind")
            .eq("id", recommendation_id)
            .limit(1)
            .execute()
        )
        if not existing.data:
            raise HTTPException(404, "recommendation_not_found")
        current = existing.data[0]
        current_status = current["status"]
        new_status = body.status

        # 2) Valida transição
        legal_transitions = {
            "pending":    {"approved", "rejected", "superseded"},
            "approved":   {"rejected", "superseded"},
            "applied":    set(),  # terminal
            "rejected":   {"superseded"},
            "superseded": set(),  # terminal
        }
        if new_status not in legal_transitions.get(current_status, set()):
            raise HTTPException(
                409,
                f"transição ilegal {current_status} → {new_status}. "
                f"Legais a partir de '{current_status}': {sorted(legal_transitions.get(current_status, set()))}",
            )

        # 3) Validação: rejeição de alta confiança exige review_notes
        if new_status == "rejected" and float(current.get("confidence") or 0) >= 0.85:
            if not body.review_notes or len(body.review_notes.strip()) < 10:
                raise HTTPException(
                    422,
                    "review_notes obrigatório (≥10 chars) para rejeitar recommendation "
                    "com confidence >= 0.85",
                )

        # 4) Extrai user_id do JWT (sub claim)
        from src.api import _extract_vectraclip_claims
        import base64
        import json as _json2
        try:
            token = request.state.token
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            jwt_claims = _json2.loads(base64.b64decode(payload_b64))
            reviewer_id = jwt_claims.get("sub")
        except Exception:
            reviewer_id = None

        # 5) Update
        update_payload: Dict[str, Any] = {
            "status": new_status,
            "reviewed_at": _dt.now(_tz.utc).isoformat(),
            "reviewed_by_user_id": reviewer_id,
        }
        if body.review_notes:
            update_payload["review_notes"] = body.review_notes

        res = (
            client.table("athena_recommendations")
            .update(update_payload)
            .eq("id", recommendation_id)
            .execute()
        )
        if not res.data:
            raise HTTPException(500, "update returned empty")
        return AthenaRecommendationOut(**res.data[0]).model_dump()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("athena.patch_recommendation failed: %s", e)
        raise HTTPException(500, str(e))


@router.post("/api/athena/recommendations/{recommendation_id}/apply")
@router.post("/athena/recommendations/{recommendation_id}/apply")
async def apply_athena_recommendation(
    request: Request,
    recommendation_id: str,
    body: ApplyRecommendationBody,
):
    """Executa mutações do proposed_changes_json (5 kinds executáveis v1).

    Pré-requisito: status='approved' (PATCH antes).
    Kinds informativos → 422 kind_not_executable.
    dry_run=true valida sem persistir (recommendation permanece approved).
  """
    from fastapi.responses import JSONResponse

    from src.api import get_authenticated_client, supabase
    from src.services.athena_recommendation_apply import apply_athena_recommendation

    if not supabase:
        raise HTTPException(503, "supabase_required")

    try:
        client = get_authenticated_client(request.state.token)
        existing = (
            client.table("athena_recommendations")
            .select("*")
            .eq("id", recommendation_id)
            .limit(1)
            .execute()
        )
        if not existing.data:
            raise HTTPException(404, "recommendation_not_found")

        rec = existing.data[0]
        notes = None
        if body.dry_run:
            notes = "dry_run"

        result = apply_athena_recommendation(
            supabase,
            rec,
            dry_run=body.dry_run,
            review_notes_append=notes,
        )
        payload = ApplyRecommendationResult(**result).model_dump()

        if result["status"] in ("failed", "partial_apply"):
            return JSONResponse(status_code=422, content=payload)
        if result.get("errors") and result["status"] == "applied":
            # already_applied ou dry_run marker
            if result["errors"].get("status") == "already_applied":
                raise HTTPException(409, detail=payload)
        return payload
    except HTTPException:
        raise
    except Exception as e:
        logger.error("athena.apply_recommendation failed: %s", e)
        raise HTTPException(500, str(e))


@router.post("/api/athena/recommendations/{recommendation_id}/mark-applied")
@router.post("/athena/recommendations/{recommendation_id}/mark-applied")
async def mark_recommendation_applied(
    request: Request,
    recommendation_id: str,
    body: AthenaRecommendationMarkAppliedBody,
):
    """Marca recommendation aprovada como aplicada manualmente.

    Workflow:
    1. Recommendation precisa estar em status='approved' (PATCH approve antes)
    2. Humano copia o proposed_prompt e aplica via /agents/{id}/edit (trigger
       agent_prompt_history grava snapshot automaticamente)
    3. Chama este endpoint passando opcionalmente applied_history_id (UUID do
       history row criado pelo trigger)
    4. status vira 'applied', applied_history_id linkado

    Validação:
    - status atual precisa ser 'approved' (pending → mark-applied = ilegal,
      precisa aprovar antes)
    - applied_history_id, se fornecido, precisa existir em
      agent_prompt_history e referenciar o mesmo target_agent_id
    """
    from src.api import supabase, get_authenticated_client

    if not supabase:
        raise HTTPException(503, "supabase_required")

    try:
        client = get_authenticated_client(request.state.token)
        existing = (
            client.table("athena_recommendations")
            .select("id,status,target_agent_id")
            .eq("id", recommendation_id)
            .limit(1)
            .execute()
        )
        if not existing.data:
            raise HTTPException(404, "recommendation_not_found")
        current = existing.data[0]

        if current["status"] != "approved":
            raise HTTPException(
                409,
                f"mark-applied só permitido em status='approved'. Atual: '{current['status']}'. "
                f"Faça PATCH com status='approved' antes.",
            )

        # Validação opcional: applied_history_id consistente com target_agent_id
        if body.applied_history_id:
            hist = (
                client.table("agent_prompt_history")
                .select("id,agent_id")
                .eq("id", body.applied_history_id)
                .limit(1)
                .execute()
            )
            if not hist.data:
                raise HTTPException(
                    422,
                    f"applied_history_id={body.applied_history_id} não existe em agent_prompt_history",
                )
            if str(hist.data[0].get("agent_id")) != str(current.get("target_agent_id")):
                raise HTTPException(
                    409,
                    "applied_history_id referencia agent diferente do target_agent_id da recommendation",
                )

        update_payload: Dict[str, Any] = {"status": "applied"}
        if body.applied_history_id:
            update_payload["applied_history_id"] = body.applied_history_id
        if body.notes:
            update_payload["review_notes"] = (
                (current.get("review_notes") or "") + f"\n[mark-applied] {body.notes}"
            ).strip()

        res = (
            client.table("athena_recommendations")
            .update(update_payload)
            .eq("id", recommendation_id)
            .execute()
        )
        if not res.data:
            raise HTTPException(500, "update returned empty")
        return AthenaRecommendationOut(**res.data[0]).model_dump()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("athena.mark_applied failed: %s", e)
        raise HTTPException(500, str(e))


@router.post("/api/athena/monitor-workflows")
@router.post("/athena/monitor-workflows")
async def athena_monitor_workflows(request: Request):
    """Dispara a rotina de monitoramento Athena para a company do usuário.

    Consome telemetria dos últimos 30 dias e gera recommendations
    (`prompt_adjust`, `suggest_hire_agent`) quando thresholds são atingidos.
    Requer JWT válido (RLS filtra company_id).

    Retorna lista de recommendations criadas (pode ser vazia).
    """
    from src.api import supabase, get_authenticated_client
    from src.services.athena_monitor import monitor_workflows

    if not supabase:
        raise HTTPException(503, "supabase_required")

    try:
        client = get_authenticated_client(request.state.token)
        # Extrai company_id do JWT (padrão usado em outros endpoints)
        from src.api import _extract_vectraclip_claims
        claims = _extract_vectraclip_claims(request.state.token)
        company_id = claims.get("company_id")
        # Fallback para auth disabled (request.state.company_id setado no middleware)
        if not company_id:
            company_id = getattr(request.state, "company_id", None)
        if not company_id:
            raise HTTPException(403, "JWT sem company_id")

        recommendations = monitor_workflows(supabase, company_id)
        return {
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "company_id": company_id,
            "recommendations_created": len(recommendations),
            "recommendations": [AthenaRecommendationOut(**r).model_dump() for r in recommendations],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("athena.monitor_workflows failed: %s", e)
        raise HTTPException(500, str(e))
