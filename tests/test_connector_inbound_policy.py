"""Política inbound Meta — guardrail de auto-dispatch."""
import os

import pytest

from src.services.connector_inbound_policy import (
    META_INBOUND_CHANNELS,
    inbound_auto_dispatch_enabled,
    inbound_auto_dispatch_skip_reason,
    is_meta_inbound_channel,
    may_auto_dispatch_inbound_task,
)


def test_meta_channels_frozen():
    assert META_INBOUND_CHANNELS == frozenset({"whatsapp", "instagram"})


def test_is_meta_channel():
    assert is_meta_inbound_channel("whatsapp")
    assert is_meta_inbound_channel("instagram")
    assert not is_meta_inbound_channel("email")
    assert not is_meta_inbound_channel("telegram")


def test_auto_dispatch_off_by_default(monkeypatch):
    monkeypatch.delenv("VECTRACLAW_CONNECTOR_INBOUND_AUTO_DISPATCH", raising=False)
    assert inbound_auto_dispatch_enabled() is False
    assert may_auto_dispatch_inbound_task("whatsapp") is False
    assert inbound_auto_dispatch_skip_reason("whatsapp") is not None


def test_auto_dispatch_opt_in(monkeypatch):
    monkeypatch.setenv("VECTRACLAW_CONNECTOR_INBOUND_AUTO_DISPATCH", "true")
    assert inbound_auto_dispatch_enabled() is True
    assert may_auto_dispatch_inbound_task("whatsapp") is True
    assert may_auto_dispatch_inbound_task("email") is False
