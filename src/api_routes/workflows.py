"""
src.api_routes.workflows — definições de workflow + materialização de tasks.

Endpoints:
- GET    /api/companies/{id}/workflows                    list_company_workflows
- GET    /api/companies/{id}/workflows/{slug}             get_company_workflow
- POST   /api/companies/{id}/workflows                    upsert_company_workflow_post
- PUT    /api/companies/{id}/workflows/{slug}             upsert_company_workflow_put
- POST   /api/companies/{id}/workflows/import             import_company_workflow
- POST   /api/companies/{id}/tasks/from-workflow          create_tasks_from_workflow
- GET    /api/companies/{id}/tasks/{parent_id}/tree       get_task_tree

Modelos Pydantic locais: WorkflowUpsertMeta, WorkflowUpsertBody,
RunWorkflowBody, WorkflowImportBody.

Helpers locais (nao usados por outros submodules):
- _slugify_workflow
- _steps_for_validation
- _activities_to_workflow_steps
- _persist_workflow_steps
- _save_workflow_definition_and_steps

Dependencias src.* sao importadas lazy dentro de cada handler para evitar
circular import com api.py.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.models import TaskBlueprint, WorkflowStepRich
from src.postgrest_errors import PostgrestAPIError

logger = logging.getLogger("api.workflows")
router = APIRouter(tags=["workflows"])


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models locais
# ─────────────────────────────────────────────────────────────────────────────

class WorkflowUpsertMeta(BaseModel):
    """Metadata do workflow definition.

    PR-T1: ganhou `trigger_type`, `cron_expression`, `is_scheduled` (workflow
    vira fonte única de configuração de disparo — agendado ou manual). Quando
    trigger_type='cron' e is_scheduled=true, o handler de save sincroniza
    automaticamente uma row em `vectraclip.routines` (preserva compat com
    daemon cron existente até PR-T3 deprecar o endpoint de routines).
    """

    slug: Optional[str] = None
    name: str
    description: Optional[str] = None
    trigger_type: Optional[str] = None       # default 'manual' aplicado no save
    cron_expression: Optional[str] = None
    is_scheduled: Optional[bool] = None

    class Config:
        populate_by_name = True
        extra = "ignore"


class WorkflowUpsertBody(BaseModel):
    workflow: WorkflowUpsertMeta
    steps: List[WorkflowStepRich]

    class Config:
        populate_by_name = True
        extra = "ignore"


class RunWorkflowBody(BaseModel):
    workflowSlug: str
    parent: TaskBlueprint
    stepInputs: Optional[Dict[str, Dict[str, Any]]] = None

    class Config:
        populate_by_name = True
        extra = "ignore"


class WorkflowImportBody(BaseModel):
    processName: str
    sector: Optional[str] = None
    activities: List[Dict[str, Any]]

    class Config:
        populate_by_name = True
        extra = "ignore"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _slugify_workflow(name: str, explicit_slug: Optional[str] = None) -> str:
    if explicit_slug and str(explicit_slug).strip():
        s = str(explicit_slug).strip().lower()
        s = re.sub(r"[^a-z0-9_-]+", "-", s)
        s = re.sub(r"-+", "-", s).strip("-")
        return (s[:80] if s else "workflow")
    x = (name or "").lower().strip()
    x = re.sub(r"[^a-z0-9]+", "-", x)
    x = re.sub(r"-+", "-", x).strip("-")
    return (x[:80] if x else "workflow")


def _steps_for_validation(steps: List[WorkflowStepRich]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in steps:
        d = s.dict(by_alias=True)
        code = (s.step_code or (s.slug or "")).strip()
        d["step_code"] = code
        d["slug"] = code
        d["proximo"] = list(s.proximo or [])
        out.append(d)
    return out


def _activities_to_workflow_steps(
    activities: List[Dict[str, Any]], sector: Optional[str]
) -> List[WorkflowStepRich]:
    """Traduz saída bruta do Workflow Builder ou workflow_steps[] já estruturado."""
    if not activities:
        raise HTTPException(
            status_code=422,
            detail={"violations": ["activities[] vazio"]},
        )
    first = activities[0]
    if first.get("stepCode") or first.get("step_code"):
        return [WorkflowStepRich(**a) for a in activities]

    out: List[WorkflowStepRich] = []
    for i, act in enumerate(activities):
        code = f"W{i + 1}"
        nome = act.get("name") or act.get("nome") or f"Atividade {i + 1}"
        proximo = [f"W{i + 2}"] if i < len(activities) - 1 else []
        five = act.get("5w2h") or act.get("fiveW2H") or {}
        lp = act.get("logicPattern") or act.get("logic_pattern") or "SIMPLE"
        score = act.get("automationScore")
        responsavel = act.get("responsavel")
        if score is not None:
            try:
                if int(score) < 40:
                    responsavel = "humano"
            except (TypeError, ValueError):
                pass
        out.append(
            WorkflowStepRich(
                step_code=code,
                nome=nome,
                descricao=act.get("descricao"),
                logic_pattern=lp,
                responsavel=responsavel or "agente",
                setor=act.get("setor") or sector,
                ferramentas=list(act.get("ferramentas") or []),
                sla_horas=act.get("slaHoras") or act.get("sla_horas"),
                alertas=list(act.get("alertas") or []),
                proximo=proximo,
                suppliers=act.get("suppliers"),
                inputs=act.get("inputs"),
                outputs=act.get("outputs"),
                customers=act.get("customers"),
                decisions=act.get("decisions"),
                five_w2h=five if isinstance(five, dict) else None,
            )
        )
    return out


def _persist_workflow_steps(
    wf_id: str, steps: List[WorkflowStepRich], sector_fallback: Optional[str]
) -> List[Dict[str, Any]]:
    """Remove steps antigos e insere lote; devolve linhas inseridas (com id)."""
    from src.api import supabase
    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_required")
    supabase.table("workflow_steps").delete().eq("workflow_id", wf_id).execute()
    inserted: List[Dict[str, Any]] = []
    for i, s in enumerate(steps, start=1):
        code = (s.step_code or s.slug or "").strip()
        if not code:
            raise HTTPException(
                status_code=422,
                detail={"violations": [f"step ordem {i}: stepCode obrigatório"]},
            )
        prox = list(s.proximo or [])
        row: Dict[str, Any] = {
            "workflow_id": wf_id,
            "step_order": i,
            "name": s.resolved_name(),
            "slug": code,
            "requires_approval": False,
            "logic_pattern": s.logic_pattern,
            "responsavel": s.responsavel,
            "setor": s.setor or sector_fallback,
            "ferramentas": list(s.ferramentas or []),
            "sla_horas": s.resolved_sla_hours(),
            "alertas": list(s.alertas or []),
            "proximo_step_codes": prox,
            "default_operation_type": s.default_operation_type,
            "specialty_slug": s.default_assigned_specialty_slug,
            "trigger_type": (s.trigger_type or "realtime").strip() or "realtime",
            "trigger_config": dict(s.trigger_config or {}),
            "agent_specialty_config_id": s.agent_specialty_config_id,
            "active": True,
        }
        if s.sipoc_meta is not None:
            row["sipoc_meta"] = dict(s.sipoc_meta)
        opt_json = {
            "suppliers": s.suppliers,
            "inputs": s.inputs,
            "outputs": s.outputs,
            "customers": s.customers,
            "decisions": s.decisions,
            "five_w2h": s.five_w2h,
        }
        for k, v in opt_json.items():
            if v is not None:
                row[k] = v
        ins = supabase.table("workflow_steps").insert(row).execute()
        if ins.data:
            inserted.append(ins.data[0])
    slug_to_id = {(r.get("slug") or "").strip(): r.get("id") for r in inserted}
    for r in inserted:
        prox = r.get("proximo_step_codes") or []
        if isinstance(prox, str):
            prox = [prox]
        if not prox:
            continue
        nxt_id = slug_to_id.get(str(prox[0]).strip())
        if nxt_id:
            supabase.table("workflow_steps").update({"on_success_step_id": nxt_id}).eq(
                "id", r["id"]
            ).execute()
    return inserted


# PR-T1: tipos canon válidos pro CHECK em routines.operation_type
# (snapshot pós migration 20260512190530). Quando o primeiro step do workflow
# tem operation_type fora dessa lista, cai em 'other' para não bloquear o
# UPSERT na routine sincronizada.
_ROUTINE_OP_TYPE_WHITELIST = {
    "email_lead", "route-cost-calculation", "freight-quotation",
    "crm-fill", "crm-fill-precheck", "financial-audit",
    "financial-bookkeeping", "planner-import-ofx",
    "planner-categorize-pendings",
    # Task #18 (sessão 2026-05-14): audit histórico
    "kronos-audit-historico", "planner-apply-corrections",
    "other",
}


def _sync_routine_for_workflow(
    supabase: Any,
    wf_id: str,
    company_id: str,
    wf_name: str,
    trigger_type: Optional[str],
    cron_expression: Optional[str],
    is_scheduled: Optional[bool],
    first_step: Optional[Dict[str, Any]],
) -> None:
    """PR-T2 — sincroniza row em vectraclip.routines a partir do workflow.

    Comportamento:
    - trigger_type='cron' AND is_scheduled=true AND cron_expression válido:
        UPSERT routine vinculada (workflow_definition_id=wf_id). Status='active'.
    - Qualquer outro caso (manual, paused, sem cron):
        PAUSE routine vinculada se houver (preserva histórico — não DELETE).

    Resolve agent_id via primeiro step.specialty_slug (MorpheusDispatcher).
    Fallback operation_type='other' quando o primeiro step tem op_type fora do
    CHECK em routines.operation_type.
    """
    is_cron_active = (
        (trigger_type or "").strip() == "cron"
        and bool(is_scheduled)
        and bool((cron_expression or "").strip())
    )

    existing = (
        supabase.table("routines")
        .select("id")
        .eq("workflow_definition_id", wf_id)
        .limit(1)
        .execute()
    )
    routine_id = existing.data[0]["id"] if existing.data else None

    if not is_cron_active:
        if routine_id:
            try:
                supabase.table("routines").update({"status": "paused"}).eq(
                    "id", routine_id
                ).execute()
            except Exception as exc:
                logger.warning(
                    "sync_routine_for_workflow: pause failed wf=%s routine=%s err=%s",
                    wf_id, routine_id, exc,
                )
        return

    op_type = (first_step or {}).get("default_operation_type") or "other"
    if op_type not in _ROUTINE_OP_TYPE_WHITELIST:
        op_type = "other"

    agent_id: Optional[str] = None
    spec_slug = (first_step or {}).get("specialty_slug")
    if spec_slug:
        from src.services.morpheus_dispatcher import MorpheusDispatcher
        try:
            agent_id = MorpheusDispatcher(supabase)._find_agent(company_id, spec_slug)
        except Exception as exc:
            logger.warning(
                "sync_routine_for_workflow: _find_agent failed spec=%s err=%s",
                spec_slug, exc,
            )

    schedule_jsonb = {
        "cron": (cron_expression or "").strip(),
        "timezone": "America/Sao_Paulo",
    }

    row = {
        "company_id": company_id,
        "name": wf_name,
        "status": "active",
        "schedule": schedule_jsonb,
        "agent_id": agent_id,
        "operation_type": op_type,
        "workflow_definition_id": wf_id,
    }

    try:
        if routine_id:
            supabase.table("routines").update(row).eq("id", routine_id).execute()
        else:
            supabase.table("routines").insert(row).execute()
    except Exception as exc:
        logger.error(
            "sync_routine_for_workflow: write failed wf=%s op=%s err=%s",
            wf_id, op_type, exc,
        )


async def _save_workflow_definition_and_steps(
    company_id: str, body: WorkflowUpsertBody, *, slug_from_path: Optional[str] = None
) -> Dict[str, Any]:
    from src.api import supabase
    from src.services.workflow_graph import validate_workflow_steps

    meta = body.workflow
    slug = _slugify_workflow(meta.name, slug_from_path or meta.slug)
    graph_steps = _steps_for_validation(body.steps)
    # Workflow vazio é permitido (rascunho n8n-style): user cria a
    # definição primeiro, depois adiciona steps pelo canvas. Validação só
    # roda quando HÁ steps. A materialização (TaskFactory) faz validação
    # estrita depois — não dá pra rodar workflow vazio mesmo.
    # Restaurando comportamento do commit e319fed (regressão posterior).
    if graph_steps:
        violations = validate_workflow_steps(graph_steps)
        if violations:
            raise HTTPException(status_code=422, detail={"violations": violations})

    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_required")

    # postgrest-py 0.13.2: maybe_single() retorna None ao invés de
    # {"data": None} quando não acha. Usamos .limit(1) e tratamos como lista.
    #
    # Lookup duplo: 1) workflow company-specific 2) workflow global (company_id NULL).
    # Edita o que aparecer (global continua editável pra company que o vê);
    # se nenhum existir, INSERT cria company-specific novo.
    # Restaura HOTFIX-7 perdido em merge posterior.
    existing_co = (
        supabase.table("workflow_definitions")
        .select("*")
        .eq("company_id", company_id)
        .eq("slug", slug)
        .limit(1)
        .execute()
    )
    co_rows = list(existing_co.data or [])
    wf_row: Optional[Dict[str, Any]] = co_rows[0] if co_rows else None
    if wf_row is None:
        existing_global = (
            supabase.table("workflow_definitions")
            .select("*")
            .is_("company_id", "null")
            .eq("slug", slug)
            .limit(1)
            .execute()
        )
        gl_rows = list(existing_global.data or [])
        if gl_rows:
            wf_row = gl_rows[0]

    now = datetime.now(timezone.utc).isoformat()
    sector_fallback = None

    # PR-T1: trigger fields opcionais — só propaga ao DB quando vieram no payload
    trigger_patch: Dict[str, Any] = {}
    if meta.trigger_type is not None:
        trigger_patch["trigger_type"] = meta.trigger_type
    if meta.cron_expression is not None:
        trigger_patch["cron_expression"] = meta.cron_expression
    if meta.is_scheduled is not None:
        trigger_patch["is_scheduled"] = bool(meta.is_scheduled)

    if wf_row:
        new_ver = int(wf_row.get("version") or 1) + 1
        upd = {
            "name": meta.name,
            "description": meta.description,
            "updated_at": now,
            "version": new_ver,
            **trigger_patch,
        }
        supabase.table("workflow_definitions").update(upd).eq("id", wf_row["id"]).execute()
        wf_id = wf_row["id"]
    else:
        insert_row = {
            "company_id": company_id,
            "name": meta.name,
            "slug": slug,
            "description": meta.description,
            "is_active": True,
            "version": 1,
            "created_at": now,
            "updated_at": now,
            **trigger_patch,
        }
        ins = supabase.table("workflow_definitions").insert(insert_row).execute()
        if not ins.data:
            raise HTTPException(status_code=500, detail="workflow_insert_failed")
        wf_row = ins.data[0]
        wf_id = wf_row["id"]

    step_rows = _persist_workflow_steps(wf_id, body.steps, sector_fallback)

    # PR-T2: sincroniza routine vinculada ao workflow (UPSERT ou PAUSE)
    first_step = step_rows[0] if step_rows else None
    _sync_routine_for_workflow(
        supabase=supabase,
        wf_id=wf_id,
        company_id=company_id,
        wf_name=meta.name,
        trigger_type=meta.trigger_type,
        cron_expression=meta.cron_expression,
        is_scheduled=meta.is_scheduled,
        first_step=first_step,
    )

    detail = (
        supabase.table("workflow_definitions")
        .select("*")
        .eq("id", wf_id)
        .maybe_single()
        .execute()
    )
    return {
        "workflow": detail.data or wf_row,
        "steps": step_rows,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/companies/{company_id}/workflows")
@router.get("/companies/{company_id}/workflows")
async def list_company_workflows(request: Request, company_id: str):
    """List workflows visíveis para a company: específicos dela + globais (company_id NULL).

    Task #45 (consolidação): endpoint era duplicado em src/api.py:6755 (versão
    monolítica) e aqui (versão moderna com steps_count + JWT validation). Versões
    divergiam: a monolítica incluía workflows globais (company_id IS NULL) mas
    não validava JWT nem populava steps_count; esta validava JWT e populava
    steps_count mas filtrava só por company_id. Consolidado aqui — preserva todos
    os comportamentos:
      • company_id = X OR company_id IS NULL (globais visíveis a todas)
      • is_active = true
      • steps_count populado
      • JWT validation
    """
    from src.api import supabase, validate_jwt_company_id

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_required")
    # postgrest-py 0.13.2 não expõe .or_() no SyncSelectRequestBuilder.
    # Fazemos union manual: workflows da company + globais (company_id IS NULL).
    res_co = (
        supabase.table("workflow_definitions")
        .select("*")
        .eq("company_id", company_id)
        .eq("is_active", True)
        .order("name")
        .execute()
    )
    res_global = (
        supabase.table("workflow_definitions")
        .select("*")
        .is_("company_id", "null")
        .eq("is_active", True)
        .order("name")
        .execute()
    )
    seen: set[str] = set()
    rows: List[Dict[str, Any]] = []
    for r in list(res_co.data or []) + list(res_global.data or []):
        rid = str(r.get("id"))
        if rid in seen:
            continue
        seen.add(rid)
        rows.append(r)
    rows.sort(key=lambda r: str(r.get("name") or "").lower())
    if not rows:
        return []
    wf_ids = [r["id"] for r in rows]
    st = (
        supabase.table("workflow_steps")
        .select("workflow_id")
        .in_("workflow_id", wf_ids)
        .execute()
    )
    counts = Counter(str(r["workflow_id"]) for r in (st.data or []))
    out = []
    for w in rows:
        item = dict(w)
        item["steps_count"] = counts.get(str(w["id"]), 0)
        out.append(item)
    return out


@router.get("/api/companies/{company_id}/workflows/{slug}")
@router.get("/companies/{company_id}/workflows/{slug}")
async def get_company_workflow(request: Request, company_id: str, slug: str):
    from src.api import supabase, validate_jwt_company_id

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_required")
    res = supabase.table("workflow_definitions").select("*").eq("slug", slug).execute()
    candidates = list(res.data or [])
    wf = next((r for r in candidates if str(r.get("company_id") or "") == str(company_id)), None)
    if not wf:
        wf = next((r for r in candidates if r.get("company_id") is None), None)
    if not wf:
        raise HTTPException(status_code=404, detail="workflow_not_found")
    steps_res = (
        supabase.table("workflow_steps")
        .select("*")
        .eq("workflow_id", wf["id"])
        .order("step_order")
        .execute()
    )
    return {"workflow": wf, "steps": steps_res.data or []}


@router.post("/api/companies/{company_id}/workflows")
@router.post("/companies/{company_id}/workflows")
async def upsert_company_workflow_post(
    request: Request, company_id: str, body: WorkflowUpsertBody
):
    from src.api import validate_jwt_company_id

    validate_jwt_company_id(request.state.token, company_id)
    try:
        return await _save_workflow_definition_and_steps(company_id, body)
    except HTTPException:
        raise
    except PostgrestAPIError as e:
        logger.error("upsert_workflow failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/api/companies/{company_id}/workflows/{slug}")
@router.put("/companies/{company_id}/workflows/{slug}")
async def upsert_company_workflow_put(
    request: Request, company_id: str, slug: str, body: WorkflowUpsertBody
):
    from src.api import validate_jwt_company_id

    validate_jwt_company_id(request.state.token, company_id)
    if body.workflow.slug is None:
        body.workflow.slug = slug
    try:
        return await _save_workflow_definition_and_steps(
            company_id, body, slug_from_path=slug
        )
    except HTTPException:
        raise
    except PostgrestAPIError as e:
        logger.error("upsert_workflow put failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/api/companies/{company_id}/workflows/{slug}")
@router.delete("/companies/{company_id}/workflows/{slug}")
async def delete_company_workflow(
    request: Request, company_id: str, slug: str
):
    """Remove um workflow definition + steps.

    Semântica alinhada com upsert/list:
    - Lookup company-specific PRIMEIRO; se não achar, fallback global
      (company_id IS NULL).
    - Pausa routines vinculadas (não DELETE — preserva histórico de
      runs/agendamento). PR-T3 futuro vai deprecar essas routines.
    - DELETE workflow_steps + workflow_definitions (FK on delete cascade
      cobriria steps, mas executamos explícito para garantir ordem +
      facilitar telemetria).

    Retorna 204 No Content em sucesso, 404 se workflow não existe.
    """
    from src.api import supabase, validate_jwt_company_id
    from fastapi import Response

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_required")

    # Lookup company-specific primeiro
    co_res = (
        supabase.table("workflow_definitions")
        .select("id, slug, name, company_id")
        .eq("company_id", company_id)
        .eq("slug", slug)
        .limit(1)
        .execute()
    )
    wf_row: Optional[Dict[str, Any]] = (co_res.data or [None])[0]

    # Fallback global
    if wf_row is None:
        gl_res = (
            supabase.table("workflow_definitions")
            .select("id, slug, name, company_id")
            .is_("company_id", "null")
            .eq("slug", slug)
            .limit(1)
            .execute()
        )
        wf_row = (gl_res.data or [None])[0]

    if wf_row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "workflow_not_found", "slug": slug},
        )

    wf_id = str(wf_row["id"])

    # Pausa routines vinculadas (preserva histórico)
    try:
        supabase.table("routines").update({"status": "paused"}).eq(
            "workflow_definition_id", wf_id
        ).execute()
    except Exception as exc:
        logger.warning(
            "delete_workflow: pause routines failed wf=%s err=%s", wf_id, exc
        )

    # DELETE steps + workflow
    try:
        supabase.table("workflow_steps").delete().eq("workflow_id", wf_id).execute()
        supabase.table("workflow_definitions").delete().eq("id", wf_id).execute()
    except PostgrestAPIError as exc:
        logger.error("delete_workflow failed wf=%s err=%s", wf_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("delete_workflow unexpected wf=%s err=%s", wf_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info(
        "delete_workflow OK wf=%s slug=%s scope=%s",
        wf_id, slug, "company" if wf_row.get("company_id") else "global",
    )
    return Response(status_code=204)


@router.post("/api/companies/{company_id}/workflows/import")
@router.post("/companies/{company_id}/workflows/import")
async def import_company_workflow(
    request: Request, company_id: str, body: WorkflowImportBody
):
    from src.api import validate_jwt_company_id

    validate_jwt_company_id(request.state.token, company_id)
    steps = _activities_to_workflow_steps(body.activities, body.sector)
    slug = _slugify_workflow(body.processName)
    inner = WorkflowUpsertBody(
        workflow=WorkflowUpsertMeta(
            slug=slug,
            name=body.processName,
            description=f"Importado — setor: {body.sector}" if body.sector else None,
        ),
        steps=steps,
    )
    try:
        return await _save_workflow_definition_and_steps(company_id, inner)
    except HTTPException:
        raise
    except PostgrestAPIError as e:
        logger.error("workflow import failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/companies/{company_id}/tasks/from-workflow")
@router.post("/companies/{company_id}/tasks/from-workflow")
async def create_tasks_from_workflow(
    request: Request, company_id: str, body: RunWorkflowBody
):
    from src.api import supabase, validate_jwt_company_id
    from src.services.task_factory import TaskFactory, TaskFactoryError

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_required")
    factory = TaskFactory(supabase)
    try:
        materialized = factory.materialize_workflow(
            company_id,
            body.workflowSlug,
            body.parent,
            body.stepInputs,
        )
    except TaskFactoryError as e:
        raise HTTPException(status_code=422, detail={"violations": [str(e)]})
    return {
        "parent": materialized.parent.to_zod_dict(),
        "subtasks": [t.to_zod_dict() for t in materialized.subtasks],
    }


@router.get("/api/companies/{company_id}/tasks/{parent_id}/tree")
@router.get("/companies/{company_id}/tasks/{parent_id}/tree")
async def get_task_tree(request: Request, company_id: str, parent_id: str):
    from src.api import supabase, validate_jwt_company_id
    from src.models import Task

    validate_jwt_company_id(request.state.token, company_id)
    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_required")
    pres = (
        supabase.table("tasks")
        .select("*")
        .eq("id", parent_id)
        .eq("company_id", company_id)
        .maybe_single()
        .execute()
    )
    if not pres.data:
        raise HTTPException(status_code=404, detail="task_not_found")
    parent_row = pres.data
    ch_res = (
        supabase.table("tasks")
        .select("*")
        .eq("parent_task_id", parent_id)
        .order("created_at")
        .execute()
    )
    children = list(ch_res.data or [])
    rollup_res = (
        supabase.table("task_tree_status")
        .select("*")
        .eq("parent_id", parent_id)
        .maybe_single()
        .execute()
    )
    rollup = rollup_res.data

    slug_status: Dict[str, str] = {}
    for t in children:
        slug = (t.get("input_json") or {}).get("workflowStepSlug")
        if slug:
            slug_status[str(slug)] = str(t.get("status") or "")

    queued_step_codes: List[str] = []
    ready_backlog_codes: List[str] = []
    for t in children:
        slug = (t.get("input_json") or {}).get("workflowStepSlug")
        if not slug:
            continue
        st = str(t.get("status") or "")
        if st == "queued":
            queued_step_codes.append(str(slug))
        elif st == "backlog":
            deps = t.get("dependency_step_codes") or []
            if isinstance(deps, str):
                deps = [deps]
            # Wave 1A: dep deve estar DONE (era done|skipped). Erro bloqueia successor.
            if all(slug_status.get(str(d)) == "done" for d in deps):
                ready_backlog_codes.append(str(slug))

    parent_input = parent_row.get("input_json") or {}
    return {
        "parent": Task(**parent_row).to_zod_dict(),
        "children": [Task(**c).to_zod_dict() for c in children],
        "rollup": rollup,
        "execution": {
            "queuedStepCodes": queued_step_codes,
            "readyBacklogStepCodes": ready_backlog_codes,
            "estimatedSlaHours": parent_input.get("estimatedSlaHours"),
            "criticalPath": parent_input.get("criticalPath"),
            "topologicalGenerations": parent_input.get("topologicalGenerations"),
            "workflowSlug": parent_input.get("workflowSlug"),
        },
    }
