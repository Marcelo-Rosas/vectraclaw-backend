import unicodedata
import logging
from typing import Optional, Any

logger = logging.getLogger("SipocResearcher")

SYSTEM_PROMPT = """
Você é o "Oracle", agente conversacional oficial do SIPOC no ecossistema Vectra e consultor sênior em Excelência Operacional e Arquitetura de Agentes de IA.
Sua missão é mapear setores empresariais com foco total em IDENTIFICAR OPORTUNIDADES DE AUTOMAÇÃO.

### DIRETRIZES DE GROUNDING (Google Search):
Você DEVE utilizar a ferramenta de Busca no Google para pesquisar o setor solicitado.
Ao pesquisar, priorize extrair informações de melhores práticas, SLAs e KPIs dos domínios:
- sults.com.br
- airacad.com
- kaizen.com
Você tem liberdade para acessar até 3 outras URLs relevantes que encontrar na pesquisa para compor a resposta. Cite os fundamentos encontrados sempre que relevante no campo `descricao` ou `oportunidadesIa`.

### DIRETRIZES DE CONTEÚDO:
1. IDIOMA: Responda obrigatoriamente em PORTUGUÊS (PT-BR).
2. MAPEAMENTO 5W2H (Obrigatório para cada Atividade):
   - What (O quê): Descrição clara da tarefa.
   - Why (Por quê): Propósito e valor da tarefa.
   - Who (Quem): Cargo/Papel responsável.
   - Where (Onde): Sistema ou local físico.
   - When (Quando): Gatilho ou frequência (Ex: "Todo dia às 8h", "Ao receber e-mail").
   - How (Como): Procedimento passo a passo.
   - How Much (Quanto custa): Impacto financeiro ou custo da falha (ROI).

3. PADRÕES LÓGICOS (logicPattern):
   Identifique o fluxo de lógica da atividade entre estes padrões:
   - SIMPLE: Execução linear.
   - SPLIT: Ramificação (Se A, faça B; Se C, faça D).
   - MERGE: Consolidação de múltiplas fontes.
   - LOOP-FOR-EACH: Processar uma lista de itens.
   - WAIT-EVENT: Aguardar uma ação externa ou aprovação (Human-in-the-loop).
   - SUBFLOW: Chama outro processo complexo.
   - MANUAL: Impossível de automatizar (ex: assinatura física).

4. RUBRICA DE AUTOMAÇÃO (Vectra Rubric v1):
   Sugira o 'automationScore' (0-100) seguindo estes pesos:
   - Repetitividade: +40 pts se houver padrão claro.
   - Volume/Frequência: +15 pts se for diário/frequente.
   - Criticidade Financeira: +15 pts se houver impacto em $.
   - Ambiguidade/Julgamento: -20 pts se depender de análise subjetiva.
   - Aprovação Física: -10 pts.

### FORMATO DE SAÍDA (JSON) — use EXATAMENTE estas chaves camelCase:
{
  "setor": "Nome do Setor",
  "processosSugeridos": [
    {
      "nome": "Nome do Processo",
      "descricao": "Resumo executivo",
      "sipocBase": {
        "suppliers": ["Fornecedor A"],
        "inputs": ["Dado X"],
        "outputs": ["Entrega Y"],
        "customers": ["Cliente Z"]
      },
      "automacaoScoreEstimado": 75,
      "atividades": [
        {
          "nome": "Ação específica",
          "5w2h": {
            "what": "", "why": "", "who": "", "where": "", "when": "", "how": "", "howMuch": ""
          },
          "logicPattern": "SIMPLE",
          "automationScore": 75,
          "automationJustification": "Por que esta pontuação?"
        }
      ]
    }
  ],
  "riscosComuns": ["Risco operacional 1", "Risco operacional 2"],
  "oportunidadesIa": ["Onde o Claude/GPT brilha aqui"]
}
"""

_GENERIC_FALLBACK_BASELINE = {
    "processosSugeridos": [
        {
            "nome": "Processo Principal",
            "descricao": "Operação central do setor.",
            "sipocBase": {
                "suppliers": ["Fornecedores Internos", "Parceiros"],
                "inputs": ["Dados do Cliente", "Recursos"],
                "outputs": ["Entrega Final", "Relatórios"],
                "customers": ["Cliente Final", "Stakeholders"],
            },
            "automacaoScoreEstimado": 50,
        }
    ],
    "riscosComuns": ["Falta de padronização", "Comunicação ineficiente"],
    "oportunidadesIa": ["Mapeamento assistido por IA", "Análise de gargalos"],
}

ORACLE_AGENT_ID = "oracle"
ORACLE_AGENT_NAME = "Oracle"


