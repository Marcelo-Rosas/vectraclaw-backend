"""
Decision Engine: determina se uma task deve ser executada via CMA (Managed Agent)
ou via Harness (PortRuntime daemon).

Critérios de pontuação (0-100):
  - operation_type: tipos analíticos/simples pontuam alto (→ CMA); código/orquestração pontuam baixo (→ Harness)
  - Comprimento da descrição: curta = bônus, muito longa = penalidade
  - budget_limit: orçamento muito apertado favorece CMA (mais rápido/barato)

Threshold: score >= 50 → managed_agent; caso contrário → harness
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("ManagedAgents.DecisionEngine")

# Peso base por operation_type (0 = sempre harness, 100 = sempre CMA)
_OPERATION_TYPE_SCORES: Dict[str, int] = {
    "orchestration": 0,       # coordenação multi-step → harness
    "code_generation": 15,    # precisa de bash/file tools → harness
    "qa_testing": 35,         # pode precisar de execução → lean harness
    "email_lead": 10,         # HermesReporter daemon handles natively; CMA path breaks with key issues
    "freight-quotation": 80,  # extração de briefing + cotação → CMA
    "code_review": 65,        # análise pura → lean CMA
    "document_generation": 75,  # síntese estruturada → CMA
    "other": 60,              # padrão simples → lean CMA
    "research": 85,           # síntese de informação → CMA
}

CMA_THRESHOLD = 50


@dataclass
class RoutingDecision:
    executor_type: str          # "managed_agent" | "harness"
    score: int
    rationale: str
    operation_type: str


def should_use_managed_agent(task: Dict[str, Any]) -> RoutingDecision:
    """
    Recebe um dict de task (campos do banco ou modelo Task serializado)
    e retorna a decisão de roteamento com score e rationale.
    """
    operation_type: str = task.get("operation_type") or "other"
    description: str = task.get("description") or ""
    budget_limit: Optional[int] = task.get("budget_limit")

    score = _OPERATION_TYPE_SCORES.get(operation_type, 60)
    reasons = [f"operation_type={operation_type} base_score={score}"]

    # Ajuste por comprimento da descrição
    desc_len = len(description)
    if desc_len < 100:
        score += 15
        reasons.append(f"descrição curta ({desc_len} chars) +15")
    elif desc_len > 600:
        score -= 20
        reasons.append(f"descrição longa ({desc_len} chars) -20")

    # Ajuste por budget apertado (favorece CMA)
    if budget_limit is not None and 0 < budget_limit < 100:
        score += 10
        reasons.append(f"budget apertado ({budget_limit}) +10")

    score = max(0, min(100, score))
    executor = "managed_agent" if score >= CMA_THRESHOLD else "harness"

    rationale = "; ".join(reasons) + f" → score={score} → {executor}"
    logger.info(
        "DecisionEngine task_id=%s score=%d executor=%s",
        task.get("id", "?"),
        score,
        executor,
    )

    return RoutingDecision(
        executor_type=executor,
        score=score,
        rationale=rationale,
        operation_type=operation_type,
    )
