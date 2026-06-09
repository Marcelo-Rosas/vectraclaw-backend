"""
src/services/telemetry_aggregation.py — Agregação de telemetria para governança (FASE 4).

Provê funções para computar métricas de custo e SLA por workflow, goal e step.
Consome as views materializadas do schema vectraclip (FASE 4 migration)
ou calcula dinamicamente via Supabase/PostgREST.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("telemetry")


def get_workflow_telemetry(supabase, workflow_id: str) -> Dict[str, Any]:
    """Retorna telemetria completa de um workflow_definition.

    Inclui:
      - Custo total (tasks + heartbeats)
      - Contagem de tasks por status
      - SLA compliance por step
      - Resumo de agentes envolvidos
      - Tendência de custo (últimos 30 dias vs total)
    """
    if not supabase:
        return {"error": "supabase_not_available"}

    # 1. Dados do workflow
    wf_res = (
        supabase.table("workflow_definitions")
        .select("id, slug, name, goal_id, kind, created_at")
        .eq("id", workflow_id)
        .limit(1)
        .execute()
    )
    if not wf_res.data:
        return {"error": "workflow_not_found"}
    workflow = wf_res.data[0]

    # 2. Custo agregado (via view cost_by_workflow)
    cost_res = (
        supabase.table("cost_by_workflow")
        .select("*")
        .eq("workflow_definition_id", workflow_id)
        .limit(1)
        .execute()
    )
    cost_row = cost_res.data[0] if cost_res.data else {}

    # 3. SLA compliance por step (via view sla_compliance_by_step)
    sla_res = (
        supabase.table("sla_compliance_by_step")
        .select("*")
        .eq("workflow_definition_id", workflow_id)
        .execute()
    )
    sla_steps = sla_res.data or []

    # 4. Agentes envolvidos (distinct assigned_to_agent_id nas tasks do workflow)
    agents_res = (
        supabase.table("tasks")
        .select("assigned_to_agent_id, status")
        .eq("workflow_definition_id", workflow_id)
        .not_.is_("assigned_to_agent_id", "null")
        .execute()
    )
    agent_stats: Dict[str, Dict[str, Any]] = {}
    for row in (agents_res.data or []):
        aid = row.get("assigned_to_agent_id")
        if not aid:
            continue
        if aid not in agent_stats:
            agent_stats[aid] = {"task_count": 0, "done": 0, "blocked": 0, "errored": 0}
        agent_stats[aid]["task_count"] += 1
        status = row.get("status")
        if status == "done":
            agent_stats[aid]["done"] += 1
        elif status == "blocked":
            agent_stats[aid]["blocked"] += 1
        elif status == "errored":
            agent_stats[aid]["errored"] += 1

    # 5. Resumo de custo dos últimos 30 dias
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    recent_tasks_res = (
        supabase.table("tasks")
        .select("cost_usd")
        .eq("workflow_definition_id", workflow_id)
        .gte("created_at", cutoff)
        .execute()
    )
    recent_cost = sum(float(r.get("cost_usd") or 0) for r in (recent_tasks_res.data or []))

    recent_hb_res = (
        supabase.table("heartbeats")
        .select("cost_usd")
        .eq("workflow_definition_id", workflow_id)
        .gte("created_at", cutoff)
        .execute()
    )
    # heartbeats não têm workflow_definition_id diretamente; usamos JOIN implícito via task
    # Fallback: calcular via task_id das tasks do workflow
    task_ids = [
        r["id"] for r in (
            supabase.table("tasks")
            .select("id")
            .eq("workflow_definition_id", workflow_id)
            .execute()
            .data or []
        )
    ]
    recent_hb_cost = 0.0
    if task_ids:
        # PostgREST .in_ suporta lista
        hb_res = (
            supabase.table("heartbeats")
            .select("cost_usd")
            .in_("task_id", task_ids)
            .gte("created_at", cutoff)
            .execute()
        )
        recent_hb_cost = sum(float(r.get("cost_usd") or 0) for r in (hb_res.data or []))

    total_cost = float(cost_row.get("total_cost_usd") or 0)
    recent_total = recent_cost + recent_hb_cost

    return {
        "workflow_id": workflow_id,
        "slug": workflow.get("slug"),
        "name": workflow.get("name"),
        "goal_id": workflow.get("goal_id"),
        "kind": workflow.get("kind"),
        "cost": {
            "total_usd": round(total_cost, 8),
            "tasks_usd": round(float(cost_row.get("tasks_cost_usd") or 0), 8),
            "heartbeats_usd": round(float(cost_row.get("heartbeats_cost_usd") or 0), 8),
            "avg_task_usd": round(float(cost_row.get("avg_task_cost_usd") or 0), 8),
            "last_30_days_usd": round(recent_total, 8),
            "last_30_days_pct": round((recent_total / total_cost * 100), 2) if total_cost > 0 else 0,
        },
        "tasks": {
            "total": int(cost_row.get("total_tasks") or 0),
            "completed": int(cost_row.get("completed_tasks") or 0),
            "blocked": int(cost_row.get("blocked_tasks") or 0),
            "errored": int(cost_row.get("errored_tasks") or 0),
        },
        "sla_compliance": {
            "steps": [
                {
                    "step_id": s.get("workflow_step_id"),
                    "slug": s.get("step_slug"),
                    "name": s.get("step_name"),
                    "sla_hours": s.get("sla_horas"),
                    "total_tasks": int(s.get("total_tasks") or 0),
                    "completed_tasks": int(s.get("completed_tasks") or 0),
                    "avg_completion_hours": round(float(s.get("avg_completion_hours") or 0), 2) if s.get("avg_completion_hours") else None,
                    "sla_met_count": int(s.get("sla_met_count") or 0),
                    "compliance_pct": round(float(s.get("sla_compliance_pct") or 0), 2) if s.get("sla_compliance_pct") else None,
                }
                for s in sla_steps
            ],
            "overall_pct": (
                round(
                    sum(
                        float(s.get("sla_compliance_pct") or 0)
                        for s in sla_steps
                        if s.get("sla_compliance_pct") is not None
                    )
                    / len([s for s in sla_steps if s.get("sla_compliance_pct") is not None]),
                    2,
                )
                if any(s.get("sla_compliance_pct") is not None for s in sla_steps)
                else None
            ),
        },
        "agents": [
            {
                "agent_id": aid,
                "task_count": stats["task_count"],
                "done": stats["done"],
                "blocked": stats["blocked"],
                "errored": stats["errored"],
            }
            for aid, stats in agent_stats.items()
        ],
    }


def get_goal_telemetry(supabase, goal_id: str) -> Dict[str, Any]:
    """Retorna telemetria agregada por goal."""
    if not supabase:
        return {"error": "supabase_not_available"}

    res = (
        supabase.table("cost_by_goal")
        .select("*")
        .eq("goal_id", goal_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return {"error": "goal_not_found_or_no_data"}
    row = res.data[0]
    return {
        "goal_id": goal_id,
        "title": row.get("goal_title"),
        "total_cost_usd": round(float(row.get("total_cost_usd") or 0), 8),
        "tasks_cost_usd": round(float(row.get("tasks_cost_usd") or 0), 8),
        "heartbeats_cost_usd": round(float(row.get("heartbeats_cost_usd") or 0), 8),
        "total_tasks": int(row.get("total_tasks") or 0),
        "completed_tasks": int(row.get("completed_tasks") or 0),
        "blocked_tasks": int(row.get("blocked_tasks") or 0),
    }
