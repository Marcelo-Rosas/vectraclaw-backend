from typing import List, Dict, Any
from uuid import UUID

def validate_sipoc_consistency(components: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Executa as regras de validação cruzada R1-R6.
    """
    issues = []
    
    # Separar componentes por tipo para facilitar busca
    suppliers = [c for c in components if c['type'] == 'supplier']
    inputs = [c for c in components if c['type'] == 'input']
    activities = [c for c in components if c['type'] == 'activity']
    outputs = [c for c in components if c['type'] == 'output']
    customers = [c for c in components if c['type'] == 'customer']
    
    # Helper: extrair nomes para comparação
    def get_name(c): return (c.get('content') or {}).get('name', '').lower().strip()
    
    # R1: Todo Input vinculado a Supplier (na nossa estrutura, assumimos que se há inputs, deve haver fornecedores)
    if inputs and not suppliers:
        issues.append({
            "level": "yellow",
            "rule": "R1",
            "message": "Existem Entradas (Inputs) mas nenhum Fornecedor (Supplier) foi mapeado.",
            "suggestion": "Adicione quem fornece esses insumos."
        })
        
    # R2: Todo Output vinculado a Customer
    if outputs and not customers:
        issues.append({
            "level": "red",
            "rule": "R2",
            "message": "Existem Saídas (Outputs) sem Clientes definidos.",
            "suggestion": "Mapeie quem recebe o valor gerado por este processo."
        })
        
    # R3 & R4: Atividades consomem Inputs
    if activities:
        if not inputs:
            issues.append({
                "level": "yellow",
                "rule": "R3",
                "message": "Atividades mapeadas mas nenhuma entrada (Input) definida.",
                "suggestion": "O que a atividade processa? Adicione inputs."
            })
            
    # R5: Outputs sem origem
    if outputs and not activities:
        issues.append({
            "level": "red",
            "rule": "R5",
            "message": "Existem Saídas (Outputs) mas nenhuma atividade foi definida para gerá-las.",
            "suggestion": "Mapeie as atividades do 'P' (Process) que resultam nessas saídas."
        })
        
    # R6: WHO do 5W2H deve bater com atores
    # (Poderíamos validar se o 'who' nas atividades existe nos cargos da empresa)
    for act in activities:
        content = act.get('content', {})
        who = content.get('who', '').lower()
        if not who:
             issues.append({
                "level": "yellow",
                "rule": "R6",
                "message": f"Atividade '{content.get('name')}' não tem responsável (Who) definido.",
                "suggestion": "Defina quem executa esta tarefa no 5W2H."
            })

    # Cálculo do Score de Consistência
    total_rules = 6
    fail_count = len([i for i in issues if i['level'] == 'red'])
    warn_count = len([i for i in issues if i['level'] == 'yellow'])
    
    # Score de 0 a 100
    consistency_score = max(0, 100 - (fail_count * 20) - (warn_count * 5))
    
    return {
        "score": consistency_score,
        "issues": issues,
        "is_valid": fail_count == 0
    }
