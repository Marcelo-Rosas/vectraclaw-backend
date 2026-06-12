"""Agente Maker do fluxo SIPOC.

O ``OracleMaker`` é responsável por gerar as respostas do assistente
 durante a construção de um SIPOC. Ele interpreta o estado atual do
diálogo (evento, estágio, perfil do usuário) e invoca o LLM Oracle
produzindo tanto texto para o usuário quanto estruturas de dados
para o backend.

Integração com o orquestrador:
- Recebe o ``FlowState`` completo do ``executor_node``.
- Lê ``previous_feedback`` (feedback do checker da iteração anterior)
  e o incorpora no prompt quando presente.
- Retorna um partial update contendo ``maker_response_text`` e
  ``maker_structured``.

O campo ``iteration_count`` NÃO deve ser modificado aqui; o
orquestrador (``supervisor_node``) é o único responsável por
incrementá-lo, garantindo controle centralizado do loop.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from src.agents.oracle import build_oracle_prompt
from src.services.oracle_llm_stream import stream_oracle_response
from src.services.oracle_session import get_stream_queue

logger = logging.getLogger("OracleMaker")


def _parse_w2h_analysis(text: str) -> Dict[str, Any]:
    """Extrai score, padrão lógico e sugestão de uma análise 5W2H.

    Essa função utiliza expressões regulares permissivas para
    compatibilizar variações de idioma (ex: "Score de Automação"
    vs "Score") e capitalização.
    """
    score_m = re.search(
        r"Score\s*(?:de\s*Automa[çc][aã]o)?[:\s*]*(\d+)\s*/\s*100",
        text,
        re.IGNORECASE,
    )
    pattern_m = re.search(
        r"Padr[aã]o\s*L[oó]gico[:\s*]*"
        r"(SIMPLE|SPLIT|LOOP-FOR-EACH|WAIT-EVENT|SUBFLOW|MANUAL)",
        text,
        re.IGNORECASE,
    )
    suggestion_m = re.search(r"Sugest[aã]o[:\s*]+(.+?)(?:\n|$)", text, re.IGNORECASE)
    return {
        "score": int(score_m.group(1)) if score_m else None,
        "pattern": pattern_m.group(1).upper() if pattern_m else None,
        "suggestion": suggestion_m.group(1).strip("*").strip() if suggestion_m else None,
    }


def _classify_meta_intent(text: str) -> str:
    """Classifica a intenção da mensagem do usuário em meta-diálogo.

    Categorias:
        correction: usuário quer corrigir algo previamente dito.
        question:  usuário faz uma pergunta sobre o processo/SIPOC.
        skip:      usuário pede para avançar/ignorar etapa.
        other:     qualquer outra intenção.
    """
    t = (text or "").lower()
    if re.search(r"\b(corrig|errei|errado|muda|alterar|substituir|troca)\w*\b", t):
        return "correction"
    if re.search(r"\b(como|quando|onde|por que|porque|o que\s+[eé]|dúvida|duvida|explica)\b", t):
        return "question"
    if re.search(r"\b(pr[oó]ximo|skip|pular|avan[çc]ar|pode continuar|pronto|ok)\b", t):
        return "skip"
    return "other"


def _event_to_component_type(stage: str) -> str:
    """Traduz o estágio atual do SIPOC para o tipo de componente."""
    return {
        "mapping_suppliers": "supplier",
        "mapping_inputs": "input",
        "mapping_activities": "activity",
        "mapping_outputs": "output",
        "mapping_customers": "customer",
    }.get(stage, "supplier")


def _build_context_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Monta o contexto específico para o prompt do Oracle.

    O contexto varia conforme o evento atual do diálogo:
    - ``stage_intro``: informa o tipo de componente do estágio.
    - ``component_ack``: informa o valor confirmado pelo usuário.
    - ``w2h_question``: traz a atividade e respostas 5W2H já coletadas.
    - ``w2h_analysis``: traz os dados 5W2H completos para análise.
    """
    event = state.get("current_event", "")
    stage = state.get("current_stage", "")
    activity = (state.get("pending_activity") or {}).get("name", "atividade")
    field = state.get("current_w2h_field")

    if event == "stage_intro":
        return {"component_type": _event_to_component_type(stage)}
    if event == "component_ack":
        return {
            "component_type": _event_to_component_type(stage),
            "value": state.get("last_user_message", ""),
        }
    if event == "w2h_question":
        pending = state.get("pending_activity") or {}
        return {
            "w2h_field": field or "what",
            "activity_name": activity,
            "previous_answers": pending.get("w2h_data", {}),
        }
    if event == "w2h_analysis":
        return {
            "activity_name": activity,
            "w2h_data": (state.get("pending_activity") or {}).get("w2h_data", {}),
        }
    return {}


