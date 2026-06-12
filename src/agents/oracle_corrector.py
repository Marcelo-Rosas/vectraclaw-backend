import logging
from typing import Any, Dict

from src.agent_ids import ORACLE_AGENT_ID
from src.services.agent_llm import generate_for_agent
from src.services.gemini_client import DEFAULT_MODEL

logger = logging.getLogger("OracleCorrector")

async def run_corrector(state: Dict[str, Any]) -> Dict[str, Any]:
    maker_response_text = state.get("maker_response_text", "")
    checker_feedback = state.get("checker_feedback", "")
    domain = state.get("domain", "Processo")
    session_id = state.get("session_id", "")
    
    if not checker_feedback:
        return {}

    logger.info("OracleCorrector session=%s aplicando correções. Iteration=%d", session_id, state.get("iteration_count", 0))

    prompt = (
        f"Você é o Oracle Corrector. Sua tarefa é corrigir a seguinte resposta "
        f"gerada anteriormente pelo Maker, baseando-se no feedback estrito do Checker, "
        f"mantendo a coesão com o domínio '{domain}'.\n\n"
        f"RESPOSTA ORIGINAL (Maker):\n{maker_response_text}\n\n"
        f"FEEDBACK DO REVISOR (Checker):\n{checker_feedback}\n\n"
        f"Reescreva a resposta corrigindo os problemas apontados. Forneça APENAS a "
        f"resposta final, sem saudações ou introduções justificando a correção."
    )
    
    try:
        corrected_text, _ = await generate_for_agent(
            ORACLE_AGENT_ID, prompt,
            fallback_model=DEFAULT_MODEL,
        )
        return {
            "maker_response_text": corrected_text.strip(),
            "iteration_count": state.get("iteration_count", 0) + 1
        }
    except Exception as exc:
        logger.error("OracleCorrector falhou na session=%s: %s", session_id, exc)
        return {}
