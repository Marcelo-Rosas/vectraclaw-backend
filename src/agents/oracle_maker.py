import logging
import re
from typing import Any, Dict

from src.agents.oracle import build_oracle_prompt
from src.services.oracle_llm_stream import stream_oracle_response
from src.services.oracle_session import get_stream_queue

logger = logging.getLogger("OracleMaker")


def _parse_w2h_analysis(text: str) -> Dict[str, Any]:
    score_m = re.search(
        r"Score\s*(?:de\s*Automa[çc][aã]o)?[:\s*]*(\d+)\s*/\s*100",
        text, re.IGNORECASE,
    )
    pattern_m = re.search(
        r"Padr[aã]o\s*L[oó]gico[:\s*]*"
        r"(SIMPLE|SPLIT|LOOP-FOR-EACH|WAIT-EVENT|SUBFLOW|MANUAL)",
        text, re.IGNORECASE,
    )
    suggestion_m = re.search(r"Sugest[aã]o[:\s*]+(.+?)(?:\n|$)", text, re.IGNORECASE)
    return {
        "score": int(score_m.group(1)) if score_m else None,
        "pattern": pattern_m.group(1).upper() if pattern_m else None,
        "suggestion": suggestion_m.group(1).strip("*").strip() if suggestion_m else None,
    }


def _classify_meta_intent(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"\b(corrig|errei|errado|muda|alterar|substituir|troca)\w*\b", t):
        return "correction"
    if re.search(r"\b(como|quando|onde|por que|porque|o que\s+[eé]|dúvida|duvida|explica)\b", t):
        return "question"
    if re.search(r"\b(pr[oó]ximo|skip|pular|avan[çc]ar|pode continuar|pronto|ok)\b", t):
        return "skip"
    return "other"


def _event_to_component_type(stage: str) -> str:
    return {
        "mapping_suppliers": "supplier",
        "mapping_inputs": "input",
        "mapping_activities": "activity",
        "mapping_outputs": "output",
        "mapping_customers": "customer",
    }.get(stage, "supplier")


def _build_context_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
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


async def run_maker(state: Dict[str, Any]) -> Dict[str, Any]:
    session_id = state.get("session_id", "")
    current_event = state.get("current_event", "meta_input")
    checker_feedback = state.get("checker_feedback", "")
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

    if checker_feedback:
        user_prompt = (
            f"[O revisor indicou um problema na resposta anterior: {checker_feedback}]\n"
            f"Revise sua resposta levando isso em conta.\n\n"
            f"{user_prompt}"
        )

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

    return {
        "maker_response_text": full_text,
        "maker_structured": maker_structured,
        "iteration_count": state.get("iteration_count", 0) + 1,
        "current_node": "checker",
    }
