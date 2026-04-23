import unicodedata
import logging
from typing import Optional, Any

logger = logging.getLogger("SipocResearcher")

SYSTEM_PROMPT = """
Você é um consultor sênior especializado em Gestão de Processos e Metodologia SIPOC.
Sua missão é realizar uma pesquisa profunda sobre um setor específico de uma empresa para fornecer um "Baseline de Processo".

### Suas Diretrizes:
1. PESQUISA SETORIAL: Identifique as melhores práticas e processos padrão para o setor informado.
2. ESTRUTURA SIPOC: Para cada processo identificado, sugira:
   - Fornecedores (Suppliers) típicos.
   - Entradas (Inputs) fundamentais.
   - Saídas (Outputs) principais.
   - Clientes (Customers) finais ou internos.
3. DICAS 5W2H: Forneça orientações sobre quem (Who) e como (How) essas tarefas costumam ser executadas no mercado.
4. FOCO EM DESONERAÇÃO: Destaque áreas onde a automação (IA) costuma gerar maior ROI e margem de lucro.

### Formato de Saída (JSON):
Sempre responda em JSON estruturado para que o sistema possa pré-popular o banco de dados:
{
  "setor": "string",
  "processos_sugeridos": [
    {
      "nome": "string",
      "descricao": "string",
      "sipoc_base": {
        "suppliers": ["string"],
        "inputs": ["string"],
        "outputs": ["string"],
        "customers": ["string"]
      },
      "automacao_score_estimado": 0-100
    }
  ],
  "riscos_comuns": ["string"],
  "oportunidades_ia": ["string"]
}

### Idioma:
Siga estritamente a diretriz de governança: TODO O CONTEÚDO DEVE SER EM PORTUGUÊS.
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


async def research_sector(sector_name: str, supabase_client: Optional[Any] = None) -> dict:
    """
    Busca o baseline do setor no banco (sipoc_sector_baselines).
    Se não encontrar, retorna o fallback genérico.
    O cliente Supabase é injetado para evitar acoplamento direto ao módulo api.
    """
    slug = _normalize_slug(sector_name)

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
                return payload
        except Exception as e:
            logger.warning(f"research_sector: DB lookup failed for '{slug}', using fallback: {e}")

    # Fallback genérico quando o banco não tem o setor
    logger.info(f"research_sector: no baseline found for '{slug}', returning generic fallback")
    payload = dict(_GENERIC_FALLBACK_BASELINE)
    payload["setor"] = sector_name.capitalize()
    payload["source"] = "fallback"
    return payload
