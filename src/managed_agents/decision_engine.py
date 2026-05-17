"""
Decision Engine: determina se uma task deve ser executada via CMA (Managed Agent)
ou via Harness (PortRuntime daemon).

Critérios de pontuação (0-100):
  - operation_type: tipos analíticos/simples pontuam alto (→ CMA); código/orquestração pontuam baixo (→ Harness)
  - Comprimento da descrição: curta = bônus, muito longa = penalidade
  - budget_limit: orçamento muito apertado favorece CMA (mais rápido/barato)

Threshold: score >= 50 → managed_agent; caso contrário → harness

A.4 do ADR Fase A (P13 — 2026-05-17): score por operation_type é catalog-driven
via `vectraclip.operation_types_catalog.routing_score`. Antes era hardcoded em
`_OPERATION_TYPE_SCORES` (10 entries) — 30 dos 40 op_types caíam no default 60
sem visibilidade. Regra de Ouro #2 (NO HARDCODE).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("ManagedAgents.DecisionEngine")

# Cache de routing_score por operation_type. TTL 60s (espelha pattern de
# `_load_operation_type_ids` em api.py). Lazy load via lookup Supabase.
_ROUTING_SCORE_CACHE: Dict[str, int] = {}
_ROUTING_SCORE_CACHE_FETCHED_AT: float = 0.0
_ROUTING_SCORE_CACHE_TTL_S: float = 60.0
_DEFAULT_ROUTING_SCORE = 60  # bate com DEFAULT do DB (operation_types_catalog.routing_score)


def _load_operation_type_routing_scores() -> Dict[str, int]:
    """Lê `{operation_type_id: routing_score}` de `operation_types_catalog`.

    Cache TTL 60s. Falha-segura: cache antigo (pode ser vazio) se Supabase off.
    Lazy import de `src.api.supabase` (evita circular import — `api.py` importa
    `should_use_managed_agent` no router).
    """
    global _ROUTING_SCORE_CACHE, _ROUTING_SCORE_CACHE_FETCHED_AT
    now = time.time()
    if _ROUTING_SCORE_CACHE and (now - _ROUTING_SCORE_CACHE_FETCHED_AT) < _ROUTING_SCORE_CACHE_TTL_S:
        return _ROUTING_SCORE_CACHE
    try:
        from src.api import supabase
        if not supabase:
            return _ROUTING_SCORE_CACHE
        res = (
            supabase.table("operation_types_catalog")
            .select("id,routing_score,is_active")
            .eq("is_active", True)
            .execute()
        )
        rows = res.data or []
        new_cache = {str(r["id"]): int(r.get("routing_score", _DEFAULT_ROUTING_SCORE)) for r in rows if r.get("id")}
        previous = _ROUTING_SCORE_CACHE
        if previous != new_cache:
            logger.info("routing_score cache refreshed: count=%d", len(new_cache))
        _ROUTING_SCORE_CACHE = new_cache
        _ROUTING_SCORE_CACHE_FETCHED_AT = now
        return new_cache
    except Exception as e:
        logger.warning("_load_operation_type_routing_scores fallback (cached=%d): %s", len(_ROUTING_SCORE_CACHE), e)
        return _ROUTING_SCORE_CACHE


CMA_THRESHOLD = 50


@dataclass
class RoutingDecision:
    executor_type: str          # "managed_agent" | "harness"
    score: int
    rationale: str
    operation_type: str


def should_use_managed_agent(task: Dict[str, Any]) -> RoutingDecision:
    """
    Recebe um dict de task (campos do banco ou modelo Task serializado)
    e retorna a decisão de roteamento com score e rationale.
    """
    operation_type: str = task.get("operation_type") or "other"
    description: str = task.get("description") or ""
    budget_limit: Optional[int] = task.get("budget_limit")

    scores = _load_operation_type_routing_scores()
    score = scores.get(operation_type, _DEFAULT_ROUTING_SCORE)
    reasons = [f"operation_type={operation_type} base_score={score}"]

    # Ajuste por comprimento da descrição
    desc_len = len(description)
    if desc_len < 100:
        score += 15
        reasons.append(f"descrição curta ({desc_len} chars) +15")
    elif desc_len > 600:
        score -= 20
        reasons.append(f"descrição longa ({desc_len} chars) -20")

    # Ajuste por budget apertado (favorece CMA)
    if budget_limit is not None and 0 < budget_limit < 100:
        score += 10
        reasons.append(f"budget apertado ({budget_limit}) +10")

    score = max(0, min(100, score))
    executor = "managed_agent" if score >= CMA_THRESHOLD else "harness"

    rationale = "; ".join(reasons) + f" → score={score} → {executor}"
    logger.info(
        "DecisionEngine task_id=%s score=%d executor=%s",
        task.get("id", "?"),
        score,
        executor,
    )

    return RoutingDecision(
        executor_type=executor,
        score=score,
        rationale=rationale,
        operation_type=operation_type,
    )
