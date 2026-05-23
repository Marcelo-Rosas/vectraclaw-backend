"""Política de inbound Meta (Conversas) — quais canais existem e quando criar task.

Regra de produto (2026-05):
- A UI Conversas (VectraClip) só faz listagem + reply humano — nunca INSERT em tasks.
- Task automática só via webhook Meta se explicitamente habilitada (env) E
  roteamento catalog-driven (`connector_channels.default_inbound_operation_type`).
- Fluxos humanos/conhecidos: POST /api/tasks/dispatch, workflows, rotinas, UI Tasks.

Env:
  VECTRACLAW_CONNECTOR_INBOUND_AUTO_DISPATCH=true|false  (default: false)
"""
from __future__ import annotations

import os

# Canais com webhook + outbound implementados em connectors.py / connector_bus.
META_INBOUND_CHANNELS = frozenset({"whatsapp", "instagram"})


def inbound_auto_dispatch_enabled() -> bool:
    raw = os.getenv("VECTRACLAW_CONNECTOR_INBOUND_AUTO_DISPATCH", "false").strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_meta_inbound_channel(channel: str | None) -> bool:
    return (channel or "").strip().lower() in META_INBOUND_CHANNELS


def inbound_auto_dispatch_skip_reason(channel: str | None) -> str | None:
    """None = permitido tentar dispatch (ainda depende de default_inbound_operation_type no DB)."""
    if not is_meta_inbound_channel(channel):
        return "channel_not_meta_implemented"
    if not inbound_auto_dispatch_enabled():
        return "auto_dispatch_disabled_set_VECTRACLAW_CONNECTOR_INBOUND_AUTO_DISPATCH=true"
    return None


def may_auto_dispatch_inbound_task(channel: str | None) -> bool:
    return inbound_auto_dispatch_skip_reason(channel) is None
