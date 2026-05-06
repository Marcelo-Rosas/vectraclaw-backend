"""
Workflow DAG helpers backed by networkx.

Used by workflow CRUD validation and TaskFactory materialization.
Plain dict/Mapping inputs avoid circular imports with models.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, MutableMapping, Sequence

import networkx as nx

__all__ = [
    "step_code",
    "proximo_list",
    "sla_hours",
    "build_graph",
    "validate_proximo_targets",
    "validate_chain",
    "validate_workflow_steps",
    "topological_generations_with_meta",
    "critical_path",
    "edges_from_linear_chain",
    "enrich_steps_with_legacy_edges",
]


def step_code(row: Mapping[str, Any]) -> str:
    v = row.get("stepCode") or row.get("step_code") or row.get("slug") or ""
    return str(v).strip()


def proximo_list(row: Mapping[str, Any]) -> list[str]:
    v = row.get("proximo") or row.get("proximo_step_codes") or []
    if v is None:
        return []
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    return [str(x).strip() for x in v if str(x).strip()]


def sla_hours(row: Mapping[str, Any]) -> int:
    v = row.get("slaHoras") or row.get("sla_horas") or 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def build_graph(steps: Sequence[Mapping[str, Any]]) -> nx.DiGraph:
    """
    Build DiGraph from rich step rows.
    Node id = step_code/slug. Node attributes: full row copy + normalized slaHoras.
    Only edges whose targets exist as defined steps are added (avoids phantom nodes).
    """
    G = nx.DiGraph()

    for raw in steps:
        code = step_code(raw)
        if not code:
            continue
        attrs = dict(raw)
        attrs["slaHoras"] = sla_hours(raw)
        G.add_node(code, **attrs)

    defined_set = set(G.nodes)

    for raw in steps:
        code = step_code(raw)
        if not code:
            continue
        for nxt in proximo_list(raw):
            if nxt in defined_set:
                G.add_edge(code, nxt)

    return G


def validate_proximo_targets(steps: Sequence[Mapping[str, Any]]) -> list[str]:
    """Edges referencing unknown step codes."""
    defined_set = {step_code(s) for s in steps if step_code(s)}
    errors: list[str] = []
    for raw in steps:
        code = step_code(raw)
        if not code:
            continue
        for nxt in proximo_list(raw):
            if nxt not in defined_set:
                errors.append(f"step {code!r}: unknown proximo target {nxt!r}")
    return errors


def validate_chain(G: nx.DiGraph, defined_codes: Iterable[str]) -> list[str]:
    """Return human-readable validation errors (empty list = OK)."""
    errors: list[str] = []
    defined_set = set(defined_codes)

    if not defined_set:
        errors.append("no steps defined")
        return errors

    if not nx.is_directed_acyclic_graph(G):
        try:
            cycles = list(nx.simple_cycles(G))
            for cyc in cycles[:10]:
                errors.append("cycle: " + " -> ".join(cyc))
            if len(cycles) > 10:
                errors.append(f"... and {len(cycles) - 10} more cycles")
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"cycle detection failed: {exc}")

    entrypoints = [n for n in defined_set if n in G and G.in_degree(n) == 0]
    if not entrypoints:
        errors.append("no entry-point (every step has a predecessor)")

    if entrypoints:
        reachable: set[str] = set()
        for ep in entrypoints:
            reachable.add(ep)
            reachable |= nx.descendants(G, ep)
        unreachable = defined_set - reachable
        if unreachable:
            errors.append(f"unreachable steps from entry-points: {sorted(unreachable)!r}")

    return errors


def validate_workflow_steps(steps: Sequence[Mapping[str, Any]]) -> list[str]:
    """Full validation: unknown proximo targets + DAG properties."""
    errs = validate_proximo_targets(steps)
    defined_codes = [step_code(s) for s in steps if step_code(s)]
    G = build_graph(steps)
    errs.extend(validate_chain(G, defined_codes))
    return errs


def topological_generations_with_meta(G: nx.DiGraph) -> list[list[str]]:
    """Parallel execution waves (Kahn layering via networkx)."""
    return [list(level) for level in nx.topological_generations(G)]


def critical_path(G: nx.DiGraph, weight: str = "slaHoras") -> tuple[list[str], int]:
    """
    Longest-weight path in DAG (CPM-style) using **node** weights (e.g. slaHoras).

    networkx.dag_longest_path only supports edge weights; TaskFactory expects SLA on nodes.
    """
    if G.number_of_nodes() == 0:
        return [], 0
    if not nx.is_directed_acyclic_graph(G):
        return [], 0

    def node_w(n: str) -> int:
        try:
            return int(G.nodes[n].get(weight, 0) or 0)
        except (TypeError, ValueError):
            return 0

    dp: dict[str, int] = {}
    prev: dict[str, str | None] = {}
    for n in nx.topological_sort(G):
        preds = list(G.predecessors(n))
        wn = node_w(n)
        if not preds:
            dp[n] = wn
            prev[n] = None
        else:
            best_p = max(preds, key=lambda p: dp[p])
            dp[n] = dp[best_p] + wn
            prev[n] = best_p

    end = max(G.nodes, key=lambda n: dp[n])
    total = dp[end]
    path_rev: list[str] = []
    cur: str | None = end
    while cur is not None:
        path_rev.append(cur)
        cur = prev[cur]
    return list(reversed(path_rev)), total


def edges_from_linear_chain(rows_by_order: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """Build (slug_i, slug_{i+1}) pairs from rows sorted by step_order (legacy workflows)."""
    slugs = [step_code(r) for r in rows_by_order if step_code(r)]
    out: list[tuple[str, str]] = []
    for i in range(len(slugs) - 1):
        out.append((slugs[i], slugs[i + 1]))
    return out


def enrich_steps_with_legacy_edges(steps: list[MutableMapping[str, Any]]) -> None:
    """
    Mutate steps in-place: if proximo_step_codes/proximo empty but on_success_step_id
    is set, append successor slug resolved from id->slug map.
    """
    id_to_slug: dict[str, str] = {}
    for s in steps:
        sid = str(s.get("id") or "")
        sc = step_code(s)
        if sid:
            id_to_slug[sid] = sc

    for s in steps:
        if proximo_list(s):
            continue
        succ_id = s.get("on_success_step_id")
        if not succ_id:
            continue
        tgt = id_to_slug.get(str(succ_id))
        if not tgt:
            continue
        existing = list(s.get("proximo_step_codes") or s.get("proximo") or [])
        if isinstance(existing, str):
            existing = [existing]
        merged = list(existing) + [tgt]
        s["proximo_step_codes"] = merged
