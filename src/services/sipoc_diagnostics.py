from typing import List, Dict, Any
import re

DIAGNOSTIC_PATTERNS = [
    {
        "id": "repetitive_task",
        "pattern": r"(?i)(planilha|manual|caderno|digito|copio)",
        "label": "Tarefa Repetitiva",
        "severity": "medium",
        "diagnosis": "Dependência de entrada manual de dados, aumentando o risco de erro humano.",
        "solution": "Automação via RPA ou Integração API entre CRM e ERP.",
        "impact": "Perda estimada de 2h/mês por operador em tarefas de baixo valor.",
        "base_risk_value": 2000
    },
    {
        "id": "operational_bottleneck",
        "pattern": r"(?i)(atrasa|demora|fulano|esperando|gargalo)",
        "label": "Gargalo Operacional",
        "severity": "high",
        "diagnosis": "Ponto único de falha humana gerando ociosidade em toda a cadeia.",
        "solution": "Workflow com SLAs automáticos e escalonamento de pendências.",
        "impact": "Aumento no Lead Time e risco de perda de janelas de carga.",
        "base_risk_value": 5000
    },
    {
        "id": "antt_floor_violation",
        "pattern": r"(?i)(valor|frete|pago|cobrado).*?(R\$?\s?\d+)",
        "label": "Violação MP 1.343/2026",
        "severity": "critical",
        "diagnosis": "O valor mencionado pode estar abaixo do piso mínimo obrigatório da ANTT para esta rota.",
        "solution": "Utilizar o motor de cálculo do CRM (SQL Supabase) para validar o frete antes da emissão.",
        "impact": "Multa de 2x a diferença entre o valor pago e o piso mínimo (ANTT).",
        "base_risk_value": 15000
    },
    {
        "id": "fiscal_insurance_engineering",
        "pattern": r"(?i)(seguro|100%|totalidade).*?(receita|faturamento|fiscal)",
        "label": "Engenharia Fiscal de Alto Risco",
        "severity": "critical",
        "diagnosis": "A classificação de 100% da receita como 'Seguro' é considerada fraude fiscal.",
        "solution": "Segregar corretamente Frete Peso, Frete Valor e GRIS conforme a apólice Berkley.",
        "impact": "Multas de até 150% do imposto omitido e risco criminal.",
        "base_risk_value": 50000
    },
    {
        "id": "missing_ciot_vpo",
        "pattern": r"(?i)(sem|não|esquece).*?(CIOT|VPO|Vale Pedágio)",
        "label": "Ausência de CIOT/VPO",
        "severity": "high",
        "diagnosis": "A falta de CIOT e Vale Pedágio Obrigatório é um gatilho para fiscalização da ANTT.",
        "solution": "Integrar a emissão do MDF-e com a geração automática de CIOT/VPO.",
        "impact": "Multa administrativa de R$ 550 a R$ 10.500 por viagem.",
        "base_risk_value": 5500
    },
    {
        "id": "idle_time_risk",
        "pattern": r"(?i)(espera|descarga|cliente|demora).*?(não cobra|cortesia|livre)",
        "label": "Risco de Estadia Não Cobrada",
        "severity": "medium",
        "diagnosis": "A legislação obriga o pagamento de estadia após 5h de espera.",
        "solution": "Implementar controle dinâmico de Check-in/Check-out via CRM.",
        "impact": "Indenização de R$ 2,21 por tonelada/hora (Lei 11.442).",
        "base_risk_value": 2500
    },
    {
        "id": "missing_pod_risk",
        "pattern": r"(?i)(entrega|chegada|finaliza).*?(sem|não).*?(canhoto|comprovante|pod)",
        "label": "Risco de Glosa (Falta de POD)",
        "severity": "high",
        "diagnosis": "A falta de registro digital do canhoto (POD) impede a comprovação da entrega para faturamento.",
        "solution": "Automatizar a captura de POD via App do Motorista integrado ao CRM.",
        "impact": "Atraso no recebimento do frete e risco de não pagamento pelo cliente.",
        "base_risk_value": 12000
    },
    {
        "id": "toll_discrepancy_risk",
        "pattern": r"(?i)(pedágio|vpo).*?(acerto|diferença|conferência)",
        "label": "Divergência de Pedágio Real",
        "severity": "medium",
        "diagnosis": "Não há um processo claro de conciliação entre o pedágio previsto e o pedagio_real pago na rota.",
        "solution": "Utilizar o módulo de conciliação automática de VPO do CRM.",
        "impact": "Vazamento de margem operacional (custo invisível).",
        "base_risk_value": 1500
    },
    {
        "id": "mdfe_omission_risk",
        "pattern": r"(?i)(inicia|viagem|estrada).*?(sem|esquece).*?(MDF-e|manifesto)",
        "label": "Risco de Apreensão (Sem MDF-e)",
        "severity": "critical",
        "diagnosis": "Iniciar o transporte sem o MDF-e autorizado é infração gravíssima.",
        "solution": "Bloqueio sistêmico: o status da Ordem só muda para 'Em Viagem' com MDF-e validado.",
        "impact": "Multas pesadas e retenção do veículo em postos fiscais.",
        "base_risk_value": 35000
    }
]

def diagnose_text(text: str, sector: str = "general") -> List[Dict]:
    """
    Analisa um texto em busca de padrões de risco logístico e fiscal.
    """
    findings = []
    
    for pattern in DIAGNOSTIC_PATTERNS:
        if re.search(pattern["pattern"], text):
            finding = pattern.copy()
            # Lógica para detecção dinâmica de contexto logístico (KM/Eixos)
            if "km" in text.lower() or "eixo" in text.lower():
                finding["diagnosis"] += " [DETECÇÃO DINÂMICA DE ROTA ATIVA]"
            
            findings.append(finding)
            
    return findings

run_diagnostic = diagnose_text
