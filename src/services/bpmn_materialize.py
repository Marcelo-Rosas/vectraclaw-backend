"""Service que materializa BPMN diagram em workflow executável.

Phase 3 do `docs/HANDOFF-BPMN-WORKFLOW-BRIDGE.md` (autopilot 2026-05-19).

Pipeline:
  1. SELECT bpmn_diagrams.diagram_json (jsonb {nodes, edges})
  2. Tenant defense: bpmn_diagrams.company_id == request.state.company_id
  3. Topological sort dos sequence_flow (Kahn algorithm)
  4. Filter executable nodes (service_task | task com agent_specialty_config_id;
     user_task | manual_task viram steps com responsavel=humano)
  5. INSERT workflow_definitions (1 row, com slug derivado do diagrama)
  6. INSERT workflow_steps em ordem topológica, copiando node.data:
       - agent_specialty_config_id, default_operation_type, responsavel
       - proximo_step_codes (lista de slugs dos targets do sequence_flow)
       - logic_pattern via gateway adjacente (best-effort, default 'simple')
  7. 2ª pass: resolve on_success_step_id FK depois de todos rows criados
  8. UPDATE bpmn_diagrams.linked_workflow_id
  9. Retorna {workflow_id, steps_created, warnings}

Convenções:
- Service usa service_role supabase (cross-table reads/writes + RLS bypass).
  Defense-in-depth: validate company_id explicitly antes de qualquer write.
- Idempotency: se diagram.linked_workflow_id existir e replace=False → 409.
  Com replace=True: deleta workflow + steps antigos antes de recriar.
- Best-effort em mapping gateways: MVP só mapeia 'simple'. Gateways exclusive/
  parallel viram warning na response (refator futuro PR Phase 3b).

Referências:
- HANDOFF-BPMN-WORKFLOW-BRIDGE.md §2.1/§2.2 (mapping semântico)
- src/components/bpmn/nodes/bpmnNodeData.ts (frontend SSOT do node.data)
"""
from __future__ import annotations

import logging
from fastapi import HTTPException
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx  # type: ignore  # dep já usada em src/services/workflow_graph.py

from src.services.bpmn_gateway_catalog import (
    load_gateway_lookup,
    resolve_logic_pattern_for_gateway,
    resolve_binding_row,
    infer_gateway_topology,
)

logger = logging.getLogger("BpmnMaterialize")

# Tipos de nó BPMN considerados executáveis (viram workflow_steps).
# Outros (start_event, end_event, gateway_*) são estruturais — não criam step.
_EXECUTABLE_NODE_TYPES: Set[str] = {"service_task", "task", "user_task", "manual_task"}

class BpmnMaterializeError(Exception):
    """Erro fatal do materialize. Endpoint mapeia pra HTTP status."""

    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(label: str, fallback: str = "step") -> str:
    """Slug snake-kebab compat com workflow_steps.slug (text livre, sem CHECK)."""
    if not label or not isinstance(label, str):
        return fallback
    s = re.sub(r"[^a-zA-Z0-9]+", "-", label.lower()).strip("-")
    return s or fallback


def _ensure_unique_slug(slug: str, taken: Set[str]) -> str:
    """Adiciona sufixo numérico se slug colidir."""
    if slug not in taken:
        return slug
    i = 2
    while f"{slug}-{i}" in taken:
        i += 1
    return f"{slug}-{i}"


