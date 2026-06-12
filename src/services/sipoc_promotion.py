from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import logging

from src.services.roi_calculator import calculate_automation_potential
from src.models import Agent, Routine, RoutineSchedule, TaskBlueprint
from src.services.task_factory import TaskFactory

logger = logging.getLogger("SipocPromotion")


def _slugify(name: str) -> str:
    import re
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return s or "step"


def _ensure_unique_slug(slug: str, taken: set) -> str:
    if slug not in taken:
        return slug
    i = 2
    while f"{slug}-{i}" in taken:
        i += 1
    return f"{slug}-{i}"


async def promote_process_to_workflow(
    supabase_client,
    *,
    sipoc_process_id: str,
    goal_id: Optional[str] = None,
    company_id: Optional[str] = None,
    kind: str = "project",
) -> Dict[str, Any]:
    """Promove um SIPOC process inteiro para workflow definition + steps + tasks.

    Pipeline:
      1. Busca processo + atividades (components type='activity')
      2. Cria workflow_definition com goal_id e kind
      3. Cria workflow_steps para cada atividade
      4. Atualiza sipoc_processes.workflow_definition_id
      5. Chama TaskFactory.materialize_workflow() para gerar tasks

    Returns {workflow_id, steps_created, materialized, warnings}
    """
    warnings: List[str] = []
    now = datetime.now(timezone.utc).isoformat()

    # 1. Busca processo
    proc_res = (
        supabase_client.table("sipoc_processes")
        .select("*, sipoc_sectors(company_id)")
        .eq("id", sipoc_process_id)
        .limit(1)
        .execute()
    )
    if not proc_res.data:
        return {"error": "SIPOC process not found", "process_id": sipoc_process_id}
    process = proc_res.data[0]

    resolved_company_id = company_id or process.get("company_id")
    if not resolved_company_id and process.get("sipoc_sectors"):
        resolved_company_id = process["sipoc_sectors"].get("company_id")
    if not resolved_company_id:
        return {"error": "company_id could not be resolved", "process_id": sipoc_process_id}

    # 2. Busca atividades do processo
    comp_res = (
        supabase_client.table("sipoc_components")
        .select("id, type, content, responsible_position_id")
        .eq("process_id", sipoc_process_id)
        .eq("type", "activity")
        .order("created_at")
        .execute()
    )
    activities = list(comp_res.data or [])
    if not activities:
        return {"error": "No activities found in SIPOC process", "process_id": sipoc_process_id}

    # 3. Cria workflow_definition
    workflow_id = str(uuid4())
    process_name = (process.get("name") or "SIPOC Workflow").strip()
    workflow_slug = _ensure_unique_slug(_slugify(process_name), set())

    # Garante slug único no DB
    existing = (
        supabase_client.table("workflow_definitions")
        .select("slug")
        .eq("company_id", resolved_company_id)
        .execute()
    )
    taken_slugs = {r["slug"] for r in (existing.data or [])}
    workflow_slug = _ensure_unique_slug(workflow_slug, taken_slugs)

    wf_row = {
        "id": workflow_id,
        "company_id": resolved_company_id,
        "name": process_name[:200],
        "slug": workflow_slug[:200],
        "description": process.get("description"),
        "is_active": True,
        "version": 1,
        "trigger_type": "manual",
        "is_scheduled": False,
        "goal_id": goal_id,
        "kind": kind if kind in ("project", "routine") else "project",
        "created_at": now,
        "updated_at": now,
    }
    try:
        supabase_client.table("workflow_definitions").insert(wf_row).execute()
    except Exception as exc:
        logger.exception("promote_process: workflow insert failed")
        return {"error": f"workflow insert failed: {exc}", "process_id": sipoc_process_id}

    # 4. Cria workflow_steps para cada atividade
    step_rows: List[Dict[str, Any]] = []
    taken_step_slugs: set = set()
    for idx, act in enumerate(activities):
        content = act.get("content") or {}
        name = (content.get("name") or act.get("name") or f"activity-{idx+1}").strip()
        slug = _ensure_unique_slug(_slugify(name), taken_step_slugs)
        taken_step_slugs.add(slug)

        step_row = {
            "id": str(uuid4()),
            "workflow_id": workflow_id,
            "step_order": idx,
            "name": name[:200],
            "slug": slug[:200],
            # description não existe em workflow_steps; what vai para sipoc_meta
            "requires_approval": False,
            "on_success_step_id": None,
            "on_failure_action": "block",
            "active": True,
            "contract_version": "v1",
            "validation_status": "amarelo",
            "validation_errors": [],
            "logic_pattern": None,
            "responsavel": "agente",  # CHECK aceita 'agente'|'humano'|'sistema'; who vai para sipoc_meta
            "setor": None,
            "ferramentas": [],
            "sla_horas": None,
            "alertas": [],
            "sipoc_meta": {
                "source": "sipoc_promotion",
                "sipoc_component_id": act.get("id"),
                "sipoc_process_id": sipoc_process_id,
                "responsible_position_id": act.get("responsible_position_id"),
            },
            "proximo_step_codes": [],
            "default_operation_type": None,
            "trigger_type": None,
            "trigger_config": {},
            "created_at": now,
        }
        step_rows.append(step_row)

    # Resolve proximo_step_codes (linear chain) — on_success_step_id populado em 2ª pass
    for i in range(len(step_rows) - 1):
        step_rows[i]["proximo_step_codes"] = [step_rows[i + 1]["slug"]]

    inserted = 0
    slug_to_id: Dict[str, str] = {}
    for row in step_rows:
        try:
            supabase_client.table("workflow_steps").insert(row).execute()
            inserted += 1
            slug_to_id[row["slug"]] = row["id"]
        except Exception as exc:
            logger.warning("promote_process: step insert failed slug=%s: %s", row["slug"], exc)
            warnings.append(f"step '{row['slug']}': insert failed ({exc!s})")

    # 2ª pass: resolve on_success_step_id para chain linear
    for i in range(len(step_rows) - 1):
        row_id = slug_to_id.get(step_rows[i]["slug"])
        next_id = slug_to_id.get(step_rows[i + 1]["slug"])
        if row_id and next_id:
            try:
                supabase_client.table("workflow_steps").update(
                    {"on_success_step_id": next_id}
                ).eq("id", row_id).execute()
            except Exception as exc:
                logger.warning("promote_process: on_success update failed: %s", exc)
                warnings.append(f"on_success update failed for {step_rows[i]['slug']}: {exc!s}")

    # 5. Atualiza sipoc_processes.workflow_definition_id
    try:
        supabase_client.table("sipoc_processes").update(
            {"workflow_definition_id": workflow_id, "goal_id": goal_id, "updated_at": now}
        ).eq("id", sipoc_process_id).execute()
    except Exception as exc:
        logger.warning("promote_process: sipoc update failed: %s", exc)
        warnings.append(f"sipoc_process update failed: {exc!s}")

    # 6. Materializa tasks via TaskFactory
    materialized = None
    try:
        factory = TaskFactory(supabase_client)
        blueprint = TaskBlueprint(
            title=f"[SIPOC→Workflow] {process_name}",
            description=process.get("description") or f"Workflow gerado a partir do SIPOC '{process_name}'",
            budget_limit=200_000,
            goal_id=goal_id,
        )
        materialized = factory.materialize_workflow(
            company_id=resolved_company_id,
            workflow_slug=workflow_slug,
            parent_input=blueprint,
        )
    except Exception as exc:
        logger.exception("promote_process: task materialization failed")
        warnings.append(f"task materialization failed: {exc!s}")

    return {
        "workflow_id": workflow_id,
        "workflow_slug": workflow_slug,
        "steps_created": inserted,
        "steps_expected": len(step_rows),
        "materialized": {
            "parent_task_id": materialized.parent.id if materialized else None,
            "subtask_count": len(materialized.subtasks) if materialized else 0,
        } if materialized else None,
        "warnings": warnings,
    }


