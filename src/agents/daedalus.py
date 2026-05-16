"""
Daedalus — modelador BPMN visual (engine própria, sem Camunda).

operation_type='bpmn-generate' (despachado por agent_daemon).
AGENT_ID: d4ed4145-0000-4000-8000-000000000005 (registrado em PR F #158).
adapter_type='gemini' (config schema oferece também Claude e Ollama).

Pipeline atual (PR G+H — fallback estatístico, sem LLM):
  1. Lê input_json: {source_type, source_id?, freeform_text?, name?, ...}
  2. Para source_type='sipoc_process': lê sipoc_components do processo,
     gera diagrama LINEAR (start → user_task por activity → end)
  3. Para source_type='freeform': gera diagrama mínimo (start → 1 task com
     o título → end) — placeholder enquanto Gemini está bloqueado (R1)
  4. Persiste em vectraclip.bpmn_diagrams (generated_by='daedalus',
     linked_sipoc_process_id setado se aplicável)
  5. Retorna envelope I/T/O com diagram_id e diagram_json

Doc de planejamento: docs/EXECUCAO-G1-RISK-REGISTER-E-DAEDALUS.md §2.3
Quando R1 (Gemini 403) for resolvido, o handler ganha branch LLM antes
do fallback estatístico — fallback fica como rede de segurança permanente.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger("Daedalus")

DAEDALUS_AGENT_ID = "d4ed4145-0000-4000-8000-000000000005"
DAEDALUS_SPECIALTY = "bpmn-modeling"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error_envelope(task_id: str, started_at: str, code: str, message: str) -> Dict[str, Any]:
    """Envelope I/T/O para erros. status=blocked."""
    return {
        "output_json": {
            "handler_name": "bpmn-generate",
            "execution_id": task_id,
            "execution_started_at": started_at,
            "execution_completed_at": _now_iso(),
            "inputs_used": {},
            "tools_techniques_applied": ["expert_judgment"],
            "outputs": {"status": "error", "code": code, "message": message},
            "validation": {
                "all_required_inputs_present": False,
                "confidence": 0.0,
                "warnings": [code],
                "needs_human_review": True,
            },
            "citations": [],
            "metadata": {"persisted_diagram_id": None},
        },
        "cost_usd": 0.0,
        "status_override": "blocked",
    }


def _load_sipoc_process_components(supabase: Any, process_id: str) -> List[Dict[str, Any]]:
    """Lê components do processo SIPOC, ordenados por display_order/created_at."""
    try:
        res = (
            supabase.table("sipoc_components")
            .select("id, type, content, order, automation_status, responsible_position_id")
            .eq("process_id", process_id)
            .order("order")
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.warning("Daedalus: falha ao ler sipoc_components process=%s: %s", process_id, exc)
        return []


def _activity_label(component: Dict[str, Any], idx: int) -> str:
    """Extrai nome legível do component (content.name ou fallback)."""
    content = component.get("content") or {}
    if isinstance(content, dict):
        name = content.get("name") or content.get("title")
        if name:
            return str(name)[:80]
    return f"Atividade {idx + 1}"


def _generate_linear_diagram(
    *,
    activity_labels: List[str],
    layout_step_x: int = 200,
    layout_y: int = 200,
) -> Dict[str, Any]:
    """Gera diagrama linear: start → 1 user_task por activity → end.

    Layout simples horizontal: start em x=0, tasks em x=200,400,..., end por último.
    Frontend pode reposicionar (auto_layout=true ativa dagre na UI).
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    # Start
    start_id = "start"
    nodes.append({
        "id": start_id,
        "type": "start_event",
        "position": {"x": 0, "y": layout_y},
        "data": {"label": "Início"},
    })

    prev_id = start_id
    x_cursor = layout_step_x

    # 1 user_task por activity
    for i, label in enumerate(activity_labels):
        node_id = f"task-{i + 1}"
        nodes.append({
            "id": node_id,
            "type": "user_task",
            "position": {"x": x_cursor, "y": layout_y},
            "data": {"label": label},
        })
        edges.append({
            "id": f"edge-{prev_id}-{node_id}",
            "source": prev_id,
            "target": node_id,
            "type": "sequence_flow",
        })
        prev_id = node_id
        x_cursor += layout_step_x

    # End
    end_id = "end"
    nodes.append({
        "id": end_id,
        "type": "end_event",
        "position": {"x": x_cursor, "y": layout_y},
        "data": {"label": "Fim"},
    })
    edges.append({
        "id": f"edge-{prev_id}-{end_id}",
        "source": prev_id,
        "target": end_id,
        "type": "sequence_flow",
    })

    return {"nodes": nodes, "edges": edges}


def _persist_bpmn_diagram(
    supabase: Any,
    *,
    company_id: str,
    name: str,
    diagram_json: Dict[str, Any],
    generated_by_task_id: Optional[str],
    linked_sipoc_process_id: Optional[str],
    description: Optional[str] = None,
) -> Optional[str]:
    """Insere row em bpmn_diagrams. Retorna id ou None se falhar."""
    row: Dict[str, Any] = {
        "company_id": company_id,
        "name": name[:200],
        "diagram_json": diagram_json,
        "generated_by": "daedalus",
    }
    if description:
        row["description"] = description
    if generated_by_task_id:
        row["generated_by_task_id"] = generated_by_task_id
    if linked_sipoc_process_id:
        row["linked_sipoc_process_id"] = linked_sipoc_process_id

    try:
        res = supabase.table("bpmn_diagrams").insert(row).execute()
        if res.data:
            return res.data[0].get("id")
    except Exception as exc:
        logger.error(
            "Daedalus: falha ao persistir bpmn_diagram name=%r company=%s: %s",
            name, company_id, exc,
        )
    return None