def _topological_sort(
    node_ids: List[str], edges: List[Dict[str, Any]]
) -> Tuple[List[str], List[str]]:
    """Topological sort via networkx (alinha com src/services/workflow_graph.py).

    Retorna (ordered_ids, warnings). Edges: list of {source, target, ...}.
    Self-loops e edges com endpoints fora de node_ids são ignorados.
    Ciclos → warning + fallback pra input order (não bloqueia materialize).

    Auditor (2026-05-19): usar nx em vez de Kahn manual evita drift entre
    bpmn_materialize e workflow_graph.
    """
    warnings: List[str] = []
    if not node_ids:
        return [], warnings

    G = nx.DiGraph()
    G.add_nodes_from(node_ids)
    for e in edges:
        src = e.get("source")
        tgt = e.get("target")
        if not src or not tgt or src == tgt:
            continue
        if src in G.nodes and tgt in G.nodes:
            G.add_edge(src, tgt)

    try:
        ordered = [str(n) for n in nx.topological_sort(G)]
        return ordered, warnings
    except nx.NetworkXUnfeasible:
        # Ciclo detectado — fallback estável (input order)
        cycle_nodes: List[str] = []
        try:
            cycle = list(nx.find_cycle(G, orientation="original"))
            cycle_nodes = sorted({u for u, *_ in cycle})
        except Exception:
            pass
        warnings.append(
            f"ciclo detectado{' em ' + ','.join(cycle_nodes) if cycle_nodes else ''}; "
            "ordem fallback = input order"
        )
        return list(node_ids), warnings


