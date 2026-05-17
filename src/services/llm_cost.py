"""LLM cost lookup — catalog-driven (A.3 do ADR Fase A).

Aposenta constantes hardcoded (`_GEMINI_PRO_COST_PER_TOKEN`,
`_GEMINI_FLASH_COST_PER_TOKEN`, etc.) em favor de lookup contra
`vectraclip.llm_models` (PK composta `(id, effective_from)`).

Regra de Ouro #2 (NO HARDCODE) — `docs/CODE-PATTERNS.md` P1.

Padrão consumido por `src/agents/athena.py` + `src/agents/oracle.py`
e qualquer agente futuro que reporte `cost_usd` em tasks.

Notas de implementação:
- Cache TTL 5min (300s) — custos mudam raro (preço por modelo é
  trimestral/anual em geral; cache mais agressivo do que op_types/exec_modes)
- PK composta `(id, effective_from)`: lookup busca a row ativa mais recente
  via `order(effective_from desc).limit(1)` — respeita versionamento de preço
- Fallback offline: retorna 0.0 (NÃO usa constante hardcoded — preferível
  subestimar do que cravar valor desatualizado que mente sobre custo real)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("Vectra.LLMCost")

_LLM_COST_CACHE: Dict[str, Dict[str, Any]] = {}
_LLM_COST_CACHE_TTL_S = 300.0


def _load_llm_cost(supabase: Any, model_id: str) -> Optional[Dict[str, float]]:
    """Busca custo por TOKEN do modelo ativo mais recente em `llm_models`.

    Args:
        supabase: cliente Supabase (None em boot offline → retorna None)
        model_id: id do modelo em `vectraclip.llm_models` (ex: `gemini-2.5-pro`)

    Returns:
        `{"input": float, "output": float}` em USD por TOKEN, ou None se
        supabase indisponível / modelo não encontrado / row inativa.
    """
    if not supabase or not model_id:
        return None

    now = time.time()
    cached = _LLM_COST_CACHE.get(model_id)
    if cached and (now - cached.get("fetched_at", 0.0)) < _LLM_COST_CACHE_TTL_S:
        return cached.get("cost")

    try:
        res = (
            supabase.table("llm_models")
            .select("id,input_cost_per_1m,output_cost_per_1m,effective_from,is_active")
            .eq("id", model_id)
            .eq("is_active", True)
            .order("effective_from", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            logger.warning("llm_cost lookup empty for model_id=%s", model_id)
            _LLM_COST_CACHE[model_id] = {"cost": None, "fetched_at": now}
            return None
        row = rows[0]
        cost = {
            "input": float(row["input_cost_per_1m"]) / 1_000_000.0,
            "output": float(row["output_cost_per_1m"]) / 1_000_000.0,
        }
        previous = (cached or {}).get("cost")
        if previous != cost:
            logger.info(
                "llm_cost refreshed model=%s input=$%.4f/M output=$%.4f/M effective_from=%s",
                model_id, float(row["input_cost_per_1m"]), float(row["output_cost_per_1m"]),
                row.get("effective_from"),
            )
        _LLM_COST_CACHE[model_id] = {"cost": cost, "fetched_at": now}
        return cost
    except Exception as e:
        logger.warning("_load_llm_cost fallback (returning None): %s", e)
        return None


def calc_llm_cost(supabase: Any, model_id: str, tokens: Dict[str, int]) -> float:
    """Calcula custo USD a partir de tokens dict + model_id.

    Padrão chamado por `_calc_cost(supabase, tokens)` em athena.py / oracle.py.

    Args:
        supabase: cliente Supabase (None → retorna 0.0)
        model_id: id em `vectraclip.llm_models` (ex: `gemini-2.5-flash`)
        tokens: dict com chaves `"input"` e `"output"` (int)

    Returns:
        Custo USD (float). 0.0 se supabase indisponível ou modelo não
        encontrado (fail-safe — não cravar valor errado).
    """
    cost = _load_llm_cost(supabase, model_id)
    if cost is None:
        return 0.0
    return (
        tokens.get("input", 0) * cost["input"]
        + tokens.get("output", 0) * cost["output"]
    )
