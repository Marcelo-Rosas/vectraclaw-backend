"""
Tests para o Decision Engine e roteamento CMA vs Harness.
"""
import time
import pytest
from src.managed_agents.decision_engine import should_use_managed_agent, CMA_THRESHOLD


# A.4 do ADR Fase A (2026-05-17): decision_engine virou catalog-driven —
# routing_score vem de operation_types_catalog. Em testes sem Supabase, o
# cache do helper fica vazio e cai no default 60 (CMA), quebrando testes que
# esperam orchestration→harness etc.
#
# Fixture autouse pre-popula o cache com os 10 valores historicamente
# hardcoded pra preservar comportamento dos testes pré-A.4. Em produção, esses
# valores vêm do DB (migration 20260517170000 fez backfill idêntico).
@pytest.fixture(autouse=True)
def _seed_routing_score_cache(monkeypatch):
    from src.managed_agents import decision_engine
    monkeypatch.setattr(
        decision_engine,
        "_ROUTING_SCORE_CACHE",
        {
            "orchestration": 0,
            "code_generation": 15,
            "qa_testing": 35,
            "email_lead": 10,
            "freight-quotation": 80,
            "code_review": 65,
            "document_generation": 75,
            "other": 60,
            "research": 85,
            "athena-onboarding": 85,
        },
    )
    monkeypatch.setattr(decision_engine, "_ROUTING_SCORE_CACHE_FETCHED_AT", time.time())


def _task(operation_type="other", description="", budget_limit=1000):
    return {
        "id": "task-test",
        "title": "Test task",
        "description": description,
        "operation_type": operation_type,
        "budget_limit": budget_limit,
    }


def test_simple_task_routed_to_cma():
    decision = should_use_managed_agent(_task(operation_type="research", description="Pesquise X"))
    assert decision.executor_type == "managed_agent"
    assert decision.score >= CMA_THRESHOLD


def test_orchestration_task_routed_to_harness():
    decision = should_use_managed_agent(_task(operation_type="orchestration"))
    assert decision.executor_type == "harness"
    assert decision.score < CMA_THRESHOLD


def test_code_generation_routed_to_harness():
    decision = should_use_managed_agent(_task(operation_type="code_generation"))
    assert decision.executor_type == "harness"


def test_research_always_cma():
    decision = should_use_managed_agent(_task(operation_type="research"))
    assert decision.executor_type == "managed_agent"
    assert decision.score >= 80


def test_document_generation_cma():
    decision = should_use_managed_agent(_task(operation_type="document_generation"))
    assert decision.executor_type == "managed_agent"


def test_long_description_penalty():
    long_desc = "x " * 400  # 800 chars
    decision_long = should_use_managed_agent(_task(operation_type="other", description=long_desc))
    decision_short = should_use_managed_agent(_task(operation_type="other", description="curta"))
    assert decision_short.score > decision_long.score


def test_short_description_bonus():
    decision = should_use_managed_agent(_task(operation_type="other", description="Calcule CBM"))
    # "other" base=60 + short +15 = 75
    assert decision.score >= 70


def test_tight_budget_bonus():
    decision_tight = should_use_managed_agent(_task(operation_type="qa_testing", budget_limit=50))
    decision_normal = should_use_managed_agent(_task(operation_type="qa_testing", budget_limit=500))
    assert decision_tight.score > decision_normal.score


def test_rationale_is_populated():
    decision = should_use_managed_agent(_task(operation_type="research", description="Analise X"))
    assert "research" in decision.rationale
    assert "score=" in decision.rationale


def test_score_clamped_to_100():
    # research(85) + short(+15) = 100 max
    decision = should_use_managed_agent(_task(operation_type="research", description="OK"))
    assert decision.score <= 100


def test_score_clamped_to_zero():
    # orchestration(0) + long desc(-20) = clamped to 0
    long_desc = "y " * 400
    decision = should_use_managed_agent(_task(operation_type="orchestration", description=long_desc))
    assert decision.score >= 0


def test_explicit_operation_type_respected():
    # code_review(65) + short(+15) = 80 → CMA
    decision = should_use_managed_agent(_task(operation_type="code_review", description="Revise isso"))
    assert decision.executor_type == "managed_agent"
    assert decision.operation_type == "code_review"


def test_force_mode_overrides_auto():
    """Garantia que force_mode é respeitado — testado no nível do router."""
    from src.managed_agents.decision_engine import RoutingDecision
    forced = RoutingDecision(
        executor_type="harness",
        score=-1,
        rationale="force_mode=harness",
        operation_type="research",
    )
    assert forced.executor_type == "harness"
    assert forced.score == -1
