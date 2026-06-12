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
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.services.agent_llm import generate_for_agent

logger = logging.getLogger("Daedalus")

from src.agent_ids import DAEDALUS_AGENT_ID  # SSOT — ver src/agent_ids.py

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
            .select("id, type, content, order, responsible_position_id, sipoc_positions(metadata)")
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


def _resolve_specialty_configs(supabase: Any, company_id: str) -> Dict[str, str]:
    """Resolve todos os agent_specialty_configs da company.
    
    Retorna mapeamento: agent_id -> agent_specialty_config_id
    Assumimos 1 config primária por agente para o escopo do Daedalus inicial,
    ou escolhe a primeira encontrada.
    """
    try:
        res = (
            supabase.table("agent_specialty_configs")
            .select("id, agent_id")
            .eq("company_id", company_id)
            .execute()
        )
        mapping = {}
        for row in res.data or []:
            config_id = row.get("id")
            agent_id = row.get("agent_id")
            if agent_id and config_id and agent_id not in mapping:
                mapping[agent_id] = config_id
        return mapping
    except Exception as exc:
        logger.warning("Daedalus: falha ao resolver specialty configs company=%s: %s", company_id, exc)
        return {}


def _generate_linear_diagram(
    *,
    activities: List[Dict[str, Any]],
    op_type_map: Dict[str, str],
    layout_step_x: int = 200,
    layout_y: int = 200,
) -> Dict[str, Any]:
    """Gera diagrama linear: start → 1 task por activity → end.

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

    for i, act in enumerate(activities):
        label = _activity_label(act, i)
        node_id = f"task-{i + 1}"
        
        pos = act.get("sipoc_positions") or {}
        pos_meta = pos.get("metadata") or {}
        is_bot = pos_meta.get("is_bot") is True
        agent_id = pos_meta.get("linked_agent_id")
        cfg_id = op_type_map.get(agent_id) if agent_id else None
        
        node_type = "user_task"
        if is_bot and cfg_id:
            node_type = "service_task"

        nodes.append({
            "id": node_id,
            "type": node_type,
            "position": {"x": x_cursor, "y": layout_y},
            "data": {
                "label": label,
                "linked_sipoc_component_id": act.get("id"),
                **({"agent_specialty_config_id": cfg_id} if node_type == "service_task" else {})
            },
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


def _apply_horizontal_layout(diagram_json: Dict[str, Any], step_x: int = 200, layout_y: int = 200) -> Dict[str, Any]:
    """Adiciona positions horizontais em nodes que não têm.

    Layout: start → tasks → gateways → end, da esquerda pra direita.
    Forks deslocam branches pra cima/baixo.
    """
    nodes = list(diagram_json.get("nodes") or [])
    edges = list(diagram_json.get("edges") or [])
    if not nodes:
        return diagram_json

    # Indexa edges por source
    outgoing: Dict[str, List[Dict[str, Any]]] = {}
    for e in edges:
        src = e.get("source")
        if src:
            outgoing.setdefault(src, []).append(e)

    # Ordena topologicamente simples (BFS a partir de start_event)
    node_map: Dict[str, Dict[str, Any]] = {n["id"]: n for n in nodes if n.get("id")}
    start_nodes = [n for n in nodes if n.get("type") == "start_event"]
    start_id = start_nodes[0]["id"] if start_nodes else nodes[0]["id"]

    visited: set = set()
    order: List[str] = []
    queue = [start_id]
    while queue:
        nid = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        order.append(nid)
        for e in outgoing.get(nid, []):
            tgt = e.get("target")
            if tgt and tgt not in visited:
                queue.append(tgt)

    # Adiciona nodes órfãos no final
    for n in nodes:
        if n["id"] not in visited:
            order.append(n["id"])

    # Atribui positions
    rank: Dict[str, int] = {}
    for nid in order:
        preds = [e for e in edges if e.get("target") == nid]
        if preds:
            rank[nid] = max(rank.get(e.get("source", nid), 0) for e in preds) + 1
        else:
            rank[nid] = 0

    max_rank = max(rank.values()) if rank else 0
    branch_offsets: Dict[str, int] = {}

    for nid in order:
        node = node_map[nid]
        if "position" in node:
            continue
        r = rank[nid]
        x = r * step_x
        gtype = node.get("type", "")
        out_edges = outgoing.get(nid, [])

        if gtype.startswith("gateway_") and len(out_edges) >= 2:
            # Fork: gateway central, branches deslocadas
            node["position"] = {"x": x, "y": layout_y}
            for i, e in enumerate(out_edges):
                tgt = e.get("target")
                offset = (i - (len(out_edges) - 1) / 2) * 120
                branch_offsets[tgt] = offset
        else:
            y_off = branch_offsets.get(nid, 0)
            node["position"] = {"x": x, "y": layout_y + y_off}

    return {"nodes": nodes, "edges": edges}


def _enrich_diagram_with_sipoc_data(
    diagram_json: Dict[str, Any],
    activities: List[Dict[str, Any]],
    op_type_map: Dict[str, str],
) -> Dict[str, Any]:
    """Pós-processamento para injetar o auto-cabeamento do SIPOC no diagrama gerado pelo LLM."""
    nodes = diagram_json.get("nodes", [])
    
    for node in nodes:
        node_type = node.get("type")
        if node_type not in ("user_task", "service_task"):
            continue
            
        node_data = node.get("data") or {}
        label = node_data.get("label", "")
        
        best_act = None
        for i, act in enumerate(activities):
            act_label = _activity_label(act, i)
            # Match bidirecional simples ignorando case
            if label and act_label and (act_label.lower() in label.lower() or label.lower() in act_label.lower()):
                best_act = act
                break
                
        if best_act:
            pos = best_act.get("sipoc_positions") or {}
            pos_meta = pos.get("metadata") or {}
            is_bot = pos_meta.get("is_bot") is True
            agent_id = pos_meta.get("linked_agent_id")
            cfg_id = op_type_map.get(agent_id) if agent_id else None
            
            node_data["linked_sipoc_component_id"] = best_act.get("id")
            if is_bot and cfg_id:
                node["type"] = "service_task"
                node_data["agent_specialty_config_id"] = cfg_id
                
            node["data"] = node_data
            
    return diagram_json


_DAEDALUS_SYSTEM_PROMPT = """You are Daedalus, a BPMN diagram generator for the Vectra workflow engine.

