import json
import logging
from typing import Any, Dict, List

from src.agent_ids import ORACLE_AGENT_ID
from src.services.agent_llm import generate_for_agent
from src.services.gemini_client import DEFAULT_MODEL

logger = logging.getLogger("OracleChecker")

_VECTRA_RUBRIC = (
    "Vectra Rubric v1:\n"
    "- Repetitividade alta (+40): processo ocorre com frequência regular\n"
    "- Volume alto (+15): afeta muitas instâncias por execução\n"
    "- Criticidade alta (+15): impacto em operações, faturamento ou compliance\n"
    "- Ambiguidade alta (-20): falta clareza no 'como' ou 'quem'\n"
    "- Aprovação física (-10): requer presença física ou assinatura manual\n\n"
    "Padrões lógicos válidos: SIMPLE | SPLIT | LOOP-FOR-EACH | WAIT-EVENT | SUBFLOW | MANUAL"
)

_VALID_PATTERNS = frozenset(
    ["SIMPLE", "SPLIT", "LOOP-FOR-EACH", "WAIT-EVENT", "SUBFLOW", "MANUAL"]
)


async def run_checker(state: Dict[str, Any]) -> Dict[str, Any]:
    event = state.get("current_event", "meta_input")
    maker_text = state.get("maker_response_text", "")
    session_id = state.get("session_id", "")

    try:
        if event == "w2h_analysis":
            return await _check_w2h_analysis(state, maker_text)
        if event == "component_ack":
            return await _check_component_ack(state, maker_text)
        if event == "meta_input":
            return await _check_meta_input(state, maker_text)
        return _check_format_only(maker_text, max_lines=6)
    except Exception as exc:
        logger.error("oracle_checker failed session=%s event=%s: %s", session_id, event, exc)
        return _accept()


async def _check_w2h_analysis(state: Dict[str, Any], maker_text: str) -> Dict[str, Any]:
    activity = (state.get("pending_activity") or {}).get("name", "atividade")
    w2h_data = (state.get("pending_activity") or {}).get("w2h_data") or {}
    w2h_rows = "\n".join(f"- {k}: {v}" for k, v in w2h_data.items() if v) or "(sem dados)"
    maker_structured = state.get("maker_structured") or {}
    score = maker_structured.get("score")
    pattern = maker_structured.get("pattern")

    prompt = (
        f"{_VECTRA_RUBRIC}\n\n"
        f"Atividade: '{activity}'\n"
        f"Dados 5W2H:\n{w2h_rows}\n\n"
        f"Resposta do Oracle:\n{maker_text}\n\n"
        f"Score extraído: {score}\nPadrão extraído: {pattern}\n\n"
        "Valide:\n"
        "1. Se os campos 5W2H têm menos de 5 palavras cada, o score DEVE ser < 40 (dados insuficientes).\n"
        "2. O padrão lógico é plausível dado o campo 'how'?\n"
        "3. A sugestão é acionável (não genérica como 'automatize o processo')?\n\n"
        'Retorne APENAS JSON (sem markdown): {"verdict":"accept","score_correction":null,'
        '"pattern_correction":null,"replacement_text":null,"feedback":""}'
    )

    text, _ = await generate_for_agent(
        ORACLE_AGENT_ID, prompt,
        response_mime_type="application/json",
        fallback_model=DEFAULT_MODEL,
    )
    return _parse_result(text, state, event="w2h_analysis")


async def _check_component_ack(state: Dict[str, Any], maker_text: str) -> Dict[str, Any]:
    value = state.get("last_user_message", "")
    stage = state.get("current_stage", "")
    comp_type = _event_to_component_type(stage)
    domain = state.get("domain", "")

    prompt = (
        f"Avalie o ack abaixo para registrar '{value}' como {comp_type} no domínio '{domain}':\n\n"
        f"Ack: {maker_text}\n\n"
        "Critérios:\n"
        "- Máximo 3 linhas\n"
        "- Não inventou dados além do fornecido\n"
        "- Insight (se presente) é relevante\n\n"
        'Retorne APENAS JSON: {"verdict":"accept","replacement_text":null,"feedback":""}'
    )

    text, _ = await generate_for_agent(
        ORACLE_AGENT_ID, prompt,
        response_mime_type="application/json",
        fallback_model=DEFAULT_MODEL,
    )
    return _parse_result(text, state, event="component_ack")


