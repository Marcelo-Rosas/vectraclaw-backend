import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("GeminiInteractions")

DEEP_RESEARCH_AGENT = "deep-research-preview-04-2026"

# F5 N3 (2026-05-17): `_COST_PER_TOKEN` hardcoded ($0.075/$0.30 per 1M tokens
# era preço Flash sub-estimado) aposentado. Custo agora vem de
# `vectraclip.llm_models` via `src.services.llm_cost.calc_llm_cost` — preço
# do `DEEP_RESEARCH_AGENT` foi seedado em llm_models pelo PR #192 (Opção C
# Deep Research) com `per_request_cost_usd=0.035` (Google Search grounding).
# Regra de Ouro #2 NO HARDCODE.


def normalize_research_documents(documents: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Normaliza itens de input_json.documents para consumo consistente (uri vs url).
    Garante chave `uri` quando só `url` foi enviado; preserva demais chaves.
    """
    if not documents:
        return []
    out: List[Dict[str, Any]] = []
    for d in documents:
        if not isinstance(d, dict):
            continue
        item = dict(d)
        uri = item.get("uri") or item.get("url")
        if uri:
            item["uri"] = uri
        out.append(item)
    return out


def enrich_research_prompt_with_documents(prompt: str, documents: Optional[List[Dict[str, Any]]]) -> str:
    """Prefixa URLs ao prompt do Deep Research (a API não recebe `documents` separado no create atual)."""
    docs = normalize_research_documents(documents or [])
    urls: List[str] = []
    for d in docs:
        u = d.get("uri") or d.get("url")
        if u and isinstance(u, str):
            urls.append(u.strip())
    if not urls:
        return prompt
    block = "Fontes primárias a consultar (priorize estas URLs na pesquisa):\n" + "\n".join(f"- {u}" for u in urls)
    return f"{block}\n\n{prompt}"


def _calc_cost(tokens: Dict[str, int], supabase: Optional[Any] = None) -> float:
    """Custo USD do DEEP_RESEARCH_AGENT via lookup catalog-driven em llm_models.

    F5 N3: substitui hardcoded `_COST_PER_TOKEN`. Supabase é opcional pra preservar
    callers de `get_research_status` (utility sem supabase no escopo) — se ausente,
    `calc_llm_cost` retorna 0.0 fail-safe.
    """
    from src.services.llm_cost import calc_llm_cost
    return calc_llm_cost(supabase, DEEP_RESEARCH_AGENT, tokens)


async def start_research(
    prompt: str,
    documents: Optional[List[Dict]] = None,
) -> str:
    """
    Inicia Deep Research em background e retorna interaction_id imediatamente.
    O resultado fica disponível via get_research_status() após alguns minutos.
    URLs em `documents` são normalizadas (url→uri) e injetadas no texto do prompt.
    """
    from src.services.gemini_client import get_client
    client = get_client()

    input_text = enrich_research_prompt_with_documents(prompt, documents)

    t0 = time.monotonic()
    interaction = await asyncio.to_thread(
        client.interactions.create,
        input=input_text,
        agent=DEEP_RESEARCH_AGENT,
        background=True,
    )
    logger.info(
        "deep_research.started id=%s elapsed=%.0fms",
        interaction.id, (time.monotonic() - t0) * 1000,
    )
    return interaction.id


async def get_research_status(interaction_id: str) -> Dict[str, Any]:
    """
    Verifica status de uma interação Deep Research.
    Retorna dict com 'status': 'in_progress' | 'completed' | 'failed'
    Returns {"status": "failed"} for 403/404 instead of raising.
    """
    from src.services.gemini_client import get_client
    client = get_client()

    try:
        interaction = await asyncio.to_thread(client.interactions.get, interaction_id)
    except Exception as e:
        err = str(e).lower()
        if "403" in err or "permission" in err or "denied" in err:
            logger.error("deep_research.permission_denied id=%s — API access revoked", interaction_id)
            return {"status": "failed", "error": f"Deep Research API access revoked (403): {e}"}
        if "404" in err or "not_found" in err or "not found" in err:
            logger.warning("deep_research.not_found id=%s — interaction expired or invalid", interaction_id)
            return {"status": "failed", "error": f"Interaction not found (expired or invalid ID): {e}"}
        raise
    status = getattr(interaction, "status", "in_progress")

    if status == "completed":
        text = ""
        citations: List[Dict] = []

        outputs = getattr(interaction, "outputs", None) or []
        if outputs:
            last = outputs[-1]
            text = getattr(last, "text", "") or ""
            gm = getattr(last, "grounding_metadata", None)
            if gm:
                for chunk in getattr(gm, "grounding_chunks", []):
                    web = getattr(chunk, "web", None)
                    if web:
                        citations.append({
                            "title": getattr(web, "title", ""),
                            "uri": getattr(web, "uri", ""),
                        })

        usage = getattr(interaction, "usage_metadata", None)
        tokens: Dict[str, int] = {}
        if usage:
            tokens = {
                "input": getattr(usage, "prompt_token_count", 0) or 0,
                "output": getattr(usage, "candidates_token_count", 0) or 0,
                "total": getattr(usage, "total_token_count", 0) or 0,
            }

        logger.info(
            "deep_research.completed id=%s tokens=%s citations=%d",
            interaction_id, tokens.get("total", 0), len(citations),
        )
        return {
            "status": "completed",
            "text": text,
            "citations": citations,
            "tokens": tokens,
            "cost_usd": _calc_cost(tokens),
        }

    elif status == "failed":
        error = str(getattr(interaction, "error", "Unknown research failure"))
        logger.warning("deep_research.failed id=%s error=%s", interaction_id, error)
        return {"status": "failed", "error": error}

    return {"status": "in_progress"}