Your task: analyze a list of business activities and generate a BPMN diagram JSON that may include real gateways (decision points and parallel splits) when the workflow logic suggests them.

Rules:
1. Use ONLY these node types: start_event, end_event, user_task, service_task, gateway_exclusive, gateway_parallel
2. Every gateway_exclusive MUST have exactly 2 outgoing edges with labels "Sim" and "Não" (or meaningful business labels)
3. Every gateway_parallel MUST have 2+ outgoing edges (no labels needed)
4. All edges must be type: "sequence_flow"
5. Do NOT include positions — they will be auto-generated
6. Node IDs must be unique strings (e.g., "start", "task-1", "gw-1", "end")
7. Data labels must be in Portuguese, concise (max 40 chars)
8. A node that points to a gateway MUST NOT have any other outgoing edges. Exactly ONE sequence_flow should go from the node to the gateway. Do NOT create bypass edges.
9. You MUST include nodes for ALL the provided activities. Do not skip or truncate the process.

Gateway heuristics:
- If an activity involves approval, verification, validation, or a yes/no decision → insert gateway_exclusive AFTER it
- If activities can run independently/simultaneously → use gateway_parallel to fork and gateway_parallel to join
- If the text mentions "se ... então ... senão" or "caso" → gateway_exclusive
- If the text mentions "ao mesmo tempo", "em paralelo", "simultaneamente" → gateway_parallel

