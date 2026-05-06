import operator
import logging
from typing import Annotated, Any, Dict, List, Optional, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import END, StateGraph

logger = logging.getLogger("OracleFlow")


class FlowState(TypedDict):
    session_id: str
    process_id: Optional[str]
    domain: str
    user_profile: str  # beginner | advanced | pmo

    messages: Annotated[Sequence[BaseMessage], operator.add]

    sipoc_snapshot: Dict[str, Any]
    collected_5w2h: Dict[str, Dict[str, str]]
    current_stage: str
    current_event: str
    current_w2h_field: Optional[str]
    pending_activity: Optional[Dict[str, Any]]
    last_user_message: Optional[str]

    maker_response_text: str
    maker_structured: Dict[str, Any]

    checker_verdict: str  # accept | revise
    checker_feedback: str
    checker_corrections: List[Dict[str, Any]]

    iteration_count: int
    current_node: str


async def supervisor_node(state: FlowState) -> Dict[str, Any]:
    iterations = state.get("iteration_count", 0)
    logger.info("oracle.flow.supervisor_decided session=%s iteration=%d",
                state.get("session_id"), iterations)
    if iterations >= 3:
        return {"current_node": "human_fallback"}
    return {"current_node": "execute_task"}


async def executor_node(state: FlowState) -> Dict[str, Any]:
    from src.agents.oracle_maker import run_maker
    logger.info("oracle.flow.maker_started session=%s event=%s iteration=%d",
                state.get("session_id"), state.get("current_event"), state.get("iteration_count", 0))
    result = await run_maker(state)
    logger.info("oracle.flow.maker_done session=%s", state.get("session_id"))
    return result


async def checker_node(state: FlowState) -> Dict[str, Any]:
    from src.agents.oracle_checker import run_checker
    result = await run_checker(state)
    verdict = result.get("checker_verdict", "accept")
    feedback = result.get("checker_feedback", "")
    logger.info("oracle.flow.checker_verdict session=%s verdict=%s feedback=%.200s",
                state.get("session_id"), verdict, feedback)
    if verdict == "revise":
        logger.info("oracle.flow.iteration_loop session=%s iteration=%d",
                    state.get("session_id"), state.get("iteration_count", 0))
    return result


async def human_fallback_node(state: FlowState) -> Dict[str, Any]:
    feedback = (
        state.get("checker_feedback")
        or "Oracle não conseguiu gerar resposta satisfatória após 3 tentativas."
    )
    logger.warning("oracle.flow.human_fallback session=%s feedback=%.200s",
                   state.get("session_id"), feedback)
    return {
        "checker_corrections": [
            {
                "type": "requires_human_review",
                "reason": feedback,
                "suggested_question": (
                    "Por favor, reformule ou detalhe melhor a informação que deseja registrar."
                ),
            }
        ],
        "current_node": "end",
    }


def _route_after_supervisor(state: FlowState) -> str:
    if state.get("current_node") == "human_fallback":
        return "human_fallback"
    return "executor"


def _route_after_checker(state: FlowState) -> str:
    verdict = state.get("checker_verdict", "accept")
    if verdict == "accept":
        return END
    return "supervisor"


_ORCHESTRATOR = None


def build_orchestrator():
    workflow = StateGraph(FlowState)

    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("checker", checker_node)
    workflow.add_node("human_fallback", human_fallback_node)

    workflow.set_entry_point("supervisor")
    workflow.add_conditional_edges("supervisor", _route_after_supervisor)
    workflow.add_edge("executor", "checker")
    workflow.add_conditional_edges("checker", _route_after_checker)
    workflow.add_edge("human_fallback", END)

    return workflow.compile()


def get_orchestrator():
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        _ORCHESTRATOR = build_orchestrator()
    return _ORCHESTRATOR
