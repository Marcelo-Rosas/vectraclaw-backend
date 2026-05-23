"""API: create sipoc sector exige tenant claim e força company_id server-side."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.api import MOCK_USER  # noqa: E402

TENANT = MOCK_USER["companyId"]


@pytest.fixture()
def client_dev(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VECTRACLAW_AUTH_DISABLED", "true")
    from src.api import app

    return TestClient(app)


def test_create_sector_without_tenant_claim_returns_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VECTRACLAW_AUTH_DISABLED", raising=False)
    from src.api import app

    with patch(
        "src.api.validate_supabase_jwt",
        return_value={"sub": "u1", "app_metadata": {}},
    ):
        c = TestClient(app)
        r = c.post(
            "/api/sipoc/sectors",
            json={"name": "Setor X"},
            headers={
                "Authorization": "Bearer fake",
                "Origin": "http://localhost:3000",
            },
        )
    assert r.status_code == 403
    assert "tenant_claim_missing" in r.json().get("detail", "")


def test_create_sector_overrides_client_company_id(client_dev: TestClient) -> None:
    """company_id do body é substituído pelo tenant do JWT/state."""
    fake_row = {
        "id": "11111111-1111-4111-8111-111111111111",
        "name": "Setor API",
        "slug": "setor-api",
        "company_id": TENANT,
        "created_at": "2026-05-22T12:00:00+00:00",
        "updated_at": "2026-05-22T12:00:00+00:00",
    }
    mock_table = MagicMock()
    mock_table.insert.return_value.execute.return_value = MagicMock(data=[fake_row])
    mock_client = MagicMock()
    mock_client.table.return_value = mock_table

    with patch("src.api.supabase", MagicMock()), patch(
        "src.api.get_authenticated_client", return_value=mock_client
    ):
        r = client_dev.post(
            "/api/sipoc/sectors",
            json={
                "name": "Setor API",
                "companyId": "00000000-0000-0000-0000-000000000099",
            },
        )
    assert r.status_code == 200
    insert_arg = mock_table.insert.call_args[0][0]
    assert insert_arg["company_id"] == TENANT
