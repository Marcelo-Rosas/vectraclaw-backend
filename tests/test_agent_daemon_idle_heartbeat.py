"""Testes do idle heartbeat tick (VEC-377). Mocks Supabase + clock."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


def _build_daemon(monkeypatch, agent_id="00000000-0000-0000-0000-000000000003"):
    """Constrói daemon com mocks e agent_id setado, sem ler env real."""
    monkeypatch.setenv("AGENT_ID", agent_id)
    monkeypatch.setenv("DAEMON_IDLE_HEARTBEAT_SECONDS", "30")
    from src.agent_daemon import ResilientHarnessDaemon
    d = ResilientHarnessDaemon()
    return d


def _mock_supabase_with_company(company_id="cid-A"):
    """Mock supabase: agents.select() devolve company_id, heartbeats.insert() captura row."""
    sb = MagicMock()
    agents_table = MagicMock()
    agents_table.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"company_id": company_id},
    )
    heartbeats_table = MagicMock()
    heartbeats_table.insert.return_value.execute.return_value = MagicMock(data=[{"id": "hb-NEW"}])

    def _route(name):
        if name == "agents":
            return agents_table
        if name == "heartbeats":
            return heartbeats_table
        return MagicMock()

    sb.table.side_effect = _route
    return sb, heartbeats_table


def test_emit_idle_heartbeat_inserts_row(monkeypatch):
    """Primeira chamada (sem _last_heartbeat_at) emite heartbeat."""
    d = _build_daemon(monkeypatch)
    sb, hb_table = _mock_supabase_with_company()
    d._supabase = sb

    d._emit_idle_heartbeat()

    hb_table.insert.assert_called_once()
    inserted = hb_table.insert.call_args.args[0]
    assert inserted["agent_id"] == "00000000-0000-0000-0000-000000000003"
    assert inserted["status"] == "idle"
    assert inserted["tokens_used"] == 0
    assert inserted["company_id"] == "cid-A"
    assert d._last_heartbeat_at is not None


def test_emit_idle_heartbeat_rate_limited(monkeypatch):
    """Segunda chamada dentro do interval NÃO emite."""
    d = _build_daemon(monkeypatch)
    sb, hb_table = _mock_supabase_with_company()
    d._supabase = sb

    d._emit_idle_heartbeat()  # 1ª: emite
    d._emit_idle_heartbeat()  # 2ª imediata: skip

    assert hb_table.insert.call_count == 1


def test_emit_idle_heartbeat_after_interval_emits_again(monkeypatch):
    """Após interval >= configurado, emite de novo."""
    d = _build_daemon(monkeypatch)
    sb, hb_table = _mock_supabase_with_company()
    d._supabase = sb

    # Simula que o último heartbeat foi há 35s (> 30s configurado)
    d._last_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=35)
    d._emit_idle_heartbeat()

    assert hb_table.insert.call_count == 1


def test_emit_idle_heartbeat_no_agent_id_skips(monkeypatch):
    """Sem AGENT_ID setado, skip silencioso."""
    monkeypatch.delenv("AGENT_ID", raising=False)
    from src.agent_daemon import ResilientHarnessDaemon
    d = ResilientHarnessDaemon()
    sb, hb_table = _mock_supabase_with_company()
    d._supabase = sb
    d._emit_idle_heartbeat()
    hb_table.insert.assert_not_called()


def test_emit_idle_heartbeat_no_supabase_skips(monkeypatch):
    """Sem supabase client, skip silencioso (não crash)."""
    d = _build_daemon(monkeypatch)
    d._supabase = None
    monkeypatch.setattr(d, "_get_supabase", lambda: None)
    d._emit_idle_heartbeat()  # não deve raise
    assert d._last_heartbeat_at is None


def test_emit_idle_heartbeat_db_error_does_not_crash(monkeypatch):
    """Erro no insert é absorvido (logger.debug); polling loop não cai."""
    d = _build_daemon(monkeypatch)
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(data={"company_id": "cid"})
    sb.table.return_value.insert.return_value.execute.side_effect = Exception("DB temporarily unavailable")
    d._supabase = sb

    d._emit_idle_heartbeat()  # não deve raise
    # _last_heartbeat_at NÃO foi atualizado (erro)
    assert d._last_heartbeat_at is None


def test_company_id_cached_after_first_lookup(monkeypatch):
    """Após primeira chamada, _agent_config cacheia company_id (otimiza re-emits)."""
    d = _build_daemon(monkeypatch)
    sb, _ = _mock_supabase_with_company()
    d._supabase = sb

    d._emit_idle_heartbeat()
    assert d._agent_config.get("company_id") == "cid-A"
