"""Serializa workflow_definitions + workflow_steps em formato pro endpoint
GET /api/agent/workflow.

Substitui `src/services/brain/workflow_aduaneiro.workflow_to_dict()` (estático).
Em M5 (cleanup Brain) o brain pode ser deletado — este service é o sucessor.

Schema de output mantém compat aproximada com brain:
{
  "id": uuid,
  "slug": text,
  "version": int,
  "name": text,
  "description": text,
  "company_id": uuid,
  "trigger_type": text,
  "is_active": bool,
  "etapas": [
    {
      "step_order": int,
      "slug": text,
      "name": text,
      "default_operation_type": text,
      "responsavel": text,
      "setor": text,
      "ferramentas": [string],
      "proximo_step_codes": [string],
      "ferramentas_detail": [tools_catalog row]  (enrichment opcional via ?detail=true)
    }
  ]
}
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("WorkflowSerializer")


def fetch_workflow_dict(
    supabase: Any,
    *,
    company_id: str,
    slug: Optional[str] = None,
    workflow_id: Optional[str] = None,
    include_tool_details: bool = False,
) -> Optional[Dict[str, Any]]:
    """Carrega workflow_definitions + steps + (opcional) tools detail.

    Retorna dict serializado ou None se workflow não encontrado.

    Args:
        supabase: client (service_role OK — multi-tenant guard via company_id).
        company_id: validado contra workflow_definitions.company_id.
        slug: lookup por slug (preferido). Se vazio e workflow_id também,
            usa o primeiro is_active=true mais recente.
        workflow_id: lookup por UUID direto (alternativa a slug).
        include_tool_details: se True, popula `ferramentas_detail` com row
            completo de tools_catalog pra cada string em `ferramentas[]`.
    """
    try:
        q = supabase.table("workflow_definitions").select(
            "id, company_id, name, slug, description, is_active, version, trigger_type, is_scheduled"
        ).eq("company_id", company_id)

        if workflow_id:
            q = q.eq("id", workflow_id)
        elif slug:
            q = q.eq("slug", slug)
        else:
            q = q.eq("is_active", True).order("updated_at", desc=True)

        res = q.limit(1).execute()
        if not res.data:
            return None
        wf = res.data[0]
    except Exception as exc:
        logger.error("fetch_workflow_dict: workflow_definitions query failed: %s", exc)
        return None

    # Steps
    try:
        steps_res = (
            supabase.table("workflow_steps")
            .select(
                "id, step_order, slug, name, default_operation_type, responsavel, "
                "setor, ferramentas, proximo_step_codes, logic_pattern, requires_approval, "
                "agent_specialty_config_id"
            )
            .eq("workflow_id", wf["id"])
            .order("step_order")
            .execute()
        )
        steps = steps_res.data or []
    except Exception as exc:
        logger.warning("fetch_workflow_dict: workflow_steps query failed wf=%s: %s", wf["id"], exc)
        steps = []

    # Optional: tools catalog enrichment
    tools_lookup: Dict[str, Dict[str, Any]] = {}
    if include_tool_details:
        try:
            all_tool_ids: List[str] = []
            for s in steps:
                fer = s.get("ferramentas") or []
                if isinstance(fer, list):
                    all_tool_ids.extend([t for t in fer if isinstance(t, str)])
            if all_tool_ids:
                tools_res = (
                    supabase.table("tools_catalog")
                    .select("id, name, description, category, runtime_module")
                    .in_("id", list(set(all_tool_ids)))
                    .execute()
                )
                tools_lookup = {t["id"]: t for t in (tools_res.data or [])}
        except Exception as exc:
            logger.warning("fetch_workflow_dict: tools_catalog lookup failed: %s", exc)

    etapas: List[Dict[str, Any]] = []
    for s in steps:
        fer = s.get("ferramentas") or []
        step_dict: Dict[str, Any] = {
            "step_order": s.get("step_order"),
            "slug": s.get("slug"),
            "name": s.get("name"),
            "default_operation_type": s.get("default_operation_type"),
            "responsavel": s.get("responsavel"),
            "setor": s.get("setor"),
            "ferramentas": fer,
            "proximo_step_codes": s.get("proximo_step_codes") or [],
            "logic_pattern": s.get("logic_pattern"),
            "requires_approval": s.get("requires_approval", False),
            "agent_specialty_config_id": s.get("agent_specialty_config_id"),
        }
        if include_tool_details:
            step_dict["ferramentas_detail"] = [
                tools_lookup.get(t) for t in fer if isinstance(t, str)
            ]
        etapas.append(step_dict)

    return {
        "id": wf.get("id"),
        "company_id": wf.get("company_id"),
        "slug": wf.get("slug"),
        "name": wf.get("name"),
        "description": wf.get("description"),
        "version": wf.get("version"),
        "trigger_type": wf.get("trigger_type"),
        "is_active": wf.get("is_active"),
        "is_scheduled": wf.get("is_scheduled"),
        "etapas": etapas,
        "source": "vectraclip.workflow_definitions",
    }


def list_active_workflows(supabase: Any, company_id: str) -> List[Dict[str, Any]]:
    """Lista resumida de workflows ativos da company (sem steps)."""
    try:
        res = (
            supabase.table("workflow_definitions")
            .select("id, slug, name, description, version, trigger_type, is_active, updated_at")
            .eq("company_id", company_id)
            .eq("is_active", True)
            .order("updated_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("list_active_workflows failed: %s", exc)
        return []
