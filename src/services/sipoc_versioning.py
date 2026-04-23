# Engine de Versionamento e Auditoria SIPOC
# Objetivo: Garantir rastreabilidade e governança de dados

def create_process_snapshot(process_id, components, user_id):
    """
    Cria um snapshot completo do estado atual do processo.
    """
    snapshot = {
        "process_id": process_id,
        "version": None, # Será auto-incrementado no banco
        "data": components,
        "created_by": user_id,
        "change_summary": "Nova versão gerada após revisão."
    }
    # Aqui entraria a lógica de inserção na tabela de histórico
    return snapshot

def diff_versions(v1_data, v2_data):
    """
    Retorna a diferença entre duas versões do SIPOC (Diff Visual).
    """
    # Comparação simples de componentes
    additions = [c for c in v2_data if c not in v1_data]
    removals = [c for c in v1_data if c not in v2_data]
    
    return {
        "adicionado": additions,
        "removido": removals
    }
