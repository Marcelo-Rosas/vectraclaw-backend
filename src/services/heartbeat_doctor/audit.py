"""
VEC-199b — Matriz de 6 eventos do `vectraclip.incident_audit`.

Toda transição de estado de um incidente (detecção, fix, undo, decisão do
conselho) deve gerar um registro aqui. A falha de auditoria NÃO pode quebrar
o fluxo principal do Doctor — por isso todas as escritas ficam dentro de
try/except com log.

Imports de `src.api` são lazy para evitar ciclo de import.
"""

from typing import Any, Dict, Optional, Union
from uuid import UUID

AUDIT_TABLE = "incident_audit"

# Matriz de 6 eventos (VEC-199b §Fix 2)
EVENT_DETECTED = "detected"                 # Doctor detectou sintoma
EVENT_FIX_EXECUTED = "fix_executed"         # Fix aplicado com sucesso
EVENT_FIX_FAILED = "fix_failed"             # Fix tentado e falhou
EVENT_UNDO = "undo"                         # Humano desfez auto-heal
EVENT_COUNCIL_APPROVED = "council_approved" # Humano aprovou incidente high
EVENT_COUNCIL_REJECTED = "council_rejected" # Humano rejeitou incidente high

ALL_EVENTS = frozenset({
    EVENT_DETECTED,
    EVENT_FIX_EXECUTED,
    EVENT_FIX_FAILED,
    EVENT_UNDO,
    EVENT_COUNCIL_APPROVED,
    EVENT_COUNCIL_REJECTED,
})


async def append_audit(
    incident_id: Union[str, UUID],
    *,
    event: str,
    actor: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Grava um evento na audit trail.

    - `event` deve estar em ALL_EVENTS (usa matriz de 6 eventos).
    - `actor` é `doctor` (loop automático) ou `user_id` (decisão humana).
    - `payload` é um dict JSON-serializável com contexto extra.
    - Falhas de DB viram warning, não exception.
    """
    # Schema já está fixado no boot via `supabase.postgrest.schema(SCHEMA)` em api.py;
    # não precisamos chamar `.schema(...)` aqui.
    from src.api import supabase, logger  # lazy: quebra ciclo

    if event not in ALL_EVENTS:
        logger.warning(f"[audit] unknown event '{event}' — persisting anyway")

    if not supabase:
        logger.info(
            f"[audit] (memory-only) incident={incident_id} event={event} "
            f"actor={actor} payload={payload}"
        )
        return

    try:
        supabase.table(AUDIT_TABLE).insert(
            {
                "incident_id": str(incident_id),
                "event": event,
                "actor": actor,
                "payload": payload or {},
            }
        ).execute()
    except Exception as exc:
        logger.error(f"[audit] failed to append event={event} incident={incident_id}: {exc}")
