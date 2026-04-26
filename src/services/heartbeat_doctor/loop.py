"""
VEC-199b — Loop do Heartbeat Doctor.

Responsabilidades:
- A cada tick (30s), scanear agentes e rodar detectores S1..S6.
- Para cada sintoma, aplicar fix automático (LOW/MEDIUM) ou escalar ao conselho (HIGH).
- Persistir tudo em `vectraclip.incidents` via `store.py`.
- Gravar cada transição (detected, fix_executed, fix_failed) em `vectraclip.incident_audit`
  via `audit.py` usando a matriz de 6 eventos.

Fallback em memória (`app.state.incidents` / `incident_audit`) é usado apenas em
ambiente SEM Supabase (smoke test local sem creds) — não duplica gravação
quando o DB está disponível.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from postgrest.exceptions import APIError

from src.models import Agent, Heartbeat, Task

from . import audit as audit_mod
from . import store as store_mod
from .fixes import SYMPTOM_TO_FIX, Fix
from .rate_limit import rate_limiter
from .symptoms import (
    BURN_RATE_HARD_CAP_MULT,
    HB_GAP_THRESHOLD,
    SENTINEL_THRESHOLD,
    TASK_STALE_THRESHOLD,
    Symptom,
)

logger = logging.getLogger("HeartbeatDoctor")


# =====================================================================
# Severity scoring (D1..D5) — mesma fórmula da V1
# =====================================================================


def bucket(score: int) -> str:
    if score <= 2:
        return "low"
    if score <= 5:
        return "medium"
    return "high"


def calc_severity(
    symptom: Symptom,
    fix: Fix,
    agent: Dict[str, Any],
    company_tier: str,
) -> int:
    # D1: Blast Radius — V1 sempre 1 agente isolado
    d1 = 0

    # D2: Reversibilidade
    d2_map = {
        Fix.RESET_HB_LOOP: 0,
        Fix.CLEAR_CONTEXT_CACHE: 0,
        Fix.REGEN_JWT: 0,
        Fix.SKIP_TASK: 1,
        Fix.RESTART_ADAPTER: 1,
        Fix.DETECT_ONLY: 2,
    }
    d2 = d2_map.get(fix, 2)

    # D3: Confiança no diagnóstico
    d3 = 0
    if symptom == Symptom.UNKNOWN_SENTINEL:
        d3 = 2
    elif fix == Fix.DETECT_ONLY:
        d3 = 1

    # D4: Custo financeiro
    d4 = 0
    token_budget = agent.get("tokenBudget", 0)
    current_burn = agent.get("currentBurnRate", 0)
    if token_budget > 0 and current_burn > (token_budget * 0.1):
        d4 = 1

    # D5: Company Tier (requer `companies.tier` do VEC-199b migration)
    d5_map = {"trial": 0, "standard": 1, "enterprise": 2}
    d5 = d5_map.get(company_tier, 0)

    return min(10, d1 + d2 + d3 + d4 + d5)


# =====================================================================
# Detectores
# =====================================================================


async def run_all_detectors(
    agent: Dict[str, Any],
    last_hb: Optional[Dict[str, Any]],
    active_task: Optional[Dict[str, Any]],
) -> List[Symptom]:
    """
    Roda os 6 detectores. S5 (`burn_rate_anomaly`) dispara mesmo em agentes
    offline — VEC-199b §Fix 5.
    """
    symptoms: List[Symptom] = []
    now = datetime.now(timezone.utc)
    status = agent.get("status")
    is_offline = status in ("offline", "paused")

    # S1: heartbeat_gap — só faz sentido para agentes supostamente vivos.
    if not is_offline and last_hb:
        hb_created_at = datetime.fromisoformat(
            last_hb["createdAt"].replace("Z", "+00:00")
        )
        if now - hb_created_at > HB_GAP_THRESHOLD and last_hb["status"] != "error":
            symptoms.append(Symptom.HEARTBEAT_GAP)

    # S2: task_claim_stale — igual a S1, não faz sentido para offline.
    if not is_offline and active_task and active_task["status"] == "in_progress":
        claimed_at_str = active_task.get("claimedAt")
        if claimed_at_str:
            claimed_at = datetime.fromisoformat(
                claimed_at_str.replace("Z", "+00:00")
            )
            if now - claimed_at > TASK_STALE_THRESHOLD:
                symptoms.append(Symptom.TASK_CLAIM_STALE)

    # S3: jwt_expired — sinal vem do log_excerpt (aplicável em qualquer status).
    if last_hb and "401" in last_hb.get("logExcerpt", ""):
        symptoms.append(Symptom.JWT_EXPIRED)

    # S4: adapter_unresponsive — só quando último HB foi erro.
    if last_hb and last_hb["status"] == "error":
        excerpt = last_hb.get("logExcerpt", "").lower()
        if any(word in excerpt for word in ["adapter", "timeout", "50"]):
            symptoms.append(Symptom.ADAPTER_UNRESPONSIVE)

    # S5: burn_rate_anomaly — VEC-199b §Fix 5: DEVE monitorar offline também.
    # Um agente que foi killed com burn_rate alto ainda é evidência de pós-mortem.
    burn = agent.get("currentBurnRate", 0) or 0
    budget = agent.get("tokenBudget", 0) or 0
    if burn < 0 or (budget > 0 and burn > (budget * BURN_RATE_HARD_CAP_MULT)):
        symptoms.append(Symptom.BURN_RATE_ANOMALY)

    # S6: unknown_sentinel — só quando agente está supostamente working.
    if not symptoms and status == "working" and last_hb:
        hb_created_at = datetime.fromisoformat(
            last_hb["createdAt"].replace("Z", "+00:00")
        )
        if now - hb_created_at > SENTINEL_THRESHOLD:
            symptoms.append(Symptom.UNKNOWN_SENTINEL)

    return symptoms


# =====================================================================
# Execução de fixes
# =====================================================================


ADAPTER_STATE: Dict[str, Any] = {}  # cache-lite compartilhado (F2/F5)


async def execute_fix(fix: Fix, agent_id: str, api_state: Any) -> bool:
    """Executa o fix lógico. Retorna True se aplicado, False caso contrário."""
    logger.info(f"[doctor] executing fix={fix.value} agent={agent_id}")

    if fix == Fix.RESET_HB_LOOP:
        if hasattr(api_state, "agent_runtime"):
            api_state.agent_runtime.pop(agent_id, None)
        return True

    if fix == Fix.CLEAR_CONTEXT_CACHE:
        ADAPTER_STATE.pop(agent_id, None)
        return True

    if fix == Fix.REGEN_JWT:
        # V1: marca que o adapter deve re-autenticar na próxima chamada.
        return True

    if fix == Fix.RESTART_ADAPTER:
        ADAPTER_STATE.pop(agent_id, None)
        if hasattr(api_state, "agent_runtime"):
            api_state.agent_runtime.pop(agent_id, None)
        return True

    if fix == Fix.SKIP_TASK:
        # Execução direta é feita em `handle_symptom` (precisa do client + task_id).
        return True

    if fix == Fix.DETECT_ONLY:
        return True

    return False


# =====================================================================
# Persistência — delega em store.py / audit.py
# =====================================================================


def _build_incident_row(
    *,
    incident_id: str,
    agent: Dict[str, Any],
    symptom: Symptom,
    fix: Optional[Fix],
    severity: str,
    score: int,
    snapshot: Dict[str, Any],
    decision: str,
    undo_expires: Optional[str],
) -> Dict[str, Any]:
    return {
        "id": incident_id,
        "company_id": agent["companyId"],
        "agent_id": agent["id"],
        "symptom": symptom.value if isinstance(symptom, Symptom) else symptom,
        "fix_applied": (fix.value if isinstance(fix, Fix) else fix) if fix else None,
        "severity": severity,
        "severity_score": score,
        "agent_snapshot": snapshot,
        "decision": decision,
        "undo_expires_at": undo_expires,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def create_incident_record(
    agent: Dict[str, Any],
    symptom: Symptom,
    fix: Optional[Fix],
    severity: str,
    score: int,
    snapshot: Dict[str, Any],
    decision: str,
    *,
    undo_expires: Optional[str] = None,
    api_state: Any = None,
    event: str = audit_mod.EVENT_DETECTED,
    extra_payload: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Insere o incidente + grava evento de audit. Retorna o incident_id.

    - Tenta DB primeiro (via store). Em falha, cai para memória (`api_state`).
    - Audit é gravado SEMPRE que houver persistência (DB ou memória).
    """
    incident_id = str(uuid.uuid4())
    row = _build_incident_row(
        incident_id=incident_id,
        agent=agent,
        symptom=symptom,
        fix=fix,
        severity=severity,
        score=score,
        snapshot=snapshot,
        decision=decision,
        undo_expires=undo_expires,
    )

    persisted_in_db = False
    try:
        incident = await store_mod.insert_incident(row)
        if incident is not None:
            incident_id = incident.id
            persisted_in_db = True
    except APIError as exc:
        logger.warning(f"[doctor] incident insert API error: {exc}")
    except Exception as exc:
        logger.warning(f"[doctor] incident insert failed: {exc}")

    # Fallback em memória APENAS quando DB não aceitou (sem creds ou erro).
    if not persisted_in_db and api_state is not None and hasattr(api_state, "incidents"):
        api_state.incidents.append(row)

    payload = {"snapshot": snapshot}
    if extra_payload:
        payload.update(extra_payload)

    await audit_mod.append_audit(
        incident_id,
        event=event,
        actor="doctor",
        payload=payload,
    )
    if not persisted_in_db and api_state is not None and hasattr(api_state, "incident_audit"):
        api_state.incident_audit.append(
            {
                "incident_id": incident_id,
                "event": event,
                "actor": "doctor",
                "payload": payload,
            }
        )

    return incident_id


