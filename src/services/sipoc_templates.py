from typing import List, Dict, Any

SIPOC_TEMPLATES = {
    "logistica": {
        "name": "Gestão de Fretes e Cargas",
        "sector": "Logística",
        "description": "Mapeamento padrão para contratação e monitoramento de fretes rodoviários.",
        "components": [
            {"type": "supplier", "content": {"name": "Embarcador / Cliente"}},
            {"type": "input", "content": {"name": "Ordem de Carga / XML"}},
            {"type": "activity", "content": {
                "name": "Cotação de Frete", 
                "what": "Buscar melhor preço no mercado", 
                "logicPattern": "SPLIT",
                "automationScore": 85
            }},
            {"type": "output", "content": {"name": "Tabela de Frete Aprovada"}},
            {"type": "customer", "content": {"name": "Transportadora / Motorista"}}
        ]
    },
    "financeiro": {
        "name": "Contas a Pagar",
        "sector": "Financeiro",
        "description": "Fluxo de aprovação e liquidação de faturas de fornecedores.",
        "components": [
            {"type": "supplier", "content": {"name": "Fornecedores de Insumos"}},
            {"type": "input", "content": {"name": "Nota Fiscal / Boleto"}},
            {"type": "activity", "content": {
                "name": "Conciliação Bancária", 
                "what": "Validar extrato vs ERP", 
                "logicPattern": "LOOP-ITEM",
                "automationScore": 95
            }},
            {"type": "output", "content": {"name": "Comprovante de Pagamento"}},
            {"type": "customer", "content": {"name": "Contabilidade / Fiscal"}}
        ]
    }
}

def get_templates_list() -> List[Dict[str, Any]]:
    return [
        {"id": k, "name": v["name"], "sector": v["sector"], "description": v["description"]}
        for k, v in SIPOC_TEMPLATES.items()
    ]

def get_template_detail(template_id: str) -> Dict[str, Any]:
    return SIPOC_TEMPLATES.get(template_id)
