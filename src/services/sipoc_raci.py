from typing import List, Dict, Any
from uuid import UUID

def calculate_raci_stats(matrix_data: List[Dict[str, Any]], positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analisa a matriz RACI em busca de gargalos e inconsistências.
    """
    stats = {
        "overloaded_positions": [], # Cargos com muitos R's
        "missing_accountable": [],  # Atividades sem um A
        "multiple_accountable": [], # Atividades com mais de um A
    }
    
    # Agrupar por atividade (component_id)
    by_activity = {}
    by_position = {}
    
    for entry in matrix_data:
        comp_id = entry['component_id']
        pos_id = entry['position_id']
        role = entry['role']
        
        if comp_id not in by_activity: by_activity[comp_id] = []
        by_activity[comp_id].append(role)
        
        if pos_id not in by_position: by_position[pos_id] = 0
        if role == 'R': by_position[pos_id] += 1

    # Validar A's (Accountable)
    for comp_id, roles in by_activity.items():
        a_count = roles.count('A')
        if a_count == 0: stats["missing_accountable"].append(comp_id)
        if a_count > 1: stats["multiple_accountable"].append(comp_id)
        
    # Identificar sobrecarga (> 3 R's por cargo em um único processo é um alerta)
    for pos_id, r_count in by_position.items():
        if r_count > 3:
            pos_name = next((p['title'] for p in positions if p['id'] == pos_id), "Cargo Desconhecido")
            stats["overloaded_positions"].append({"name": pos_name, "count": r_count})
            
    return stats