def _resolve_diagram(
    supabase, diagram_id: str, user_company_id: str
) -> Dict[str, Any]:
    """SELECT bpmn_diagrams + verifica tenant. Retorna row ou raise."""
    res = (
        supabase.table("bpmn_diagrams")
        .select("id, company_id, name, description, diagram_json, linked_workflow_id, linked_sipoc_process_id")
        .eq("id", diagram_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise BpmnMaterializeError("diagram_not_found", f"diagrama {diagram_id} não existe", 404)
    diagram = res.data[0]
    if str(diagram["company_id"]) != user_company_id:
        logger.warning(
            "materialize cross-tenant attempt: diagram=%s company=%s user=%s",
            diagram_id, diagram["company_id"], user_company_id,
        )
        raise BpmnMaterializeError("diagram_not_found", f"diagrama {diagram_id} não existe", 404)
    return diagram


def get_bpmn_diagram_by_process_id(supabase, process_id: str, company_id: str) -> dict:
    """Fetch BPMN diagram linked to a SIPOC process.
    Raises HTTPException 404 if not found or tenant mismatch.
    """
    res = (
        supabase.table("bpmn_diagrams")
        .select("id, diagram_json, linked_sipoc_process_id, company_id")
        .eq("linked_sipoc_process_id", process_id)
        .eq("company_id", company_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail=f"BPMN diagram for process {process_id} not found")
    row = res.data[0]
    return {"diagramId": row.get("id"), "diagramJson": row.get("diagram_json")}


def _validate_specialty_config(
    supabase, specialty_config_id: Optional[str], company_id: str
) -> Optional[str]:
    """Soft validation FK agent_specialty_configs. Retorna ID se válido, None caso contrário."""
    if not specialty_config_id:
        return None
    try:
        res = (
            supabase.table("agent_specialty_configs")
            .select("id")
            .eq("id", specialty_config_id)
            .eq("company_id", company_id)
            .limit(1)
            .execute()
        )
        return specialty_config_id if res.data else None
    except Exception as exc:
        logger.warning("materialize specialty_config validate failed id=%s: %s", specialty_config_id, exc)
        return None


def _validate_operation_type(supabase, op_slug: Optional[str]) -> Optional[str]:
    """Auditor P1.2 (2026-05-19): default_operation_type não tem FK no DB
    mas o routine scheduler degrada silenciosamente quando o slug não está
    em operation_types_catalog. Validamos aqui pra emitir warning explícito.
    """
    if not op_slug:
        return None
    try:
        res = (
            supabase.table("operation_types_catalog")
            .select("id")
            .eq("id", op_slug)
            .limit(1)
            .execute()
        )
        return op_slug if res.data else None
    except Exception as exc:
        logger.warning("materialize op_type validate failed id=%s: %s", op_slug, exc)
        return None


def _has_active_tasks_for_workflow(supabase, workflow_id: str) -> int:
    """Auditor risco 2 (2026-05-19): replace destrutivo se houver tasks ativas
    apontando pro workflow. Retorna count (0 = safe to replace).

    workflow_id é vinculado a tasks via workflow_steps → tasks.step_id (best-effort
    lookup; se schema não conecta, retorna 0).
    """
    try:
        # Busca steps do workflow
        steps_res = (
            supabase.table("workflow_steps")
            .select("id")
            .eq("workflow_id", workflow_id)
            .execute()
        )
        step_ids = [r["id"] for r in (steps_res.data or [])]
        if not step_ids:
            return 0
        # tasks que apontam pra esses steps + ainda ativas
        res = (
            supabase.table("tasks")
            .select("id", count="exact")
            .in_("workflow_step_id", step_ids)
            .in_("status", ["queued", "in_progress"])
            .limit(1)
            .execute()
        )
        return int(res.count or 0)
    except Exception as exc:
        # Schema sem workflow_step_id em tasks → assume safe
        logger.warning("active_tasks check failed workflow=%s: %s", workflow_id, exc)
        return 0


def _delete_workflow_cascade(supabase, workflow_id: str) -> None:
    """Pré-replace: deleta workflow_definitions + steps. FKs na engine permitem CASCADE
    ou requerem manual. Por segurança deletamos steps primeiro (mesmo que CASCADE exista
    no DB — evita race conditions)."""
    try:
        supabase.table("workflow_steps").delete().eq("workflow_id", workflow_id).execute()
    except Exception as exc:
        logger.warning("materialize replace: delete steps falhou workflow=%s: %s", workflow_id, exc)
    try:
        supabase.table("workflow_definitions").delete().eq("id", workflow_id).execute()
    except Exception as exc:
        logger.warning("materialize replace: delete definition falhou workflow=%s: %s", workflow_id, exc)


def _count_edges(node_id: str, edges: List[Dict[str, Any]]) -> Tuple[int, int]:
    incoming = sum(1 for e in edges if e.get("target") == node_id)
    outgoing = sum(1 for e in edges if e.get("source") == node_id)
    return incoming, outgoing


def _gateway_logic_hint(
    node: Dict[str, Any],
    all_nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    gateway_lookup: Dict[Tuple[str, str], Dict[str, Any]],
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Se o próximo nó downstream do step for um gateway, retorna o logic_pattern
    correspondente (kebab) + a binding row. Best-effort — só olha 1 hop downstream."""
    node_id = node.get("id")
    if not node_id:
        return None, None
    for e in edges:
        if e.get("source") == node_id:
            target_id = e.get("target")
            target = all_nodes.get(target_id) if target_id else None
            if not target:
                continue
            gtype = target.get("type")
            if not gtype or not gtype.startswith("gateway_"):
                continue
            incoming, outgoing = _count_edges(target_id, edges)
            topology = infer_gateway_topology(gtype, incoming, outgoing)
            if topology:
                pattern = resolve_logic_pattern_for_gateway(gateway_lookup, gtype, topology)
                binding = resolve_binding_row(gateway_lookup, gtype, topology)
                return pattern, binding
    return None, None


def _build_decisions_for_gateway(
    gateway_node: Dict[str, Any],
    all_nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    node_id_to_row_id: Dict[str, str],
) -> Optional[List[Dict[str, Any]]]:
    """Se gateway_exclusive fork com 2+ edges label, mapeia true/false step_ids.
    
    Estrutura mínima alinhada com engine v2 (workflow_engine.py).
    """
    gtype = gateway_node.get("type")
    if gtype != "gateway_exclusive":
        return None
    gid = gateway_node.get("id")
    outgoing = [e for e in edges if e.get("source") == gid]
    if len(outgoing) < 2:
        return None
    
    # Walk cada edge do gateway até achar próximo executable node
    def _next_executable_row_id(edge: Dict[str, Any]) -> Optional[str]:
        visited: Set[str] = set()
        stack = [edge.get("target")]
        while stack:
            nid = stack.pop()
            if not nid or nid in visited:
                continue
            visited.add(nid)
            node = all_nodes.get(nid)
            if not node:
                continue
            if node.get("type") in _EXECUTABLE_NODE_TYPES:
                return node_id_to_row_id.get(nid)
            # Se for gateway/event, segue downstream
            for e2 in edges:
                if e2.get("source") == nid:
                    stack.append(e2.get("target"))
        return None
    
    labeled = []
    for e in outgoing:
        label = (e.get("label") or e.get("data", {}).get("label") or "").strip()
        target_row = _next_executable_row_id(e)
        if target_row:
            labeled.append({"label": label or "segue", "target_row_id": target_row})
    
    if len(labeled) < 2:
        return None
    
    # Primeiro label = true, segundo = false (convenção mínima; user edita depois)
    return [{
        "condition": {
            "op": "eq",
            "field": "edge_label",
            "value": labeled[0]["label"],
        },
        "true_step_id": labeled[0]["target_row_id"],
        "false_step_id": labeled[1]["target_row_id"],
    }]


def _resolve_sipoc_columns_map(
    supabase,
    component_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Batch lookup: linked_sipoc_component_id → {type, content}.

    Silencioso se tabela ausente ou sem rows.
    """
    if not component_ids:
        return {}
    try:
        res = (
            supabase.table("sipoc_components")
            .select("id, type, content")
            .in_("id", list(set(component_ids)))
            .execute()
        )
        out: Dict[str, Dict[str, Any]] = {}
        for row in res.data or []:
            out[row.get("id")] = {
                "type": row.get("type"),
                "content": row.get("content"),
            }
        return out
    except Exception as exc:
        logger.warning("_resolve_sipoc_columns_map failed: %s", exc)
        return {}


def _resolve_setor_map(
    supabase,
    position_ids: List[str],
    company_id: str,
) -> Dict[str, str]:
    """Batch lookup: assignee_position_id → setor (sipoc_sectors.name).
    
    Silencioso se tabela ausente ou sem rows.
    """
    if not position_ids:
        return {}
    try:
        res = (
            supabase.table("sipoc_positions")
            .select("id, sector_id, sipoc_sectors(name)")
            .in_("id", position_ids)
            .eq("company_id", company_id)
            .execute()
        )
        out: Dict[str, str] = {}
        for row in res.data or []:
            sector = row.get("sipoc_sectors")
            if isinstance(sector, dict):
                name = sector.get("name") or sector.get("slug")
            else:
                name = None
            if name:
                out[row.get("id")] = name
        return out
    except Exception as exc:
        logger.warning("_resolve_setor_map failed: %s", exc)
        return {}


def _build_step_row(
    *,
    workflow_id: str,
    step_order: int,
    slug: str,
    node: Dict[str, Any],
    node_data: Dict[str, Any],
    proximo_codes: List[str],
    company_id: str,
    supabase,
    warnings: List[str],
    decisions: Optional[List[Dict[str, Any]]] = None,
    setor: Optional[str] = None,
    sipoc_component: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Constrói row de workflow_steps a partir de BpmnNode + node.data."""
    label = node_data.get("label") or node.get("data", {}).get("label") or slug
    node_type = node.get("type", "task")

    # responsavel: default 'agente' pra service_task, 'humano' pra user_task/manual_task
    responsavel = node_data.get("responsavel")
    if not responsavel:
        if node_type in ("user_task", "manual_task"):
            responsavel = "humano"
        elif node_type in ("service_task", "task"):
            responsavel = "agente" if node_data.get("agent_specialty_config_id") else "humano"

    # FK validation soft
    spec_config_id = _validate_specialty_config(
        supabase, node_data.get("agent_specialty_config_id"), company_id
    )
    if node_data.get("agent_specialty_config_id") and not spec_config_id:
        warnings.append(
            f"node={slug}: agent_specialty_config_id '{node_data.get('agent_specialty_config_id')}' "
            f"inválido pra company, gravado como NULL"
        )

    # Auditor P1.2: operation_type warning (sem FK no DB, mas routine scheduler degrada silenciosamente)
    op_type_raw = node_data.get("default_operation_type")
    op_type_validated = _validate_operation_type(supabase, op_type_raw)
    if op_type_raw and not op_type_validated:
        warnings.append(
            f"node={slug}: default_operation_type '{op_type_raw}' não existe em operation_types_catalog. "
            "Step será criado mas routine scheduler degradará silenciosamente."
        )
    # Sempre grava o valor que veio (auditor: não silenciar, só avisar)

    return {
        "id": str(uuid.uuid4()),
        "workflow_id": workflow_id,
        "step_order": step_order,
        "name": str(label)[:200],
        "slug": slug[:200],
        "specialty_slug": None,  # legado — agent_specialty_config_id substituiu
        "requires_approval": False,
        "on_success_step_id": None,  # populado em 2ª pass
        "on_failure_action": "block",  # FailureAction enum (block|skip|retry|escalate); engine workflow_engine.py:191 coage p/ enum — "errored" causava ValueError latente
        "active": True,
        "contract_version": "v1",
        "validation_status": "amarelo",  # CHECK aceita verde|amarelo|vermelho; amarelo=não-validado (era "pending" → 23514)
        "validation_errors": [],
        "logic_pattern": node_data.get("logic_pattern"),  # se vier do BPMN; senão NULL
        "responsavel": responsavel,
        "setor": setor,
        "ferramentas": [],
        "sla_horas": None,
        "alertas": [],
        "suppliers": [sipoc_component["content"]] if sipoc_component and sipoc_component.get("type") == "supplier" else None,
        "inputs": [sipoc_component["content"]] if sipoc_component and sipoc_component.get("type") == "input" else None,
        "outputs": [sipoc_component["content"]] if sipoc_component and sipoc_component.get("type") == "output" else None,
        "customers": [sipoc_component["content"]] if sipoc_component and sipoc_component.get("type") == "customer" else None,
        "decisions": decisions,
        "five_w2h": node_data.get("five_w2h") if isinstance(node_data.get("five_w2h"), dict) else None,
        "sipoc_meta": {
            "source": "bpmn_materialize",
            "node_id": node.get("id"),
            "node_type": node_type,
            "linked_sipoc_component_id": node_data.get("linked_sipoc_component_id"),
            "assignee_position_id": node_data.get("assignee_position_id"),
        },
        "proximo_step_codes": proximo_codes,
        "default_operation_type": node_data.get("default_operation_type"),
        "trigger_type": None,
        "trigger_config": {},
        "agent_specialty_config_id": spec_config_id,
    }


def materialize_bpmn_to_workflow(
    supabase,
    *,
    diagram_id: str,
    user_company_id: str,
    replace: bool = False,
) -> Dict[str, Any]:
    """Phase 3 main entry point.

    Returns dict with: workflow_id, workflow_slug, steps_created, warnings,
    linked_diagram_id, replaced (bool).

    Raises BpmnMaterializeError pra fluxo HTTP.
    """
    if not user_company_id:
        raise BpmnMaterializeError("missing_company", "company_id ausente", 403)

    diagram = _resolve_diagram(supabase, diagram_id, user_company_id)
    diagram_json = diagram.get("diagram_json") or {}
    if not isinstance(diagram_json, dict):
        raise BpmnMaterializeError("invalid_diagram_json", "diagram_json não é dict", 400)

    nodes_raw = diagram_json.get("nodes") or []
    edges = diagram_json.get("edges") or []
    if not isinstance(nodes_raw, list) or not isinstance(edges, list):
        raise BpmnMaterializeError(
            "invalid_diagram_json", "diagram_json.nodes/edges devem ser listas", 400
        )

    warnings: List[str] = []

    # Idempotency check
    existing_workflow_id = diagram.get("linked_workflow_id")
    if existing_workflow_id and not replace:
        raise BpmnMaterializeError(
            "already_materialized",
            f"diagrama já tem linked_workflow_id={existing_workflow_id}. "
            "Use ?replace=true pra sobrescrever.",
            409,
        )
    replaced = False
    if existing_workflow_id and replace:
        # Auditor risco 2: refusa replace destrutivo se houver tasks ativas
        active_count = _has_active_tasks_for_workflow(supabase, existing_workflow_id)
        if active_count > 0:
            raise BpmnMaterializeError(
                "active_tasks_block_replace",
                f"workflow_id={existing_workflow_id} tem {active_count} task(s) ativa(s) "
                f"(queued/in_progress). Aborte essas tasks antes de replace.",
                409,
            )
        _delete_workflow_cascade(supabase, existing_workflow_id)
        replaced = True
        warnings.append(f"workflow_id={existing_workflow_id} substituído (replace=true)")

    # Indexa nodes pra lookup rápido
    all_nodes: Dict[str, Dict[str, Any]] = {n.get("id"): n for n in nodes_raw if n.get("id")}

    # P0-BE-1: catálogo gateway bindings (metadata-driven, sem dict hardcoded)
    gateway_lookup = load_gateway_lookup(supabase)

    # P0-BE-2: batch resolve setor via assignee_position_id → sipoc_positions → sipoc_sectors
    position_ids: List[str] = []
    for n in all_nodes.values():
        pos_id = (n.get("data") or {}).get("assignee_position_id")
        if pos_id:
            position_ids.append(pos_id)
    setor_map = _resolve_setor_map(supabase, list(set(position_ids)), user_company_id)

    # P2-BE-7: batch resolve SIPOC columns via linked_sipoc_component_id
    component_ids: List[str] = []
    for n in all_nodes.values():
        comp_id = (n.get("data") or {}).get("linked_sipoc_component_id")
        if comp_id:
            component_ids.append(comp_id)
    sipoc_columns_map = _resolve_sipoc_columns_map(supabase, component_ids)

    # Filtra nodes executáveis
    executable_ids: List[str] = [
        nid for nid, n in all_nodes.items() if n.get("type") in _EXECUTABLE_NODE_TYPES
    ]
    if not executable_ids:
        raise BpmnMaterializeError(
            "no_executable_nodes",
            "diagram_json não tem nós executáveis (service_task/task/user_task/manual_task)",
            400,
        )

    # Topological sort (sobre TODOS os nodes pra ordem consistente, depois filtra)
    all_node_ids = list(all_nodes.keys())
    ordered_all, sort_warnings = _topological_sort(all_node_ids, edges)
    warnings.extend(sort_warnings)
    ordered_executable = [nid for nid in ordered_all if nid in executable_ids]

    # Create workflow_definition
    now = _now_iso()
    workflow_id = str(uuid.uuid4())
    workflow_name = (diagram.get("name") or "BPMN workflow").strip()
    workflow_slug = _slugify(workflow_name, fallback="bpmn-workflow")
    # Postgres slug pode colidir; pra MVP confia no UUID + autogen do user
    workflow_def_row = {
        "id": workflow_id,
        "company_id": user_company_id,
        "name": workflow_name[:200],
        "slug": workflow_slug[:200],
        "description": diagram.get("description"),
        "is_active": True,
        "version": 1,
        "trigger_type": "manual",  # FK workflow_trigger_types
        "is_scheduled": False,
        "goal_id": diagram.get("linked_goal_id"),
        "kind": diagram.get("workflow_kind") or "project",
        "created_at": now,
        "updated_at": now,
    }
    try:
        supabase.table("workflow_definitions").insert(workflow_def_row).execute()
    except Exception as exc:
        raise BpmnMaterializeError("workflow_definition_insert_failed", str(exc), 500)

    # Map node_id → slug pra resolver proximo_step_codes
    node_id_to_slug: Dict[str, str] = {}
    taken_slugs: Set[str] = set()
    for nid in ordered_executable:
        node = all_nodes[nid]
        node_data = node.get("data") or {}
        label = node_data.get("label") or node_data.get("name") or f"step-{len(node_id_to_slug)+1}"
        slug = _ensure_unique_slug(_slugify(label), taken_slugs)
        taken_slugs.add(slug)
        node_id_to_slug[nid] = slug

    # Build proximo_step_codes per node — só conta target executável (gateway pula através)
    def resolve_downstream_slugs(source_id: str) -> List[str]:
        """Walk edges from source_id; quando passar por gateway, segue até next executable."""
        result: List[str] = []
        visited: Set[str] = set()

        def walk(node_id: str) -> None:
            for e in edges:
                if e.get("source") != node_id:
                    continue
                target_id = e.get("target")
                if not target_id or target_id in visited:
                    continue
                visited.add(target_id)
                target = all_nodes.get(target_id)
                if not target:
                    continue
                if target.get("type") in _EXECUTABLE_NODE_TYPES:
                    if target_id in node_id_to_slug:
                        result.append(node_id_to_slug[target_id])
                else:
                    # Gateway/event — recursivamente segue downstream
                    walk(target_id)

        walk(source_id)
        return result

    # Insere steps em batch
    step_rows: List[Dict[str, Any]] = []
    node_id_to_row_id: Dict[str, str] = {}
    for idx, nid in enumerate(ordered_executable):
        node = all_nodes[nid]
        node_data = node.get("data") or {}
        slug = node_id_to_slug[nid]
        proximo_codes = resolve_downstream_slugs(nid)

        # P0-BE-2: resolve setor via assignee_position_id
        step_setor = setor_map.get(node_data.get("assignee_position_id")) or None

        # P2-BE-7: resolve SIPOC columns via linked_sipoc_component_id
        step_sipoc_component = sipoc_columns_map.get(node_data.get("linked_sipoc_component_id"))

        # P0-BE-2: gateway logic pattern + warnings (decisions em 2ª pass depois)
        logic_pattern_hint = None
        binding_row = None
        if not node_data.get("logic_pattern"):
            logic_pattern_hint, binding_row = _gateway_logic_hint(
                node, all_nodes, edges, gateway_lookup
            )
            if binding_row and binding_row.get("engine_status") == "pending":
                warnings.append(
                    f"node={slug}: gateway binding '{binding_row.get('bpmn_gateway_type')}' "
                    f"({binding_row.get('topology')}) está pending — "
                    "materializa, mas execução paralela ainda não ativa"
                )

        row = _build_step_row(
            workflow_id=workflow_id,
            step_order=idx,
            slug=slug,
            node=node,
            node_data=node_data,
            proximo_codes=proximo_codes,
            company_id=user_company_id,
            supabase=supabase,
            warnings=warnings,
            setor=step_setor,
            sipoc_component=step_sipoc_component,
        )
        # Gateway hint pro logic_pattern (se step não trouxe explicit)
        if not row.get("logic_pattern") and logic_pattern_hint:
            row["logic_pattern"] = logic_pattern_hint

        step_rows.append(row)
        node_id_to_row_id[nid] = row["id"]

    inserted_count = 0
    for row in step_rows:
        try:
            res = supabase.table("workflow_steps").insert(row).execute()
            if res.data:
                inserted_count += 1
            else:
                warnings.append(f"step '{row['slug']}': INSERT vazio")
        except Exception as exc:
            warnings.append(f"step '{row['slug']}': INSERT falhou ({exc!s})")
            logger.exception("materialize step insert failed slug=%s", row["slug"])

    # 2ª pass: resolve on_success_step_id (primeiro target executável de cada step)
    for row in step_rows:
        node_id = None
        # Achar node_id correspondente a este row (via mapping reverso)
        for nid, rid in node_id_to_row_id.items():
            if rid == row["id"]:
                node_id = nid
                break
        if not node_id:
            continue
        downstream_slugs = row.get("proximo_step_codes") or []
        if not downstream_slugs:
            continue
        first_slug = downstream_slugs[0]
        # Mapeia slug → row_id
        target_row_id = None
        for r in step_rows:
            if r["slug"] == first_slug:
                target_row_id = r["id"]
                break
        if target_row_id and target_row_id != row["id"]:
            try:
                supabase.table("workflow_steps").update(
                    {"on_success_step_id": target_row_id}
                ).eq("id", row["id"]).execute()
            except Exception as exc:
                warnings.append(f"step '{row['slug']}': on_success_step_id update falhou ({exc!s})")

    # 3ª pass: resolve decisions[] para steps upstream de gateway_exclusive fork
    # (precisa de node_id_to_row_id completo — por isso após INSERT)
    for row in step_rows:
        node_id = None
        for nid, rid in node_id_to_row_id.items():
            if rid == row["id"]:
                node_id = nid
                break
        if not node_id:
            continue
        # Procura gateway downstream
        gateway_node = None
        for e in edges:
            if e.get("source") == node_id:
                tgt = all_nodes.get(e.get("target"))
                if tgt and tgt.get("type") == "gateway_exclusive":
                    gateway_node = tgt
                    break
        if not gateway_node:
            continue
        decisions_payload = _build_decisions_for_gateway(
            gateway_node, all_nodes, edges, node_id_to_row_id
        )
        if decisions_payload:
            try:
                supabase.table("workflow_steps").update(
                    {"decisions": decisions_payload}
                ).eq("id", row["id"]).execute()
            except Exception as exc:
                warnings.append(f"step '{row['slug']}': decisions update falhou ({exc!s})")

    # Atualiza bpmn_diagrams.linked_workflow_id
    try:
        supabase.table("bpmn_diagrams").update(
            {"linked_workflow_id": workflow_id, "updated_at": now}
        ).eq("id", diagram_id).execute()
    except Exception as exc:
        warnings.append(f"linked_workflow_id update falhou: {exc!s}")

    logger.info(
        "bpmn_materialize done diagram=%s workflow=%s steps=%d warnings=%d replaced=%s",
        diagram_id, workflow_id, inserted_count, len(warnings), replaced,
    )

    return {
        "workflow_id": workflow_id,
        "workflow_slug": workflow_slug,
        "steps_created": inserted_count,
        "warnings": warnings,
        "linked_diagram_id": diagram_id,
        "replaced": replaced,
    }


# ════════════════════════════════════════════════════════════════════════════
# Wrappers compatíveis com testes legados (P0-BE-2)
# ════════════════════════════════════════════════════════════════════════════

def _find_immediate_downstream_gateway(
    node_id: str,
    all_nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Retorna o primeiro gateway downstream de um nó (1 hop)."""
    for e in edges:
        if e.get("source") == node_id:
            target = all_nodes.get(e.get("target"))
            if target and target.get("type", "").startswith("gateway_"):
                return target
    return None


def _resolve_gateway_logic_from_catalog(
    gateway_node: Dict[str, Any],
    edges: List[Dict[str, Any]],
    gateway_lookup: Dict[Tuple[str, str], Dict[str, Any]],
    warnings: List[str],
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Resolve logic_pattern + binding row para um gateway node.

    Wrapper usado por testes legados; materialize principal usa
    `_gateway_logic_hint` (olha a partir do step upstream).
    """
    gtype = gateway_node.get("type")
    gid = gateway_node.get("id")
    incoming, outgoing = _count_edges(gid, edges)
    topology = infer_gateway_topology(gtype, incoming, outgoing)
    if not topology:
        return None, None
    binding = resolve_binding_row(gateway_lookup, gtype, topology)
    if binding and binding.get("engine_status") == "pending":
        warnings.append(
            f"gateway binding '{gtype}' ({topology}) está pending — "
            "materializa, mas execução paralela ainda não ativa"
        )
    return resolve_logic_pattern_for_gateway(gateway_lookup, gtype, topology), binding


def _build_exclusive_fork_decisions(
    gateway_id: str,
    edges: List[Dict[str, Any]],
    all_nodes: Dict[str, Dict[str, Any]],
    node_id_to_row_id: Dict[str, str],
    warnings: List[str],  # noqa: ARG001
) -> Optional[List[Dict[str, Any]]]:
    """Wrapper compatível com testes legados."""
    gateway_node = all_nodes.get(gateway_id)
    if not gateway_node:
        return None
    return _build_decisions_for_gateway(gateway_node, all_nodes, edges, node_id_to_row_id)