def entrypoint(task: dict, supabase: Any) -> Dict[str, Any]:
    """Handler do daemon para operation_type='bpmn-generate'.

    Args:
        task: row vectraclip.tasks (id, company_id, input_json, ...).
        supabase: client service_role (do daemon).

    Returns:
        {output_json, cost_usd, status_override}
    """
    started_at = _now_iso()
    task_id = task.get("id", "")
    company_id = task.get("company_id")
    input_data: Dict[str, Any] = task.get("input_json") or {}

    if not company_id:
        return _error_envelope(task_id, started_at, "missing_company_id", "task.company_id ausente")

    source_type = (input_data.get("source_type") or "").strip().lower()
    if source_type not in {"sipoc_process", "freeform"}:
        return _error_envelope(
            task_id, started_at, "invalid_source_type",
            f"source_type inválido: {source_type!r}. Esperado 'sipoc_process' ou 'freeform'. "
            "('charter' será implementado quando R1 Gemini desbloquear LLM real.)",
        )

    logger.info(
        "Daedalus start task=%s company=%s source_type=%s",
        task_id, company_id, source_type,
    )

    diagram_name: str = (input_data.get("name") or "").strip()
    linked_sipoc_process_id: Optional[str] = None
    activity_labels: List[str] = []

    if source_type == "sipoc_process":
        process_id = input_data.get("source_id")
        if not process_id:
            return _error_envelope(
                task_id, started_at, "missing_source_id",
                "source_type='sipoc_process' exige input_json.source_id (UUID do processo)",
            )
        linked_sipoc_process_id = str(process_id)
        components = _load_sipoc_process_components(supabase, str(process_id))
        activities = [c for c in components if (c.get("type") or "").lower() == "activity"]

        if not activities:
            return _error_envelope(
                task_id, started_at, "no_activities_in_process",
                f"Processo SIPOC {process_id} não tem components do tipo 'activity'. "
                "Adicione atividades antes de gerar diagrama.",
            )

        activity_labels = [_activity_label(c, i) for i, c in enumerate(activities)]
        if not diagram_name:
            diagram_name = f"BPMN linear gerado por Daedalus ({len(activities)} atividades)"

    else:  # freeform
        text = (input_data.get("freeform_text") or "").strip()
        if not text:
            return _error_envelope(
                task_id, started_at, "missing_freeform_text",
                "source_type='freeform' exige input_json.freeform_text",
            )
        activity_labels = [text[:80]]
        if not diagram_name:
            diagram_name = f"BPMN freeform: {text[:60]}"

    diagram_json = _generate_linear_diagram(activity_labels=activity_labels)

    diagram_id = _persist_bpmn_diagram(
        supabase,
        company_id=str(company_id),
        name=diagram_name,
        diagram_json=diagram_json,
        generated_by_task_id=task_id or None,
        linked_sipoc_process_id=linked_sipoc_process_id,
        description=f"Gerado pelo Daedalus (fallback estatístico, sem LLM). source_type={source_type}",
    )

    completed_at = _now_iso()
    nodes_count = len(diagram_json.get("nodes", []))
    edges_count = len(diagram_json.get("edges", []))

    logger.info(
        "Daedalus done task=%s diagram_id=%s nodes=%d edges=%d source_type=%s",
        task_id, diagram_id, nodes_count, edges_count, source_type,
    )

    warnings: List[str] = []
    if not diagram_id:
        warnings.append("persist_failed_diagram_not_saved")

    return {
        "output_json": {
            "handler_name": "bpmn-generate",
            "execution_id": task_id,
            "execution_started_at": started_at,
            "execution_completed_at": completed_at,
            "inputs_used": {
                "source_type": source_type,
                "source_id": str(input_data.get("source_id")) if input_data.get("source_id") else None,
                "diagram_name": diagram_name,
            },
            "tools_techniques_applied": ["expert_judgment", "statistical_fallback", "linear_layout"],
            "outputs": {
                "status": "done",
                "diagram_id": diagram_id,
                "diagram_json": diagram_json,
                "nodes_count": nodes_count,
                "edges_count": edges_count,
                "engine_mode": "statistical_fallback",  # vira "llm" quando R1 Gemini for resolvido
            },
            "validation": {
                "all_required_inputs_present": True,
                "confidence": 0.5,  # fallback estatístico = baixa confiança vs LLM real
                "warnings": warnings,
                "needs_human_review": True,  # diagrama linear é só ponto de partida pra edição manual
            },
            "citations": [],
            "metadata": {"persisted_diagram_id": diagram_id},
        },
        "cost_usd": 0.0,  # zero LLM call neste handler
        "status_override": "done" if diagram_id else "review",
    }


async def execute_specialty(task: Dict[str, Any], supabase: Any) -> Dict[str, Any]:
    """Async wrapper para alinhar com contrato Oracle/Athena (já que dispatch
    do daemon usa asyncio.run em handlers async)."""
    return await asyncio.to_thread(entrypoint, task, supabase)
