# Engine de Cálculo de ROI e Score de Automação
# Objetivo: Quantificar o valor da consultoria VectraClip

def calculate_automation_potential(activities):
    """
    Calcula o score de automação (0-100) baseado na estrutura 5W2H.
    """
    total_activities = len(activities)
    if total_activities == 0: return 0
    
    automation_points = 0
    for a in activities:
        content = a.get('content', {})
        # Regras de Decisão Claras? (High Automation Potential)
        if "procedimento" in content.get('how', '').lower():
            automation_points += 20
        # Frequência alta?
        if "diário" in content.get('when', '').lower() or "todo" in content.get('when', '').lower():
            automation_points += 30
            
    return min(100, (automation_points / total_activities) * 2)

def calculate_roi(hours_saved, hourly_rate, implementation_cost):
    """
    Retorna o ROI financeiro estimado.
    """
    savings = hours_saved * hourly_rate
    if implementation_cost == 0: return savings
    roi_percent = ((savings - implementation_cost) / implementation_cost) * 100
    return {
        "economia_anual": savings * 12,
        "payback_meses": implementation_cost / savings if savings > 0 else 0,
        "roi_percentual": roi_percent
    }
