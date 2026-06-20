"""workflow_builder — cliente do executor genérico (src/agents/specialty_generic.py).

Registra hooks pro slug 'workflow-builder':

- INPUT_BUILDER: lê o processo SIPOC (atividades 5W2H + logicPattern +
  automationScore) E o catálogo de operation_types disponíveis. Monta o JSON de
  input esperado pelo system_prompt_template (migration vec_331), AUMENTADO com
  `availableOperationTypes` — assim o LLM escolhe um op_type/specialty executável
  por step (em vez de deixar o roteamento vazio como o daedalus pelado fazia).

- EFFECT: parseia o array de steps do LLM e escreve workflow_definition +
  workflow_steps RICOS (5W2H, logic_pattern, responsavel, sla, ferramentas,
  default_operation_type, agent_specialty_config_id, assigned_to_agent_id).
  Path B (decisão Marcelo 2026-06-20): se o op_type escolhido não existir/for
  null, o step é escrito mesmo assim com default_operation_type=null e marca
  `needs_handler` em sipoc_meta — handlers folha (enrich-phone/outbound-wa) vêm
  em PR3. A estrutura executável já fica pronta.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.agents.specialty_generic import register_effect, register_input_builder

logger = logging.getLogger("WorkflowBuilder")

SLUG = "workflow-builder"
_VALID_VALIDATION = {"verde", "amarelo", "vermelho"}
_VALID_FAILURE = {"block", "skip", "retry", "escalate"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(text: str, fallback: str = "step") -> str:
    s = (text or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return (s[:80] if s else fallback)


def _activity_name(content: Dict[str, Any], idx: int) -> str:
    if isinstance(content, dict):
        name = content.get("name") or content.get("title") or content.get("label")
        if name:
            return str(name)[:120]
    return f"Atividade {idx + 1}"


def _five_w2h(content: Dict[str, Any]) -> Dict[str, Any]:
    """Extrai 5W2H — aceita nested (fiveW2H) ou flat (what/why/...)."""
    if not isinstance(content, dict):
        return {}
    nested = content.get("fiveW2H") or content.get("5w2h")
    if isinstance(nested, dict) and nested:
        return nested
    flat = {k: content.get(k) for k in ("what", "why", "who", "where", "when", "how", "howMuch")}
    return {k: v for k, v in flat.items() if v}


def _find_process_id(task: Dict[str, Any], supabase: Any) -> Optional[str]:
    """source_id no input_json, senão via goal_id → sipoc_processes."""
    inp = task.get("input_json") if isinstance(task.get("input_json"), dict) else {}
    pid = inp.get("source_id") or inp.get("process_id")
    if pid:
        return str(pid)
    goal_id = task.get("goal_id") or inp.get("goal_id")
    if goal_id and supabase:
        try:
            r = (supabase.table("sipoc_processes").select("id")
                 .eq("goal_id", goal_id).order("created_at", desc=True).limit(1).execute())
            if r.data:
                return str(r.data[0]["id"])
        except Exception as exc:
            logger.warning("find_process_id via goal=%s falhou: %s", goal_id, exc)
    return None


def _load_process(supabase: Any, process_id: str) -> Tuple[str, Optional[str], List[Dict[str, Any]]]:
    """(process_name, sector_name, activities[]) — activities no formato do prompt."""
    name, sector = "Processo", None
    try:
        pr = (supabase.table("sipoc_processes")
              .select("name, sector_id").eq("id", process_id).limit(1).execute())
        if pr.data:
            name = pr.data[0].get("name") or name
            sector_id = pr.data[0].get("sector_id")
            if sector_id:
                sr = (supabase.table("sipoc_sectors").select("name")
                      .eq("id", sector_id).limit(1).execute())
                if sr.data:
                    sector = sr.data[0].get("name")
    except Exception as exc:
        logger.warning("load_process meta falhou process=%s: %s", process_id, exc)

    activities: List[Dict[str, Any]] = []
    try:
        cr = (supabase.table("sipoc_components")
              .select("type, content, order, automation_status, diagnostic_metadata")
              .eq("process_id", process_id).eq("type", "activity").execute())
        # ordena client-side: a coluna "order" colide com o param `order` do PostgREST.
        comps = sorted(cr.data or [], key=lambda c: (c.get("order") if c.get("order") is not None else 0))
        for idx, comp in enumerate(comps):
            content = comp.get("content") or {}
            diag = comp.get("diagnostic_metadata") or {}
            score = diag.get("automationScore") if isinstance(diag, dict) else None
            activities.append({
                "name": _activity_name(content, idx),
                "5w2h": _five_w2h(content),
                "logicPattern": (content.get("logicPattern") if isinstance(content, dict) else None) or "SIMPLE",
                "automationScore": score if isinstance(score, (int, float)) else 50,
            })
    except Exception as exc:
        logger.warning("load_process activities falhou process=%s: %s", process_id, exc)
    return name, sector, activities


def _available_op_types(supabase: Any) -> List[Dict[str, Any]]:
    try:
        r = (supabase.table("operation_types_catalog")
             .select("id, description, default_specialty_slug, primary_agent_id")
             .eq("is_active", True).execute())
        return [
            {"operationType": row["id"], "specialtySlug": row.get("default_specialty_slug"),
             "description": (row.get("description") or "")[:140]}
            for row in (r.data or [])
        ]
    except Exception as exc:
        logger.warning("available_op_types falhou: %s", exc)
        return []


def _resolve_agent_for_op(supabase: Any, op_type: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(primary_agent_id, agent_specialty_config_id) pro op_type — None se não mapear."""
    if not op_type or not supabase:
        return None, None
    try:
        r = (supabase.table("operation_types_catalog")
             .select("primary_agent_id, default_specialty_slug").eq("id", op_type).limit(1).execute())
        if not r.data:
            return None, None
        agent_id = r.data[0].get("primary_agent_id")
        slug = r.data[0].get("default_specialty_slug")
        cfg_id = None
        if agent_id and slug:
            sp = supabase.table("agent_specialties").select("id").eq("slug", slug).limit(1).execute()
            if sp.data:
                c = (supabase.table("agent_specialty_configs").select("id")
                     .eq("agent_id", agent_id).eq("specialty_id", sp.data[0]["id"]).limit(1).execute())
                if c.data:
                    cfg_id = c.data[0]["id"]
        return agent_id, cfg_id
    except Exception as exc:
        logger.warning("resolve_agent_for_op(%s) falhou: %s", op_type, exc)
        return None, None


