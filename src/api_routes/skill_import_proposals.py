"""Bloco A — skill import staging + promote para agent_specialties draft.

POST /api/skill-import-proposals — bulk insert (status=queued).
POST /api/skill-import-proposals/{id}/promote — curadoria → catálogo global draft.

Isolamento por company_id na API (service_role + JWT), espelha pr1a RLS USING(true).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, Field

from src.models import AgentSpecialty, SkillImportProposal

logger = logging.getLogger("api.skill_import_proposals")

router = APIRouter(tags=["skill-import"])

_PROPOSAL_SOURCES = frozenset({"import_csv", "markdown_upload"})


def _resolve_caller(request: Request) -> tuple[str, str]:
    company_id = getattr(request.state, "company_id", None)
    user_id = getattr(request.state, "user_id", None)
    if not company_id or not user_id:
        raise HTTPException(status_code=401, detail="unauthenticated")
    return str(company_id), str(user_id)


def _slugify(value: str) -> str:
    s = value.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "skill-import"


def _extract_operation_types(config_schema: Any) -> List[str]:
    """Lê operation_types[] de config_schema (objeto ou lista legada)."""
    if isinstance(config_schema, dict):
        raw = config_schema.get("operation_types") or config_schema.get("operationTypes")
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if x and str(x).strip()]
    return []


def _ensure_agent_domain(supabase: Any, domain_id: str) -> None:
    """FK agent_specialties.domain → agent_domains.id; cria domínio global se ausente."""
    dom = domain_id.strip()
    if not dom:
        raise HTTPException(status_code=400, detail="domain_required")
    res = supabase.table("agent_domains").select("id").eq("id", dom).limit(1).execute()
    if res.data:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    supabase.table("agent_domains").insert(
        {
            "id": dom,
            "name": dom.replace("-", " ").replace("_", " ").title(),
            "description": "Domínio criado na promoção de skill import (curadoria).",
            "is_active": True,
            "display_order": 999,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
    ).execute()


def _ensure_operation_types_catalog(
    supabase: Any, op_type_ids: List[str], *, domain: str, specialty_slug: str
) -> None:
    """Garante cada op_type em operation_types_catalog (daemon dispatch)."""
    if not op_type_ids:
        return
    existing = _load_operation_type_ids(supabase)
    category = domain.strip() or "other"
    for op_id in op_type_ids:
        if op_id in existing:
            continue
        supabase.table("operation_types_catalog").insert(
            {
                "id": op_id,
                "name": op_id.replace("-", " ").replace(":", " ").title(),
                "description": (
                    f"Registrado na promoção da skill '{specialty_slug}' "
                    "(skill import — curadoria)."
                ),
                "category": category,
                "primary_agent_id": None,
                "default_specialty_slug": specialty_slug,
                "routing_score": 50,
                "is_active": True,
                "display_order": 9500,
            }
        ).execute()
        existing.add(op_id)


def _load_operation_type_ids(supabase: Any) -> set:
    try:
        res = (
            supabase.table("operation_types_catalog")
            .select("id")
            .eq("is_active", True)
            .execute()
        )
        return {str(r["id"]) for r in (res.data or []) if r.get("id")}
    except Exception as e:
        logger.warning("operation_types_catalog load failed: %s", e)
        return set()


class SkillImportProposalItemInput(BaseModel):
    source: Literal["import_csv", "markdown_upload"]
    rawInput: Optional[str] = None
    name: Optional[str] = None
    slug: Optional[str] = None
    domain: Optional[str] = None
    description: Optional[str] = None
    compatibleRoles: List[str] = Field(default_factory=list)
    systemPromptTemplate: Optional[str] = None
    configSchema: Optional[Any] = None


class SkillImportProposalsBulkInput(BaseModel):
    proposals: List[SkillImportProposalItemInput] = Field(..., min_length=1)


@router.post("/api/skill-import-proposals")
@router.post("/skill-import-proposals")
async def create_skill_import_proposals(
    request: Request, payload: SkillImportProposalsBulkInput
) -> List[Dict[str, Any]]:
    """Bulk insert em skill_import_proposals (status=queued)."""
    company_id, user_id = _resolve_caller(request)
    from src.api import supabase

    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_unavailable")

    now_iso = datetime.now(timezone.utc).isoformat()
    rows: List[Dict[str, Any]] = []
    for item in payload.proposals:
        if item.source not in _PROPOSAL_SOURCES:
            raise HTTPException(status_code=400, detail="invalid_proposal_source")
        rows.append(
            {
                "company_id": company_id,
                "source": item.source,
                "status": "queued",
                "raw_input": item.rawInput,
                "name": item.name,
                "slug": item.slug,
                "domain": item.domain,
                "description": item.description,
                "compatible_roles": item.compatibleRoles,
                "system_prompt_template": item.systemPromptTemplate,
                "config_schema": item.configSchema,
                "created_by": user_id,
                "created_at": now_iso,
                "updated_at": now_iso,
            }
        )

    try:
        res = supabase.table("skill_import_proposals").insert(rows).execute()
        return [SkillImportProposal(**row).to_zod_dict() for row in (res.data or [])]
    except Exception as e:
        logger.error("create_skill_import_proposals failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/skill-import-proposals/{proposal_id}/promote")
@router.post("/skill-import-proposals/{proposal_id}/promote")
async def promote_skill_import_proposal(
    request: Request,
    proposal_id: str = Path(..., description="UUID da proposta em staging"),
) -> Dict[str, Any]:
    """Promove proposta → agent_specialties (status=draft, source da proposta)."""
    company_id, _user_id = _resolve_caller(request)
    from src.api import supabase

    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_unavailable")

    try:
        prop_res = (
            supabase.table("skill_import_proposals")
            .select("*")
            .eq("id", proposal_id)
            .single()
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=404, detail="proposal_not_found")

    proposal = prop_res.data
    if not proposal:
        raise HTTPException(status_code=404, detail="proposal_not_found")

    if str(proposal.get("company_id")) != company_id:
        raise HTTPException(status_code=403, detail="cross_company_forbidden")

    status = proposal.get("status")
    if status == "promoted":
        raise HTTPException(status_code=409, detail="proposal_already_promoted")
    if status == "dismissed":
        raise HTTPException(status_code=409, detail="proposal_dismissed")

    name = (proposal.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="proposal_name_required")

    slug = (proposal.get("slug") or "").strip() or _slugify(name)
    domain = (proposal.get("domain") or "").strip()
    if not domain:
        raise HTTPException(status_code=400, detail="proposal_domain_required")

    source = proposal.get("source")
    if source not in _PROPOSAL_SOURCES:
        raise HTTPException(status_code=400, detail="invalid_proposal_source")

    config_schema = proposal.get("config_schema")
    op_types = _extract_operation_types(config_schema)

    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        _ensure_agent_domain(supabase, domain)
        _ensure_operation_types_catalog(
            supabase, op_types, domain=domain, specialty_slug=slug
        )

        specialty_row = {
            "id": slug,
            "slug": slug,
            "name": name,
            "domain": domain,
            "description": proposal.get("description") or "",
            "compatible_roles": proposal.get("compatible_roles") or [],
            "system_prompt_template": proposal.get("system_prompt_template") or "",
            "config_schema": config_schema,
            "is_active": True,
            "status": "draft",
            "source": source,
            "created_at": now_iso,
        }

        sp_res = supabase.table("agent_specialties").insert(specialty_row).execute()
        if not sp_res.data:
            raise HTTPException(status_code=500, detail="specialty_insert_empty")

        specialty = sp_res.data[0]

        supabase.table("skill_import_proposals").update(
            {
                "status": "promoted",
                "promoted_specialty_id": specialty["id"],
                "updated_at": now_iso,
            }
        ).eq("id", proposal_id).execute()

        return {
            "proposal": SkillImportProposal(
                **{**proposal, "status": "promoted", "promoted_specialty_id": specialty["id"]}
            ).to_zod_dict(),
            "specialty": AgentSpecialty(**specialty).to_zod_dict(),
        }
    except HTTPException:
        raise
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "23505" in err:
            raise HTTPException(status_code=409, detail="specialty_id_or_slug_exists")
        logger.error("promote_skill_import_proposal failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
