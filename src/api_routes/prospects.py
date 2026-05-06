"""
src.api_routes.prospects — Prospect profiles + research dispatch.

Endpoints:
- GET    /api/companies/{company_id}/prospects                   list_prospects
- POST   /api/companies/{company_id}/prospects                   create_or_upsert_prospect
- GET    /api/prospects/{prospect_id}                            get_prospect
- POST   /api/companies/{company_id}/prospects/{id}/research     dispatch_prospect_research
- POST   /api/companies/{company_id}/prospects/{id}/research/cancel  cancel_prospect_research
- POST   /api/prospects/{prospect_id}/send-outreach              send_prospect_outreach_email
- PATCH  /api/prospects/{prospect_id}                            patch_prospect
- DELETE /api/prospects/{prospect_id}                            delete_prospect

Helpers ficam em api.py: validate_jwt_company_id, get_authenticated_client,
HERMES_REPORTER_AGENT_ID, _ORACLE_AGENT_ID. Importados lazy dentro de
cada função para evitar circular import (api.py também importa este módulo).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Body, HTTPException, Request, Response

logger = logging.getLogger("api.prospects")
router = APIRouter(tags=["prospects"])

_PROSPECT_OUTREACH_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_outreach_recipients(
    raw: Any,
    prospect_row: Dict[str, Any],
) -> List[str]:
    out: List[str] = []
    if isinstance(raw, str):
        s = raw.strip()
        if s and _PROSPECT_OUTREACH_EMAIL_RE.match(s):
            return [s.lower()]
    if isinstance(raw, list):
        for x in raw:
            if isinstance(x, str) and _PROSPECT_OUTREACH_EMAIL_RE.match(x.strip()):
                out.append(x.strip().lower())
    if out:
        return list(dict.fromkeys(out))
    ec = prospect_row.get("email_contato")
    if isinstance(ec, str) and _PROSPECT_OUTREACH_EMAIL_RE.match(ec.strip()):
        return [ec.strip().lower()]
    for dm in prospect_row.get("decisores") or []:
        if not isinstance(dm, dict):
            continue
        em = dm.get("email")
        if isinstance(em, str) and _PROSPECT_OUTREACH_EMAIL_RE.match(em.strip()):
            return [em.strip().lower()]
    return []


@router.get("/api/companies/{company_id}/prospects")
@router.get("/companies/{company_id}/prospects")
async def list_prospects(request: Request, company_id: str):
    from src.api import supabase, get_authenticated_client
    from src.models import ProspectProfile

    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("prospect_profiles")
            .select("*")
            .eq("company_id", company_id)
            .order("enriched_at", desc=True)
            .execute()
        )
        return [ProspectProfile(**row).to_zod_dict() for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_prospects failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/api/companies/{company_id}/prospects")
@router.post("/companies/{company_id}/prospects")
async def create_or_upsert_prospect(request: Request, company_id: str, payload: Dict[str, Any]):
    from src.api import supabase, validate_jwt_company_id
    from src.models import ProspectProfile

    validate_jwt_company_id(request.state.token, company_id)

    CAMEL_TO_SNAKE = {
        "nomeRazaoSocial": "nome_razao_social",
        "emailContato": "email_contato",
        "sourceTaskId": "source_task_id",
        "enrichedAt": "enriched_at",
        "rawResearch": "raw_research",
        "linkedinUrl": "linkedin_url",
        "instagramHandle": "instagram_handle",
        "extraUrls": "extra_urls",
        "cnpjLookupData": "cnpj_lookup_data",
        "researchTemplateId": "research_template_id",
        "researchStatus": "research_status",
        "researchProgress": "research_progress",
        "researchCronExpr": "research_cron_expr",
        "nextResearchAt": "next_research_at",
        "lastResearchAt": "last_research_at",
    }
    normalised = {CAMEL_TO_SNAKE.get(k, k): v for k, v in payload.items()}

    ALLOWED = {
        "nome_razao_social", "cnpj", "website", "setor", "endereco",
        "telefone", "email_contato", "decisores", "source_task_id",
        "enriched_at", "raw_research", "artifacts",
        "tipo", "linkedin_url", "instagram_handle", "extra_urls",
        "cnpj_lookup_data", "qsa",
        "research_template_id", "research_status", "research_progress",
        "research_cron_expr", "next_research_at", "last_research_at",
    }
    row = {k: v for k, v in normalised.items() if k in ALLOWED}
    row["company_id"] = company_id

    if not supabase:
        row["id"] = f"prospect_tmp_{int(datetime.now().timestamp())}"
        row["created_at"] = datetime.now(timezone.utc).isoformat()
        row["updated_at"] = row["created_at"]
        row["enriched_at"] = row.get("enriched_at") or row["created_at"]
        return row

    try:
        cnpj = row.get("cnpj")
        if cnpj:
            existing = (
                supabase.table("prospect_profiles")
                .select("id")
                .eq("company_id", company_id)
                .eq("cnpj", cnpj)
                .limit(1)
                .execute()
            )
            if existing.data:
                prospect_id = existing.data[0]["id"]
                res = (
                    supabase.table("prospect_profiles")
                    .update(row)
                    .eq("id", prospect_id)
                    .execute()
                )
                return ProspectProfile(**res.data[0]).to_zod_dict()

        res = supabase.table("prospect_profiles").insert(row).execute()
        return ProspectProfile(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"create_or_upsert_prospect failed: {e}")
        raise HTTPException(500, str(e))


@router.get("/api/prospects/{prospect_id}")
@router.get("/prospects/{prospect_id}")
async def get_prospect(request: Request, prospect_id: str):
    from src.api import supabase, get_authenticated_client
    from src.models import ProspectProfile

    if not supabase:
        raise HTTPException(404, "prospect_not_found")
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("prospect_profiles")
            .select("*")
            .eq("id", prospect_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(404, "prospect_not_found")
        return ProspectProfile(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_prospect failed: {e}")
        raise HTTPException(500, str(e))


@router.post("/api/companies/{company_id}/prospects/{prospect_id}/research")
@router.post("/companies/{company_id}/prospects/{prospect_id}/research")
async def dispatch_prospect_research(
    request: Request,
    company_id: str,
    prospect_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
):
    """Dispara pesquisa Oracle (oracle-research) para um prospect.

    Modos:
      - imediato (default): cria task oracle-research e marca research_status=queued.
      - agendado: payload.schedule = {cron_expr, next_research_at} → cron worker varre.
    """
    from src.api import supabase, validate_jwt_company_id, _ORACLE_AGENT_ID

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        raise HTTPException(503, "supabase_required")

    try:
        prospect_res = (
            supabase.table("prospect_profiles")
            .select("*")
            .eq("id", prospect_id)
            .eq("company_id", company_id)
            .maybe_single()
            .execute()
        )
    except Exception as e:
        logger.error(f"dispatch_prospect_research load prospect failed: {e}")
        raise HTTPException(500, str(e))
    if not prospect_res.data:
        raise HTTPException(404, "prospect_not_found")
    prospect = prospect_res.data

    template_id = (
        payload.get("templateId")
        or payload.get("template_id")
        or prospect.get("research_template_id")
    )
    if not template_id:
        raise HTTPException(400, "template_id_required")

    try:
        tpl_res = (
            supabase.table("research_templates")
            .select("*")
            .eq("id", template_id)
            .maybe_single()
            .execute()
        )
    except Exception as e:
        logger.error(f"dispatch_prospect_research load template failed: {e}")
        raise HTTPException(500, str(e))
    if not tpl_res.data:
        raise HTTPException(404, "template_not_found")
    template = tpl_res.data
    if template.get("company_id") not in (None, company_id):
        raise HTTPException(403, "template_not_owned")
    if not template.get("active", True):
        raise HTTPException(400, "template_inactive")

    from src.services.research_template_renderer import build_research_input

    urls_override = payload.get("urlsOverride") or payload.get("urls_override")
    review_override = payload.get("requireHumanReview")
    if review_override is None:
        review_override = payload.get("require_human_review")

    input_json = build_research_input(
        prospect, template,
        urls_override=urls_override,
        require_human_review_override=review_override,
    )
    input_json["_research_prospect_id"] = prospect_id

    schedule = payload.get("schedule") or {}
    cron_expr = schedule.get("cron_expr") or schedule.get("cronExpr")
    next_at_iso = schedule.get("next_research_at") or schedule.get("nextResearchAt")

    if cron_expr or next_at_iso:
        if not (cron_expr and next_at_iso):
            raise HTTPException(400, "schedule requires both cron_expr and next_research_at")
        try:
            supabase.table("prospect_profiles").update({
                "research_template_id": template_id,
                "research_cron_expr": cron_expr,
                "next_research_at": next_at_iso,
                "research_status": "idle",
            }).eq("id", prospect_id).execute()
        except Exception as e:
            logger.error(f"dispatch_prospect_research schedule update failed: {e}")
            raise HTTPException(500, str(e))
        logger.info(
            "prospect_research scheduled prospect=%s cron=%s next=%s",
            prospect_id, cron_expr, next_at_iso,
        )
        return {
            "prospect_id": prospect_id,
            "scheduled_at": next_at_iso,
            "cron_expr": cron_expr,
            "mode": "scheduled",
        }

    title = f"Pesquisa: {prospect.get('nome_razao_social') or 'prospect'}"
    task_row = {
        "company_id": company_id,
        "title": title[:200],
        "description": (input_json.get("prompt") or "")[:2000],
        "operation_type": "oracle-research",
        "status": "queued",
        "budget_limit": 200_000,
        "executor_type": "auto",
        "assigned_to_agent_id": _ORACLE_AGENT_ID,
        "input_json": input_json,
    }
    try:
        res = supabase.table("tasks").insert(task_row).execute()
        if not res.data:
            raise HTTPException(500, "task_creation_failed")
        task_id = res.data[0]["id"]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"dispatch_prospect_research task insert failed: {e}")
        raise HTTPException(500, str(e))

    try:
        supabase.table("prospect_profiles").update({
            "research_template_id": template_id,
            "research_status": "queued",
            "research_progress": {
                "step": 0,
                "total": 100,
                "message": "Enfileirado",
                "task_id": task_id,
            },
            "source_task_id": task_id,
        }).eq("id", prospect_id).execute()
    except Exception as e:
        logger.warning(f"dispatch_prospect_research prospect update failed: {e}")

    logger.info(
        "prospect_research dispatched prospect=%s task=%s template=%s",
        prospect_id, task_id, template.get("slug"),
    )
    return {
        "prospect_id": prospect_id,
        "task_id": task_id,
        "status": "queued",
        "mode": "immediate",
    }


@router.post("/api/companies/{company_id}/prospects/{prospect_id}/research/cancel")
@router.post("/companies/{company_id}/prospects/{prospect_id}/research/cancel")
async def cancel_prospect_research(
    request: Request,
    company_id: str,
    prospect_id: str,
):
    """Cancela pesquisa em andamento ou agendada para um prospect."""
    from src.api import supabase, validate_jwt_company_id

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        raise HTTPException(503, "supabase_required")

    try:
        prospect_res = (
            supabase.table("prospect_profiles")
            .select("source_task_id,research_status")
            .eq("id", prospect_id)
            .eq("company_id", company_id)
            .maybe_single()
            .execute()
        )
    except Exception as e:
        raise HTTPException(500, str(e))
    if not prospect_res.data:
        raise HTTPException(404, "prospect_not_found")

    task_id = prospect_res.data.get("source_task_id")

    if task_id:
        try:
            supabase.table("tasks").update({
                "status": "cancelled",
            }).eq("id", task_id).in_("status", ["queued", "in_progress"]).execute()
        except Exception as e:
            logger.warning(f"cancel_prospect_research task update failed: {e}")

    try:
        supabase.table("prospect_profiles").update({
            "research_status": "cancelled",
            "research_progress": None,
        }).eq("id", prospect_id).execute()
    except Exception as e:
        logger.error(f"cancel_prospect_research prospect update failed: {e}")
        raise HTTPException(500, str(e))

    return {"prospect_id": prospect_id, "status": "cancelled", "task_id": task_id}


@router.post("/api/prospects/{prospect_id}/send-outreach")
@router.post("/prospects/{prospect_id}/send-outreach")
async def send_prospect_outreach_email(
    request: Request,
    prospect_id: str,
    body: Dict[str, Any] = Body(default_factory=dict),
):
    """Enfileira envio SMTP via HermesReporter (oracle-report)."""
    from src.api import (
        supabase,
        get_authenticated_client,
        validate_jwt_company_id,
        HERMES_REPORTER_AGENT_ID,
    )

    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_required")
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("prospect_profiles")
            .select("*")
            .eq("id", prospect_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="prospect_not_found")
        row = res.data[0]
        company_id = str(row.get("company_id") or "")
        validate_jwt_company_id(request.state.token, company_id)

        artifacts = row.get("artifacts") or {}
        if not isinstance(artifacts, dict):
            artifacts = {}
        oe = artifacts.get("outreach_email") or {}
        if not isinstance(oe, dict):
            oe = {}
        subject = str(oe.get("assunto") or "").strip()
        corpo = str(oe.get("corpo_texto") or "").strip()
        if not subject or not corpo:
            raise HTTPException(status_code=422, detail="missing_outreach_email")

        recipients = _normalize_outreach_recipients(body.get("to"), row)
        if not recipients:
            raise HTTPException(status_code=422, detail="no_valid_recipients")

        parent_sid = row.get("source_task_id")
        desc_lines = [
            f"RECIPIENT: {', '.join(recipients)}",
            f"SUBJECT: {subject}",
        ]
        if parent_sid:
            desc_lines.append(f"PARENT_TASK_ID: {parent_sid}")
        desc_lines.extend(["", "---", "", "## Mensagem", "", corpo])
        description = "\n".join(desc_lines)

        insert_row: Dict[str, Any] = {
            "company_id": company_id,
            "title": f"Abordagem prospect — {row.get('nome_razao_social') or prospect_id[:8]}",
            "description": description,
            "budget_limit": 0,
            "operation_type": "oracle-report",
            "status": "queued",
            "spent": 0,
            "cost_usd": 0,
            "assigned_to_agent_id": HERMES_REPORTER_AGENT_ID,
            "input_json": {
                "prospect_outreach": True,
                "plain_subject": subject,
                "plain_body": corpo,
                "prospect_id": prospect_id,
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        ins = supabase.table("tasks").insert(insert_row).execute()
        if not ins.data:
            raise HTTPException(status_code=500, detail="insert_returned_empty")
        tid = str(ins.data[0].get("id") or "")
        return {"taskId": tid, "status": "queued", "recipients": recipients}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"send_prospect_outreach_email failed: {e}")
        raise HTTPException(500, str(e))


@router.patch("/api/prospects/{prospect_id}")
@router.patch("/prospects/{prospect_id}")
async def patch_prospect(request: Request, prospect_id: str, payload: Dict[str, Any]):
    from src.api import supabase, get_authenticated_client
    from src.models import ProspectProfile

    if not supabase:
        raise HTTPException(404, "prospect_not_found")
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("prospect_profiles")
            .select("id")
            .eq("id", prospect_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(404, "prospect_not_found")

        CAMEL_TO_SNAKE = {
            "nomeRazaoSocial": "nome_razao_social",
            "emailContato": "email_contato",
            "sourceTaskId": "source_task_id",
            "enrichedAt": "enriched_at",
            "rawResearch": "raw_research",
        }
        normalised = {CAMEL_TO_SNAKE.get(k, k): v for k, v in payload.items()}

        ALLOWED = {
            "nome_razao_social", "cnpj", "website", "setor", "endereco",
            "telefone", "email_contato", "decisores", "source_task_id",
            "enriched_at", "raw_research", "artifacts",
        }
        update_data = {k: v for k, v in normalised.items() if k in ALLOWED}
        if not update_data:
            raise HTTPException(400, "no_valid_fields")

        updated = (
            client.table("prospect_profiles")
            .update(update_data)
            .eq("id", prospect_id)
            .execute()
        )
        return ProspectProfile(**updated.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_prospect failed: {e}")
        raise HTTPException(500, str(e))


@router.delete("/api/prospects/{prospect_id}")
@router.delete("/prospects/{prospect_id}")
async def delete_prospect(request: Request, prospect_id: str):
    from src.api import supabase, get_authenticated_client

    if not supabase:
        raise HTTPException(404, "prospect_not_found")
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("prospect_profiles")
            .select("id")
            .eq("id", prospect_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(404, "prospect_not_found")
        client.table("prospect_profiles").delete().eq("id", prospect_id).execute()
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_prospect failed: {e}")
        raise HTTPException(500, str(e))
