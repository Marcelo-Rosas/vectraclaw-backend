"""
Kronos Apply Corrections — handler do `operation_type='planner-apply-corrections'`.

Task #18 (sessão 2026-05-14). Workflow `kronos-audit-historico` Step 3.

Aplica sugestões aprovadas (vindas do parent_task.output_json) editando:
1. Excel local (CSV export do Planner) — atualiza coluna categoria/subcategoria
2. Lançamentos no Planner via Playwright — re-categoriza inline
3. Duplicatas — marca pra remoção via UI

Pré-requisito: task.parent_task_id deve apontar pra um Step 1 audit-historico
que rodou e gerou suggestions. Step 2 (audit-review) deve ter passado por
aprovação humana (task.approved_at not null no Step 2).

Output:
    {
      "applied": N,
      "failed": N,
      "duplicates_removed": N,
      "details": [
        {"data": "...", "valor_centavos": N, "action": "recategorize",
         "from": {"cat": "...", "sub": "..."}, "to": {...}, "status": "ok"|"error"},
        ...
      ]
    }

Dispatched por src/agent_daemon.py quando operation_type='planner-apply-corrections'.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.agents.kronos_browser import KronosPlannerSession

logger = logging.getLogger("KronosApplyCorrections")


def entrypoint_apply_corrections(task: dict, supabase_client: Any) -> dict:
    """Handler sync chamado pelo agent_daemon."""
    try:
        return asyncio.run(_run_apply_async(task, supabase_client))
    except Exception as exc:
        logger.exception("entrypoint_apply_corrections falhou")
        return {
            "status": "errored",
            "error": str(exc),
            "output_json": {
                "error_detail": {
                    "message": str(exc),
                    "exception": type(exc).__name__,
                }
            },
        }


async def _run_apply_async(task: dict, supabase_client: Any) -> dict:
    """Flow real. TODO: implementar em PR subsequente.

    Etapas previstas:
    1. Resolver suggestions do parent_task.output_json (via Step 2 que herdou Step 1)
    2. Validar aprovação: parent (Step 2 audit-review) tem approved_at != null
    3. Pra cada sugestão:
       a. Tipo=recategorize: edita Excel + abre lançamento no Planner via Playwright
          e altera categoria/subcategoria
       b. Tipo=remove_duplicate: deleta lançamento no Planner (botão lixeira)
    4. Reusa KronosPlannerSession + helpers de categorize (selects estáveis)
    5. Output estruturado com per-item status
    """
    task_id = task.get("id", "unknown")
    parent_task_id = task.get("parent_task_id")

    if not parent_task_id or supabase_client is None:
        return {
            "status": "errored",
            "error": "task sem parent_task_id ou supabase indisponível — não é possível ler suggestions",
        }

    # TODO: implementar busca do Step 1 sibling (audit-historico) +
    # validação de aprovação no Step 2 audit-review.

    logger.info("task=%s: apply corrections — TODO completo", task_id)

    return {
        "status": "done",
        "output_json": {
            "applied": 0,
            "failed": 0,
            "duplicates_removed": 0,
            "details": [],
            "skeleton": "handler pendente de implementação — Task #21",
        },
    }
