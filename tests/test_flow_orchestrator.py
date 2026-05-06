"""Tests for LangGraph Oracle Maker-Checker flow orchestrator."""
import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage

from src.services.flow_orchestrator import FlowState, get_orchestrator


def _base_state(**overrides) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "session_id": "test-session",
        "process_id": None,
        "domain": "farmácia hospitalar",
        "user_profile": "advanced",
        "messages": [HumanMessage(content="teste")],
        "sipoc_snapshot": {},
        "collected_5w2h": {},
        "current_stage": "idle",
        "current_event": "meta_input",
        "current_w2h_field": None,
        "pending_activity": None,
        "last_user_message": "teste",
        "maker_response_text": "",
        "maker_structured": {},
        "checker_verdict": "accept",
        "checker_feedback": "",
        "checker_corrections": [],
        "iteration_count": 0,
        "current_node": "supervisor",
    }
    state.update(overrides)
    return state


_MAKER_ACCEPT = {
    "maker_response_text": "Resposta do Oracle.",
    "maker_structured": {"intent": "other"},
    "current_node": "checker",
}

_CHECKER_ACCEPT = {
    "checker_verdict": "accept",
    "checker_feedback": "",
    "checker_corrections": [],
    "current_node": "end",
}

_CHECKER_REVISE = {
    "checker_verdict": "revise",
    "checker_feedback": "Score muito alto para dados insuficientes.",
    "checker_corrections": [],
    "current_node": "execute_task",
}


@pytest.mark.asyncio
async def test_supervisor_routes_to_executor_on_first_iter():
    orch = get_orchestrator()
    state = _base_state(iteration_count=0)

    with (
        patch("src.agents.oracle_maker.run_maker", new_callable=AsyncMock, return_value=_MAKER_ACCEPT),
        patch("src.agents.oracle_checker.run_checker", new_callable=AsyncMock, return_value=_CHECKER_ACCEPT),
    ):
        result = await orch.ainvoke(state)

    assert result["maker_response_text"] == "Resposta do Oracle."
    assert result["checker_verdict"] == "accept"


@pytest.mark.asyncio
async def test_supervisor_routes_to_human_fallback_after_3():
    orch = get_orchestrator()
    state = _base_state(
        iteration_count=3,
        checker_feedback="Não foi possível gerar resposta adequada.",
    )

    with (
        patch("src.agents.oracle_maker.run_maker", new_callable=AsyncMock, return_value=_MAKER_ACCEPT),
        patch("src.agents.oracle_checker.run_checker", new_callable=AsyncMock, return_value=_CHECKER_REVISE),
    ):
        result = await orch.ainvoke(state)

    corrections = result.get("checker_corrections", [])
    assert any(c.get("type") == "requires_human_review" for c in corrections), (
        f"Expected requires_human_review in corrections, got: {corrections}"
    )


@pytest.mark.asyncio
async def test_checker_revise_loops_back_with_feedback():
    """Checker rejects on iter 0 → loops to executor iter 1 → accepts."""
    orch = get_orchestrator()
    state = _base_state(iteration_count=0)

    call_count = {"maker": 0, "checker": 0}

    async def maker_side_effect(s):
        call_count["maker"] += 1
        return _MAKER_ACCEPT

    async def checker_side_effect(s):
        call_count["checker"] += 1
        if call_count["checker"] == 1:
            return _CHECKER_REVISE
        return _CHECKER_ACCEPT

    with (
        patch("src.agents.oracle_maker.run_maker", side_effect=maker_side_effect),
        patch("src.agents.oracle_checker.run_checker", side_effect=checker_side_effect),
    ):
        result = await orch.ainvoke(state)

    assert call_count["maker"] == 2, f"Expected 2 maker calls, got {call_count['maker']}"
    assert call_count["checker"] == 2, f"Expected 2 checker calls, got {call_count['checker']}"
    assert result["checker_verdict"] == "accept"


@pytest.mark.asyncio
async def test_w2h_analysis_full_flow_with_mock_gemini():
    """w2h_analysis event: Checker emits score correction via overwrite_component."""
    orch = get_orchestrator()
    state = _base_state(
        current_event="w2h_analysis",
        current_stage="activity_5w2h",
        pending_activity={"id": "act-001", "name": "Dispensação", "w2h_data": {"what": "a", "how": "b"}},
    )

    maker_result = {
        "maker_response_text": "Score: 75/100\nPadrão Lógico: SIMPLE",
        "maker_structured": {"score": 75, "pattern": "SIMPLE"},
        "current_node": "checker",
    }

    checker_result = {
        "checker_verdict": "accept",
        "checker_feedback": "",
        "checker_corrections": [
            {
                "type": "correction",
                "kind": "overwrite_component",
                "component_id": "act-001",
                "patch": {"automationScore": 30, "logicPattern": "SIMPLE"},
            }
        ],
        "current_node": "end",
    }

    with (
        patch("src.agents.oracle_maker.run_maker", new_callable=AsyncMock, return_value=maker_result),
        patch("src.agents.oracle_checker.run_checker", new_callable=AsyncMock, return_value=checker_result),
    ):
        result = await orch.ainvoke(state)

    corrections = result.get("checker_corrections", [])
    assert len(corrections) == 1
    corr = corrections[0]
    assert corr["kind"] == "overwrite_component"
    assert corr["component_id"] == "act-001"
    assert corr["patch"]["automationScore"] == 30
