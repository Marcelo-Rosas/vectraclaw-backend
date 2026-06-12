"""Catálogo BPMN gateway → workflow_logic_patterns (P0-BE-1).

Substitui o dict hardcoded `_GATEWAY_TYPES_TO_LOGIC` em `bpmn_materialize.py`
(Regra de Ouro #2). Fonte: `vectraclip.bpmn_gateway_bindings`.

Uso:
- GET /api/bpmn/gateway-bindings (API)
- P0-BE-2: materialize chama `resolve_logic_pattern_for_gateway`
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("BpmnGatewayCatalog")

# Chave de lookup: (bpmn_gateway_type, topology)
GatewayKey = Tuple[str, str]

VALID_GATEWAY_TYPES = frozenset({
    "gateway_exclusive",
    "gateway_parallel",
    "gateway_inclusive",
})
VALID_TOPOLOGIES = frozenset({"fork", "join"})


def rows_to_lookup(rows: List[Dict[str, Any]]) -> Dict[GatewayKey, Dict[str, Any]]:
    """Indexa rows do catálogo por (bpmn_gateway_type, topology)."""
    out: Dict[GatewayKey, Dict[str, Any]] = {}
    for row in rows or []:
        gtype = (row.get("bpmn_gateway_type") or "").strip()
        topo = (row.get("topology") or "").strip()
        if gtype and topo:
            out[(gtype, topo)] = row
    return out


def fetch_gateway_bindings(supabase) -> List[Dict[str, Any]]:
    """SELECT catálogo ativo. Retorna [] se tabela ausente ou erro."""
    try:
        res = (
            supabase.table("bpmn_gateway_bindings")
            .select(
                "bpmn_gateway_type,topology,logic_pattern_id,name,description,"
                "engine_status,display_order,is_active"
            )
            .eq("is_active", True)
            .order("display_order")
            .execute()
        )
        return list(res.data or [])
    except Exception as exc:
        logger.warning("fetch_gateway_bindings failed: %s", exc)
        return []


def infer_gateway_topology(
    gateway_type: str,
    incoming_count: int,
    outgoing_count: int,
) -> Optional[str]:
    """Infere fork vs join pela topologia do nó no diagrama.

    fork: 1+ entradas e 2+ saídas (split)
    join: 2+ entradas e 0–1 saídas típico (merge)
    """
    if outgoing_count >= 2 and incoming_count <= 1:
        return "fork"
    if incoming_count >= 2 and outgoing_count <= 1:
        return "join"
    # Ambíguo ou inválido (ex.: 1-in-1-out)
    return None


def resolve_logic_pattern_for_gateway(
    lookup: Dict[GatewayKey, Dict[str, Any]],
    gateway_type: str,
    topology: str,
) -> Optional[str]:
    """Retorna logic_pattern_id (kebab) ou None."""
    row = lookup.get((gateway_type, topology))
    if not row:
        return None
    return row.get("logic_pattern_id")


def resolve_binding_row(
    lookup: Dict[GatewayKey, Dict[str, Any]],
    gateway_type: str,
    topology: str,
) -> Optional[Dict[str, Any]]:
    return lookup.get((gateway_type, topology))


def load_gateway_lookup(supabase) -> Dict[GatewayKey, Dict[str, Any]]:
    """Convenience: fetch + index para materialize / API."""
    return rows_to_lookup(fetch_gateway_bindings(supabase))
