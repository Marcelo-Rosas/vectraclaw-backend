"""
Kronos Apply Corrections — handler do `operation_type='planner-apply-corrections'`.

Aplica sugestões (vindas do sibling task `planner-categorize-pendings`).
Lançamentos no Planner via Playwright — re-categoriza inline.

Output:
    {
      "applied": N,
      "failed": N,
      "details": [
        ...
      ]
    }
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.agents.kronos_browser import KronosPlannerSession
from src.agents.kronos_planner import (
    PLANNER_LANCAMENTOS_URL,
    _wait_for_lancamentos_populated,
    _maximize_rows_per_page,
    _apply_categorization_to_row,
    _read_row_data,
    MatchResult,
    _EDIT_ROW_SELECTOR,
    _LANCAMENTOS_TABLE_SELECTOR
)

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
    task_id = task.get("id", "unknown")
    parent_task_id = task.get("parent_task_id")

    if not parent_task_id or supabase_client is None:
        return {
            "status": "errored",
            "error": "task sem parent_task_id ou supabase indisponível",
        }

    # 1. Buscar o sibling task (categorize-pendings)
    res = supabase_client.table("tasks").select("output_json").eq("parent_task_id", parent_task_id).eq("operation_type", "planner-categorize-pendings").order("created_at", desc=True).limit(1).execute()
    if not res.data:
        return {
            "status": "errored",
            "error": "Sibling task planner-categorize-pendings não encontrado",
        }
    
    categorize_output = res.data[0].get("output_json", {})
    details = categorize_output.get("categorization", {}).get("details", [])

    if not details:
        logger.info("Nenhuma sugestão encontrada em categorize-pendings.")
        return {
            "status": "done",
            "output_json": {"applied": 0, "failed": 0, "details": []}
        }

    valid_details = [d for d in details if "categoria" in d and "subcategoria" in d]
    skipped_details = [d for d in details if d.get("action") == "skipped" or "categoria" not in d]

    logger.info("task=%s: %d validas para aplicar, %d skipped", task_id, len(valid_details), len(skipped_details))

    stats = {
        "applied": 0,
        "failed": 0,
        "details": [],
        "errors": [],
        "unclassified_items": []
    }

    if valid_details:
        async with KronosPlannerSession() as session:
            page = session.page
            await page.goto(PLANNER_LANCAMENTOS_URL, wait_until="domcontentloaded")
            await _wait_for_lancamentos_populated(page)
            await _maximize_rows_per_page(page)
            
            for item in valid_details:
                target_desc = item.get("original_desc") or item.get("desc")
                # Procurar a linha pelo desc
                found = False
                rows = page.locator(f'{_LANCAMENTOS_TABLE_SELECTOR} tbody tr:not([data-kronos-applied])')
                count = await rows.count()
                
                for i in range(count):
                    row = rows.nth(i)
                    row_data = await _read_row_data(row)
                    if row_data["desc"] == target_desc:
                        # Marcar a linha temporariamente para evitar pegá-la de novo
                        await row.evaluate("(el) => el.setAttribute('data-kronos-applied', 'true')")
                        
                        match_res = MatchResult(
                            categoria=item["categoria"],
                            subcategoria=item["subcategoria"],
                            rule_name="from-step-2",
                            priority=1
                        )
                        try:
                            await _apply_categorization_to_row(session, row, match_res)
                            stats["applied"] += 1
                            item["status"] = "applied"
                            stats["details"].append(item)
                            found = True
                        except Exception as exc:
                            logger.warning("Falha ao aplicar %s: %s", target_desc, exc)
                            item["status"] = "failed"
                            item["error"] = str(exc)
                            stats["failed"] += 1
                            stats["errors"].append(item)
                            stats["details"].append(item)
                            
                            # Cancelar se ficou preso na tela de edição
                            try:
                                cancel = page.locator(f'{_EDIT_ROW_SELECTOR} button[type="button"]').first
                                if await cancel.count() > 0:
                                    await cancel.click(timeout=2_000)
                            except Exception:
                                pass
                        break
                
                if not found:
                    logger.warning("Linha não encontrada para %s", target_desc)
                    item["status"] = "failed"
                    item["error"] = "Row not found in DOM"
                    stats["failed"] += 1
                    stats["errors"].append(item)
                    stats["details"].append(item)

    # Reportar skipped para o próximo step do workflow (Hermes Auditor)
    for item in skipped_details:
        item["status"] = "skipped"
        item["error"] = "Sem regra de categorização"
        stats["unclassified_items"].append({
            "description": item.get("original_desc") or item.get("desc"),
            "date": item.get("date", ""),
            "amount": item.get("amount", 0.0),
            "transaction_id": item.get("transaction_id", "")
        })
        stats["details"].append(item)

    # Não bloqueamos mais a task. O workflow UI conectará ao ofx-audit naturalmente.
    final_status = "done"

    return {
        "status": final_status,
        "output_json": stats,
    }