async def promote_activity_to_automation(supabase_client, component_id: str) -> Dict[str, Any]:
    """
    Transforma uma atividade SIPOC em um Agente e uma Rotina funcional.
    """
    # 1. Buscar o componente
    comp_res = supabase_client.table("sipoc_components").select("*, sipoc_processes(*)").eq("id", component_id).single().execute()
    if not comp_res.data:
        return {"error": "Component not found"}
    
    component = comp_res.data
    process = component.get("sipoc_processes")
    content = component.get("content", {})
    
    # 2. Calcular Score Final (Rubrica v1)
    score = calculate_automation_potential(content)
    
    # 3. Definir Adaptador e Lógica
    logic_pattern = content.get("logicPattern", "SIMPLE")
    adapter_type = "claude_code"
    if logic_pattern == "WAIT-EVENT":
        adapter_type = "webhook" # Exemplo de mapeamento
    
    # 4. Criar o Agente
    agent_id = str(uuid4())
    agent_data = {
        "id": agent_id,
        "company_id": process.get("company_id"),
        "name": content.get("name", "Novo Agente"),
        "role": f"Automatizador de {process.get('name')}",
        "status": "idle",
        "token_budget": 50000,
        "current_burn_rate": 0.0,
        "adapter_type": adapter_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    supabase_client.table("agents").insert(agent_data).execute()
    
    # 5. Criar a Rotina (Schedule)
    when = content.get("when", "").lower()
    cron = "0 9 * * *" # Default: todo dia às 9h
    if "semanal" in when:
        cron = "0 9 * * 1" # Toda segunda às 9h
    
    routine_id = str(uuid4())
    routine_data = {
        "id": routine_id,
        "company_id": process.get("company_id"),
        "name": f"Rotina: {content.get('name')}",
        "status": "active",
        "schedule": {
            "cron": cron,
            "timezone": "America/Sao_Paulo",
            "human": f"Execução baseada em: {when}"
        },
        "agent_id": agent_id,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    supabase_client.table("routines").insert(routine_data).execute()
    
    # 6. Atualizar o componente SIPOC com o score e status
    supabase_client.table("sipoc_components").update({
        "validation_status": "verde" if score > 60 else "amarelo",
        "metadata": {
            **component.get("metadata", {}),
            "promoted_at": datetime.now(timezone.utc).isoformat(),
            "agent_id": agent_id,
            "routine_id": routine_id,
            "automation_score": score
        }
    }).eq("id", component_id).execute()
    
    return {
        "success": True,
        "agent_id": agent_id,
        "routine_id": routine_id,
        "score": score
    }