async def _check_meta_input(state: Dict[str, Any], maker_text: str) -> Dict[str, Any]:
    intent = (state.get("maker_structured") or {}).get("intent", "other")
    user_message = state.get("last_user_message", "")

    prompt = (
        f"Mensagem do usuário: '{user_message}'\n"
        f"Intenção classificada: '{intent}'\n"
        f"Resposta do Oracle: {maker_text}\n\n"
        "Verifique se a classificação de intenção está correta e a resposta é útil.\n"
        'Retorne APENAS JSON: {"verdict":"accept","intent_correction":null,'
        '"replacement_text":null,"feedback":""}'
    )

    text, _ = await generate_for_agent(
        ORACLE_AGENT_ID, prompt,
        response_mime_type="application/json",
        fallback_model=DEFAULT_MODEL,
    )
    return _parse_result(text, state, event="meta_input")


def _check_format_only(maker_text: str, max_lines: int = 6) -> Dict[str, Any]:
    line_count = len([l for l in maker_text.strip().split("\n") if l.strip()])
    if line_count <= max_lines * 2:
        return _accept()
    truncated = "\n".join(maker_text.strip().split("\n")[:max_lines])
    return {
        "checker_verdict": "revise",
        "checker_feedback": f"Resposta muito longa ({line_count} linhas, máx {max_lines}). Seja mais conciso.",
        "checker_corrections": [
            {"type": "correction", "kind": "replace_text", "replacement": truncated}
        ],
        "current_node": "execute_task",
    }


def _accept() -> Dict[str, Any]:
    return {
        "checker_verdict": "accept",
        "checker_feedback": "",
        "checker_corrections": [],
        "current_node": "end",
    }


def _parse_result(result_text: str, state: Dict[str, Any], event: str) -> Dict[str, Any]:
    corrections: List[Dict[str, Any]] = []
    feedback = ""
    verdict = "accept"

    try:
        cleaned = result_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:])
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()

        data = json.loads(cleaned)
        verdict = str(data.get("verdict", "accept"))
        feedback = str(data.get("feedback", ""))

        replacement = data.get("replacement_text")
        if replacement:
            corrections.append({
                "type": "correction",
                "kind": "replace_text",
                "replacement": str(replacement),
            })

        if event == "w2h_analysis":
            patch: Dict[str, Any] = {}
            score_corr = data.get("score_correction")
            if score_corr is not None:
                try:
                    patch["automationScore"] = int(score_corr)
                except (ValueError, TypeError):
                    pass
            pattern_corr = data.get("pattern_correction")
            if isinstance(pattern_corr, str) and pattern_corr.upper() in _VALID_PATTERNS:
                patch["logicPattern"] = pattern_corr.upper()

            if patch:
                activity_id = (state.get("pending_activity") or {}).get("id")
                if activity_id:
                    corrections.append({
                        "type": "correction",
                        "kind": "overwrite_component",
                        "component_id": str(activity_id),
                        "patch": patch,
                    })

    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("oracle_checker parse failed: %s — raw: %.300s", exc, result_text)
        verdict = "accept"

    current_node = "end" if verdict == "accept" else "execute_task"
    return {
        "checker_verdict": verdict,
        "checker_feedback": feedback,
        "checker_corrections": corrections,
        "current_node": current_node,
    }


def _event_to_component_type(stage: str) -> str:
    return {
        "mapping_suppliers": "supplier",
        "mapping_inputs": "input",
        "mapping_activities": "activity",
        "mapping_outputs": "output",
        "mapping_customers": "customer",
    }.get(stage, "supplier")