Output format (strict JSON, no markdown):
{
  "nodes": [
    {"id": "start", "type": "start_event", "data": {"label": "Início"}},
    {"id": "task-1", "type": "user_task", "data": {"label": "Verificar documento"}},
    {"id": "gw-1", "type": "gateway_exclusive", "data": {"label": "Aprovado?"}},
    {"id": "task-2", "type": "user_task", "data": {"label": "Processar pagamento"}},
    {"id": "task-3", "type": "user_task", "data": {"label": "Notificar rejeição"}},
    {"id": "end", "type": "end_event", "data": {"label": "Fim"}}
  ],
  "edges": [
    {"id": "e1", "source": "start", "target": "task-1", "type": "sequence_flow"},
    {"id": "e2", "source": "task-1", "target": "gw-1", "type": "sequence_flow"},
    {"id": "e3", "source": "gw-1", "target": "task-2", "type": "sequence_flow", "label": "Sim"},
    {"id": "e4", "source": "gw-1", "target": "task-3", "type": "sequence_flow", "label": "Não"},
    {"id": "e5", "source": "task-2", "target": "end", "type": "sequence_flow"},
    {"id": "e6", "source": "task-3", "target": "end", "type": "sequence_flow"}
  ]
}"""


def _build_bpmn_prompt(activity_labels: List[str], source_type: str, context: str = "") -> str:
    activities_block = "\n".join(f"{i + 1}. {label}" for i, label in enumerate(activity_labels))
    ctx_block = f"\nContexto adicional:\n{context}" if context else ""
    return (
        f"Atividades do processo ({source_type}):\n{activities_block}{ctx_block}\n\n"
        "Gere o diagrama BPMN JSON conforme as regras. "
        "Insira gateways reais (exclusive/parallel) sempre que o fluxo de negócio indicar decisão ou paralelismo. "
        "Responda APENAS com JSON válido, sem markdown."
    )


async def _generate_llm_diagram(
    activity_labels: List[str],
    source_type: str,
    context: str = "",
) -> Optional[Dict[str, Any]]:
    """Tenta gerar diagrama via LLM. Retorna dict {nodes, edges} ou None se falhar."""
    prompt = _build_bpmn_prompt(activity_labels, source_type, context)
    try:
        text, meta = await generate_for_agent(
            DAEDALUS_AGENT_ID,
            prompt,
            system_instruction=_DAEDALUS_SYSTEM_PROMPT,
            response_mime_type="application/json",
            fallback_model="gemini-3-flash-preview",
        )
        logger.info("Daedalus LLM: model=%s tokens=%s", meta.get("model_used"), meta.get("tokens"))
        raw = json.loads(text.strip())
        nodes = raw.get("nodes")
        edges = raw.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            logger.warning("Daedalus LLM: resposta sem nodes/edges válidos")
            return None
        # Sanity check: IDs únicos
        ids = [n.get("id") for n in nodes if n.get("id")]
        if len(ids) != len(set(ids)):
            logger.warning("Daedalus LLM: IDs duplicados nos nodes")
            return None
        # Sanity check: edges referenciam nodes existentes
        node_ids = set(ids)
        for e in edges:
            if e.get("source") not in node_ids or e.get("target") not in node_ids:
                logger.warning("Daedalus LLM: edge referencia node inexistente")
                return None
        return {"nodes": nodes, "edges": edges}
    except Exception as exc:
        logger.warning("Daedalus LLM generation failed: %s", exc)
        return None


def _handle_bpmn_generate(task: dict, supabase: Any) -> Dict[str, Any]:
    """Handler op_type='bpmn-generate' (mantido sem mudança desde PR G+H).

    Movido pra função própria em M4 (2026-05-19) pra alinhar com pattern
    _SPECIALTY_DISPATCH (vide src/agents/athena.py:3846).
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
        "Daedalus bpmn-generate start task=%s company=%s source_type=%s",
        task_id, company_id, source_type,
    )

    diagram_name: str = (input_data.get("name") or "").strip()
    linked_sipoc_process_id: Optional[str] = None
    activity_labels: List[str] = []
    activities: List[Dict[str, Any]] = []

    op_type_map = _resolve_specialty_configs(supabase, str(company_id))

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
        activities = [{"content": {"name": text[:80]}}]
        if not diagram_name:
            diagram_name = f"BPMN freeform: {text[:60]}"

    # P3-BE-8 — tenta LLM real com gateways; fallback estatístico permanente
    context = ""
    if source_type == "sipoc_process" and linked_sipoc_process_id:
        context = f"Processo SIPOC ID: {linked_sipoc_process_id}"

    llm_diagram = asyncio.run(_generate_llm_diagram(activity_labels, source_type, context))
    if llm_diagram:
        diagram_json = _apply_horizontal_layout(llm_diagram)
        diagram_json = _enrich_diagram_with_sipoc_data(diagram_json, activities, op_type_map)
        engine_mode = "llm"
        confidence = 0.85
        tools = ["expert_judgment", "llm_gemini", "gateway_inference", "sipoc_auto_cabling"]
        description = f"Gerado pelo Daedalus (LLM com gateways e auto-cabeamento). source_type={source_type}"
        warnings: List[str] = []
    else:
        diagram_json = _generate_linear_diagram(activities=activities, op_type_map=op_type_map)
        engine_mode = "statistical_fallback"
        confidence = 0.5
        tools = ["expert_judgment", "statistical_fallback", "linear_layout", "sipoc_auto_cabling"]
        description = f"Gerado pelo Daedalus (fallback estatístico, sem LLM, com auto-cabeamento). source_type={source_type}"
        warnings = ["llm_generation_failed_fallback_linear"]

    diagram_id = _persist_bpmn_diagram(
        supabase,
        company_id=str(company_id),
        name=diagram_name,
        diagram_json=diagram_json,
        generated_by_task_id=task_id or None,
        linked_sipoc_process_id=linked_sipoc_process_id,
        description=description,
    )

    completed_at = _now_iso()
    nodes_count = len(diagram_json.get("nodes", []))
    edges_count = len(diagram_json.get("edges", []))

    logger.info(
        "Daedalus done task=%s diagram_id=%s nodes=%d edges=%d engine_mode=%s",
        task_id, diagram_id, nodes_count, edges_count, engine_mode,
    )

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
            "tools_techniques_applied": tools,
            "outputs": {
                "status": "done",
                "diagram_id": diagram_id,
                "diagram_json": diagram_json,
                "nodes_count": nodes_count,
                "edges_count": edges_count,
                "engine_mode": engine_mode,
            },
            "validation": {
                "all_required_inputs_present": True,
                "confidence": confidence,
                "warnings": warnings,
                "needs_human_review": engine_mode != "llm",
            },
            "citations": [],
            "metadata": {"persisted_diagram_id": diagram_id},
        },
        "cost_usd": 0.0,  # LLM cost é trackeado em agent_llm / gemini_client
        "status_override": "done" if diagram_id else "review",
    }


