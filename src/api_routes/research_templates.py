"""
src.api_routes.research_templates — CRUD de templates de pesquisa Oracle.

Templates definem o prompt usado em oracle-research por prospect. Globais
(company_id IS NULL) só via migration; tenants criam/editam/desativam os seus.

Endpoints:
- GET    /api/companies/{company_id}/research-templates
- POST   /api/companies/{company_id}/research-templates
- PATCH  /api/companies/{company_id}/research-templates/{template_id}
- DELETE /api/companies/{company_id}/research-templates/{template_id}
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("api.research_templates")
router = APIRouter(tags=["research_templates"])

_CAMEL_TO_SNAKE = {
    "promptTemplate": "prompt_template",
    "outputSections": "output_sections",
    "defaultUrls": "default_urls",
    "requireReview": "require_review",
}

_ALLOWED_CREATE = {
    "slug", "name", "description", "prompt_template",
    "output_sections", "default_urls", "require_review", "active",
}
_ALLOWED_UPDATE = {
    "name", "description", "prompt_template",
    "output_sections", "default_urls", "require_review", "active",
}


@router.get("/api/companies/{company_id}/research-templates")
@router.get("/companies/{company_id}/research-templates")
async def list_research_templates(request: Request, company_id: str):
    """Lista templates ativos: globais (company_id IS NULL) + do tenant."""
    from src.api import supabase, get_authenticated_client, validate_jwt_company_id
    from src.models import ResearchTemplate

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        global_res = (
            client.table("research_templates")
            .select("*")
            .is_("company_id", "null")
            .eq("active", True)
            .order("name", desc=False)
            .execute()
        )
        tenant_res = (
            client.table("research_templates")
            .select("*")
            .eq("company_id", company_id)
            .eq("active", True)
            .order("name", desc=False)
            .execute()
        )
        rows = list(global_res.data or []) + list(tenant_res.data or [])
        rows.sort(key=lambda r: (r.get("company_id") is not None, (r.get("name") or "").lower()))
        return [ResearchTemplate(**row).to_zod_dict() for row in rows]
    except Exception as e:
        logger.error(f"list_research_templates failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/api/companies/{company_id}/research-templates")
@router.post("/companies/{company_id}/research-templates")
async def create_research_template(
    request: Request,
    company_id: str,
    payload: Dict[str, Any],
):
    """Cria template específico do tenant. Globais (NULL) só via migration."""
    from src.api import supabase, validate_jwt_company_id
    from src.models import ResearchTemplate

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        raise HTTPException(503, "supabase_required")

    normalised = {_CAMEL_TO_SNAKE.get(k, k): v for k, v in (payload or {}).items()}
    row = {k: v for k, v in normalised.items() if k in _ALLOWED_CREATE}

    if not row.get("slug") or not row.get("name") or not row.get("prompt_template"):
        raise HTTPException(400, "slug_name_prompt_template_required")

    row["company_id"] = company_id

    try:
        res = supabase.table("research_templates").insert(row).execute()
        return ResearchTemplate(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"create_research_template failed: {e}")
        raise HTTPException(500, str(e))


@router.patch("/api/companies/{company_id}/research-templates/{template_id}")
@router.patch("/companies/{company_id}/research-templates/{template_id}")
async def update_research_template(
    request: Request,
    company_id: str,
    template_id: str,
    payload: Dict[str, Any],
):
    """Atualiza template do tenant. Globais (company_id NULL) são read-only."""
    from src.api import supabase, validate_jwt_company_id
    from src.models import ResearchTemplate

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        raise HTTPException(503, "supabase_required")

    existing = (
        supabase.table("research_templates")
        .select("id,company_id")
        .eq("id", template_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(404, "template_not_found")
    if existing.data[0].get("company_id") is None:
        raise HTTPException(403, "global_template_readonly")
    if existing.data[0].get("company_id") != company_id:
        raise HTTPException(403, "template_not_owned")

    normalised = {_CAMEL_TO_SNAKE.get(k, k): v for k, v in (payload or {}).items()}
    row = {k: v for k, v in normalised.items() if k in _ALLOWED_UPDATE}
    if not row:
        raise HTTPException(400, "no_fields_to_update")

    try:
        res = (
            supabase.table("research_templates")
            .update(row)
            .eq("id", template_id)
            .execute()
        )
        return ResearchTemplate(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"update_research_template failed: {e}")
        raise HTTPException(500, str(e))


@router.delete("/api/companies/{company_id}/research-templates/{template_id}")
@router.delete("/companies/{company_id}/research-templates/{template_id}")
async def delete_research_template(
    request: Request,
    company_id: str,
    template_id: str,
):
    """Soft delete (active=false) do template do tenant. Globais bloqueados."""
    from src.api import supabase, validate_jwt_company_id

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        raise HTTPException(503, "supabase_required")

    existing = (
        supabase.table("research_templates")
        .select("id,company_id")
        .eq("id", template_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(404, "template_not_found")
    if existing.data[0].get("company_id") is None:
        raise HTTPException(403, "global_template_readonly")
    if existing.data[0].get("company_id") != company_id:
        raise HTTPException(403, "template_not_owned")

    try:
        supabase.table("research_templates").update({"active": False}).eq("id", template_id).execute()
        return {"deleted": template_id}
    except Exception as e:
        logger.error(f"delete_research_template failed: {e}")
        raise HTTPException(500, str(e))
