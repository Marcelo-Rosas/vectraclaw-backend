"""Plutus — Agente Auditor Financeiro.

Responsável por analisar DREs Operacionais, detectar vazamentos de custo
e comparar planejado vs realizado baseado nos dados do Cargo Flow Navigator.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from src.schemas.dre import DreTable, DreCanonicalRow

logger = logging.getLogger("Plutus")

def _analyze_dre_variances(rows: List[DreCanonicalRow]) -> List[str]:
    """Gera insights baseados nas variações da DRE."""
    insights = []
    
    # Encontrar as linhas críticas
    custos_diretos = next((r for r in rows if r.line_code == "custos_diretos"), None)
    resultado = next((r for r in rows if r.line_code == "resultado_liquido"), None)
    
    if custos_diretos and custos_diretos.variance_percent > 5.0:
        insights.append(
            f"⚠️ Alerta: Custos diretos estouraram em {custos_diretos.variance_percent:.1f}% "
            f"(R$ {custos_diretos.variance_value:.2f} acima do planejado)."
        )
        
    if resultado and resultado.variance_value < 0:
        insights.append(
            f"🚨 Margem comprometida: O resultado líquido real ficou R$ {abs(resultado.variance_value):.2f} "
            "abaixo do previsto."
        )
    elif resultado and resultado.variance_value > 0:
        insights.append(
            f"✅ Economia operacional: O resultado líquido real ficou R$ {resultado.variance_value:.2f} "
            "acima do previsto."
        )
        
    if not insights:
        insights.append("📊 DRE aderente ao previsto. Nenhuma variação crítica de custos detectada.")
        
    return insights

def handle_dre_audit(task: Dict[str, Any], supabase_client) -> Dict[str, Any]:
    """Entry point dispatchado por agent_daemon._execute_task quando
    op_type=='dre-audit'.
    """
    task_id = task.get("id", "?")
    input_json = task.get("input_json") or {}

    logger.info("Plutus dre-audit task=%s", task_id)
    
    raw_dre = input_json.get("dre_data")
    if not raw_dre:
        return {
            "status": "error",
            "output_text": "Falha: payload da DRE (dre_data) não fornecido na task.",
            "output_json": {"error": "missing_dre_data"},
            "log_excerpt": "Plutus falhou: dre_data ausente na task"
        }

    try:
        # Validação do Schema
        dre_table = DreTable.parse_obj(raw_dre)
        
        # Gerar insights
        insights = _analyze_dre_variances(dre_table.rows)
        
        response_text = "Análise DRE concluída:\n" + "\n".join(f"- {i}" for i in insights)
        
        return {
            "status": "done",
            "output_text": response_text,
            "output_json": {
                "handler": "plutus.dre_audit",
                "reference_date": dre_table.reference_date,
                "quote_code": dre_table.quote_code,
                "os_number": dre_table.os_number,
                "insights": insights,
                "dre_status": dre_table.status
            },
            "log_excerpt": f"Plutus concluiu análise DRE para OS {dre_table.os_number}"
        }

    except Exception as e:
        logger.exception("Plutus failed to parse DRE on task=%s", task_id)
        return {
            "status": "error",
            "output_text": f"Falha ao validar a estrutura da DRE: {str(e)}",
            "output_json": {"error": "schema_validation_failed", "details": str(e)},
            "log_excerpt": f"Plutus falhou ao validar DRE: {type(e).__name__}"
        }
