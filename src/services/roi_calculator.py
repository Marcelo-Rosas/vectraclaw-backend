# Engine de Cálculo de ROI e Score de Automação
# Objetivo: Quantificar o valor da consultoria VectraClip

def calculate_automation_potential(activity_content):
    """
    Calcula o score de automação (0-100) baseado na Vectra Automation Rubric v1.
    Recebe o dicionário 'content' de uma SipocComponent do tipo 'activity'.
    """
    score = 0
    
    # 1. Repetitividade (Max 40)
    how = activity_content.get('how', '').lower()
    if any(word in how for word in ["procedimento", "padrão", "repetitivo", "fixo", "sempre"]):
        score += 40
    elif "manual" in how:
        score += 10
        
    # 2. Volume Diário / Frequência (Max 15)
    when = activity_content.get('when', '').lower()
    if any(word in when for word in ["diário", "todo dia", "hora", "minuto", "frequente"]):
        score += 15
    elif "semanal" in when:
        score += 7
        
    # 3. Criticidade Financeira (Max 15)
    how_much = activity_content.get('how_much', '').lower() # Aceita snake_case do Python
    if any(word in how_much for word in ["caro", "alto custo", "multa", "prejuízo", "$", "receita"]):
        score += 15
        
    # 4. Penalidades (Ambiguidade e Julgamento)
    if any(word in how for word in ["subjetivo", "depende", "análise humana", "julgamento"]):
        score -= 20
        
    if "aprovação física" in how or "assinatura" in how:
        score -= 10

    return max(0, min(100, score))

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
