"""Executor AC-2 — aplica recommendations Athena aprovadas (5 kinds executáveis v1).

Contrato: docs/CONTRACTS-AGENT-CAPABILITIES.md §7.
Bundle v2 (`agent_capability_bundle`) fica fora do escopo deste módulo v1.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.agents.athena import _validate_proposed_changes_by_kind

logger = logging.getLogger("athena.recommendation_apply")

EXECUTABLE_KINDS = frozenset(
    {
        "hire_new_agent",
        "add_specialty",
        "rewrite_system_prompt",
        "create_specialty",
        "consolidate_agents",
    }
)

INFORMATIVE_KINDS = frozenset(
    {"diagnose_gap", "suggest_automation", "suggest_hire_agent"},
)

_DEFAULT_HIRE_TOKEN_BUDGET = 100_000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_created() -> Dict[str, Any]:
    return {
        "agent": False,
        "adapter_binding": False,
        "specialty_bindings": [],
        "mcp_bindings": [],
    }


def _result(
    *,
    status: str,
    recommendation_id: str,
    agent_id: Optional[str] = None,
    created: Optional[Dict[str, Any]] = None,
    errors: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return {
        "status": status,
        "recommendation_id": recommendation_id,
        "agent_id": agent_id,
        "created": created or _empty_created(),
        "errors": errors or {},
    }


def _fetch_agent(
    supabase: Any, agent_id: str, company_id: str
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    res = (
        supabase.table("agents")
        .select("id,company_id,is_system,name")
        .eq("id", agent_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None, "agent_not_found"
    row = res.data[0]
    if str(row.get("company_id")) != str(company_id):
        return None, "agent_company_mismatch"
    if row.get("is_system"):
        return None, "agent_is_system_forbidden"
    return row, None


def _apply_hire_new_agent(
    supabase: Any,
    company_id: str,
    payload: Dict[str, Any],
    *,
    dry_run: bool,
) -> Tuple[Optional[str], Dict[str, str], Dict[str, Any]]:
    created = _empty_created()
    errors: Dict[str, str] = {}
    if dry_run:
        created["agent"] = True
        return None, errors, created

    now_iso = _now_iso()
    row = {
        "company_id": company_id,
        "name": str(payload["name"]).strip(),
        "role": str(payload["role"]).strip(),
        "status": "idle",
        "token_budget": _DEFAULT_HIRE_TOKEN_BUDGET,
        "current_burn_rate": 0,
        "adapter_type": "claude_code",
        "system_prompt": str(payload["system_prompt"]),
        "requires_approval": False,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    res = supabase.table("agents").insert(row).execute()
    if not res.data:
        errors["agent"] = "insert_returned_empty"
        return None, errors, created
    agent_id = res.data[0]["id"]
    created["agent"] = True
    return agent_id, errors, created


def _apply_rewrite_system_prompt(
    supabase: Any,
    company_id: str,
    payload: Dict[str, Any],
    *,
    dry_run: bool,
) -> Tuple[Optional[str], Dict[str, str], Dict[str, Any]]:
    created = _empty_created()
    errors: Dict[str, str] = {}
    agent_id = str(payload["agent_id"])
    agent_row, err = _fetch_agent(supabase, agent_id, company_id)
    if err:
        errors["agent"] = err
        return None, errors, created

    if dry_run:
        return agent_id, errors, created

    now_iso = _now_iso()
    supabase.table("agents").update(
        {
            "system_prompt": str(payload["proposed_prompt"]),
            "updated_at": now_iso,
        }
    ).eq("id", agent_id).execute()
    return agent_id, errors, created


def _apply_add_specialty(
    supabase: Any,
    company_id: str,
    payload: Dict[str, Any],
    *,
    dry_run: bool,
) -> Tuple[Optional[str], Dict[str, str], Dict[str, Any]]:
    created = _empty_created()
    errors: Dict[str, str] = {}
    agent_id = str(payload["agent_id"])
    specialty_id = str(payload["specialty_id"])

    agent_row, err = _fetch_agent(supabase, agent_id, company_id)
    if err:
        errors["agent"] = err
        return None, errors, created

    sp = (
        supabase.table("agent_specialties")
        .select("id")
        .eq("id", specialty_id)
        .limit(1)
        .execute()
    )
    if not sp.data:
        errors["specialty"] = "specialty_not_found"
        return agent_id, errors, created

    if dry_run:
        created["specialty_bindings"] = [specialty_id]
        return agent_id, errors, created

    existing_cfg = (
        supabase.table("agent_specialty_configs")
        .select("values")
        .eq("agent_id", agent_id)
        .eq("specialty_id", specialty_id)
        .limit(1)
        .execute()
    )
    values: Dict[str, Any] = {}
    if existing_cfg.data and isinstance(existing_cfg.data[0].get("values"), dict):
        values = dict(existing_cfg.data[0]["values"])
    values["prompt_addendum"] = str(payload["prompt_addendum"])

    now_iso = _now_iso()
    supabase.table("agent_specialty_configs").upsert(
        {
            "company_id": company_id,
            "agent_id": agent_id,
            "specialty_id": specialty_id,
            "values": values,
            "updated_at": now_iso,
        },
        on_conflict="agent_id,specialty_id",
    ).execute()
    created["specialty_bindings"] = [specialty_id]
    return agent_id, errors, created


def _apply_create_specialty(
    supabase: Any,
    company_id: str,
    payload: Dict[str, Any],
    *,
    dry_run: bool,
) -> Tuple[Optional[str], Dict[str, str], Dict[str, Any]]:
    created = _empty_created()
    errors: Dict[str, str] = {}
    slug = str(payload["slug"]).strip()
    if not slug:
        errors["specialty"] = "slug_required"
        return None, errors, created

    existing = (
        supabase.table("agent_specialties")
        .select("id")
        .eq("id", slug)
        .limit(1)
        .execute()
    )
    if existing.data:
        errors["specialty"] = "specialty_slug_exists"
        return None, errors, created

    domain = str(payload.get("domain") or "knowledge").strip()

    if dry_run:
        created["specialty_bindings"] = [slug]
        return None, errors, created

    from src.api_routes.skill_import_proposals import _ensure_agent_domain

    try:
        _ensure_agent_domain(supabase, domain)
    except Exception as e:
        errors["specialty"] = f"domain_invalid:{e}"
        return None, errors, created

    now_iso = _now_iso()
    specialty_row = {
        "id": slug,
        "slug": slug,
        "name": str(payload["name"]).strip(),
        "description": str(payload.get("description") or ""),
        "domain": domain,
        "compatible_roles": payload.get("compatible_roles") or [],
        "system_prompt_template": payload.get("system_prompt_template") or "",
        "config_schema": payload.get("config_schema") or {},
        "is_active": True,
        "status": "draft",
        "source": "athena_recommendation",
        "created_at": now_iso,
    }
    res = supabase.table("agent_specialties").insert(specialty_row).execute()
    if not res.data:
        errors["specialty"] = "specialty_insert_empty"
        return None, errors, created
    created["specialty_bindings"] = [slug]
    return None, errors, created


def _apply_consolidate_agents(
    supabase: Any,
    company_id: str,
    payload: Dict[str, Any],
    *,
    dry_run: bool,
) -> Tuple[Optional[str], Dict[str, str], Dict[str, Any]]:
    created = _empty_created()
    errors: Dict[str, str] = {}
    source_ids: List[str] = [str(x) for x in payload["source_agent_ids"]]
    primary_id = source_ids[0]
    merged_prompt = str(payload["merged_prompt"])

    for aid in source_ids:
        _, err = _fetch_agent(supabase, aid, company_id)
        if err:
            errors[f"agent:{aid}"] = err

    if errors:
        return None, errors, created

    if dry_run:
        return primary_id, errors, created

    now_iso = _now_iso()
    supabase.table("agents").update(
        {"system_prompt": merged_prompt, "updated_at": now_iso}
    ).eq("id", primary_id).execute()

    for secondary_id in source_ids[1:]:
        supabase.table("agents").update(
            {"status": "offline", "updated_at": now_iso}
        ).eq("id", secondary_id).execute()

    return primary_id, errors, created


_KIND_APPLIERS = {
    "hire_new_agent": _apply_hire_new_agent,
    "rewrite_system_prompt": _apply_rewrite_system_prompt,
    "add_specialty": _apply_add_specialty,
    "create_specialty": _apply_create_specialty,
    "consolidate_agents": _apply_consolidate_agents,
}


def apply_athena_recommendation(
    supabase: Any,
    recommendation: Dict[str, Any],
    *,
    dry_run: bool = False,
    review_notes_append: Optional[str] = None,
) -> Dict[str, Any]:
    """Aplica uma row de athena_recommendations (status deve ser 'approved').

    Usa service_role client. Caller deve validar tenant via JWT/RLS na leitura.
    """
    rec_id = str(recommendation["id"])
    company_id = str(recommendation["company_id"])
    kind = str(recommendation.get("kind") or "")
    status = str(recommendation.get("status") or "")

    if kind in INFORMATIVE_KINDS:
        return _result(
            status="failed",
            recommendation_id=rec_id,
            errors={"kind": "kind_not_executable"},
        )

    if kind not in EXECUTABLE_KINDS:
        return _result(
            status="failed",
            recommendation_id=rec_id,
            errors={"kind": f"unknown_kind:{kind}"},
        )

    if status == "applied":
        return _result(
            status="applied",
            recommendation_id=rec_id,
            agent_id=recommendation.get("target_agent_id"),
            errors={"status": "already_applied"},
        )

    if status != "approved":
        return _result(
            status="failed",
            recommendation_id=rec_id,
            errors={
                "status": (
                    f"apply_requires_approved got '{status}'. "
                    "Faça PATCH status=approved antes."
                )
            },
        )

    proposed = recommendation.get("proposed_changes_json") or {}
    if not isinstance(proposed, dict):
        return _result(
            status="failed",
            recommendation_id=rec_id,
            errors={"proposed_changes_json": "must_be_object"},
        )

    # Bundle v2: fora do escopo v1 — rejeitar explicitamente
    if proposed.get("schema_version") == 2 or proposed.get("agent_capability_bundle"):
        return _result(
            status="failed",
            recommendation_id=rec_id,
            errors={"bundle": "agent_capability_bundle_v2_not_supported_in_v1_apply"},
        )

    validation_err = _validate_proposed_changes_by_kind(kind, proposed)
    if validation_err:
        return _result(
            status="failed",
            recommendation_id=rec_id,
            errors={"proposed_changes_json": validation_err},
        )

    applier = _KIND_APPLIERS[kind]
    agent_id, step_errors, created = applier(
        supabase, company_id, proposed, dry_run=dry_run
    )

    if step_errors:
        outcome = "partial_apply" if agent_id else "failed"
        return _result(
            status=outcome,
            recommendation_id=rec_id,
            agent_id=agent_id or recommendation.get("target_agent_id"),
            created=created,
            errors=step_errors,
        )

    if dry_run:
        return _result(
            status="applied",
            recommendation_id=rec_id,
            agent_id=agent_id or recommendation.get("target_agent_id"),
            created=created,
            errors={"dry_run": "validation_only_no_persist"},
        )

    now_iso = _now_iso()
    update_row: Dict[str, Any] = {
        "status": "applied",
        "updated_at": now_iso,
    }
    resolved_agent_id = agent_id or recommendation.get("target_agent_id")
    if resolved_agent_id and kind in {
        "hire_new_agent",
        "rewrite_system_prompt",
        "add_specialty",
        "consolidate_agents",
    }:
        update_row["target_agent_id"] = resolved_agent_id
    if review_notes_append:
        prev = (recommendation.get("review_notes") or "").strip()
        update_row["review_notes"] = (
            f"{prev}\n[apply] {review_notes_append}".strip()
            if prev
            else f"[apply] {review_notes_append}"
        )

    try:
        supabase.table("athena_recommendations").update(update_row).eq(
            "id", rec_id
        ).execute()
    except Exception as e:
        logger.error("apply: failed to mark recommendation applied %s: %s", rec_id, e)
        return _result(
            status="partial_apply",
            recommendation_id=rec_id,
            agent_id=resolved_agent_id,
            created=created,
            errors={"persist_status": str(e)},
        )

    return _result(
        status="applied",
        recommendation_id=rec_id,
        agent_id=resolved_agent_id,
        created=created,
    )