# =====================================================================
# Dispatcher por sintoma
# =====================================================================


async def handle_symptom(
    client,
    agent_data: Dict[str, Any],
    symptom: Symptom,
    company_tier: str,
    api_state: Any,
) -> None:
    candidates = SYMPTOM_TO_FIX.get(symptom, [Fix.DETECT_ONLY])
    agent_id = agent_data["id"]
    snapshot = dict(agent_data)

    score = calc_severity(symptom, candidates[0], agent_data, company_tier)
    severity = bucket(score)

    # Rate-limit: muitos auto-heal no mesmo agente → força escalonamento.
    if severity != "high" and await rate_limiter.exceeded(agent_id):
        severity = "high"
        snapshot["forced_high_reason"] = "rate_limit_exceeded"

    if severity == "high" or candidates[0] == Fix.DETECT_ONLY:
        await create_incident_record(
            agent_data,
            symptom,
            None,
            severity,
            score,
            snapshot,
            "pending_council",
            api_state=api_state,
            event=audit_mod.EVENT_DETECTED,
        )
        return

    # LOW / MEDIUM — tenta fixes em ordem.
    last_error: Optional[str] = None
    for fix in candidates:
        try:
            if fix == Fix.SKIP_TASK and agent_data.get("taskId") and client is not None:
                client.table("tasks").update({"status": "skipped"}).eq(
                    "id", agent_data["taskId"]
                ).execute()
            else:
                ok = await execute_fix(fix, agent_id, api_state)
                if not ok:
                    continue

            await rate_limiter.record(agent_id)

            undo_expires: Optional[str] = None
            if severity == "medium":
                undo_expires = (
                    datetime.now(timezone.utc) + timedelta(minutes=5)
                ).isoformat()

            await create_incident_record(
                agent_data,
                symptom,
                fix,
                severity,
                score,
                snapshot,
                "auto_healed",
                undo_expires=undo_expires,
                api_state=api_state,
                event=audit_mod.EVENT_FIX_EXECUTED,
                extra_payload={"fix": fix.value},
            )
            return
        except Exception as exc:
            last_error = f"{fix.value}: {exc}"
            logger.error(f"[doctor] fix {fix} failed: {exc}")
            # Registrar falha do fix no audit — sem criar incidente novo ainda.
            # O incidente será criado no caso de "all fixes failed" abaixo.
            continue

    # Esgotou candidatos → escala pra HIGH (conselho).
    escalation_payload: Dict[str, Any] = {"escalation_reason": "all_fixes_failed"}
    if last_error:
        escalation_payload["last_error"] = last_error
    await create_incident_record(
        agent_data,
        symptom,
        None,
        "high",
        max(score, 6),
        {**snapshot, **escalation_payload},
        "pending_council",
        api_state=api_state,
        event=audit_mod.EVENT_FIX_FAILED,
        extra_payload=escalation_payload,
    )