# ──────────────────────────────────────────────────────────────────────────────
# M4 (2026-05-19) — Orchestration handlers
#
# Substituem `src/services/brain/system_prompt.py` (estático) + ativam loop
# de execução de workflow_definitions criadas via bpmn-materialize (PR #236)
# ou workflow_aduaneiro seed (PR #241).
#
# Op_types (catalog vectraclip.operation_types_catalog):
#   - daedalus-orchestrate-step
#   - daedalus-route-task
#   - daedalus-replan
#   - daedalus-compile-prompt
#
# input_json contracts:
#   orchestrate-step: {workflow_id, current_step_slug?} → cria task filha próxima
#   route-task: {task_id} → UPDATE assigned_to_agent_id via specialty_config
#   replan: {failed_task_id, failure_reason} → retry/abort baseado em count
#   compile-prompt: {workflow_step_id} → retorna string prompt compilado
# ──────────────────────────────────────────────────────────────────────────────


def _ok_envelope(handler: str, task_id: str, started_at: str, outputs: Dict[str, Any], warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    """Envelope I/T/O padrão de sucesso."""
    return {
        "output_json": {
            "handler_name": handler,
            "execution_id": task_id,
            "execution_started_at": started_at,
            "execution_completed_at": _now_iso(),
            "inputs_used": {},
            "tools_techniques_applied": ["expert_judgment", "catalog_lookup"],
            "outputs": outputs,
            "validation": {
                "all_required_inputs_present": True,
                "confidence": 0.8,
                "warnings": warnings or [],
                "needs_human_review": bool(warnings),
            },
            "citations": [],
            "metadata": {},
        },
        "cost_usd": 0.0,
        "status_override": "done",
    }


def _handle_orchestrate_step(task: dict, supabase: Any) -> Dict[str, Any]:
    """Avança workflow_definitions criando task filha pro próximo step.

    Lê workflow_steps WHERE workflow_id ordenado por step_order, decide
    próximo step baseado em current_step_slug, cria task filha com
    operation_type=step.default_operation_type + assigned_to_agent_id
    via step.agent_specialty_config_id lookup.
    """
    started_at = _now_iso()
    task_id = task.get("id", "")
    company_id = task.get("company_id")
    input_data: Dict[str, Any] = task.get("input_json") or {}

    workflow_id = input_data.get("workflow_id")
    if not workflow_id:
        return _error_envelope(task_id, started_at, "missing_workflow_id", "input_json.workflow_id obrigatório")
    if not company_id:
        return _error_envelope(task_id, started_at, "missing_company_id", "task.company_id ausente")

    current_slug = input_data.get("current_step_slug")

    try:
        steps_res = (
            supabase.table("workflow_steps")
            .select("id, step_order, slug, default_operation_type, agent_specialty_config_id, proximo_step_codes")
            .eq("workflow_id", workflow_id)
            .order("step_order")
            .execute()
        )
        steps = steps_res.data or []
    except Exception as exc:
        return _error_envelope(task_id, started_at, "steps_query_failed", str(exc))

    if not steps:
        return _error_envelope(task_id, started_at, "no_steps", f"workflow {workflow_id} sem steps")

    # Decide próximo step
    if not current_slug:
        next_step = steps[0]
    else:
        cur_idx = next((i for i, s in enumerate(steps) if s.get("slug") == current_slug), None)
        if cur_idx is None:
            return _error_envelope(task_id, started_at, "current_step_not_found", f"slug {current_slug} não existe")
        # Tenta proximo_step_codes primeiro
        proximo = steps[cur_idx].get("proximo_step_codes") or []
        next_step = None
        if proximo:
            next_slug = proximo[0]
            next_step = next((s for s in steps if s.get("slug") == next_slug), None)
        if not next_step:
            # Fallback ordinal
            if cur_idx + 1 < len(steps):
                next_step = steps[cur_idx + 1]
        if not next_step:
            return _ok_envelope("daedalus-orchestrate-step", task_id, started_at, {
                "status": "workflow_completed",
                "last_step_slug": current_slug,
            })

    # Lookup agent via agent_specialty_config
    target_agent_id: Optional[str] = None
    spec_cfg_id = next_step.get("agent_specialty_config_id")
    if spec_cfg_id:
        try:
            cfg_res = (
                supabase.table("agent_specialty_configs")
                .select("agent_id")
                .eq("id", spec_cfg_id)
                .limit(1)
                .execute()
            )
            if cfg_res.data:
                target_agent_id = cfg_res.data[0].get("agent_id")
        except Exception as exc:
            logger.warning("orchestrate-step: specialty_config lookup falhou cfg=%s: %s", spec_cfg_id, exc)

    # Cria task filha
    now_iso = _now_iso()
    child = {
        "id": str(uuid4()),
        "company_id": company_id,
        "parent_task_id": task_id,
        "title": f"[Workflow {workflow_id[:8]}] {next_step.get('slug')}",
        "description": f"Step orquestrado por Daedalus. workflow_id={workflow_id} step_slug={next_step.get('slug')}",
        "operation_type": next_step.get("default_operation_type"),
        "status": "queued",
        "executor_type": "auto",
        "assigned_to_agent_id": target_agent_id,
        "input_json": {
            "_workflow_run": {
                "workflow_id": workflow_id,
                "step_id": next_step.get("id"),
                "step_slug": next_step.get("slug"),
                "step_order": next_step.get("step_order"),
                "parent_orchestrate_task_id": task_id,
            },
        },
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    try:
        ins = supabase.table("tasks").insert(child).execute()
        child_id = ins.data[0].get("id") if ins.data else None
    except Exception as exc:
        return _error_envelope(task_id, started_at, "child_insert_failed", str(exc))

    return _ok_envelope("daedalus-orchestrate-step", task_id, started_at, {
        "status": "next_step_dispatched",
        "child_task_id": child_id,
        "next_step_slug": next_step.get("slug"),
        "next_step_order": next_step.get("step_order"),
        "target_agent_id": target_agent_id,
        "default_operation_type": next_step.get("default_operation_type"),
    })


def _handle_route_task(task: dict, supabase: Any) -> Dict[str, Any]:
    """Decide qual agente recebe a task baseado em step.agent_specialty_config_id.

    Lê task_id do input_json, resolve step → specialty_config → agent_id,
    UPDATE tasks.assigned_to_agent_id.
    """
    started_at = _now_iso()
    task_id = task.get("id", "")
    target_task_id = (task.get("input_json") or {}).get("task_id")
    if not target_task_id:
        return _error_envelope(task_id, started_at, "missing_task_id", "input_json.task_id obrigatório")

    try:
        tgt_res = (
            supabase.table("tasks")
            .select("id, input_json, operation_type, assigned_to_agent_id")
            .eq("id", target_task_id)
            .limit(1)
            .execute()
        )
        if not tgt_res.data:
            return _error_envelope(task_id, started_at, "target_task_not_found", target_task_id)
        target = tgt_res.data[0]
    except Exception as exc:
        return _error_envelope(task_id, started_at, "target_task_query_failed", str(exc))

    wf_run = (target.get("input_json") or {}).get("_workflow_run") or {}
    step_id = wf_run.get("step_id")
    if not step_id:
        return _error_envelope(task_id, started_at, "no_workflow_step_link", "target task sem _workflow_run.step_id")

    try:
        step_res = (
            supabase.table("workflow_steps")
            .select("id, agent_specialty_config_id, slug")
            .eq("id", step_id)
            .limit(1)
            .execute()
        )
        if not step_res.data:
            return _error_envelope(task_id, started_at, "step_not_found", step_id)
        spec_cfg_id = step_res.data[0].get("agent_specialty_config_id")
    except Exception as exc:
        return _error_envelope(task_id, started_at, "step_query_failed", str(exc))

    if not spec_cfg_id:
        return _ok_envelope("daedalus-route-task", task_id, started_at, {
            "status": "no_specialty_config",
            "target_task_id": target_task_id,
        }, warnings=["step sem agent_specialty_config_id — task fica unrouted"])

    try:
        cfg_res = (
            supabase.table("agent_specialty_configs")
            .select("agent_id, specialty_id")
            .eq("id", spec_cfg_id)
            .limit(1)
            .execute()
        )
        if not cfg_res.data:
            return _error_envelope(task_id, started_at, "specialty_config_not_found", spec_cfg_id)
        target_agent_id = cfg_res.data[0].get("agent_id")
    except Exception as exc:
        return _error_envelope(task_id, started_at, "config_query_failed", str(exc))

    try:
        supabase.table("tasks").update({
            "assigned_to_agent_id": target_agent_id,
            "updated_at": _now_iso(),
        }).eq("id", target_task_id).execute()
    except Exception as exc:
        return _error_envelope(task_id, started_at, "task_update_failed", str(exc))

    return _ok_envelope("daedalus-route-task", task_id, started_at, {
        "status": "routed",
        "target_task_id": target_task_id,
        "target_agent_id": target_agent_id,
        "specialty_config_id": spec_cfg_id,
    })


def _handle_replan(task: dict, supabase: Any) -> Dict[str, Any]:
    """Decide retry/skip/abort após failure de step.

    M4 phase initial: retry simples até 3x (contador em task.input_json._replan_count),
    depois abort. Refinamento (LLM-driven decision) entra quando R1 Gemini desbloquear.
    """
    started_at = _now_iso()
    task_id = task.get("id", "")
    failed_task_id = (task.get("input_json") or {}).get("failed_task_id")
    if not failed_task_id:
        return _error_envelope(task_id, started_at, "missing_failed_task_id", "input_json.failed_task_id obrigatório")

    try:
        f_res = (
            supabase.table("tasks")
            .select("id, company_id, parent_task_id, operation_type, input_json, assigned_to_agent_id, output_json")
            .eq("id", failed_task_id)
            .limit(1)
            .execute()
        )
        if not f_res.data:
            return _error_envelope(task_id, started_at, "failed_task_not_found", failed_task_id)
        failed = f_res.data[0]
    except Exception as exc:
        return _error_envelope(task_id, started_at, "failed_task_query_failed", str(exc))

    inp = failed.get("input_json") or {}
    replan_count = int((inp.get("_replan_count") or 0))
    MAX_RETRIES = 3

    if replan_count >= MAX_RETRIES:
        # Abort — não retry. Marca parent workflow_run como blocked.
        return _ok_envelope("daedalus-replan", task_id, started_at, {
            "status": "aborted",
            "failed_task_id": failed_task_id,
            "replan_count": replan_count,
            "reason": f"retry limit {MAX_RETRIES} exceeded",
        }, warnings=[f"workflow blocked após {replan_count} retries de task {failed_task_id}"])

    # Retry — cria nova task com mesmo operation_type + assigned_to + _replan_count+1
    now_iso = _now_iso()
    retry_input = dict(inp)
    retry_input["_replan_count"] = replan_count + 1
    retry_input["_replan_of"] = failed_task_id
    retry = {
        "id": str(uuid4()),
        "company_id": failed.get("company_id"),
        "parent_task_id": failed.get("parent_task_id"),
        "title": f"[Retry {replan_count + 1}/{MAX_RETRIES}] task {failed_task_id[:8]}",
        "description": f"Retry orquestrado por Daedalus replan. Tentativa {replan_count + 1} de {MAX_RETRIES}.",
        "operation_type": failed.get("operation_type"),
        "status": "queued",
        "executor_type": "auto",
        "assigned_to_agent_id": failed.get("assigned_to_agent_id"),
        "input_json": retry_input,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    try:
        ins = supabase.table("tasks").insert(retry).execute()
        retry_id = ins.data[0].get("id") if ins.data else None
    except Exception as exc:
        return _error_envelope(task_id, started_at, "retry_insert_failed", str(exc))

    return _ok_envelope("daedalus-replan", task_id, started_at, {
        "status": "retry_dispatched",
        "retry_task_id": retry_id,
        "replan_count": replan_count + 1,
        "max_retries": MAX_RETRIES,
        "original_failed_task_id": failed_task_id,
    })


def _handle_compile_prompt(task: dict, supabase: Any) -> Dict[str, Any]:
    """Compila system_prompt dinâmico do orchestrator pra um workflow_step.

    Substitui src/services/brain/system_prompt.py (estático single-tenant).
    Lê: workflow_step + workflow_definition + tools_catalog (via step.ferramentas) +
    agent persona (agents.system_prompt do executor).
    """
    started_at = _now_iso()
    task_id = task.get("id", "")
    input_data: Dict[str, Any] = task.get("input_json") or {}
    step_id = input_data.get("workflow_step_id")
    if not step_id:
        return _error_envelope(task_id, started_at, "missing_workflow_step_id", "input_json.workflow_step_id obrigatório")

    try:
        step_res = (
            supabase.table("workflow_steps")
            .select("*, workflow_definitions(name,slug,description)")
            .eq("id", step_id)
            .limit(1)
            .execute()
        )
        if not step_res.data:
            return _error_envelope(task_id, started_at, "step_not_found", step_id)
        step = step_res.data[0]
    except Exception as exc:
        return _error_envelope(task_id, started_at, "step_query_failed", str(exc))

    # Lookup agent + tools
    agent_prompt = ""
    delegated_agent_id = None
    spec_cfg_id = step.get("agent_specialty_config_id")
    if spec_cfg_id:
        try:
            cfg = supabase.table("agent_specialty_configs").select("agent_id").eq("id", spec_cfg_id).limit(1).execute()
            delegated_agent_id = cfg.data[0].get("agent_id") if cfg.data else None
            if delegated_agent_id:
                ag = supabase.table("agents").select("name, role, system_prompt").eq("id", delegated_agent_id).limit(1).execute()
                if ag.data:
                    a = ag.data[0]
                    agent_prompt = f"# Agente delegado\nNome: {a.get('name')}\nRole: {a.get('role')}\n\n{a.get('system_prompt') or '(sem system_prompt definido)'}\n"
        except Exception as exc:
            logger.warning("compile-prompt agent lookup falhou: %s", exc)

    # N7.5 — MCP tools do agente delegado (agent_mcp_bindings ativos).
    # Injeta tools no formato prefixed mcp__<server>__<tool> (convenção Claude CLI;
    # hífens do server_id viram underscore). Whitelist allowed_tools respeitada.
    mcp_section = ""
    mcp_tools_count = 0
    if delegated_agent_id:
        try:
            binds = (
                supabase.table("agent_mcp_bindings")
                .select("mcp_server_id, allowed_tools, tools_cache")
                .eq("agent_id", delegated_agent_id)
                .eq("is_active", True)
                .execute()
            )
            lines = ["# MCP servers conectados (tools externas)"]
            for b in (binds.data or []):
                server_id = b.get("mcp_server_id") or ""
                prefix = "mcp__" + server_id.replace("-", "_") + "__"
                allowed = b.get("allowed_tools")  # None = todos
                cache = b.get("tools_cache") or []
                lines.append(f"\n## {server_id}")
                if not cache:
                    lines.append("- (sem tools em cache — rodar handshake)")
                for t in cache:
                    tname = t.get("name") if isinstance(t, dict) else None
                    if not tname:
                        continue
                    if allowed is not None and tname not in allowed:
                        continue
                    desc = t.get("description") if isinstance(t, dict) else ""
                    lines.append(f"- **`{prefix}{tname}`**: {desc or ''}")
                    mcp_tools_count += 1
            if mcp_tools_count > 0 or len(binds.data or []) > 0:
                mcp_section = "\n".join(lines) + "\n"
        except Exception as exc:
            logger.warning("compile-prompt mcp bindings lookup falhou: %s", exc)

    tools_section = ""
    fer = step.get("ferramentas") or []
    if isinstance(fer, list) and fer:
        try:
            t_res = supabase.table("tools_catalog").select("id, name, description, category, runtime_module").in_("id", fer).execute()
            tools = t_res.data or []
            lines = ["# Ferramentas autorizadas neste step"]
            for t in tools:
                lines.append(f"- **`{t['id']}`** ({t.get('category')}): {t.get('description', '')}")
            tools_section = "\n".join(lines) + "\n"
        except Exception as exc:
            logger.warning("compile-prompt tools lookup falhou: %s", exc)

    wf_def = step.get("workflow_definitions") or {}
    workflow_section = (
        f"# Workflow\n"
        f"Nome: {wf_def.get('name', '?')}\n"
        f"Slug: {wf_def.get('slug', '?')}\n"
        f"Descrição: {wf_def.get('description', '?')}\n"
    )
    step_section = (
        f"# Step atual\n"
        f"Ordem: {step.get('step_order')}\n"
        f"Slug: {step.get('slug')}\n"
        f"Nome: {step.get('name')}\n"
        f"Operation type esperado: {step.get('default_operation_type')}\n"
        f"Responsável: {step.get('responsavel') or 'agente'}\n"
        f"Setor: {step.get('setor') or '-'}\n"
        f"Próximos steps: {step.get('proximo_step_codes') or []}\n"
    )

    compiled = "\n---\n".join([
        agent_prompt or "# (Agente sem prompt definido)",
        workflow_section,
        step_section,
        tools_section or "# (Nenhuma ferramenta vinculada ao step)",
        mcp_section or "# (Nenhum MCP server conectado ao agente)",
    ])

    return _ok_envelope("daedalus-compile-prompt", task_id, started_at, {
        "status": "compiled",
        "workflow_step_id": step_id,
        "compiled_prompt": compiled,
        "char_count": len(compiled),
        "tools_bound_count": len(fer) if isinstance(fer, list) else 0,
        "mcp_tools_count": mcp_tools_count,
    })


# ──────────────────────────────────────────────────────────────────────────────
# Dispatch
# ──────────────────────────────────────────────────────────────────────────────

_SPECIALTY_DISPATCH = {
    "bpmn-generate":            _handle_bpmn_generate,
    "daedalus-orchestrate-step": _handle_orchestrate_step,
    "daedalus-route-task":      _handle_route_task,
    "daedalus-replan":          _handle_replan,
    "daedalus-compile-prompt":  _handle_compile_prompt,
}


def entrypoint(task: dict, supabase: Any) -> Dict[str, Any]:
    """Dispatcher Daedalus por operation_type.

    Mantém backward compat: tasks com op_type='bpmn-generate' continuam
    funcionando exatamente como antes (handler movido pra
    `_handle_bpmn_generate` em M4 2026-05-19, comportamento idêntico).
    """
    op_type = (task.get("operation_type") or "").strip()
    handler = _SPECIALTY_DISPATCH.get(op_type)
    if not handler:
        started_at = _now_iso()
        return _error_envelope(
            task.get("id", ""),
            started_at,
            "unknown_operation_type",
            f"Daedalus não tem handler pra '{op_type}'. Conhecidos: {list(_SPECIALTY_DISPATCH.keys())}",
        )
    return handler(task, supabase)


async def execute_specialty(task: Dict[str, Any], supabase: Any) -> Dict[str, Any]:
    """Async wrapper para alinhar com contrato Oracle/Athena (já que dispatch
    do daemon usa asyncio.run em handlers async)."""
    return await asyncio.to_thread(entrypoint, task, supabase)
