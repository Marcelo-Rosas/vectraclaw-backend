"""Motor de decisão para roteamento inteligente de tarefas."""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from src.models import Task, Agent

logger = logging.getLogger("DecisionEngine")


@dataclass(frozen=True)
class RoutingDecision:
    """Resultado de uma decisão de roteamento."""
    executor_type: str  # "managed_agent" ou "harness"
    score: int  # 0-100
    reasoning: str  # Explicação da decisão
    confidence: float  # 0.0-1.0


def score_task_complexity(task: Task) -> int:
    """
    Calcula score de complexidade de uma tarefa (0-100).

    Score:
    - 0-30: Simples (ideal para Managed Agents)
    - 31-70: Médio (pode ir para qualquer um)
    - 71-100: Complexo (melhor para Harness)

    Args:
        task: Task object

    Returns:
        Score de complexidade (0-100)
    """
    score = 0
    components = {}

    # 1. Complexidade da descrição (0-20 pts)
    description_len = len(task.description or "")
    components["description_complexity"] = 0
    if description_len < 100:
        components["description_complexity"] = 0
    elif description_len < 300:
        components["description_complexity"] = 5
    elif description_len < 600:
        components["description_complexity"] = 10
    elif description_len < 1000:
        components["description_complexity"] = 15
    else:
        components["description_complexity"] = 20
    score += components["description_complexity"]

    # 2. Tipo de operação (0-30 pts)
    operation_type_scores = {
        "research": 10,
        "document_generation": 15,
        "code_generation": 30,
        "code_review": 30,
        "qa_testing": 25,
        "orchestration": 20,
        "other": 0,
    }
    components["operation_type"] = operation_type_scores.get(
        task.operation_type, 0
    )
    score += components["operation_type"]

    # 3. Contexto aninhado (0-15 pts)
    components["context_depth"] = 0
    if task.parent_task_id:
        components["context_depth"] += 5
    if hasattr(task, "goal_id") and task.goal_id:
        components["context_depth"] += 5
    if hasattr(task, "budget_limit") and task.budget_limit > 50000:
        components["context_depth"] += 5
    score += components["context_depth"]

    # 4. Número estimado de ferramentas (0-20 pts)
    components["tool_complexity"] = estimate_tool_complexity(task.description or "")
    score += components["tool_complexity"]

    # 5. Status e histórico (0-15 pts)
    components["status_complexity"] = 0
    if task.status == "review":
        components["status_complexity"] = 10
    elif task.status == "blocked":
        components["status_complexity"] = 15
    score += components["status_complexity"]

    # Limitar a 100
    score = min(score, 100)

    logger.info(
        f"Score calculado para task {task.id}: {score} "
        f"(detalhes: {components})"
    )

    return score


def estimate_tool_complexity(description: str) -> int:
    """
    Estima complexidade de ferramentas baseado em keywords na descrição.

    Args:
        description: Descrição da tarefa

    Returns:
        Pontos de complexidade (0-20)
    """
    if not description:
        return 0

    desc_lower = description.lower()

    # Keywords simples (1-2 ferramentas)
    simple_keywords = [
        "calcular",
        "cbm",
        "whatsapp",
        "notificar",
        "enviar mensagem",
    ]

    # Keywords complexos (3+ ferramentas)
    complex_keywords = [
        "cruzar",
        "validar",
        "extrair",
        "múltiplos",
        "vários",
        "análise",
        "comparação",
        "integração",
        "automação",
        "orquestração",
    ]

    complexity = 0

    # Contar keywords simples
    simple_count = sum(1 for kw in simple_keywords if kw in desc_lower)
    complexity += simple_count * 3

    # Contar keywords complexos
    complex_count = sum(1 for kw in complex_keywords if kw in desc_lower)
    complexity += complex_count * 5

    return min(complexity, 20)


def should_use_managed_agent(
    task: Task,
    agent: Optional[Agent] = None,
    force_executor: Optional[str] = None,
) -> RoutingDecision:
    """
    Decide se uma tarefa deve ir para Managed Agents ou Harness.

    Args:
        task: Task a rotear
        agent: Agent que executaria a tarefa (opcional)
        force_executor: Força um executor específico ("managed_agent" ou "harness")

    Returns:
        RoutingDecision com executor_type, score e reasoning
    """

    # Se forçado explicitamente, usar isso
    if force_executor in ("managed_agent", "harness"):
        confidence = 1.0
        reasoning = f"Executor forçado via force_executor={force_executor}"
        return RoutingDecision(
            executor_type=force_executor,
            score=100 if force_executor == "harness" else 0,
            reasoning=reasoning,
            confidence=confidence,
        )

    # Se task tem executor_type explícito, respeitar
    if hasattr(task, "executor_type") and task.executor_type in ("managed_agent", "harness"):
        confidence = 0.95
        reasoning = f"Executor definido na tarefa: {task.executor_type}"
        score = 0 if task.executor_type == "managed_agent" else 100
        return RoutingDecision(
            executor_type=task.executor_type,
            score=score,
            reasoning=reasoning,
            confidence=confidence,
        )

    # Cálculo automático
    score = score_task_complexity(task)

    # Verificar capabilidades do agent
    if agent and hasattr(agent, "supports_managed_agents"):
        if not agent.supports_managed_agents:
            logger.info(f"Agent {agent.id} não suporta Managed Agents")
            return RoutingDecision(
                executor_type="harness",
                score=score,
                reasoning="Agent não suporta Managed Agents",
                confidence=0.9,
            )

    # Decisão baseada em score
    if score <= 40:
        executor_type = "managed_agent"
        confidence = 0.9
        reason = "Tarefa simples, ideal para Managed Agents"
    elif score >= 60:
        executor_type = "harness"
        confidence = 0.85
        reason = "Tarefa complexa, melhor para Harness"
    else:
        # 41-59: zona cinzenta, preferir Managed Agents para custo
        executor_type = "managed_agent"
        confidence = 0.65
        reason = "Complexidade média, roteando para Managed Agents (custo otimizado)"

    reasoning = f"{reason} (score={score}/100)"

    logger.info(
        f"Roteamento decidido para task {task.id}: "
        f"{executor_type} (score={score}, confidence={confidence:.2f})"
    )

    return RoutingDecision(
        executor_type=executor_type,
        score=score,
        reasoning=reasoning,
        confidence=confidence,
    )


def score_agent_capability(
    agent: Agent,
    task: Task,
) -> tuple[bool, str]:
    """
    Verifica se um agent pode executar uma task específica.

    Args:
        agent: Agent a verificar
        task: Task a executar

    Returns:
        Tupla (capable, reason)
    """
    reasons = []

    # Verificar status do agent
    if agent.status not in ("idle", "working"):
        return False, f"Agent status={agent.status} não permite execução"

    # Verificar se agent suporta Managed Agents (se necessário)
    if hasattr(task, "executor_type") and task.executor_type == "managed_agent":
        if not agent.supports_managed_agents:
            return False, "Agent não suporta Managed Agents"

    # Verificar budget
    if hasattr(task, "budget_limit") and hasattr(agent, "token_budget"):
        if agent.token_budget < task.budget_limit:
            reasons.append(
                f"Orçamento insuficiente (agent={agent.token_budget}, "
                f"task={task.budget_limit})"
            )

    if reasons:
        return False, "; ".join(reasons)

    return True, "Agent capaz de executar task"
