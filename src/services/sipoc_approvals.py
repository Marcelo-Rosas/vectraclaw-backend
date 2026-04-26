from typing import List, Dict, Any
from datetime import datetime
import json

def handle_status_transition(current_status: str, action: str) -> str:
    """
    Define as transições de estado do workflow de aprovação RACI.
    """
    transitions = {
        ("rascunho", "submit"): "em_revisao",
        ("em_revisao", "approve"): "aprovado",
        ("em_revisao", "reject"): "rascunho",
        ("aprovado", "edit"): "rascunho" # Ao editar um aprovado, ele volta pra rascunho
    }
    return transitions.get((current_status, action), current_status)

def generate_audit_log(user_id: str, action: str, details: str) -> Dict[str, Any]:
    return {
        "user_id": user_id,
        "action": action,
        "details": details,
        "timestamp": datetime.now().isoformat()
    }