# =====================================================================
# Tick scheduler
# =====================================================================


async def doctor_tick(client, api_state: Any) -> None:
    """
    Um tick = um scan em todos os agentes (inclusive offline — VEC-199b §Fix 5).
    """
    try:
        agents: List[Dict[str, Any]] = []
        try:
            # VEC-199b §Fix 5: não filtrar offline no listing — S5 precisa ver tudo.
            res = client.table("agents").select("*").execute()
            for row in res.data:
                try:
                    agents.append(Agent(**row).to_zod_dict())
                except Exception as model_err:
                    logger.error(
                        f"[doctor] skip agent row id={row.get('id')}: {model_err}"
                    )
        except Exception as exc:
            logger.warning(f"[doctor] DB agent list failed: {exc}")
            from src.api import MOCK_AGENTS
            agents = list(MOCK_AGENTS)

        if not agents:
            return

        for agent in agents:
            agent_id = agent.get("id")
            try:
                last_hb: Optional[Dict[str, Any]] = None
                active_task: Optional[Dict[str, Any]] = None
                try:
                    hb_res = (
                        client.table("heartbeats")
                        .select("*")
                        .eq("agent_id", agent_id)
                        .order("created_at", desc=True)
                        .limit(1)
                        .execute()
                    )
                    task_res = (
                        client.table("tasks")
                        .select("*")
                        .eq("assigned_to_agent_id", agent_id)
                        .eq("status", "in_progress")
                        .limit(1)
                        .execute()
                    )
                    last_hb = (
                        Heartbeat(**hb_res.data[0]).to_zod_dict()
                        if hb_res.data
                        else None
                    )
                    active_task = (
                        Task(**task_res.data[0]).to_zod_dict()
                        if task_res.data
                        else None
                    )
                    # VEC-183 — emite heartbeat WS para sockets conectados na company
                    if last_hb:
                        try:
                            from src.ws_manager import manager as ws_manager
                            company_id = agent.get("companyId")
                            if company_id and ws_manager.connection_count(company_id) > 0:
                                ws_manager.broadcast_nowait(
                                    company_id,
                                    {"type": "heartbeat", "payload": last_hb},
                                )
                        except Exception:
                            pass
                except Exception as ctx_err:
                    logger.debug(
                        f"[doctor] context fetch failed agent={agent_id}: {ctx_err}"
                    )

                tier = "trial"
                try:
                    comp_res = (
                        client.table("companies")
                        .select("tier")
                        .eq("company_id", agent["companyId"])
                        .execute()
                    )
                    if comp_res.data:
                        tier = comp_res.data[0].get("tier") or "trial"
                except Exception as tier_err:
                    logger.debug(
                        f"[doctor] tier fetch failed company={agent.get('companyId')}: {tier_err}"
                    )

                symptoms = await run_all_detectors(agent, last_hb, active_task)
                for sym in symptoms:
                    await handle_symptom(client, agent, sym, tier, api_state)
            except Exception as row_err:
                logger.error(f"[doctor] error processing agent={agent_id}: {row_err}")

    except Exception as fatal:
        logger.error(f"[doctor] tick fatal error: {fatal}")
