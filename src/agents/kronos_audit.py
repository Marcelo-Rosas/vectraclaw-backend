"""
Kronos Audit Histórico — handler do `operation_type='kronos-audit-historico'`.

Task #18 (sessão 2026-05-14). Workflow `kronos-audit-historico` Step 1.

Cruza 3 fontes (CSV export Planner × PDF C6 × OFX) para detectar:
1. Anomalias de categorização — linha tem categoria divergente da regra YAML
2. Duplicatas — múltiplas linhas com mesma (data, valor, descrição enriquecida)

Output (em task.output_json):
    {
      "mes_alvo": "2026-01",
      "stats": {"total_lancamentos": N, "anomalies": N, "duplicates": N},
      "anomalies": [
        {
          "data": "2026-01-15",
          "valor_centavos": -8734900,
          "descricao_atual": "Pix enviado para X",
          "categoria_atual": "Despesas Pessoais",
          "categoria_sugerida": "Movimentações Internas",
          "subcategoria_sugerida": "Transferência entre C/C",
          "razao": "regra YAML mapeia VECTRA HUB para Movimentações Internas"
        },
        ...
      ],
      "duplicates": [
        {"key": ["2026-01-15", -8734900], "count": 2, "ids": [...]},
        ...
      ],
      "suggestions": [ ... ]  # mescla de anomalies + duplicates ranked por confiança
    }

Step 2 (audit-review) lê esse output e fica em backlog até aprovação humana.
Step 3 (planner-apply-corrections) aplica `suggestions` após aprovação.

Dispatched por src/agent_daemon.py quando operation_type='kronos-audit-historico'.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from src.agents.kronos import resolve_kronos_inputs
from src.agents.kronos_categorizer import load_rules, match_rule
from src.agents.kronos_pdf_enricher import build_pdf_lookup, parse_c6_pdf

logger = logging.getLogger("KronosAudit")

_DEFAULT_RULES_PATH = Path(__file__).parent / "kronos_category_rules.yaml"


def entrypoint_kronos_audit(task: dict, supabase_client: Any) -> dict:
    """Handler sync chamado pelo agent_daemon."""
    try:
        return asyncio.run(_run_audit_async(task, supabase_client))
    except Exception as exc:
        logger.exception("entrypoint_kronos_audit falhou")
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


async def _run_audit_async(task: dict, supabase_client: Any) -> dict:
    """Flow real. TODO: implementar a lógica completa em PRs subsequentes.

    Etapas previstas:
    1. Resolver inputs: mes_alvo + 3 paths (csv_dir, ofx_dir, pdf_dir)
    2. Localizar arquivos: lancamentos-YYYY-MM.csv, OFX do período, PDF mais recente
    3. Carregar PDF lookup (reusa build_pdf_lookup de kronos_pdf_enricher)
    4. Parser CSV → lista de lançamentos com (data, valor, categoria_atual, descricao)
    5. Pra cada linha CSV:
       a. Enriquece descrição via PDF lookup (data + valor)
       b. Aplica match_rule(desc_enriquecida) → categoria_sugerida
       c. Se categoria_atual != categoria_sugerida → adiciona em anomalies
    6. Cluster por (data, valor) → grupos com count > 1 são duplicates
    7. Output estruturado
    """
    task_id = task.get("id", "unknown")
    inputs = resolve_kronos_inputs(task)

    mes_alvo = (
        inputs.get("MES_ALVO")
        or (task.get("_resolved_config") or {}).get("mes_alvo")
        or ""
    ).strip()
    if not re.match(r"^\d{4}-\d{2}$", mes_alvo):
        return {
            "status": "errored",
            "error": f"mes_alvo inválido: {mes_alvo!r} (formato esperado YYYY-MM)",
        }

    logger.info("task=%s: audit histórico mes_alvo=%s — TODO completo", task_id, mes_alvo)

    # TODO: implementar
    return {
        "status": "done",
        "output_json": {
            "mes_alvo": mes_alvo,
            "stats": {"total_lancamentos": 0, "anomalies": 0, "duplicates": 0},
            "anomalies": [],
            "duplicates": [],
            "suggestions": [],
            "skeleton": "handler pendente de implementação — Task #20",
        },
    }
