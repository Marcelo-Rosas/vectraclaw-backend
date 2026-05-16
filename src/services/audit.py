"""
Audit log helper — best-effort persistência em vectraclip.audit_log.

Doc de origem: docs/AUDIT-HANDLERS-2026-05-16.md §Camada 1.5 (gap 🔴 ALTA).
Migration: 20260516240000_audit_log_foundation.sql.

Princípio:
  Auditoria NUNCA deve quebrar o endpoint chamador. Try/except global,
  log warning, continua. Compliance gap > rollback de feature crítica.

Uso típico:
  from src.services.audit import audit_log

  audit_log(
      supabase,  # client service_role (NUNCA authenticated — INSERT bloqueado por GRANT)
      company_id=company_id,
      actor_type="human",
      actor_id=user_id,
      action="approval.approve",
      target=f"approval:{approval_id}",
      payload={"approved_by_user": user_id, "request_type": "hire_agent"},
  )

Convenções de naming (manter consistente pra greppability):
  action: "<recurso>.<verbo>" (ex: approval.approve, risk.create, user.role_change)
  target: "<recurso>:<id>" (ex: approval:<uuid>, user:<uuid>, risk:<uuid>)
  actor_type: "human" (request via UI) | "agent" (daemon) | "system" (cron/migration)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

logger = logging.getLogger("AuditLog")

ActorType = Literal["human", "agent", "system"]


def audit_log(
    supabase: Any,
    *,
    company_id: str,
    actor_type: ActorType,
    actor_id: str,
    action: str,
    target: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Best-effort INSERT em vectraclip.audit_log.

    Args:
        supabase: cliente Supabase com service_role (GRANT INSERT exige).
        company_id: UUID stringified da company (tenant scope).
        actor_type: 'human' | 'agent' | 'system' (CHECK constraint).
        actor_id: identificador do ator (user_id | agent_id | "system-<componente>").
        action: "<recurso>.<verbo>" em snake/dot case. Ex: "approval.approve".
        target: "<recurso>:<id>". Ex: "approval:<uuid>".
        payload: dict livre com contexto adicional. Default = {}.

    Returns:
        ID do log criado, ou None se falhou (não levanta — só warning).
    """
    if not supabase:
        logger.warning("audit_log skipped — supabase=None action=%s target=%s", action, target)
        return None

    row = {
        "company_id": str(company_id),
        "actor_type": actor_type,
        "actor_id": str(actor_id),
        "action": action,
        "target": target,
        "payload": payload or {},
    }

    try:
        res = supabase.table("audit_log").insert(row).execute()
        if res.data:
            log_id = res.data[0].get("id")
            logger.info(
                "audit_log id=%s action=%s target=%s actor=%s:%s",
                log_id, action, target, actor_type, actor_id,
            )
            return log_id
    except Exception as exc:
        # NUNCA quebra o endpoint chamador. Audit gap > rollback de mutation.
        logger.warning(
            "audit_log INSERT failed (non-fatal) action=%s target=%s err=%s",
            action, target, exc,
        )

    return None
