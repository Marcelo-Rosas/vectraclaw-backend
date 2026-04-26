from typing import List, Dict, Any
from datetime import datetime

def calculate_sipoc_kpis(processes: List[Dict[str, Any]], components: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Gera métricas analíticas sobre o ecossistema de processos.
    """
    total_processes = len(processes)
    if total_processes == 0: return {}
    
    # Status distribution
    status_counts = {"rascunho": 0, "em_revisao": 0, "aprovado": 0}
    for p in processes:
        status = p.get('status', 'rascunho')
        status_counts[status] = status_counts.get(status, 0) + 1
        
    # Consistency analysis
    # (Mock para o exemplo, no real cruzaríamos com o motor de validação)
    avg_consistency = 78.5 
    
    # Setores mais ativos
    sector_distribution = {}
    for p in processes:
        s_name = p.get('sector_name', 'Geral')
        sector_distribution[s_name] = sector_distribution.get(s_name, 0) + 1

    return {
        "summary": {
            "total_processes": total_processes,
            "avg_consistency": f"{avg_consistency}%",
            "approved_rate": f"{(status_counts.get('aprovado', 0) / total_processes) * 100:.1f}%",
            "pending_alerts": 12 # Exemplo
        },
        "charts": {
            "status": [
                {"name": "Rascunho", "value": status_counts.get('rascunho', 0)},
                {"name": "Em Revisão", "value": status_counts.get('em_revisao', 0)},
                {"name": "Aprovado", "value": status_counts.get('aprovado', 0)}
            ],
            "sectors": [{"sector": k, "count": v} for k, v in sector_distribution.items()]
        }
    }
