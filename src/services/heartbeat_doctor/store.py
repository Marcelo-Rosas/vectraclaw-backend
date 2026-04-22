"""
VEC-199b — Persistência Postgres do Heartbeat Doctor.

Todo acesso a `vectraclip.incidents` e `vectraclip.incident_audit` passa por este
módulo. O cliente usado é o `service_role` (global `supabase` em `src.api`), que
bypassa RLS — por isso TODAS as queries que filtram por tenant devem receber
`company_id` explicitamente.

Imports do `src.api` são lazy (dentro das funções) para evitar ciclo com o
scheduler do Doctor que é montado no próprio `src.api`.

Observação sobre schema: `api.py` fixa `supabase.postgrest.schema(SCHEMA)` no
boot, portanto `.table(...)` já aponta para `vectraclip` sem precisar chamar
`.schema(...)` em toda query.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from src.models import Agent, Incident, IncidentAudit

INCIDENTS_TABLE = "incidents"
AUDIT_TABLE = "incident_audit"


def _service_client():
    """Retorna o cliente `service_role` global do `src.api` (ou None se ausente)."""
    from src.api import supabase  # lazy: quebra ciclo com api.py
    return supabase


def _as_id(value: Union[str, UUID, None]) -> Optional[str]:
    if value is None:
        return None
    return str(value)


async def insert_incident(row: Dict[str, Any]) -> Optional[Incident]:
    """
    Insere um incidente. `row` deve estar em snake_case.

    Retorna o `Incident` do DB (quando disponível). Se `supabase` não existir
    (ambiente de smoke sem creds), retorna None — o caller decide o fallback.
    """
    client = _service_client()
    if not client:
        return None

    payload = dict(row)
    payload.pop("updated_at", None)

    result = client.table(INCIDENTS_TABLE).insert(payload).execute()
    if not result.data:
        raise RuntimeError("incident_insert_failed")
    return Incident(**result.data[0])


async def get_incident_by_id(
    incident_id: Union[str, UUID],
    company_id: Union[str, UUID],
) -> Optional[Incident]:
    """Busca incidente por id filtrando também por `company_id` (isolamento multi-tenant)."""
    client = _service_client()
    if not client:
        return None

    result = (
        client.table(INCIDENTS_TABLE)
        .select("*")
        .eq("id", _as_id(incident_id))
        .eq("company_id", _as_id(company_id))
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return Incident(**result.data[0])


async def list_incidents(
    company_id: Union[str, UUID],
    *,
    decision: Optional[str] = None,
    limit: int = 50,
) -> List[Incident]:
    """Lista incidentes de uma empresa, ordenados por created_at desc."""
    client = _service_client()
    if not client:
        return []

    q = (
        client.table(INCIDENTS_TABLE)
        .select("*")
        .eq("company_id", _as_id(company_id))
        .order("created_at", desc=True)
        .limit(limit)
    )
    if decision and decision != "all":
        q = q.eq("decision", decision)

    res = q.execute()
    return [Incident(**r) for r in res.data]


async def update_incident_decision(
    incident_id: Union[str, UUID],
    company_id: Union[str, UUID],
    *,
    decision: str,
    resolved: bool = False,
) -> Optional[Incident]:
    """Atualiza a decisão de um incidente (filtrado por company_id)."""
    client = _service_client()
    if not client:
        return None

    patch: Dict[str, Any] = {"decision": decision}
    if resolved:
        patch["resolved_at"] = datetime.now(timezone.utc).isoformat()

    result = (
        client.table(INCIDENTS_TABLE)
        .update(patch)
        .eq("id", _as_id(incident_id))
        .eq("company_id", _as_id(company_id))
        .execute()
    )
    if not result.data:
        return None
    return Incident(**result.data[0])


async def fetch_all_agents(include_offline: bool = True) -> List[Agent]:
    """
    Busca agentes para o scan do Doctor.

    Por padrão inclui agentes `offline` — o detector S5 (`burn_rate_anomaly`)
    precisa ver currentBurnRate de agentes mortos/pausados para disparar o
    pós-mortem mesmo fora do status `working`.
    """
    client = _service_client()
    if not client:
        return []

    q = client.table("agents").select("*")
    if not include_offline:
        q = q.neq("status", "offline")
    res = q.execute()
    return [Agent(**r) for r in res.data]


async def get_incident_audit(incident_id: Union[str, UUID]) -> List[IncidentAudit]:
    """Lista o log de auditoria de um incidente (mais recente primeiro)."""
    client = _service_client()
    if not client:
        return []

    res = (
        client.table(AUDIT_TABLE)
        .select("*")
        .eq("incident_id", _as_id(incident_id))
        .order("created_at", desc=True)
        .execute()
    )
    return [IncidentAudit(**r) for r in res.data]
