import unicodedata
import logging
from typing import Optional, Any

logger = logging.getLogger("SipocResearcher")

SYSTEM_PROMPT = """
Você é o "Vectra Sipoc Master", um consultor sênior em Excelência Operacional e Arquitetura de Agentes de IA.
Sua missão é mapear setores empresariais com foco total em IDENTIFICAR OPORTUNIDADES DE AUTOMAÇÃO.

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

### FORMATO DE SAÍDA (JSON):
{
  "setor": "Nome do Setor",
  "processos_sugeridos": [
    {
      "nome": "Nome do Processo",
      "descricao": "Resumo executivo",
      "atividades": [
        {
          "nome": "Ação específica",
          "5w2h": {
            "what": "", "why": "", "who": "", "where": "", "when": "", "how": "", "howMuch": ""
          },
          "logicPattern": "Enum",
          "automationScore": 0-100,
          "automationJustification": "Por que esta pontuação?"
        }
      ],
      "sipoc_base": {
        "suppliers": [], "inputs": [], "outputs": [], "customers": []
      }
    }
  ],
  "oportunidades_ia": ["Onde o Claude/GPT brilha aqui"]
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


def _normalize_slug(name: str) -> str:
    """Normaliza o nome do setor para corresponder ao sector_slug no banco."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    return ascii_str.lower().strip().replace(" ", "_")


import json
import logging
import os
import httpx
from typing import Optional, Any

logger = logging.getLogger("SipocResearcher")

# ... (SYSTEM_PROMPT já atualizado no passo anterior)

async def _call_llm_for_sipoc(sector_name: str) -> dict:
    """
    Chama o Claude (Anthropic) para gerar um baseline de alta qualidade.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY não encontrada. Usando fallback estático.")
        return {}

    prompt = f"Gere um baseline SIPOC completo e detalhado para o setor de: {sector_name}. Siga rigorosamente o formato JSON e as diretrizes do Sistema."
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-3-5-sonnet-20240620",
                    "max_tokens": 4096,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2
                },
                timeout=60.0
            )
            
            if response.status_code != 200:
                logger.error(f"Erro na API da Anthropic: {response.text}")
                return {}
            
            data = response.json()
            content = data["content"][0]["text"]
            
            # Limpeza básica caso o modelo coloque markdown em volta do JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            
            return json.loads(content)
    except Exception as e:
        logger.error(f"Falha na geração via LLM: {e}")
        return {}

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
            if res.data:
                row = res.data
                payload = row["baseline"]
                payload["setor"] = row["sector_display_name"]
                payload["source"] = row["source"]
                logger.info(f"research_sector: baseline encontrado no banco para '{slug}'")
                return payload
        except Exception as e:
            logger.warning(f"research_sector: DB lookup failed for '{slug}': {e}")

    # 2. Geração via LLM
    logger.info(f"research_sector: gerando baseline via IA para '{sector_name}'...")
    llm_payload = await _call_llm_for_sipoc(sector_name)
    if llm_payload:
        llm_payload["source"] = "ai_generation"
        # Opcional: Salvar no banco para cache futuro
        if supabase_client:
            try:
                supabase_client.table("sipoc_sector_baselines").insert({
                    "sector_slug": slug,
                    "sector_display_name": sector_name,
                    "baseline": llm_payload,
                    "source": "ai_generation"
                }).execute()
            except: pass
        return llm_payload

    # 3. Fallback genérico (último recurso)
    logger.info(f"research_sector: usando fallback genérico para '{slug}'")
    payload = dict(_GENERIC_FALLBACK_BASELINE)
    payload["setor"] = sector_name.capitalize()
    payload["source"] = "fallback"
    return payload
