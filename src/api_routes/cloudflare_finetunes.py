"""Endpoints para Cloudflare Workers AI.

Finetunes, modelos, tomarkdown e inferência direta (run, embeddings,
image-generation). Auth via middleware existente (request.state.user_id +
company_id). Account ID pode vir do adapter config da company ou de query
param (fallback admin).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field

from src.services import cloudflare_finetunes as cf_ft
from src.services import cloudflare_models as cf_models
from src.services import cloudflare_tomarkdown as cf_md
from src.services import cloudflare_inference as cf_inf
from src.services import cloudflare_ai_gateway as cf_ag
from src.services import cloudflare_ai_search as cf_as
from src.services import cloudflare_browser_rendering as cf_br

logger = logging.getLogger("api.cloudflare_finetunes")
router = APIRouter(tags=["cloudflare-finetunes"])

_ADMIN_ROLES = {"admin", "owner", "root"}


def _resolve_caller(request: Request) -> tuple[str, str, Optional[str]]:
    company_id = getattr(request.state, "company_id", None)
    user_id = getattr(request.state, "user_id", None)
    role = getattr(request.state, "role", None) or getattr(
        request.state, "user_role", None
    )
    if not company_id or not user_id:
        raise HTTPException(status_code=401, detail="unauthenticated")
    return str(company_id), str(user_id), (str(role) if role else None)


def _is_admin(role: Optional[str]) -> bool:
    return (role or "").lower() in _ADMIN_ROLES


def _resolve_account_id(request: Request, account_id: Optional[str] = None) -> str:
    """Account ID: query param (admin) > adapter config > env > erro."""
    _, _, role = _resolve_caller(request)
    if account_id:
        if not _is_admin(role):
            raise HTTPException(status_code=403, detail="admin_required_for_account_override")
        return account_id
    # Tenta ler do adapter config da company (cloudflare_ai)
    company_id = getattr(request.state, "company_id", None)
    if company_id:
        try:
            from src.api import supabase
            if supabase:
                res = (
                    supabase.table("company_adapter_values")
                    .select("field_values_json")
                    .eq("company_id", company_id)
                    .execute()
                )
                for row in res.data or []:
                    fv = row.get("field_values_json") or {}
                    if isinstance(fv, str):
                        import json
                        fv = json.loads(fv)
                    if fv.get("account_id"):
                        return str(fv["account_id"])
        except Exception as e:
            logger.debug("adapter lookup account_id failed: %s", e)
    # Fallback env
    import os
    env_acc = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    if env_acc:
        return env_acc
    raise HTTPException(status_code=400, detail="cloudflare_account_id_required")


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/cloudflare/finetunes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/cloudflare/finetunes")
async def list_finetunes(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Lista todos os finetuning jobs da conta Cloudflare."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ft.list_finetunes(acc)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("list_finetunes failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/cloudflare/finetunes
# ─────────────────────────────────────────────────────────────────────────────

class FinetuneCreateBody(BaseModel):
    model: str = Field(..., min_length=1, description="Modelo base (ex: @cf/meta/llama-3.1-8b-instruct)")
    name: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = Field(default=None, max_length=2048)
    public: Optional[bool] = Field(default=None)


@router.post("/api/cloudflare/finetunes")
async def create_finetune(
    request: Request,
    body: FinetuneCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Cria um novo fine-tuning job."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ft.create_finetune(
            acc,
            model=body.model,
            name=body.name,
            description=body.description,
            public=body.public,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_finetune failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/cloudflare/finetunes/{finetune_id}/assets
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/cloudflare/finetunes/{finetune_id}/assets")
async def upload_finetune_asset(
    request: Request,
    finetune_id: str,
    file: UploadFile = File(...),
    file_name: Optional[str] = Query(default=None, description="Nome do arquivo. Default: upload filename"),
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Faz upload de training data asset para um finetune job."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    fname = file_name or file.filename or "asset.bin"
    try:
        contents = await file.read()
        return await cf_ft.upload_asset(acc, finetune_id, file_bytes=contents, file_name=fname)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("upload_finetune_asset failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/cloudflare/finetunes/public
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/cloudflare/finetunes/public")
async def list_public_finetunes(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
    limit: Optional[int] = Query(default=None, ge=1, le=1000),
    offset: Optional[int] = Query(default=None, ge=0),
    order_by: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Lista finetunes públicos disponíveis na Workers AI."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ft.list_public_finetunes(
            acc, limit=limit, offset=offset, order_by=order_by
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("list_public_finetunes failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/cloudflare/models
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/cloudflare/models")
async def search_models(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
    author: Optional[str] = Query(default=None),
    format: Optional[str] = Query(default=None, description='"openrouter" ou omitir'),
    hide_experimental: Optional[bool] = Query(default=None),
    page: Optional[int] = Query(default=None, ge=1),
    per_page: Optional[int] = Query(default=None, ge=1, le=1000),
    search: Optional[str] = Query(default=None, description="Termo de busca por nome/desc"),
    source: Optional[int] = Query(default=None),
    task: Optional[str] = Query(default=None, description="Filtrar por task (ex: text-generation)"),
) -> Dict[str, Any]:
    """Busca modelos Workers AI por nome, descrição, autor ou task."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_models.search_models(
            acc,
            author=author,
            format=format,
            hide_experimental=hide_experimental,
            page=page,
            per_page=per_page,
            search=search,
            source=source,
            task=task,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("search_models failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/cloudflare/models/schema
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/cloudflare/models/schema")
async def get_model_schema(
    request: Request,
    model: str = Query(..., min_length=1, description="Nome do modelo (ex: @cf/meta/llama-3.1-8b-instruct)"),
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna o JSON Schema de input/output de um modelo Workers AI."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_models.get_model_schema(acc, model=model)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_model_schema failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/cloudflare/tomarkdown
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api/cloudflare/tomarkdown")
async def transform_to_markdown(
    request: Request,
    files: List[UploadFile] = File(..., description="Arquivos para converter em Markdown"),
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Converte arquivos para Markdown usando Workers AI."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        file_bytes = []
        file_names = []
        for f in files:
            file_bytes.append(await f.read())
            file_names.append(f.filename or "file.bin")
        return await cf_md.transform_to_markdown(acc, files=file_bytes, file_names=file_names)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("transform_to_markdown failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/cloudflare/tomarkdown/supported
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/cloudflare/tomarkdown/supported")
async def list_supported_formats(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Lista formatos de arquivo suportados para conversão em Markdown."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_md.list_supported_formats(acc)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("list_supported_formats failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/cloudflare/run — inferência texto / chat
# ─────────────────────────────────────────────────────────────────────────────

class RunMessage(BaseModel):
    role: str = Field(..., min_length=1, description="ex: user, assistant, system")
    content: str = Field(..., min_length=1)


class RunInferenceBody(BaseModel):
    model: str = Field(..., min_length=1, description="ex: @cf/meta/llama-3.1-8b-instruct")
    messages: List[RunMessage] = Field(..., min_length=1)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    temperature: Optional[float] = Field(default=None, ge=0.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    top_k: Optional[int] = Field(default=None, ge=1)
    seed: Optional[int] = Field(default=None)
    repetition_penalty: Optional[float] = Field(default=None, ge=0.0)
    frequency_penalty: Optional[float] = Field(default=None)
    presence_penalty: Optional[float] = Field(default=None)
    raw: Optional[bool] = Field(default=None)
    stream: Optional[bool] = Field(default=None)


@router.post("/api/cloudflare/run")
async def run_inference(
    request: Request,
    body: RunInferenceBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Executa inferência em um modelo Workers AI (text-generation / chat)."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_inf.run_inference(
            acc,
            model=body.model,
            messages=[m.model_dump() for m in body.messages],
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            top_p=body.top_p,
            top_k=body.top_k,
            seed=body.seed,
            repetition_penalty=body.repetition_penalty,
            frequency_penalty=body.frequency_penalty,
            presence_penalty=body.presence_penalty,
            raw=body.raw,
            stream=body.stream,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("run_inference failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/cloudflare/embeddings
# ─────────────────────────────────────────────────────────────────────────────

class EmbeddingsBody(BaseModel):
    model: str = Field(..., min_length=1, description="ex: @cf/baai/bge-base-en-v1.5")
    text: List[str] = Field(..., min_length=1)


@router.post("/api/cloudflare/embeddings")
async def create_embeddings(
    request: Request,
    body: EmbeddingsBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Gera embeddings para uma lista de textos."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_inf.create_embeddings(acc, model=body.model, text=body.text)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_embeddings failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/cloudflare/images/generate
# ─────────────────────────────────────────────────────────────────────────────

class ImageGenerateBody(BaseModel):
    model: str = Field(..., min_length=1, description="ex: @cf/stabilityai/stable-diffusion-xl-base-1.0")
    prompt: str = Field(..., min_length=1)
    num_steps: Optional[int] = Field(default=None, ge=1, le=50)
    guidance: Optional[float] = Field(default=None, ge=0.0)
    strength: Optional[float] = Field(default=None, ge=0.0, le=1.0)


@router.post("/api/cloudflare/images/generate")
async def generate_image(
    request: Request,
    body: ImageGenerateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Response:
    """Gera uma imagem via Workers AI e retorna os bytes brutos (PNG/JPEG)."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        image_bytes = await cf_inf.generate_image(
            acc,
            model=body.model,
            prompt=body.prompt,
            num_steps=body.num_steps,
            guidance=body.guidance,
            strength=body.strength,
        )
        return Response(content=image_bytes, media_type="image/png")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("generate_image failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/cloudflare/ai-gateway/evaluation-types
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/cloudflare/ai-gateway/evaluation-types")
async def list_ai_gateway_evaluation_types(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
    order_by: Optional[str] = Query(default=None),
    order_by_direction: Optional[str] = Query(default=None, description="asc ou desc"),
    page: Optional[int] = Query(default=None, ge=1),
    per_page: Optional[int] = Query(default=None, ge=1, le=1000),
) -> Dict[str, Any]:
    """Lista evaluation types do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.list_evaluation_types(
            acc,
            order_by=order_by,
            order_by_direction=order_by_direction,
            page=page,
            per_page=per_page,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("list_ai_gateway_evaluation_types failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# AI Gateway Logs
# ─────────────────────────────────────────────────────────────────────────────

# ── GET /api/cloudflare/ai-gateway/gateways/{gateway_id}/url/{provider} ──────

@router.get("/api/cloudflare/ai-gateway/gateways/{gateway_id}/url/{provider}")
async def get_ai_gateway_url(
    request: Request,
    gateway_id: str,
    provider: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
):
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.get_gateway_url(acc, gateway_id, provider)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_gateway_url failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/ai-gateway/gateways/{gateway_id}/logs ────────────────

@router.get("/api/cloudflare/ai-gateway/gateways/{gateway_id}/logs")
async def list_ai_gateway_logs(
    request: Request,
    gateway_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
    cached: Optional[bool] = Query(default=None),
    direction: Optional[str] = Query(default=None, description="asc ou desc"),
    end_date: Optional[str] = Query(default=None),
    feedback: Optional[int] = Query(default=None, ge=0, le=1),
    max_cost: Optional[float] = Query(default=None, ge=0.0),
    max_duration: Optional[float] = Query(default=None, ge=0.0),
    max_tokens_in: Optional[float] = Query(default=None, ge=0.0),
    max_tokens_out: Optional[float] = Query(default=None, ge=0.0),
    max_total_tokens: Optional[float] = Query(default=None, ge=0.0),
    meta_info: Optional[bool] = Query(default=None),
    min_cost: Optional[float] = Query(default=None, ge=0.0),
    min_duration: Optional[float] = Query(default=None, ge=0.0),
    min_tokens_in: Optional[float] = Query(default=None, ge=0.0),
    min_tokens_out: Optional[float] = Query(default=None, ge=0.0),
    min_total_tokens: Optional[float] = Query(default=None, ge=0.0),
    model: Optional[str] = Query(default=None),
    model_type: Optional[str] = Query(default=None),
    order_by: Optional[str] = Query(default=None),
    order_by_direction: Optional[str] = Query(default=None, description="asc ou desc"),
    page: Optional[int] = Query(default=None, ge=1),
    per_page: Optional[int] = Query(default=None, ge=1, le=1000),
    provider: Optional[str] = Query(default=None),
    request_content_type: Optional[str] = Query(default=None),
    response_content_type: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    start_date: Optional[str] = Query(default=None),
    success: Optional[bool] = Query(default=None),
) -> Dict[str, Any]:
    """Lista logs de um AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.list_logs(
            acc,
            gateway_id,
            cached=cached,
            direction=direction,
            end_date=end_date,
            feedback=feedback,
            max_cost=max_cost,
            max_duration=max_duration,
            max_tokens_in=max_tokens_in,
            max_tokens_out=max_tokens_out,
            max_total_tokens=max_total_tokens,
            meta_info=meta_info,
            min_cost=min_cost,
            min_duration=min_duration,
            min_tokens_in=min_tokens_in,
            min_tokens_out=min_tokens_out,
            min_total_tokens=min_total_tokens,
            model=model,
            model_type=model_type,
            order_by=order_by,
            order_by_direction=order_by_direction,
            page=page,
            per_page=per_page,
            provider=provider,
            request_content_type=request_content_type,
            response_content_type=response_content_type,
            search=search,
            start_date=start_date,
            success=success,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("list_ai_gateway_logs failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/ai-gateway/gateways/{gateway_id}/logs/{log_id} ───────

@router.get("/api/cloudflare/ai-gateway/gateways/{gateway_id}/logs/{log_id}")
async def get_ai_gateway_log(
    request: Request,
    gateway_id: str,
    log_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna detalhes de um log do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.get_log(acc, gateway_id, log_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_gateway_log failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── PATCH /api/cloudflare/ai-gateway/gateways/{gateway_id}/logs/{log_id} ─────

class LogPatchBody(BaseModel):
    feedback: Optional[float] = Field(default=None)
    metadata: Optional[Dict[str, Any]] = Field(default=None)
    score: Optional[float] = Field(default=None)


@router.patch("/api/cloudflare/ai-gateway/gateways/{gateway_id}/logs/{log_id}")
async def update_ai_gateway_log(
    request: Request,
    gateway_id: str,
    log_id: str,
    body: LogPatchBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Atualiza metadata/feedback de um log do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.update_log(
            acc,
            gateway_id,
            log_id,
            feedback=body.feedback,
            metadata=body.metadata,
            score=body.score,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("update_ai_gateway_log failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── DELETE /api/cloudflare/ai-gateway/gateways/{gateway_id}/logs ─────────────

@router.delete("/api/cloudflare/ai-gateway/gateways/{gateway_id}/logs")
async def delete_ai_gateway_logs(
    request: Request,
    gateway_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
    limit: Optional[int] = Query(default=None, ge=1),
    order_by: Optional[str] = Query(default=None),
    order_by_direction: Optional[str] = Query(default=None, description="asc ou desc"),
) -> Dict[str, Any]:
    """Deleta logs de um AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.delete_logs(
            acc,
            gateway_id,
            limit=limit,
            order_by=order_by,
            order_by_direction=order_by_direction,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("delete_ai_gateway_logs failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/ai-gateway/gateways/{gateway_id}/logs/{log_id}/request

@router.get("/api/cloudflare/ai-gateway/gateways/{gateway_id}/logs/{log_id}/request")
async def get_ai_gateway_log_request(
    request: Request,
    gateway_id: str,
    log_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna o request payload original de um log do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.get_log_request(acc, gateway_id, log_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_gateway_log_request failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/ai-gateway/gateways/{gateway_id}/logs/{log_id}/response

@router.get("/api/cloudflare/ai-gateway/gateways/{gateway_id}/logs/{log_id}/response")
async def get_ai_gateway_log_response(
    request: Request,
    gateway_id: str,
    log_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna o response payload de um log do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.get_log_response(acc, gateway_id, log_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_gateway_log_response failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# AI Gateway Datasets
# ─────────────────────────────────────────────────────────────────────────────

class DatasetFilter(BaseModel):
    key: str = Field(..., min_length=1)
    operator: str = Field(..., min_length=1)
    value: List[Any] = Field(..., min_length=1)


class DatasetCreateBody(BaseModel):
    enable: bool = Field(...)
    filters: List[DatasetFilter] = Field(..., min_length=1)
    name: str = Field(..., min_length=1)


class DatasetUpdateBody(BaseModel):
    enable: bool = Field(...)
    filters: List[DatasetFilter] = Field(..., min_length=1)
    name: str = Field(..., min_length=1)


# ── GET /api/cloudflare/ai-gateway/gateways/{gateway_id}/datasets ────────────

@router.get("/api/cloudflare/ai-gateway/gateways/{gateway_id}/datasets")
async def list_ai_gateway_datasets(
    request: Request,
    gateway_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
    enable: Optional[bool] = Query(default=None),
    name: Optional[str] = Query(default=None),
    page: Optional[int] = Query(default=None, ge=1),
    per_page: Optional[int] = Query(default=None, ge=1, le=1000),
    search: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Lista datasets de um AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.list_datasets(
            acc,
            gateway_id,
            enable=enable,
            name=name,
            page=page,
            per_page=per_page,
            search=search,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("list_ai_gateway_datasets failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/ai-gateway/gateways/{gateway_id}/datasets/{dataset_id}

@router.get("/api/cloudflare/ai-gateway/gateways/{gateway_id}/datasets/{dataset_id}")
async def get_ai_gateway_dataset(
    request: Request,
    gateway_id: str,
    dataset_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna detalhes de um dataset do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.get_dataset(acc, gateway_id, dataset_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_gateway_dataset failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/ai-gateway/gateways/{gateway_id}/datasets ───────────

@router.post("/api/cloudflare/ai-gateway/gateways/{gateway_id}/datasets")
async def create_ai_gateway_dataset(
    request: Request,
    gateway_id: str,
    body: DatasetCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Cria um novo dataset no AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.create_dataset(
            acc,
            gateway_id,
            enable=body.enable,
            filters=[f.model_dump() for f in body.filters],
            name=body.name,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_ai_gateway_dataset failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── PUT /api/cloudflare/ai-gateway/gateways/{gateway_id}/datasets/{dataset_id}

@router.put("/api/cloudflare/ai-gateway/gateways/{gateway_id}/datasets/{dataset_id}")
async def update_ai_gateway_dataset(
    request: Request,
    gateway_id: str,
    dataset_id: str,
    body: DatasetUpdateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Atualiza um dataset do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.update_dataset(
            acc,
            gateway_id,
            dataset_id,
            enable=body.enable,
            filters=[f.model_dump() for f in body.filters],
            name=body.name,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("update_ai_gateway_dataset failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── DELETE /api/cloudflare/ai-gateway/gateways/{gateway_id}/datasets/{dataset_id}

@router.delete("/api/cloudflare/ai-gateway/gateways/{gateway_id}/datasets/{dataset_id}")
async def delete_ai_gateway_dataset(
    request: Request,
    gateway_id: str,
    dataset_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Deleta um dataset do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.delete_dataset(acc, gateway_id, dataset_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("delete_ai_gateway_dataset failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# AI Gateway Evaluations
# ─────────────────────────────────────────────────────────────────────────────

class EvaluationCreateBody(BaseModel):
    dataset_ids: List[str] = Field(..., min_length=1)
    evaluation_type_ids: List[str] = Field(..., min_length=1)
    name: str = Field(..., min_length=1)


# ── GET /api/cloudflare/ai-gateway/gateways/{gateway_id}/evaluations ─────────

@router.get("/api/cloudflare/ai-gateway/gateways/{gateway_id}/evaluations")
async def list_ai_gateway_evaluations(
    request: Request,
    gateway_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
    name: Optional[str] = Query(default=None),
    page: Optional[int] = Query(default=None, ge=1),
    per_page: Optional[int] = Query(default=None, ge=1, le=1000),
    processed: Optional[bool] = Query(default=None),
    search: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Lista evaluations de um AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.list_evaluations(
            acc,
            gateway_id,
            name=name,
            page=page,
            per_page=per_page,
            processed=processed,
            search=search,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("list_ai_gateway_evaluations failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/ai-gateway/gateways/{gateway_id}/evaluations/{evaluation_id}

@router.get("/api/cloudflare/ai-gateway/gateways/{gateway_id}/evaluations/{evaluation_id}")
async def get_ai_gateway_evaluation(
    request: Request,
    gateway_id: str,
    evaluation_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna detalhes de uma evaluation do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.get_evaluation(acc, gateway_id, evaluation_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_gateway_evaluation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/ai-gateway/gateways/{gateway_id}/evaluations ────────

@router.post("/api/cloudflare/ai-gateway/gateways/{gateway_id}/evaluations")
async def create_ai_gateway_evaluation(
    request: Request,
    gateway_id: str,
    body: EvaluationCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Cria uma nova evaluation no AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.create_evaluation(
            acc,
            gateway_id,
            dataset_ids=body.dataset_ids,
            evaluation_type_ids=body.evaluation_type_ids,
            name=body.name,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_ai_gateway_evaluation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── DELETE /api/cloudflare/ai-gateway/gateways/{gateway_id}/evaluations/{evaluation_id}

@router.delete("/api/cloudflare/ai-gateway/gateways/{gateway_id}/evaluations/{evaluation_id}")
async def delete_ai_gateway_evaluation(
    request: Request,
    gateway_id: str,
    evaluation_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Deleta uma evaluation do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.delete_evaluation(acc, gateway_id, evaluation_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("delete_ai_gateway_evaluation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# AI Gateway Dynamic Routing
# ─────────────────────────────────────────────────────────────────────────────

class RouteCreateBody(BaseModel):
    elements: List[Dict[str, Any]] = Field(..., min_length=1)
    name: str = Field(..., min_length=1)


class RouteUpdateBody(BaseModel):
    name: str = Field(..., min_length=1)


class RouteDeploymentCreateBody(BaseModel):
    version_id: str = Field(..., min_length=1)


class RouteVersionCreateBody(BaseModel):
    elements: List[Dict[str, Any]] = Field(..., min_length=1)


# ── GET /api/cloudflare/ai-gateway/gateways/{gateway_id}/routes ──────────────

@router.get("/api/cloudflare/ai-gateway/gateways/{gateway_id}/routes")
async def list_ai_gateway_routes(
    request: Request,
    gateway_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
    page: Optional[int] = Query(default=None, ge=1),
    per_page: Optional[int] = Query(default=None, ge=1, le=1000),
) -> Dict[str, Any]:
    """Lista dynamic routes de um AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.list_routes(acc, gateway_id, page=page, per_page=per_page)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("list_ai_gateway_routes failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}

@router.get("/api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}")
async def get_ai_gateway_route(
    request: Request,
    gateway_id: str,
    route_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna detalhes de uma dynamic route do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.get_route(acc, gateway_id, route_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_gateway_route failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/ai-gateway/gateways/{gateway_id}/routes ─────────────

@router.post("/api/cloudflare/ai-gateway/gateways/{gateway_id}/routes")
async def create_ai_gateway_route(
    request: Request,
    gateway_id: str,
    body: RouteCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Cria uma nova dynamic route no AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.create_route(
            acc,
            gateway_id,
            elements=body.elements,
            name=body.name,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_ai_gateway_route failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── PATCH /api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}

@router.patch("/api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}")
async def update_ai_gateway_route(
    request: Request,
    gateway_id: str,
    route_id: str,
    body: RouteUpdateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Atualiza o nome de uma dynamic route do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.update_route(acc, gateway_id, route_id, name=body.name)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("update_ai_gateway_route failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── DELETE /api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}

@router.delete("/api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}")
async def delete_ai_gateway_route(
    request: Request,
    gateway_id: str,
    route_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Deleta uma dynamic route do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.delete_route(acc, gateway_id, route_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("delete_ai_gateway_route failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}/deployments

@router.get("/api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}/deployments")
async def list_ai_gateway_route_deployments(
    request: Request,
    gateway_id: str,
    route_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Lista deployments de uma dynamic route."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.list_route_deployments(acc, gateway_id, route_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("list_ai_gateway_route_deployments failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}/deployments

@router.post("/api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}/deployments")
async def create_ai_gateway_route_deployment(
    request: Request,
    gateway_id: str,
    route_id: str,
    body: RouteDeploymentCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Cria um deployment para uma dynamic route."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.create_route_deployment(
            acc,
            gateway_id,
            route_id,
            version_id=body.version_id,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_ai_gateway_route_deployment failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}/versions

@router.get("/api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}/versions")
async def list_ai_gateway_route_versions(
    request: Request,
    gateway_id: str,
    route_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Lista versions de uma dynamic route."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.list_route_versions(acc, gateway_id, route_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("list_ai_gateway_route_versions failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}/versions

@router.post("/api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}/versions")
async def create_ai_gateway_route_version(
    request: Request,
    gateway_id: str,
    route_id: str,
    body: RouteVersionCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Cria uma nova version para uma dynamic route."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.create_route_version(
            acc,
            gateway_id,
            route_id,
            elements=body.elements,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_ai_gateway_route_version failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}/versions/{version_id}

@router.get("/api/cloudflare/ai-gateway/gateways/{gateway_id}/routes/{route_id}/versions/{version_id}")
async def get_ai_gateway_route_version(
    request: Request,
    gateway_id: str,
    route_id: str,
    version_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna detalhes de uma version de dynamic route."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.get_route_version(acc, gateway_id, route_id, version_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_gateway_route_version failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# AI Gateway Provider Configs
# ─────────────────────────────────────────────────────────────────────────────

class ProviderConfigCreateBody(BaseModel):
    alias: str = Field(..., min_length=1)
    default_config: bool = Field(...)
    provider_slug: str = Field(..., min_length=1)
    secret: str = Field(..., min_length=1)
    secret_id: str = Field(..., min_length=1)
    rate_limit: Optional[float] = Field(default=None, ge=0.0)
    rate_limit_period: Optional[float] = Field(default=None, ge=0.0)


# ── GET /api/cloudflare/ai-gateway/gateways/{gateway_id}/provider-configs ────

@router.get("/api/cloudflare/ai-gateway/gateways/{gateway_id}/provider-configs")
async def list_ai_gateway_provider_configs(
    request: Request,
    gateway_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
    page: Optional[int] = Query(default=None, ge=1),
    per_page: Optional[int] = Query(default=None, ge=1, le=1000),
) -> Dict[str, Any]:
    """Lista provider configs de um AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.list_provider_configs(acc, gateway_id, page=page, per_page=per_page)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("list_ai_gateway_provider_configs failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/ai-gateway/gateways/{gateway_id}/provider-configs ───

@router.post("/api/cloudflare/ai-gateway/gateways/{gateway_id}/provider-configs")
async def create_ai_gateway_provider_config(
    request: Request,
    gateway_id: str,
    body: ProviderConfigCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Cria uma nova provider config no AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.create_provider_config(
            acc,
            gateway_id,
            alias=body.alias,
            default_config=body.default_config,
            provider_slug=body.provider_slug,
            secret=body.secret,
            secret_id=body.secret_id,
            rate_limit=body.rate_limit,
            rate_limit_period=body.rate_limit_period,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_ai_gateway_provider_config failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# AI Gateway Billing
# ─────────────────────────────────────────────────────────────────────────────

class PaymentMethod(BaseModel):
    brand: Optional[str] = None
    last4: Optional[str] = None


class TopupConfig(BaseModel):
    amount: Optional[float] = None
    disabled_reason: Optional[str] = None
    error: Optional[str] = None
    last_failed_at: Optional[float] = None
    threshold: Optional[float] = None


class CreditBalanceResponse(BaseModel):
    balance: float
    has_default_payment_method: bool
    payment_method: Optional[PaymentMethod] = None
    topup_config: TopupConfig
    first_topup_success: Optional[bool] = None


class UsageHistoryItem(BaseModel):
    id: str
    aggregated_value: float
    end_time: float
    start_time: float


class UsageHistoryResponse(BaseModel):
    history: List[UsageHistoryItem]


class Invoice(BaseModel):
    amount_due: float
    amount_paid: float
    amount_remaining: float
    currency: str
    id: Optional[str] = None
    attempt_count: Optional[float] = None
    attempted: Optional[bool] = None
    auto_advance: Optional[bool] = None
    created: Optional[float] = None
    created_by: Optional[str] = None
    description: Optional[str] = None
    invoice_origin: Optional[str] = None
    invoice_pdf: Optional[str] = None
    status: Optional[str] = None


class Pagination(BaseModel):
    has_more: bool
    page: float
    per_page: float
    total_count: float


class InvoiceHistoryResponse(BaseModel):
    invoices: List[Invoice]
    pagination: Pagination


class InvoiceLinePeriod(BaseModel):
    end: float
    start: float


class InvoiceLinePricing(BaseModel):
    unit_amount_decimal: Optional[str] = None


class InvoiceLinePretaxCreditAmount(BaseModel):
    amount: float
    type: str
    credit_balance_transaction: Optional[str] = None
    discount: Optional[str] = None


class InvoiceLine(BaseModel):
    amount: float
    currency: str
    description: Optional[str] = None
    period: InvoiceLinePeriod
    pricing: InvoiceLinePricing
    quantity: float
    pretax_credit_amounts: Optional[List[InvoiceLinePretaxCreditAmount]] = None


class InvoicePreviewResponse(BaseModel):
    id: str
    amount_due: float
    amount_paid: float
    amount_remaining: float
    currency: str
    invoice_lines: List[InvoiceLine]
    period_end: float
    period_start: float
    status: str


# ── GET /api/cloudflare/ai-gateway/billing/credit-balance ────────────────────

@router.get("/api/cloudflare/ai-gateway/billing/credit-balance", response_model=CreditBalanceResponse)
async def get_ai_gateway_credit_balance(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna saldo de créditos, método de pagamento e config de auto top-up."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.get_credit_balance(acc)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_gateway_credit_balance failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/ai-gateway/billing/usage-history ─────────────────────

@router.get("/api/cloudflare/ai-gateway/billing/usage-history", response_model=UsageHistoryResponse)
async def get_ai_gateway_usage_history(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
    value_grouping_window: str = Query(..., description="day or hour"),
    start_time: Optional[float] = Query(default=None, description="Unix timestamp ms"),
    end_time: Optional[float] = Query(default=None, description="Unix timestamp ms"),
) -> Dict[str, Any]:
    """Retorna histórico de uso agregado do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.get_usage_history(
            acc,
            value_grouping_window=value_grouping_window,
            start_time=start_time,
            end_time=end_time,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_gateway_usage_history failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/ai-gateway/billing/invoice-history ───────────────────

@router.get("/api/cloudflare/ai-gateway/billing/invoice-history", response_model=InvoiceHistoryResponse)
async def get_ai_gateway_invoice_history(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
    type_: Optional[str] = Query(default=None, alias="type", description="auto, manual, all"),
) -> Dict[str, Any]:
    """Retorna histórico de faturas do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.get_invoice_history(acc, type_=type_)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_gateway_invoice_history failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/ai-gateway/billing/invoice-preview ───────────────────

@router.get("/api/cloudflare/ai-gateway/billing/invoice-preview", response_model=InvoicePreviewResponse)
async def get_ai_gateway_invoice_preview(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna preview da próxima fatura do AI Gateway."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.get_invoice_preview(acc)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_gateway_invoice_preview failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# AI Gateway Topup
# ─────────────────────────────────────────────────────────────────────────────

class TopupCreateBody(BaseModel):
    amount: int = Field(..., ge=1000, description="Top-up amount in cents")


class TopupStatusBody(BaseModel):
    payment_intent_id: str = Field(..., min_length=1)


class TopupCreateResponse(BaseModel):
    client_secret: Optional[str] = None
    onboarding: bool
    payment_intent_id: str
    brand: Optional[str] = None
    last4: Optional[str] = None


class TopupStatusResponse(BaseModel):
    payment_intent_id: str
    status: str = Field(..., pattern="^(completed|pending)$")


# ── POST /api/cloudflare/ai-gateway/billing/topup ────────────────────────────

@router.post("/api/cloudflare/ai-gateway/billing/topup", response_model=TopupCreateResponse)
async def create_ai_gateway_topup(
    request: Request,
    body: TopupCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Cria um top-up de créditos via Stripe PaymentIntent."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.create_topup(acc, amount=body.amount)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_ai_gateway_topup failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/ai-gateway/billing/topup/status ─────────────────────

@router.post("/api/cloudflare/ai-gateway/billing/topup/status", response_model=TopupStatusResponse)
async def get_ai_gateway_topup_status(
    request: Request,
    body: TopupStatusBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Verifica status de processamento de um top-up."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.get_topup_status(acc, payment_intent_id=body.payment_intent_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_gateway_topup_status failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# AI Gateway Topup Config
# ─────────────────────────────────────────────────────────────────────────────

class TopupConfigCreateBody(BaseModel):
    amount: int = Field(..., ge=1000, description="Auto top-up amount in cents")
    threshold: int = Field(..., ge=500, description="Balance threshold in cents")


class ConfigGetResponse(BaseModel):
    amount: Optional[float] = None
    disabled_reason: Optional[str] = None
    error: Optional[str] = None
    last_failed_at: Optional[float] = None
    threshold: Optional[float] = None


class ConfigCreateResponse(BaseModel):
    amount: float
    threshold: float


# ── GET /api/cloudflare/ai-gateway/billing/topup/config ──────────────────────

@router.get("/api/cloudflare/ai-gateway/billing/topup/config", response_model=ConfigGetResponse)
async def get_ai_gateway_topup_config(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna configuração de auto top-up."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.get_topup_config(acc)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_gateway_topup_config failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/ai-gateway/billing/topup/config ─────────────────────

@router.post("/api/cloudflare/ai-gateway/billing/topup/config", response_model=ConfigCreateResponse)
async def create_ai_gateway_topup_config(
    request: Request,
    body: TopupConfigCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Configura auto top-up com threshold e amount."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.create_topup_config(acc, amount=body.amount, threshold=body.threshold)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_ai_gateway_topup_config failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── DELETE /api/cloudflare/ai-gateway/billing/topup/config ───────────────────

@router.delete("/api/cloudflare/ai-gateway/billing/topup/config")
async def delete_ai_gateway_topup_config(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Remove configuração de auto top-up."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.delete_topup_config(acc)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("delete_ai_gateway_topup_config failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# AI Gateway Spending Limit
# ─────────────────────────────────────────────────────────────────────────────

class SpendingLimitConfig(BaseModel):
    amount: Optional[float] = None
    duration: Optional[str] = None
    strategy: Optional[str] = None


class SpendingLimitGetResponse(BaseModel):
    config: SpendingLimitConfig
    enabled: bool


class SpendingLimitCreateBody(BaseModel):
    amount: int = Field(..., ge=100, description="Spending limit in cents")
    duration: str = Field(..., pattern="^(daily|weekly|monthly)$")
    strategy: str = Field(..., pattern="^(fixed|sliding)$")


# ── GET /api/cloudflare/ai-gateway/billing/spending-limit ────────────────────

@router.get("/api/cloudflare/ai-gateway/billing/spending-limit", response_model=SpendingLimitGetResponse)
async def get_ai_gateway_spending_limit(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna configuração de spending limit."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.get_spending_limit(acc)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_gateway_spending_limit failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/ai-gateway/billing/spending-limit ───────────────────

@router.post("/api/cloudflare/ai-gateway/billing/spending-limit")
async def create_ai_gateway_spending_limit(
    request: Request,
    body: SpendingLimitCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Configura spending limit com amount, duration e strategy."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.create_spending_limit(
            acc, amount=body.amount, duration=body.duration, strategy=body.strategy
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_ai_gateway_spending_limit failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── DELETE /api/cloudflare/ai-gateway/billing/spending-limit ─────────────────

@router.delete("/api/cloudflare/ai-gateway/billing/spending-limit")
async def delete_ai_gateway_spending_limit(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Remove spending limit."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_ag.delete_spending_limit(acc)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("delete_ai_gateway_spending_limit failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# AI Search Tokens
# ─────────────────────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    id: str
    cf_api_id: str
    created_at: str
    modified_at: str
    name: str
    created_by: Optional[str] = None
    enabled: Optional[bool] = None
    legacy: Optional[bool] = None
    modified_by: Optional[str] = None


class TokenCreateBody(BaseModel):
    cf_api_id: str = Field(..., min_length=1)
    cf_api_key: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    legacy: Optional[bool] = None


class TokenUpdateBody(BaseModel):
    cf_api_id: str = Field(..., min_length=1)
    cf_api_key: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    legacy: Optional[bool] = None


# ── GET /api/cloudflare/ai-search/tokens ─────────────────────────────────────

@router.get("/api/cloudflare/ai-search/tokens")
async def list_ai_search_tokens(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
    page: Optional[int] = Query(default=None, ge=1),
    per_page: Optional[int] = Query(default=None, ge=1, le=1000),
    search: Optional[str] = Query(default=None, description="Filter by name (case-insensitive)"),
) -> Dict[str, Any]:
    """Lista tokens de AI Search."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_as.list_tokens(acc, page=page, per_page=per_page, search=search)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("list_ai_search_tokens failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/ai-search/tokens ────────────────────────────────────

@router.post("/api/cloudflare/ai-search/tokens", response_model=TokenResponse)
async def create_ai_search_token(
    request: Request,
    body: TokenCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Cria um novo token de AI Search."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_as.create_token(
            acc,
            cf_api_id=body.cf_api_id,
            cf_api_key=body.cf_api_key,
            name=body.name,
            legacy=body.legacy,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_ai_search_token failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/ai-search/tokens/{token_id} ──────────────────────────

@router.get("/api/cloudflare/ai-search/tokens/{token_id}", response_model=TokenResponse)
async def get_ai_search_token(
    request: Request,
    token_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna detalhes de um token de AI Search."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_as.get_token(acc, token_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_ai_search_token failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── PUT /api/cloudflare/ai-search/tokens/{token_id} ──────────────────────────

@router.put("/api/cloudflare/ai-search/tokens/{token_id}", response_model=TokenResponse)
async def update_ai_search_token(
    request: Request,
    token_id: str,
    body: TokenUpdateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Atualiza um token de AI Search."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_as.update_token(
            acc,
            token_id,
            cf_api_id=body.cf_api_id,
            cf_api_key=body.cf_api_key,
            name=body.name,
            legacy=body.legacy,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("update_ai_search_token failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── DELETE /api/cloudflare/ai-search/tokens/{token_id} ───────────────────────

@router.delete("/api/cloudflare/ai-search/tokens/{token_id}")
async def delete_ai_search_token(
    request: Request,
    token_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Deleta um token de AI Search."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_as.delete_token(acc, token_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("delete_ai_search_token failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Browser Rendering
# ─────────────────────────────────────────────────────────────────────────────

class BaseRenderingBody(BaseModel):
    html: Optional[str] = None
    url: Optional[str] = None
    cache_ttl: Optional[float] = None
    action_timeout: Optional[float] = None
    add_script_tag: Optional[List[Dict[str, Any]]] = None
    add_style_tag: Optional[List[Dict[str, Any]]] = None
    allow_request_pattern: Optional[List[str]] = None
    allow_resource_types: Optional[List[str]] = None
    authenticate: Optional[Dict[str, str]] = None
    best_attempt: Optional[bool] = None
    cookies: Optional[List[Dict[str, Any]]] = None
    emulate_media_type: Optional[str] = None
    goto_options: Optional[Dict[str, Any]] = None
    reject_request_pattern: Optional[List[str]] = None
    reject_resource_types: Optional[List[str]] = None
    set_extra_http_headers: Optional[Dict[str, str]] = None
    set_java_script_enabled: Optional[bool] = None
    user_agent: Optional[str] = None
    viewport: Optional[Dict[str, Any]] = None
    wait_for_selector: Optional[Dict[str, Any]] = None
    wait_for_timeout: Optional[float] = None


class ContentCreateBody(BaseRenderingBody):
    url: str = Field(..., min_length=1)


class PDFCreateBody(BaseRenderingBody):
    pdf_options: Optional[Dict[str, Any]] = None


class ScrapeCreateBody(BaseRenderingBody):
    elements: List[Dict[str, str]] = Field(..., min_length=1)


class ScreenshotCreateBody(BaseRenderingBody):
    screenshot_options: Optional[Dict[str, Any]] = None
    scroll_page: Optional[bool] = None
    selector: Optional[str] = None


class SnapshotCreateBody(BaseRenderingBody):
    screenshot_options: Optional[Dict[str, Any]] = None


class JsonCreateBody(BaseRenderingBody):
    prompt: Optional[str] = None
    response_format: Optional[Dict[str, Any]] = None
    custom_ai: Optional[List[Dict[str, Any]]] = None


class LinksCreateBody(BaseRenderingBody):
    exclude_external_links: Optional[bool] = None
    visible_links_only: Optional[bool] = None


class MarkdownCreateBody(BaseRenderingBody):
    url: str = Field(..., min_length=1)


class CrawlCreateBody(BaseRenderingBody):
    url: str = Field(..., min_length=1)
    depth: Optional[float] = None
    limit: Optional[float] = None
    formats: Optional[List[str]] = None
    options: Optional[Dict[str, Any]] = None
    crawl_purposes: Optional[List[str]] = None
    source: Optional[str] = None
    render: Optional[bool] = None
    json_options: Optional[Dict[str, Any]] = None
    max_age: Optional[float] = None
    modified_since: Optional[int] = None


class DevtoolsBrowserCreateBody(BaseModel):
    keep_alive: Optional[float] = None
    lab: Optional[bool] = None
    recording: Optional[bool] = None
    targets: Optional[bool] = None


class DevtoolsTargetCreateBody(BaseModel):
    url: Optional[str] = None


# ── POST /api/cloudflare/browser-rendering/content ───────────────────────────

@router.post("/api/cloudflare/browser-rendering/content")
async def create_browser_content(
    request: Request,
    body: ContentCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna HTML renderizado de uma URL."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.create_content(
            acc,
            url=body.url,
            html=body.html,
            cache_ttl=body.cache_ttl,
            action_timeout=body.action_timeout,
            add_script_tag=body.add_script_tag,
            add_style_tag=body.add_style_tag,
            allow_request_pattern=body.allow_request_pattern,
            allow_resource_types=body.allow_resource_types,
            authenticate=body.authenticate,
            best_attempt=body.best_attempt,
            cookies=body.cookies,
            emulate_media_type=body.emulate_media_type,
            goto_options=body.goto_options,
            reject_request_pattern=body.reject_request_pattern,
            reject_resource_types=body.reject_resource_types,
            set_extra_http_headers=body.set_extra_http_headers,
            set_java_script_enabled=body.set_java_script_enabled,
            user_agent=body.user_agent,
            viewport=body.viewport,
            wait_for_selector=body.wait_for_selector,
            wait_for_timeout=body.wait_for_timeout,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_browser_content failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/browser-rendering/pdf ───────────────────────────────

@router.post("/api/cloudflare/browser-rendering/pdf")
async def create_browser_pdf(
    request: Request,
    body: PDFCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Response:
    """Gera PDF a partir de URL ou HTML."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        pdf_bytes = await cf_br.create_pdf(
            acc,
            html=body.html,
            url=body.url,
            cache_ttl=body.cache_ttl,
            action_timeout=body.action_timeout,
            add_script_tag=body.add_script_tag,
            add_style_tag=body.add_style_tag,
            allow_request_pattern=body.allow_request_pattern,
            allow_resource_types=body.allow_resource_types,
            authenticate=body.authenticate,
            best_attempt=body.best_attempt,
            cookies=body.cookies,
            emulate_media_type=body.emulate_media_type,
            goto_options=body.goto_options,
            pdf_options=body.pdf_options,
            reject_request_pattern=body.reject_request_pattern,
            reject_resource_types=body.reject_resource_types,
            set_extra_http_headers=body.set_extra_http_headers,
            set_java_script_enabled=body.set_java_script_enabled,
            user_agent=body.user_agent,
            viewport=body.viewport,
            wait_for_selector=body.wait_for_selector,
            wait_for_timeout=body.wait_for_timeout,
        )
        return Response(content=pdf_bytes, media_type="application/pdf")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_browser_pdf failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/browser-rendering/scrape ────────────────────────────

@router.post("/api/cloudflare/browser-rendering/scrape")
async def create_browser_scrape(
    request: Request,
    body: ScrapeCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Scrape elementos de uma página."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.create_scrape(
            acc,
            elements=body.elements,
            html=body.html,
            url=body.url,
            cache_ttl=body.cache_ttl,
            action_timeout=body.action_timeout,
            add_script_tag=body.add_script_tag,
            add_style_tag=body.add_style_tag,
            allow_request_pattern=body.allow_request_pattern,
            allow_resource_types=body.allow_resource_types,
            authenticate=body.authenticate,
            best_attempt=body.best_attempt,
            cookies=body.cookies,
            emulate_media_type=body.emulate_media_type,
            goto_options=body.goto_options,
            reject_request_pattern=body.reject_request_pattern,
            reject_resource_types=body.reject_resource_types,
            set_extra_http_headers=body.set_extra_http_headers,
            set_java_script_enabled=body.set_java_script_enabled,
            user_agent=body.user_agent,
            viewport=body.viewport,
            wait_for_selector=body.wait_for_selector,
            wait_for_timeout=body.wait_for_timeout,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_browser_scrape failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/browser-rendering/screenshot ────────────────────────

@router.post("/api/cloudflare/browser-rendering/screenshot")
async def create_browser_screenshot(
    request: Request,
    body: ScreenshotCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Tira screenshot de uma página."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.create_screenshot(
            acc,
            html=body.html,
            url=body.url,
            cache_ttl=body.cache_ttl,
            action_timeout=body.action_timeout,
            add_script_tag=body.add_script_tag,
            add_style_tag=body.add_style_tag,
            allow_request_pattern=body.allow_request_pattern,
            allow_resource_types=body.allow_resource_types,
            authenticate=body.authenticate,
            best_attempt=body.best_attempt,
            cookies=body.cookies,
            emulate_media_type=body.emulate_media_type,
            goto_options=body.goto_options,
            reject_request_pattern=body.reject_request_pattern,
            reject_resource_types=body.reject_resource_types,
            screenshot_options=body.screenshot_options,
            scroll_page=body.scroll_page,
            selector=body.selector,
            set_extra_http_headers=body.set_extra_http_headers,
            set_java_script_enabled=body.set_java_script_enabled,
            user_agent=body.user_agent,
            viewport=body.viewport,
            wait_for_selector=body.wait_for_selector,
            wait_for_timeout=body.wait_for_timeout,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_browser_screenshot failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/browser-rendering/snapshot ──────────────────────────

@router.post("/api/cloudflare/browser-rendering/snapshot")
async def create_browser_snapshot(
    request: Request,
    body: SnapshotCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna HTML + screenshot de uma página."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.create_snapshot(
            acc,
            html=body.html,
            url=body.url,
            cache_ttl=body.cache_ttl,
            action_timeout=body.action_timeout,
            add_script_tag=body.add_script_tag,
            add_style_tag=body.add_style_tag,
            allow_request_pattern=body.allow_request_pattern,
            allow_resource_types=body.allow_resource_types,
            authenticate=body.authenticate,
            best_attempt=body.best_attempt,
            cookies=body.cookies,
            emulate_media_type=body.emulate_media_type,
            goto_options=body.goto_options,
            reject_request_pattern=body.reject_request_pattern,
            reject_resource_types=body.reject_resource_types,
            screenshot_options=body.screenshot_options,
            set_extra_http_headers=body.set_extra_http_headers,
            set_java_script_enabled=body.set_java_script_enabled,
            user_agent=body.user_agent,
            viewport=body.viewport,
            wait_for_selector=body.wait_for_selector,
            wait_for_timeout=body.wait_for_timeout,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_browser_snapshot failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/browser-rendering/json ──────────────────────────────

@router.post("/api/cloudflare/browser-rendering/json")
async def create_browser_json(
    request: Request,
    body: JsonCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Extrai JSON de uma página via AI."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.create_json(
            acc,
            html=body.html,
            url=body.url,
            cache_ttl=body.cache_ttl,
            action_timeout=body.action_timeout,
            add_script_tag=body.add_script_tag,
            add_style_tag=body.add_style_tag,
            allow_request_pattern=body.allow_request_pattern,
            allow_resource_types=body.allow_resource_types,
            authenticate=body.authenticate,
            best_attempt=body.best_attempt,
            cookies=body.cookies,
            custom_ai=body.custom_ai,
            emulate_media_type=body.emulate_media_type,
            goto_options=body.goto_options,
            prompt=body.prompt,
            reject_request_pattern=body.reject_request_pattern,
            reject_resource_types=body.reject_resource_types,
            response_format=body.response_format,
            set_extra_http_headers=body.set_extra_http_headers,
            set_java_script_enabled=body.set_java_script_enabled,
            user_agent=body.user_agent,
            viewport=body.viewport,
            wait_for_selector=body.wait_for_selector,
            wait_for_timeout=body.wait_for_timeout,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_browser_json failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/browser-rendering/links ─────────────────────────────

@router.post("/api/cloudflare/browser-rendering/links")
async def create_browser_links(
    request: Request,
    body: LinksCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Extrai links de uma página."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.create_links(
            acc,
            html=body.html,
            url=body.url,
            cache_ttl=body.cache_ttl,
            action_timeout=body.action_timeout,
            add_script_tag=body.add_script_tag,
            add_style_tag=body.add_style_tag,
            allow_request_pattern=body.allow_request_pattern,
            allow_resource_types=body.allow_resource_types,
            authenticate=body.authenticate,
            best_attempt=body.best_attempt,
            cookies=body.cookies,
            emulate_media_type=body.emulate_media_type,
            exclude_external_links=body.exclude_external_links,
            goto_options=body.goto_options,
            reject_request_pattern=body.reject_request_pattern,
            reject_resource_types=body.reject_resource_types,
            set_extra_http_headers=body.set_extra_http_headers,
            set_java_script_enabled=body.set_java_script_enabled,
            user_agent=body.user_agent,
            viewport=body.viewport,
            visible_links_only=body.visible_links_only,
            wait_for_selector=body.wait_for_selector,
            wait_for_timeout=body.wait_for_timeout,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_browser_links failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/browser-rendering/markdown ──────────────────────────

@router.post("/api/cloudflare/browser-rendering/markdown")
async def create_browser_markdown(
    request: Request,
    body: MarkdownCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Extrai Markdown de uma URL."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.create_markdown(
            acc,
            url=body.url,
            html=body.html,
            cache_ttl=body.cache_ttl,
            action_timeout=body.action_timeout,
            add_script_tag=body.add_script_tag,
            add_style_tag=body.add_style_tag,
            allow_request_pattern=body.allow_request_pattern,
            allow_resource_types=body.allow_resource_types,
            authenticate=body.authenticate,
            best_attempt=body.best_attempt,
            cookies=body.cookies,
            emulate_media_type=body.emulate_media_type,
            goto_options=body.goto_options,
            reject_request_pattern=body.reject_request_pattern,
            reject_resource_types=body.reject_resource_types,
            set_extra_http_headers=body.set_extra_http_headers,
            set_java_script_enabled=body.set_java_script_enabled,
            user_agent=body.user_agent,
            viewport=body.viewport,
            wait_for_selector=body.wait_for_selector,
            wait_for_timeout=body.wait_for_timeout,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_browser_markdown failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/browser-rendering/crawl ─────────────────────────────

@router.post("/api/cloudflare/browser-rendering/crawl")
async def create_browser_crawl(
    request: Request,
    body: CrawlCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Inicia um job de crawl."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.create_crawl(
            acc,
            url=body.url,
            html=body.html,
            cache_ttl=body.cache_ttl,
            action_timeout=body.action_timeout,
            add_script_tag=body.add_script_tag,
            add_style_tag=body.add_style_tag,
            allow_request_pattern=body.allow_request_pattern,
            allow_resource_types=body.allow_resource_types,
            authenticate=body.authenticate,
            best_attempt=body.best_attempt,
            cookies=body.cookies,
            crawl_purposes=body.crawl_purposes,
            depth=body.depth,
            emulate_media_type=body.emulate_media_type,
            formats=body.formats,
            goto_options=body.goto_options,
            json_options=body.json_options,
            limit=body.limit,
            max_age=body.max_age,
            modified_since=body.modified_since,
            options=body.options,
            reject_request_pattern=body.reject_request_pattern,
            reject_resource_types=body.reject_resource_types,
            render=body.render,
            set_extra_http_headers=body.set_extra_http_headers,
            set_java_script_enabled=body.set_java_script_enabled,
            source=body.source,
            viewport=body.viewport,
            wait_for_selector=body.wait_for_selector,
            wait_for_timeout=body.wait_for_timeout,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_browser_crawl failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/browser-rendering/crawl/{job_id} ─────────────────────

@router.get("/api/cloudflare/browser-rendering/crawl/{job_id}")
async def get_browser_crawl(
    request: Request,
    job_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
    cache_ttl: Optional[float] = Query(default=None),
    cursor: Optional[float] = Query(default=None),
    limit: Optional[float] = Query(default=None),
    status: Optional[str] = Query(default=None, description="queued, errored, completed, disallowed, skipped, cancelled"),
) -> Dict[str, Any]:
    """Retorna resultado de um job de crawl."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.get_crawl(
            acc,
            job_id,
            cache_ttl=cache_ttl,
            cursor=cursor,
            limit=limit,
            status=status,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_browser_crawl failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── DELETE /api/cloudflare/browser-rendering/crawl/{job_id} ──────────────────

@router.delete("/api/cloudflare/browser-rendering/crawl/{job_id}")
async def delete_browser_crawl(
    request: Request,
    job_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Cancela um job de crawl."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.delete_crawl(acc, job_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("delete_browser_crawl failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/browser-rendering/devtools/session ───────────────────

@router.get("/api/cloudflare/browser-rendering/devtools/session")
async def list_browser_devtools_sessions(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
    limit: Optional[float] = Query(default=None),
    offset: Optional[float] = Query(default=None),
) -> Dict[str, Any]:
    """Lista sessões ativas do browser devtools."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.list_devtools_sessions(acc, limit=limit, offset=offset)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("list_browser_devtools_sessions failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/browser-rendering/devtools/session/{session_id} ──────

@router.get("/api/cloudflare/browser-rendering/devtools/session/{session_id}")
async def get_browser_devtools_session(
    request: Request,
    session_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna detalhes de uma sessão devtools."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.get_devtools_session(acc, session_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_browser_devtools_session failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/cloudflare/browser-rendering/devtools/browser ──────────────────

@router.post("/api/cloudflare/browser-rendering/devtools/browser")
async def create_browser_devtools_browser(
    request: Request,
    body: DevtoolsBrowserCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Cria uma nova sessão de browser devtools."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.create_devtools_browser(
            acc,
            keep_alive=body.keep_alive,
            lab=body.lab,
            recording=body.recording,
            targets=body.targets,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_browser_devtools_browser failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/browser-rendering/devtools/browser/{session_id}/json/version

@router.get("/api/cloudflare/browser-rendering/devtools/browser/{session_id}/json/version")
async def get_browser_devtools_browser_version(
    request: Request,
    session_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna metadados da versão do browser."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.get_devtools_browser_version(acc, session_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_browser_devtools_browser_version failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/browser-rendering/devtools/browser/{session_id}/json/protocol

@router.get("/api/cloudflare/browser-rendering/devtools/browser/{session_id}/json/protocol")
async def get_browser_devtools_browser_protocol(
    request: Request,
    session_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna schema do Chrome DevTools Protocol."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.get_devtools_browser_protocol(acc, session_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_browser_devtools_browser_protocol failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── DELETE /api/cloudflare/browser-rendering/devtools/browser/{session_id} ───

@router.delete("/api/cloudflare/browser-rendering/devtools/browser/{session_id}")
async def delete_browser_devtools_browser(
    request: Request,
    session_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Fecha uma sessão de browser devtools."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.delete_devtools_browser(acc, session_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("delete_browser_devtools_browser failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── PUT /api/cloudflare/browser-rendering/devtools/browser/{session_id}/json/new

@router.put("/api/cloudflare/browser-rendering/devtools/browser/{session_id}/json/new")
async def create_browser_devtools_target(
    request: Request,
    session_id: str,
    body: DevtoolsTargetCreateBody,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Abre uma nova aba no browser."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.create_devtools_target(acc, session_id, url=body.url)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("create_browser_devtools_target failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/browser-rendering/devtools/browser/{session_id}/json/list

@router.get("/api/cloudflare/browser-rendering/devtools/browser/{session_id}/json/list")
async def list_browser_devtools_targets(
    request: Request,
    session_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Lista targets debuggáveis do browser."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.list_devtools_targets(acc, session_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("list_browser_devtools_targets failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/browser-rendering/devtools/browser/{session_id}/json/list/{target_id}

@router.get("/api/cloudflare/browser-rendering/devtools/browser/{session_id}/json/list/{target_id}")
async def get_browser_devtools_target(
    request: Request,
    session_id: str,
    target_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Retorna detalhes de um target."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.get_devtools_target(acc, session_id, target_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("get_browser_devtools_target failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/browser-rendering/devtools/browser/{session_id}/json/activate/{target_id}

@router.get("/api/cloudflare/browser-rendering/devtools/browser/{session_id}/json/activate/{target_id}")
async def activate_browser_devtools_target(
    request: Request,
    session_id: str,
    target_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Ativa (traz para frente) um target."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.activate_devtools_target(acc, session_id, target_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("activate_browser_devtools_target failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── GET /api/cloudflare/browser-rendering/devtools/browser/{session_id}/json/close/{target_id}

@router.get("/api/cloudflare/browser-rendering/devtools/browser/{session_id}/json/close/{target_id}")
async def close_browser_devtools_target(
    request: Request,
    session_id: str,
    target_id: str,
    account_id: Optional[str] = Query(default=None, description="Override — admin only"),
) -> Dict[str, Any]:
    """Fecha um target (aba) do browser."""
    _resolve_caller(request)
    acc = _resolve_account_id(request, account_id)
    try:
        return await cf_br.close_devtools_target(acc, session_id, target_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text)
    except Exception as exc:
        logger.error("close_browser_devtools_target failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
