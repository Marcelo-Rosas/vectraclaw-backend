"""Testes de resolução metadata-driven (adapter_field_resolve)."""
from unittest.mock import MagicMock, patch

from src.services.adapter_field_resolve import (
    resolve_adapter_field,
    load_mcp_imap_smtp_credentials,
)


def test_resolve_adapter_field_company_primary():
    client = MagicMock()
    with patch(
        "src.services.adapter_field_resolve.resolve_secret_value",
        side_effect=lambda _c, _co, v: str(v),
    ):
        val = resolve_adapter_field(
            client,
            "company-1",
            "smtp_host",
            agent_field_values={"smtp_host": "agent-override"},
            company_field_values={"smtp_host": "company-primary"},
        )
    assert val == "agent-override"


def test_resolve_adapter_field_falls_back_when_agent_ref_resolves_empty():
    """Regressão: agent override com vault:// órfão (resolve vazio) deve cair
    para o ref da company em vez de travar com '' — causa raiz do bug SMTP do
    Hermes (agent password apontando para secret inexistente)."""
    client = MagicMock()

    def fake_resolve(_c, _co, value):
        # ref órfão do agente resolve vazio; ref da company resolve a senha real
        if value == "vault://orphan":
            return ""
        if value == "vault://valid":
            return "real-password"
        return str(value)

    with patch(
        "src.services.adapter_field_resolve.resolve_secret_value",
        side_effect=fake_resolve,
    ):
        val = resolve_adapter_field(
            client,
            "company-1",
            "password",
            agent_field_values={"password": "vault://orphan"},
            company_field_values={"password": "vault://valid"},
        )
    assert val == "real-password"


def test_load_mcp_imap_smtp_credentials_missing_smtp_host():
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": "adp-imap"}
    ]

    company_table = MagicMock()
    company_table.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"field_values_json": {"email": "a@b.com", "password": "vault://x"}}
    ]
    agent_table = MagicMock()
    agent_table.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

    def table_side_effect(name):
        if name == "adapter_catalog":
            return mock_client.table.return_value
        if name == "company_adapter_values":
            return company_table
        if name == "agent_adapter_configs":
            return agent_table
        return MagicMock()

    mock_client.table.side_effect = table_side_effect

    with patch("src.services.adapter_field_resolve.resolve_secret_value", return_value="pwd"):
        creds = load_mcp_imap_smtp_credentials(mock_client, "company-1")

    assert creds is None
