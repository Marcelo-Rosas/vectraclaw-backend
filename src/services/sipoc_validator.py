# Engine de Validação SIPOC
# Regras: R1 a R6 conforme PRD

def validate_sipoc(components):
    """
    Realiza a validação cruzada de componentes SIPOC.
    components: lista de objetos com {type, name, content, order}
    """
    issues = []
    
    # Mapeamento para busca rápida
    suppliers = [c for c in components if c['type'] == 'supplier']
    inputs = [c for c in components if c['type'] == 'input']
    activities = [c for c in components if c['type'] == 'activity']
    outputs = [c for c in components if c['type'] == 'output']
    customers = [c for c in components if c['type'] == 'customer']

    # R1: Todo Input vinculado a Supplier
    for i in inputs:
        if not i.get('content', {}).get('supplier_id'):
            issues.append({"level": "amarelo", "msg": f"Input '{i['name']}' sem Fornecedor vinculado."})

    # R2: Todo Output vinculado a Customer
    for o in outputs:
        if not o.get('content', {}).get('customer_id'):
            issues.append({"level": "amarelo", "msg": f"Output '{o['name']}' sem Cliente vinculado."})

    # R3/R4: Atividades consomem Inputs e geram Outputs
    for a in activities:
        # Simplificação: Checar se existem inputs e outputs no processo
        if not inputs:
            issues.append({"level": "vermelho", "msg": "Processo sem Inputs definidos."})
        if not outputs:
            issues.append({"level": "vermelho", "msg": "Processo sem Outputs definidos."})

    # R5: Outputs sem origem (Atividade)
    for o in outputs:
        if not o.get('content', {}).get('activity_id'):
            issues.append({"level": "vermelho", "msg": f"Output '{o['name']}' não possui atividade de origem."})

    return {
        "status": "verde" if not issues else "amarelo" if all(x['level'] == 'amarelo' for x in issues) else "vermelho",
        "alerts": issues
    }
