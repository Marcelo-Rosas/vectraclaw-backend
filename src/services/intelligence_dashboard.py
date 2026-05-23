"""Agregações cross-company para GET /api/intelligence/dashboard (VEC-168)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from src.services.company_profile import should_list_all_companies
from src.tenant_ids import company_row_public_id

_INTELLIGENCE_ROLES = frozenset({"platform_admin", "consultant", "admin"})
_ACTIVE_AGENT_STATUSES = frozenset({"idle", "working"})
_TERMINAL_TASK_STATUSES = frozenset({"done", "errored", "blocked"})
_WEEKDAY_LABELS = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
_DURATION_BUCKETS: Tuple[Tuple[str, int, Optional[int]], ...] = (
    ("0-30s", 0, 30_000),
    ("30s-2m", 30_000, 120_000),
    ("2m-10m", 120_000, 600_000),
    ("10m+", 600_000, None),
)


def assert_intelligence_access(role: Optional[str]) -> None:
    """Apenas roles com visão portfolio cross-company."""
    if (role or "").lower() not in _INTELLIGENCE_ROLES:
        raise HTTPException(
            status_code=403,
            detail="intelligence_requires_platform_admin_consultant_or_admin",
        )


def resolve_company_scope(
    role: Optional[str],
    caller_company_id: Optional[str],
) -> Optional[List[str]]:
    """
    None = todas as companies (espelha get_companies).
    Lista de um id = tenant único.
    """
    if should_list_all_companies(role):
        return None
    if caller_company_id:
        return [str(caller_company_id)]
    # admin sem company_id no JWT — mesma regra que listagem global
    if (role or "").lower() == "admin":
        return None
    return []


def _parse_dt(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    s = str(raw).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _week_start(dt: datetime) -> datetime:
    """Segunda-feira 00:00 UTC da semana de dt."""
    d = dt.astimezone(timezone.utc)
    monday = d - timedelta(days=d.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def _week_label(week_start: datetime) -> str:
    return week_start.strftime("%d/%m")


def _duration_bucket(ms: Optional[int]) -> str:
    if ms is None or ms < 0:
        return "0-30s"
    for label, lo, hi in _DURATION_BUCKETS:
        if hi is None:
            if ms >= lo:
                return label
        elif lo <= ms < hi:
            return label
    return "10m+"


def _trend(current: float, previous: float) -> str:
    if current > previous * 1.05:
        return "up"
    if current < previous * 0.95:
        return "down"
    return "stable"


def _fetch_companies(client: Any, company_ids: Optional[List[str]]) -> Dict[str, str]:
    q = client.table("companies").select("company_id,name")
    if company_ids:
        q = q.in_("company_id", company_ids)
    res = q.execute()
    out: Dict[str, str] = {}
    for row in res.data or []:
        cid = company_row_public_id(row)
        if cid:
            out[str(cid)] = str(row.get("name") or cid)
    return out


def _fetch_rows(
    client: Any,
    table: str,
    columns: str,
    company_ids: Optional[List[str]],
    since_iso: str,
    date_column: str = "created_at",
) -> List[Dict[str, Any]]:
    q = client.table(table).select(columns).gte(date_column, since_iso)
    if company_ids:
        q = q.in_("company_id", company_ids)
    res = q.execute()
    return list(res.data or [])


def build_intelligence_dashboard(
    client: Any,
    *,
    caller_role: Optional[str],
    caller_company_id: Optional[str],
    weeks: int = 8,
) -> Dict[str, Any]:
    """Monta payload camelCase para o frontend."""
    assert_intelligence_access(caller_role)
    company_scope = resolve_company_scope(caller_role, caller_company_id)
    if company_scope is not None and not company_scope:
        return _empty_dashboard()

    weeks = max(4, min(weeks, 16))
    now = datetime.now(timezone.utc)
    since_weeks = (now - timedelta(days=weeks * 7)).isoformat()
    since_30d_dt = now - timedelta(days=30)
    since_7d_dt = now - timedelta(days=7)

    company_names = _fetch_companies(client, company_scope)
    if not company_names:
        return _empty_dashboard()

    company_ids_list = list(company_names.keys())

    task_rows = _fetch_rows(
        client,
        "tasks",
        "id,company_id,status,created_at,cost_usd,assigned_to_agent_id",
        company_ids_list,
        since_weeks,
    )
    agent_rows = _fetch_rows(
        client,
        "agents",
        "id,company_id,name,status",
        company_ids_list,
        "1970-01-01T00:00:00Z",
    )
    hb_rows = _fetch_rows(
        client,
        "heartbeats",
        "company_id,agent_id,tokens_used,created_at",
        company_ids_list,
        since_weeks,
    )
    run_rows = _fetch_rows(
        client,
        "runs",
        "company_id,agent_id,duration_ms,cost_usd,started_at",
        company_ids_list,
        since_30d_dt.isoformat(),
        date_column="started_at",
    )

    agent_meta: Dict[str, Dict[str, str]] = {}
    active_by_company: Dict[str, int] = defaultdict(int)
    for row in agent_rows:
        aid = str(row.get("id") or "")
        cid = str(row.get("company_id") or "")
        if not aid or not cid:
            continue
        agent_meta[aid] = {
            "agentName": str(row.get("name") or aid[:8]),
            "companyId": cid,
            "companyName": company_names.get(cid, cid),
        }
        if str(row.get("status") or "") in _ACTIVE_AGENT_STATUSES:
            active_by_company[cid] += 1

    week_starts = [
        _week_start(now - timedelta(days=7 * (weeks - 1 - i))) for i in range(weeks)
    ]
    week_labels = [_week_label(w) for w in week_starts]
    current_week = _week_start(now)
    prev_week = current_week - timedelta(days=7)

    tasks_by_week: Dict[datetime, int] = defaultdict(int)
    tokens_by_week: Dict[datetime, int] = defaultdict(int)
    burn_by_week_company: Dict[datetime, Dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    tasks_this_week: Dict[str, int] = defaultdict(int)
    tasks_prev_week: Dict[str, int] = defaultdict(int)
    tokens_this_week: Dict[str, int] = defaultdict(int)
    tokens_prev_week: Dict[str, int] = defaultdict(int)
    status_counts: Dict[str, int] = defaultdict(int)
    terminal_done = 0
    terminal_total = 0
    productivity: Dict[str, int] = defaultdict(int)
    heatmap: Dict[Tuple[str, int], int] = defaultdict(int)
    task_cost_by_agent: Dict[str, float] = defaultdict(float)

    for row in task_rows:
        cid = str(row.get("company_id") or "")
        created = _parse_dt(row.get("created_at"))
        if not cid or not created:
            continue
        ws = _week_start(created)
        tasks_by_week[ws] += 1
        if ws == current_week:
            tasks_this_week[cid] += 1
        elif ws == prev_week:
            tasks_prev_week[cid] += 1
        if created >= since_30d_dt:
            st = str(row.get("status") or "backlog")
            status_counts[st] += 1
            if st in _TERMINAL_TASK_STATUSES:
                terminal_total += 1
                if st == "done":
                    terminal_done += 1
            if st == "done":
                aid = str(row.get("assigned_to_agent_id") or "")
                if aid:
                    productivity[aid] += 1
            cost = float(row.get("cost_usd") or 0)
            aid = str(row.get("assigned_to_agent_id") or "")
            if aid and cost > 0:
                task_cost_by_agent[aid] += cost
        if created >= since_7d_dt:
            wd = created.weekday()
            heatmap[(cid, wd)] += 1

    tokens_month = 0
    for row in hb_rows:
        cid = str(row.get("company_id") or "")
        created = _parse_dt(row.get("created_at"))
        if not cid or not created:
            continue
        tokens = int(row.get("tokens_used") or 0)
        ws = _week_start(created)
        tokens_by_week[ws] += tokens
        burn_by_week_company[ws][cid] += tokens
        if ws == current_week:
            tokens_this_week[cid] += tokens
        elif ws == prev_week:
            tokens_prev_week[cid] += tokens
        if created >= now - timedelta(days=30):
            tokens_month += tokens

    run_cost_by_agent: Dict[str, float] = defaultdict(float)
    duration_hist: Dict[str, int] = defaultdict(int)
    for row in run_rows:
        aid = str(row.get("agent_id") or "")
        cost = float(row.get("cost_usd") or 0)
        if aid:
            run_cost_by_agent[aid] += cost
        ms = row.get("duration_ms")
        try:
            duration_hist[_duration_bucket(int(ms) if ms is not None else None)] += 1
        except (TypeError, ValueError):
            duration_hist["0-30s"] += 1

    cost_by_agent = dict(run_cost_by_agent)
    for aid, c in task_cost_by_agent.items():
        cost_by_agent[aid] = cost_by_agent.get(aid, 0.0) + c

    company_volume: Dict[str, int] = defaultdict(int)
    for ws in week_starts:
        for cid, n in burn_by_week_company[ws].items():
            company_volume[cid] += n
    top_company_ids = [
        cid
        for cid, _ in sorted(
            company_volume.items(), key=lambda x: x[1], reverse=True
        )[:5]
    ]
    burn_series_keys = top_company_ids + ["outros"]

    weekly_tasks = [
        {"week": week_labels[i], "tasks": tasks_by_week.get(week_starts[i], 0)}
        for i in range(weeks)
    ]
    weekly_tokens = [
        {"week": week_labels[i], "tokens": tokens_by_week.get(week_starts[i], 0)}
        for i in range(weeks)
    ]

    burn_by_company: List[Dict[str, Any]] = []
    for i, ws in enumerate(week_starts):
        point: Dict[str, Any] = {"week": week_labels[i]}
        by_c = burn_by_week_company[ws]
        others = 0
        for cid in company_ids_list:
            val = by_c.get(cid, 0)
            key = cid if cid in top_company_ids else "outros"
            if cid in top_company_ids:
                point[cid] = point.get(cid, 0) + val
            else:
                others += val
        if others:
            point["outros"] = others
        burn_by_company.append(point)

    companies_out: List[Dict[str, Any]] = []
    for cid, name in sorted(company_names.items(), key=lambda x: x[1].lower()):
        tw = tasks_this_week[cid]
        pw = tasks_prev_week[cid]
        tt = tokens_this_week[cid]
        pt = tokens_prev_week[cid]
        score = tw + tt / 1000.0
        prev_score = pw + pt / 1000.0
        companies_out.append(
            {
                "id": cid,
                "name": name,
                "activeAgents": active_by_company.get(cid, 0),
                "tasksThisWeek": tw,
                "tokensThisWeek": tt,
                "trend": _trend(score, prev_score),
            }
        )

    success_rate = (
        round(terminal_done / terminal_total, 4) if terminal_total > 0 else 0.0
    )

    def _top_agents_productivity() -> List[Dict[str, Any]]:
        ranked = sorted(
            productivity.items(), key=lambda x: x[1], reverse=True
        )[:5]
        out: List[Dict[str, Any]] = []
        for aid, count in ranked:
            meta = agent_meta.get(aid, {})
            out.append(
                {
                    "agentId": aid,
                    "agentName": meta.get("agentName", aid[:8]),
                    "companyId": meta.get("companyId", ""),
                    "companyName": meta.get("companyName", ""),
                    "tasksDone": count,
                }
            )
        return out

    def _top_agents_cost() -> List[Dict[str, Any]]:
        ranked = sorted(
            cost_by_agent.items(), key=lambda x: x[1], reverse=True
        )[:5]
        out: List[Dict[str, Any]] = []
        for aid, cost in ranked:
            if cost <= 0:
                continue
            meta = agent_meta.get(aid, {})
            out.append(
                {
                    "agentId": aid,
                    "agentName": meta.get("agentName", aid[:8]),
                    "companyId": meta.get("companyId", ""),
                    "companyName": meta.get("companyName", ""),
                    "costUsd": round(cost, 6),
                }
            )
        return out[:5]

    activity_heatmap: List[Dict[str, Any]] = []
    for cid, name in company_names.items():
        for wd in range(7):
            activity_heatmap.append(
                {
                    "companyId": cid,
                    "companyName": name,
                    "weekday": _WEEKDAY_LABELS[wd],
                    "count": heatmap.get((cid, wd), 0),
                }
            )

    totals = {
        "companies": len(company_names),
        "activeAgents": sum(active_by_company.values()),
        "tasksThisWeek": sum(tasks_this_week.values()),
        "tokensThisMonth": tokens_month,
        "successRate": success_rate,
    }

    return {
        "totals": totals,
        "companies": companies_out,
        "weeklyTasks": weekly_tasks,
        "weeklyTokens": weekly_tokens,
        "burnByCompany": burn_by_company,
        "burnSeriesKeys": burn_series_keys,
        "taskStatusPie": [
            {"status": k, "count": v}
            for k, v in sorted(status_counts.items(), key=lambda x: -x[1])
        ],
        "runDurationHistogram": [
            {"bucket": label, "count": duration_hist.get(label, 0)}
            for label, _, _ in _DURATION_BUCKETS
        ],
        "activityHeatmap": activity_heatmap,
        "topAgentsByProductivity": _top_agents_productivity(),
        "topAgentsByCost": _top_agents_cost(),
    }


def _empty_dashboard() -> Dict[str, Any]:
    return {
        "totals": {
            "companies": 0,
            "activeAgents": 0,
            "tasksThisWeek": 0,
            "tokensThisMonth": 0,
            "successRate": 0.0,
        },
        "companies": [],
        "weeklyTasks": [],
        "weeklyTokens": [],
        "burnByCompany": [],
        "burnSeriesKeys": [],
        "taskStatusPie": [],
        "runDurationHistogram": [
            {"bucket": label, "count": 0} for label, _, _ in _DURATION_BUCKETS
        ],
        "activityHeatmap": [],
        "topAgentsByProductivity": [],
        "topAgentsByCost": [],
    }
