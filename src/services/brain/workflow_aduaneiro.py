"""
VEC-187 – Workflow aduaneiro padrão da Vectra Cargo.

Define as etapas, regras de negócio e critérios de decisão do fluxo
de importação marítima desde o recebimento dos documentos até a
liberação aduaneira e notificação ao cliente.

Serve como fonte de verdade para o System Prompt do Orquestrador e
para a API GET /api/agent/workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

WORKFLOW_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Dados de apoio – regras de negócio
# ---------------------------------------------------------------------------

INCOTERMS = {
    "FOB": "Free On Board – vendedor responsável até o porto de origem.",
    "CIF": "Cost, Insurance and Freight – vendedor inclui frete e seguro até destino.",
    "EXW": "Ex Works – comprador assume toda a logística a partir da fábrica.",
    "DDP": "Delivered Duty Paid – vendedor entrega já desembaraçado no destino.",
    "CPT": "Carriage Paid To – frete pago até destino, risco passa na entrega ao transportador.",
}

CONTAINER_SPECS = {
    "20DC": {"teus": 1, "vol_cbm": 33.2,  "payload_kg": 28_180, "desc": "20 pés Dry Container"},
    "40DC": {"teus": 2, "vol_cbm": 67.7,  "payload_kg": 26_680, "desc": "40 pés Dry Container"},
    "40HC": {"teus": 2, "vol_cbm": 76.4,  "payload_kg": 26_330, "desc": "40 pés High Cube"},
    "20RF": {"teus": 1, "vol_cbm": 28.0,  "payload_kg": 27_700, "desc": "20 pés Reefer"},
    "40RF": {"teus": 2, "vol_cbm": 59.3,  "payload_kg": 29_300, "desc": "40 pés Reefer"},
}

PORTOS_VECTRA = {
    "BRNVT": {"nome": "Porto de Navegantes", "uf": "SC", "armadores": ["MSC", "Evergreen", "CMA CGM"]},
    "BRITJ": {"nome": "Porto de Itajaí",    "uf": "SC", "armadores": ["MSC", "Maersk", "Hapag-Lloyd"]},
    "BRSSZ": {"nome": "Porto de Santos",     "uf": "SP", "armadores": ["*todos*"]},
}

DOCUMENTOS_IMPORTACAO = [
    "BL (Bill of Lading) – original ou telex release",
    "Commercial Invoice (Fatura Comercial)",
    "Packing List",
    "Certificado de Origem (quando aplicável por acordo bilateral)",
    "LI – Licença de Importação (produtos sujeitos a controle)",
    "DI – Declaração de Importação (gerada no SISCOMEX após canais)",
    "Nota Fiscal de Entrada (emitida após DI parametrizada)",
]

CANAIS_SISCOMEX = {
    "VERDE":    "Desembaraço automático sem conferência física ou documental.",
    "AMARELO":  "Conferência documental pelo auditor fiscal.",
    "VERMELHO": "Conferência física + documental.",
    "CINZA":    "Conferência de valor aduaneiro (subfaturamento suspeito).",
}

TOLERANCIAS = {
    "peso_variacao_pct": 2.0,    # variação aceitável entre BL e PL em %
    "cbm_variacao_pct":  3.0,    # variação aceitável em CBM
    "janela_livre_dias": 3,       # dias de armazenagem livre no terminal
    "prazo_di_dias":     5,       # prazo ideal para abrir DI após chegada do navio
}


# ---------------------------------------------------------------------------
# Etapas do workflow
# ---------------------------------------------------------------------------

@dataclass
class WorkflowStep:
    id: str
    nome: str
    descricao: str
    responsavel: str           # "agente" | "humano" | "sistema"
    ferramentas: list[str]     # tools do TOOLS_REGISTRY usadas nesta etapa
    entrada: list[str]         # o que é necessário para iniciar
    saida: list[str]           # o que é produzido
    decisoes: list[str]        # bifurcações / critérios
    proximo: list[str]         # ids das próximas etapas possíveis
    alertas: list[str] = field(default_factory=list)


WORKFLOW_STEPS: list[WorkflowStep] = [
    WorkflowStep(
        id="W1",
        nome="Recebimento de Documentos",
        descricao=(
            "Receber BL e Packing List do embarcador ou agente de carga. "
            "Verificar se os arquivos são PDFs legíveis."
        ),
        responsavel="agente",
        ferramentas=[],
        entrada=["PDF do BL", "PDF do Packing List"],
        saida=["Arquivos validados prontos para OCR"],
        decisoes=["PDF ilegível → solicitar reenvio", "Apenas BL → prosseguir sem cruzamento"],
        proximo=["W2"],
        alertas=["Atenção ao telex release – confirmar liberação do BL junto ao armador"],
    ),
    WorkflowStep(
        id="W2",
        nome="OCR e Extração de Dados",
        descricao=(
            "Extrair dados estruturados do BL e do Packing List via OCR. "
            "Identificar: nº BL, embarcador, consignatário, navio, portos, containers, pesos."
        ),
        responsavel="agente",
        ferramentas=["extract_bl_pl"],
        entrada=["PDF do BL", "PDF do Packing List"],
        saida=["BL data dict", "PL data dict", "Lista de containers", "Pesos e CBM brutos"],
        decisoes=[
            "Extração falhou → escalar para humano com msg de erro",
            "doc_type=unknown → solicitar documento correto",
        ],
        proximo=["W3"],
    ),
    WorkflowStep(
        id="W3",
        nome="Cruzamento BL x Packing List",
        descricao=(
            "Comparar os dados extraídos do BL com o Packing List. "
            "Verificar containers, pesos e CBM dentro das tolerâncias definidas."
        ),
        responsavel="agente",
        ferramentas=["extract_bl_pl", "calculate_cbm"],
        entrada=["BL data dict", "PL data dict"],
        saida=["Relatório de consistência", "Lista de divergências"],
        decisoes=[
            f"Peso BL vs PL diverge > {TOLERANCIAS['peso_variacao_pct']}% → gerar alerta de inconsistência",
            f"CBM BL vs PL diverge > {TOLERANCIAS['cbm_variacao_pct']}% → verificar medidas no PL",
            "Containers no BL ausentes no PL → escalar para conferência",
            "Tudo dentro da tolerância → prosseguir para DI",
        ],
        proximo=["W4", "W4_ALERTA"],
    ),
    WorkflowStep(
        id="W4_ALERTA",
        nome="Notificação de Divergência",
        descricao=(
            "Divergência detectada entre BL e PL. "
            "Notificar responsável via WhatsApp com resumo das inconsistências."
        ),
        responsavel="agente",
        ferramentas=["send_whatsapp_webhook"],
        entrada=["Lista de divergências", "Contato do responsável"],
        saida=["Confirmação de entrega da notificação WhatsApp"],
        decisoes=[
            "Responsável confirma correção → retornar para W3",
            "Responsável autoriza prosseguir mesmo com divergência → W4 com flag de ressalva",
        ],
        proximo=["W3", "W4"],
        alertas=["Usar template 'divergencia_bl_pl' para mensagem proativa"],
    ),
    WorkflowStep(
        id="W4",
        nome="Abertura de DI no SISCOMEX",
        descricao=(
            "Com documentos consistentes, orientar abertura da Declaração de Importação. "
            f"Prazo ideal: até {TOLERANCIAS['prazo_di_dias']} dias corridos após chegada do navio."
        ),
        responsavel="humano",
        ferramentas=[],
        entrada=["BL data validado", "PL data validado", "NCM das mercadorias", "Invoice"],
        saida=["Número da DI", "Canal de parametrização SISCOMEX"],
        decisoes=[
            "Canal VERDE → avançar para W5 direto",
            "Canal AMARELO → aguardar conferência documental",
            "Canal VERMELHO → agendar vistoria física",
            "Canal CINZA → preparar dossiê de valoração aduaneira",
        ],
        proximo=["W5"],
    ),
    WorkflowStep(
        id="W5",
        nome="Acompanhamento de Canal e Liberação",
        descricao=(
            "Monitorar status da DI no SISCOMEX e acompanhar canal de parametrização. "
            "Coordenar com despachante aduaneiro para regularizações necessárias."
        ),
        responsavel="humano",
        ferramentas=["send_whatsapp_webhook"],
        entrada=["Número da DI", "Canal SISCOMEX", "Contato do despachante"],
        saida=["DI desembaraçada", "Comprovante de pagamento de impostos"],
        decisoes=[
            "DI desembaraçada → avançar para W6",
            "Exigência fiscal → providenciar documentação adicional e reapresentar",
        ],
        proximo=["W6"],
    ),
    WorkflowStep(
        id="W6",
        nome="Retirada do Terminal e Entrega",
        descricao=(
            f"DI desembaraçada. Retirar container do terminal dentro da armazenagem livre "
            f"({TOLERANCIAS['janela_livre_dias']} dias). Coordenar transporte até o destino final."
        ),
        responsavel="agente",
        ferramentas=["send_whatsapp_webhook"],
        entrada=["DI desembaraçada", "Gate pass do terminal", "Endereço de entrega"],
        saida=["Comprovante de entrega", "Devolução de container vazio"],
        decisoes=[
            "Entrega confirmada → encerrar processo e notificar cliente",
            "Avaria no container → registrar boletim de ocorrência e acionar seguro",
        ],
        proximo=["W7"],
    ),
    WorkflowStep(
        id="W7",
        nome="Encerramento e Arquivo",
        descricao=(
            "Processo concluído. Arquivar todos os documentos, fechar OS, "
            "notificar cliente com resumo e solicitar feedback."
        ),
        responsavel="agente",
        ferramentas=["send_whatsapp_webhook"],
        entrada=["Comprovante de entrega", "Todos os documentos do processo"],
        saida=["OS encerrada", "Relatório final para o cliente"],
        decisoes=["Pendência financeira → encaminhar para cobrança antes de arquivar"],
        proximo=[],
    ),
]

# Índice rápido por id
STEPS_BY_ID: dict[str, WorkflowStep] = {s.id: s for s in WORKFLOW_STEPS}


# ---------------------------------------------------------------------------
# Serialização para JSON / API
# ---------------------------------------------------------------------------

def workflow_to_dict() -> dict:
    """Serializa o workflow completo para JSON."""
    return {
        "version": WORKFLOW_VERSION,
        "nome": "Workflow Aduaneiro Padrão — Importação Marítima",
        "empresa": "Vectra Cargo",
        "portos_atuacao": list(PORTOS_VECTRA.keys()),
        "tolerancias": TOLERANCIAS,
        "canais_siscomex": CANAIS_SISCOMEX,
        "documentos_necessarios": DOCUMENTOS_IMPORTACAO,
        "incoterms_suportados": list(INCOTERMS.keys()),
        "container_specs": CONTAINER_SPECS,
        "etapas": [
            {
                "id": s.id,
                "nome": s.nome,
                "descricao": s.descricao,
                "responsavel": s.responsavel,
                "ferramentas": s.ferramentas,
                "entrada": s.entrada,
                "saida": s.saida,
                "decisoes": s.decisoes,
                "proximo": s.proximo,
                "alertas": s.alertas,
            }
            for s in WORKFLOW_STEPS
        ],
    }