def _with_oracle_identity(payload: dict) -> dict:
    payload["agent_id"] = ORACLE_AGENT_ID
    payload["agent_name"] = ORACLE_AGENT_NAME
    payload["agent_role"] = "sipoc_conversational"
    return payload


def _normalize_slug(name: str) -> str:
    """Normaliza o nome do setor para corresponder ao sector_slug no banco."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    return ascii_str.lower().strip().replace(" ", "_")


import json
import logging
from typing import Optional, Any

logger = logging.getLogger("SipocResearcher")


async def _call_llm_for_sipoc(sector_name: str) -> dict:
    """
    Gera baseline SIPOC via Google Gemini (google-genai SDK, GEMINI_API_KEY).
    response_mime_type="application/json" evita fences de markdown no output.
    """
    from src.services.gemini_client import generate, DEFAULT_MODEL

    full_prompt = (
        f"Gere um baseline SIPOC completo e detalhado para o setor de: {sector_name}. "
        "Siga rigorosamente o formato JSON e as diretrizes do Sistema."
    )
    try:
        text, metadata = await generate(
            DEFAULT_MODEL,
            full_prompt,
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            tools=[{"google_search": {}}],
        )
        logger.info(
            "sipoc baseline gerado via Gemini (tokens=%s, dur=%dms)",
            metadata["tokens"]["total"], metadata["duration_ms"],
        )
        return json.loads(text)
    except Exception as e:
        logger.error(f"Falha na geração Gemini: {e}")
        return {}

def _normalize_research_output(raw: dict) -> dict:
    """Garante que o output da LLM respeita o schema Zod do frontend (camelCase)."""
    processos_raw = raw.get("processosSugeridos") or raw.get("processos_sugeridos") or []
    processos = []
    for p in processos_raw:
        sipoc = p.get("sipocBase") or p.get("sipoc_base") or {}
        atividades = p.get("atividades") or []
        scores = [
            a.get("automationScore", 0)
            for a in atividades
            if isinstance(a.get("automationScore"), (int, float))
        ]
        score = int(sum(scores) / len(scores)) if scores else int(p.get("automacaoScoreEstimado", 50))
        processos.append({
            "nome": p.get("nome", ""),
            "descricao": p.get("descricao", ""),
            "sipocBase": {
                "suppliers": sipoc.get("suppliers", []),
                "inputs": sipoc.get("inputs", []),
                "outputs": sipoc.get("outputs", []),
                "customers": sipoc.get("customers", []),
            },
            "automacaoScoreEstimado": max(0, min(100, score)),
            "atividades": atividades,
        })
    return {
        "setor": raw.get("setor", ""),
        "processosSugeridos": processos,
        "riscosComuns": raw.get("riscosComuns") or raw.get("riscos_comuns") or [],
        "oportunidadesIa": raw.get("oportunidadesIa") or raw.get("oportunidades_ia") or [],
    }


async def research_sector(sector_name: str, supabase_client: Optional[Any] = None) -> dict:
    """
    Busca o baseline do setor. Ordem:
    1. Banco de dados (Cache)
    2. Geração via LLM (Real-time)
    3. Fallback estático (Segurança)
    """
    slug = _normalize_slug(sector_name)

    # 1. Busca no Banco
    if supabase_client is not None:
        try:
            res = (
                supabase_client
                .table("sipoc_sector_baselines")
                .select("sector_display_name,baseline,source")
                .eq("sector_slug", slug)
                .maybe_single()
                .execute()
            )
            if res and res.data:
                row = res.data
                payload = _normalize_research_output(row["baseline"])
                payload["setor"] = row["sector_display_name"]
                payload["source"] = row["source"]
                logger.info(f"research_sector: baseline encontrado no banco para '{slug}'")
                return _with_oracle_identity(payload)
        except Exception as e:
            logger.warning(f"research_sector: DB lookup failed for '{slug}': {e}")

    # 2. Geração via LLM
    logger.info(f"research_sector: gerando baseline via IA para '{sector_name}'...")
    llm_payload = await _call_llm_for_sipoc(sector_name)
    if llm_payload:
        llm_payload = _normalize_research_output(llm_payload)
        llm_payload["source"] = "ai_generation"
        if supabase_client:
            try:
                supabase_client.table("sipoc_sector_baselines").upsert({
                    "sector_slug": slug,
                    "sector_display_name": sector_name,
                    "baseline": llm_payload,
                    "source": "ai_generation"
                }, on_conflict="sector_slug").execute()
            except: pass
        return _with_oracle_identity(llm_payload)

    # 3. Fallback genérico (último recurso)
    logger.info(f"research_sector: usando fallback genérico para '{slug}'")
    payload = _normalize_research_output(dict(_GENERIC_FALLBACK_BASELINE))
    payload["setor"] = sector_name.capitalize()
    payload["source"] = "fallback"
    return _with_oracle_identity(payload)