def _inject_feedback_into_prompt(
    user_prompt: str, feedback: Optional[str]
) -> str:
    """Injeta o feedback do checker no prompt do maker.

    Quando o checker rejeitou a resposta anterior, essa função
    prefixa o prompt do maker com o feedback, orientando-o a
    corrigir os problemas apontados.
    """
    if not feedback:
        return user_prompt
    return (
        f"[O revisor indicou um problema na resposta anterior: {feedback}]\n"
        "Revise sua resposta levando isso em conta.\n\n"
        f"{user_prompt}"
    )


async def run_maker(state: Dict[str, Any]) -> Dict[str, Any]:
    """Gera a resposta do Oracle para o estado atual do diálogo.

    Args:
        state: Estado completo do fluxo SIPOC (``FlowState``).

    Returns:
        Partial update contendo:
            - ``maker_response_text``: texto completo gerado pelo LLM.
            - ``maker_structured``: dados estruturados extraídos do texto,
              quando aplicável (ex: score/pattern de análise 5W2H).
    """
    session_id = state.get("session_id", "")
    current_event = state.get("current_event", "meta_input")

    # O orquestrador garante que ``previous_feedback`` contenha o
    # feedback da iteração anterior. Mantemos fallback para
    # ``checker_feedback`` por compatibilidade com chamadas legadas.
    previous_feedback: Optional[str] = state.get("previous_feedback") or state.get("checker_feedback") or None

    logger.info(
        "oracle.flow.maker_started session=%s event=%s iteration=%d has_feedback=%s",
        session_id,
        current_event,
        state.get("iteration_count", 0),
        bool(previous_feedback),
    )

    q = get_stream_queue(session_id)

    payload = {
        "event": current_event,
        "stage": state.get("current_stage", ""),
        "user_profile": state.get("user_profile", "advanced"),
        "domain": state.get("domain", "Processo"),
        "user_message": state.get("last_user_message", ""),
        "context": _build_context_from_state(state),
    }

    system, user_prompt = build_oracle_prompt(payload)
    user_prompt = _inject_feedback_into_prompt(user_prompt, previous_feedback)

    full_text = ""
    try:
        async for chunk in stream_oracle_response(user_prompt, system_instruction=system):
            if q is not None:
                await q.put({"type": "delta", "content": chunk})
            full_text += chunk
    except Exception as exc:
        logger.error("oracle_maker.stream_generate failed session=%s: %s", session_id, exc)
        error_chunk = f"\n[Erro ao gerar resposta: {exc}]"
        if q is not None:
            await q.put({"type": "delta", "content": error_chunk})
        full_text += error_chunk

    maker_structured: Dict[str, Any] = {}
    if current_event == "w2h_analysis":
        maker_structured = _parse_w2h_analysis(full_text)
    elif current_event == "meta_input":
        maker_structured = {"intent": _classify_meta_intent(state.get("last_user_message", ""))}
    elif current_event == "component_ack":
        maker_structured = {"confirmed_value": state.get("last_user_message", "")}

    logger.info("oracle.flow.maker_done session=%s event=%s", session_id, current_event)

    return {
        "maker_response_text": full_text,
        "maker_structured": maker_structured,
    }
