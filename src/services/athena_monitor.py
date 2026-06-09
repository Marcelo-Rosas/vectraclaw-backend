"""
src/services/athena_monitor.py — Athena Monitoring Routine (FASE 4).

Consome telemetria de workflows e goals para gerar recommendations
quando métricas indicam problemas ou oportunidades de otimização.

Kinds gerados:
  - prompt_adjust: agente com alto custo/baixa performance (ajuste de prompt)
  - suggest_hire_agent: workflow com alta carga e poucos agentes
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("athena.monitor")

# Thresholds configuráveis (podem vir de env/config no futuro)
_HIGH_COST_PER_TASK_USD = 0.50
_HIGH_ERROR_RATE_PCT = 30.0
_HIGH_BLOCKED_RATE_PCT = 25.0
_LOW_AGENT_DIVERSITY = 2
_MIN_TASKS_TO_ANALYZE = 3
_MIN_WORKFLOW_COST_USD = 1.00


def _should_suggest_prompt_adjust(agent_stats: Dict[str, Any]) -> Optional[str]:
    """Verifica se um agente merece recommendation de ajuste de prompt."""
    total = agent_stats.get("task_count", 0)
    if total < _MIN_TASKS_TO_ANALYZE:
        return None
    errored = agent_stats.get("errored", 0)
    blocked = agent_stats.get("blocked", 0)
    error_rate = (errored / total) * 100
    blocked_rate = (blocked / total) * 100
    if error_rate >= _HIGH_ERROR_RATE_PCT:
        return (
            f"Agente tem {error_rate:.0f}% de tasks com erro "
            f"({errored}/{total}). Revisar prompt e instruções de sistema."
        )
    if blocked_rate >= _HIGH_BLOCKED_RATE_PCT:
        return (
            f"Agente tem {blocked_rate:.0f}% de tasks bloqueadas "
            f"({blocked}/{total}). Possível problema de capacidade ou dependências."
        )
    return None


def _should_suggest_hire_agent(workflow_stats: Dict[str, Any]) -> Optional[str]:
    """Verifica se um workflow merece recommendation de contratar novo agente."""
    total_tasks = workflow_stats.get("total_tasks", 0)
    agent_count = workflow_stats.get("agent_count", 0)
    completed = workflow_stats.get("completed", 0)
    if total_tasks < _MIN_TASKS_TO_ANALYZE:
        return None
    # Se tem muitas tasks e poucos agentes, ou completion rate baixa
    completion_rate = (completed / total_tasks) * 100 if total_tasks else 0
    if agent_count <= _LOW_AGENT_DIVERSITY and total_tasks >= 10:
        return (
            f"Workflow tem {total_tasks} tasks e apenas {agent_count} agente(s). "
            f"Considerar distribuir carga com novo agente especializado."
        )
    if completion_rate < 50 and total_tasks >= 10:
        return (
            f"Workflow tem completion rate de apenas {completion_rate:.0f}% "
            f"({completed}/{total_tasks}). Possível gargalo de capacidade."
        )
    return None


def monitor_workflows(supabase, company_id: str) -> List[Dict[str, Any]]:
    """Executa rotina de monitoramento e gera recommendations.

    Retorna lista de recommendations criadas (ou vazia se nenhuma).
    Evita duplicar recommendation pendente para o mesmo alvo+kind.
    """
    if not supabase:
        logger.warning("monitor_workflows: supabase indisponível")
        return []

    created: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=30)).isoformat()

    # 1. Busca workflows ativos da company com execução recente
    wf_res = (
        supabase.table("workflow_definitions")
        .select("id, slug, name, goal_id, kind")
        .eq("company_id", company_id)
        .eq("is_active", True)
        .execute()
    )
    workflows = wf_res.data or []

    for wf in workflows:
        wf_id = wf["id"]

        # 2. Telemetria do workflow
        tasks_res = (
            supabase.table("tasks")
            .select("id, assigned_to_agent_id, status, cost_usd, created_at")
            .eq("workflow_definition_id", wf_id)
            .gte("created_at", cutoff)
            .execute()
        )
        tasks = tasks_res.data or []
        if not tasks:
            continue

        total_cost = sum(float(t.get("cost_usd") or 0) for t in tasks)
        if total_cost < _MIN_WORKFLOW_COST_USD:
            continue

        agent_stats: Dict[str, Dict[str, Any]] = {}
        status_counts = {"done": 0, "blocked": 0, "errored": 0, "other": 0}
        for t in tasks:
            aid = t.get("assigned_to_agent_id")
            status = t.get("status")
            if aid:
                if aid not in agent_stats:
                    agent_stats[aid] = {
                        "task_count": 0, "done": 0, "blocked": 0, "errored": 0
                    }
                agent_stats[aid]["task_count"] += 1
                if status in agent_stats[aid]:
                    agent_stats[aid][status] += 1
            if status in status_counts:
                status_counts[status] += 1
            else:
                status_counts["other"] += 1

        wf_stats = {
            "total_tasks": len(tasks),
            "completed": status_counts["done"],
            "blocked": status_counts["blocked"],
            "errored": status_counts["errored"],
            "agent_count": len(agent_stats),
            "total_cost": total_cost,
        }

        # 3. Regra: suggest_hire_agent
        hire_rationale = _should_suggest_hire_agent(wf_stats)
        if hire_rationale:
            rec = _insert_recommendation_if_not_pending(
                supabase,
                company_id=company_id,
                kind="suggest_hire_agent",
                target_agent_id=None,
                triggered_by_goal_id=wf.get("goal_id"),
                title=f"Capacidade insuficiente no workflow '{wf.get('name') or wf.get('slug')}'",
                rationale=hire_rationale,
                proposed_changes={"workflow_definition_id": wf_id, "current_agents": len(agent_stats)},
                confidence=0.75,
            )
            if rec:
                created.append(rec)

        # 4. Regra: prompt_adjust por agente
        for aid, stats in agent_stats.items():
            adjust_rationale = _should_suggest_prompt_adjust(stats)
            if adjust_rationale:
                rec = _insert_recommendation_if_not_pending(
                    supabase,
                    company_id=company_id,
                    kind="prompt_adjust",
                    target_agent_id=aid,
                    triggered_by_goal_id=wf.get("goal_id"),
                    title=f"Ajuste de prompt sugerido para agente {aid[:8]}...",
                    rationale=adjust_rationale,
                    proposed_changes={
                        "agent_id": aid,
                        "workflow_definition_id": wf_id,
                        "stats": stats,
                    },
                    confidence=min(0.60 + (stats.get("errored", 0) * 0.05), 0.95),
                )
                if rec:
                    created.append(rec)

    logger.info(
        "monitor_workflows: company=%s workflows_analyzed=%d recommendations_created=%d",
        company_id, len(workflows), len(created),
    )
    return created


def _insert_recommendation_if_not_pending(
    supabase,
    company_id: str,
    kind: str,
    target_agent_id: Optional[str],
    triggered_by_goal_id: Optional[str],
    title: str,
    rationale: str,
    proposed_changes: Dict[str, Any],
    confidence: float,
) -> Optional[Dict[str, Any]]:
    """Insere recommendation se não existir uma pendente do mesmo kind+alvo."""
    # Verifica duplicata pendente
    q = (
        supabase.table("athena_recommendations")
        .select("id")
        .eq("company_id", company_id)
        .eq("kind", kind)
        .eq("status", "pending")
    )
    if target_agent_id:
        q = q.eq("target_agent_id", target_agent_id)
    else:
        q = q.is_("target_agent_id", "null")
    existing = q.limit(1).execute()
    if existing.data:
        logger.debug(
            "recommendation skipped: pending %s already exists for target=%s",
            kind, target_agent_id,
        )
        return None

    row = {
        "company_id": company_id,
        "kind": kind,
        "target_agent_id": target_agent_id,
        "triggered_by_goal_id": triggered_by_goal_id,
        "title": title,
        "rationale": rationale,
        "proposed_changes_json": proposed_changes,
        "citations": [],
        "confidence": round(confidence, 4),
        "estimated_effort": "S",
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        res = supabase.table("athena_recommendations").insert(row).execute()
        if res.data:
            logger.info(
                "recommendation created: id=%s kind=%s target=%s",
                res.data[0]["id"], kind, target_agent_id,
            )
            return res.data[0]
    except Exception as e:
        logger.error("insert_recommendation failed: %s", e)
    return None
