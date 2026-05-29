"""
Testes unitários do módulo HermesReporter (VEC-330).
Cobre: parse da descrição da task, envio SMTP, redação via LLM (mock), entrypoint.
"""
import json
import os
import smtplib
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# _parse_task_description
# ──────────────────────────────────────────────────────────────────────────────

def test_parse_task_description_extracts_recipient_and_body():
    from src.agents.hermes_reporter import _parse_task_description

    desc = (
        "RECIPIENT: marcelo.rosas@vectracargo.com.br\n"
        "SUBJECT: Audit OFX vs Planner — Abril 2024\n"
        "PARENT_TASK_ID: abc-123\n\n"
        "---\n\n"
        "# Relatório\n\nConteúdo do relatório."
    )
    recipients, subject_hint, markdown = _parse_task_description(desc)

    assert recipients == ["marcelo.rosas@vectracargo.com.br"]
    assert subject_hint == "Audit OFX vs Planner — Abril 2024"
    assert "# Relatório" in markdown
    assert "Conteúdo do relatório." in markdown


def test_parse_task_description_multiple_recipients():
    from src.agents.hermes_reporter import _parse_task_description

    desc = "RECIPIENT: a@b.com, c@d.com\n\n---\n\nCorpo."
    recipients, _, _ = _parse_task_description(desc)
    assert recipients == ["a@b.com", "c@d.com"]


def test_parse_task_description_no_separator_returns_full_body():
    from src.agents.hermes_reporter import _parse_task_description

    desc = "RECIPIENT: a@b.com\nSUBJECT: Test\n\nSem separador."
    _, _, markdown = _parse_task_description(desc)
    assert "Sem separador." in markdown


# ──────────────────────────────────────────────────────────────────────────────
# send_smtp
# ──────────────────────────────────────────────────────────────────────────────

def test_send_smtp_uses_env_vars(monkeypatch):
    from src.agents.hermes_reporter import send_smtp

    monkeypatch.setenv("HERMES_SMTP_SERVER", "smtp.test.com")
    monkeypatch.setenv("HERMES_SMTP_PORT", "465")
    monkeypatch.setenv("HERMES_EMAIL", "test@test.com")
    monkeypatch.setenv("HERMES_PASSWORD", "secret")

    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)

    with patch("smtplib.SMTP_SSL", return_value=mock_smtp) as mock_cls:
        send_smtp("Assunto Teste", "<p>HTML body</p>", ["dest@test.com"])

    mock_cls.assert_called_once_with("smtp.test.com", 465, context=mock_cls.call_args[1]["context"], timeout=30)
    mock_smtp.login.assert_called_once_with("test@test.com", "secret")
    mock_smtp.send_message.assert_called_once()


def test_send_smtp_uses_explicit_credentials(monkeypatch):
    from src.agents.hermes_reporter import send_smtp

    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)

    creds = {
        "server": "smtpout.secureserver.net",
        "port": 465,
        "user": "marcelo.rosas@vectracargo.com.br",
        "password": "vault-resolved",
    }
    with patch("smtplib.SMTP_SSL", return_value=mock_smtp) as mock_cls:
        send_smtp("Assunto", "<p>ok</p>", ["dest@test.com"], credentials=creds)

    mock_smtp.login.assert_called_once_with("marcelo.rosas@vectracargo.com.br", "vault-resolved")
    mock_cls.assert_called_once_with(
        "smtpout.secureserver.net", 465, context=mock_cls.call_args[1]["context"], timeout=30
    )


def test_load_mcp_imap_smtp_credentials_from_metadata():
    from src.services.adapter_field_resolve import load_mcp_imap_smtp_credentials

    mock_client = MagicMock()

    def table_side_effect(name):
        t = MagicMock()
        if name == "adapter_catalog":
            t.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                {"id": "adp-imap"}
            ]
        elif name == "company_adapter_values":
            t.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                {
                    "field_values_json": {
                        "email": "user@test.com",
                        "password": "vault://secret-uuid",
                        "smtp_host": "smtpout.secureserver.net",
                        "smtp_port": "465",
                    }
                }
            ]
        elif name == "agent_adapter_configs":
            t.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        return t

    mock_client.table.side_effect = table_side_effect

    def _fake_resolve(_client, _company_id, value):
        if str(value).startswith("vault://"):
            return "plain-pwd"
        return str(value)

    with patch(
        "src.services.adapter_field_resolve.resolve_secret_value",
        side_effect=_fake_resolve,
    ):
        creds = load_mcp_imap_smtp_credentials(mock_client, "01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2")

    assert creds is not None
    assert creds["user"] == "user@test.com"
    assert creds["password"] == "plain-pwd"
    assert creds["server"] == "smtpout.secureserver.net"
    assert creds["port"] == 465


# ──────────────────────────────────────────────────────────────────────────────
# entrypoint
# ──────────────────────────────────────────────────────────────────────────────

def test_entrypoint_no_recipient_returns_errored():
    from src.agents.hermes_reporter import entrypoint

    task = {
        "id": "task-001",
        "description": "Sem linha RECIPIENT\n\n---\n\nConteúdo.",
    }
    result = entrypoint(task)
    assert result["status"] == "errored"
    assert "no recipients" in result["error"]


def test_entrypoint_empty_body_returns_errored():
    from src.agents.hermes_reporter import entrypoint

    task = {
        "id": "task-001",
        "description": "RECIPIENT: a@b.com\n\n---\n\n   ",
    }
    result = entrypoint(task)
    assert result["status"] == "errored"
    assert "empty markdown" in result["error"]