# ---------------------------------------------------------------------------
# input-builder hook
# ---------------------------------------------------------------------------
def build_input(task: Dict[str, Any], supabase: Any, values: Dict[str, Any]) -> Optional[str]:
    import json
    process_id = _find_process_id(task, supabase)
    if not process_id:
        raise ValueError("workflow-builder exige input_json.source_id (process_id) ou goal_id com SIPOC")
    name, sector, activities = _load_process(supabase, process_id)
    if not activities:
        raise ValueError(f"processo SIPOC {process_id} sem activities — nada a construir")
    payload = {
        "processName": name,
        "sector": sector,
        "activities": activities,
        # Aumento do contrato: o LLM DEVE escolher operationType/specialtySlug por
        # step a partir deste catálogo (ou null se nenhum couber → placeholder).
        "availableOperationTypes": _available_op_types(supabase),
    }
    # guarda o process_id pro effect (sem reabrir a busca)
    task.setdefault("_wb", {})["process_id"] = process_id
    return "## Processo a transformar (escolha operationType/specialtySlug de availableOperationTypes por step)\n" + \
        json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# effect hook
# ---------------------------------------------------------------------------
def _extract_steps(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Tolerante: aceita {_list:[...]}, {steps:[...]}, {workflow_steps:[...]} ou dict-único."""
    for key in ("_list", "steps", "workflow_steps"):
        v = parsed.get(key)
        if isinstance(v, list):
            return v
    # dict com cara de step único
    if parsed.get("nome") or parsed.get("name") or parsed.get("stepCode"):
        return [parsed]
    return []


def _coerce_validation(v: Any) -> str:
    s = str(v or "").lower()
    return s if s in _VALID_VALIDATION else "amarelo"


def write_steps(task: Dict[str, Any], supabase: Any, parsed: Dict[str, Any],
                values: Dict[str, Any]) -> Dict[str, Any]:
    steps = _extract_steps(parsed)
    if not steps:
        raise ValueError("saída do LLM sem steps parseáveis")
    process_id = (task.get("_wb") or {}).get("process_id") or _find_process_id(task, supabase)
    company_id = task.get("company_id")
    if not company_id:
        raise ValueError("task sem company_id — não dá pra criar workflow_definition")

    proc_name, _sector, _acts = _load_process(supabase, process_id) if process_id else ("Workflow", None, [])
    now = _now_iso()
    workflow_id = str(uuid.uuid4())
    wf_slug = _slugify(f"{proc_name}-wb", fallback="workflow-wb")
    supabase.table("workflow_definitions").insert({
        "id": workflow_id, "company_id": company_id,
        "name": (proc_name + " — Workflow Builder")[:200], "slug": wf_slug[:200],
        "description": "Gerado por workflow-builder (specialty) a partir do SIPOC 5W2H.",
        "is_active": True, "version": 1, "trigger_type": "manual",
        "is_scheduled": False, "created_at": now, "updated_at": now,
    }).execute()

    needs_handler = 0
    rows: List[Dict[str, Any]] = []
    for idx, st in enumerate(steps):
        nome = st.get("nome") or st.get("name") or f"Etapa {idx + 1}"
        op_type = st.get("operationType") or st.get("operation_type")
        agent_id, cfg_id = _resolve_agent_for_op(supabase, op_type)
        if not op_type or not agent_id:
            needs_handler += 1
        responsavel = st.get("responsavel") or values.get("responsavel_default") or "agente"
        rows.append({
            "id": str(uuid.uuid4()), "workflow_id": workflow_id, "step_order": idx,
            "name": str(nome)[:200], "slug": _slugify(st.get("stepCode") or nome, f"step-{idx}")[:200],
            "specialty_slug": st.get("specialtySlug") or st.get("specialty_slug"),
            "requires_approval": bool(responsavel == "humano"),
            "on_failure_action": "block", "active": True, "contract_version": "v1",
            "validation_status": _coerce_validation(st.get("validation_status")),
            "validation_errors": [],
            "logic_pattern": st.get("logicPattern") or values.get("default_logic_pattern"),
            "responsavel": responsavel, "setor": st.get("setor"),
            "ferramentas": st.get("ferramentas") or [], "sla_horas": st.get("slaHoras"),
            "alertas": st.get("alertas") or [],
            "suppliers": st.get("suppliers"), "inputs": st.get("inputs"),
            "outputs": st.get("outputs"), "customers": st.get("customers"),
            "decisions": st.get("decisions"), "five_w2h": st.get("fiveW2H") or st.get("five_w2h"),
            "proximo_step_codes": st.get("proximo") or [],
            "default_operation_type": op_type,
            "assigned_to_agent_id": agent_id,
            "agent_specialty_config_id": cfg_id,
            "trigger_type": None, "trigger_config": {},
            "sipoc_meta": {"source": "workflow-builder", "process_id": process_id,
                           "needs_handler": bool(not op_type or not agent_id)},
        })
    if rows:
        supabase.table("workflow_steps").insert(rows).execute()

    # liga o processo ao novo workflow (coerência da árvore)
    if process_id:
        try:
            supabase.table("sipoc_processes").update(
                {"workflow_definition_id": workflow_id, "updated_at": now}).eq("id", process_id).execute()
        except Exception as exc:
            logger.warning("link process→workflow falhou: %s", exc)

    summary = f"{len(rows)} step(s) escritos no workflow {wf_slug}" + \
        (f"; {needs_handler} sem handler (placeholder PR3)" if needs_handler else "")
    return {"summary": summary, "workflow_id": workflow_id, "workflow_slug": wf_slug,
            "steps_created": len(rows), "needs_handler": needs_handler}


# registra os hooks no executor genérico (import-time)
register_input_builder(SLUG, build_input)
register_effect(SLUG, write_steps)
