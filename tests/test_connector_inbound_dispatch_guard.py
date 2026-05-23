"""Guardrail: webhook Meta grava sessão mas não INSERT em tasks sem opt-in explícito."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api import app

IG_ACCOUNT = "17841472518839486"
SENDER = "123456"
APP_SECRET = "3b5920c8fb61dd4b1bbfc416595d4f43"

SAMPLE_PAYLOAD = {
    "object": "instagram",
    "entry": [
        {
            "id": IG_ACCOUNT,
            "messaging": [
                {
                    "sender": {"id": SENDER},
                    "recipient": {"id": IG_ACCOUNT},
                    "timestamp": 1710000000,
                    "message": {"mid": "mid.guard", "text": "Smoke guardrail"},
                }
            ],
        }
    ],
}

MOCK_CFG = {
    "company_id": "01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2",
    "adapter_id": "adapter-ig-guard",
    "instagram_account_id": IG_ACCOUNT,
    "app_secret": APP_SECRET,
    "webhook_verify_token": "tok",
}


def _sign(body: bytes) -> str:
    import hashlib
    import hmac

    digest = hmac.new(APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_dispatch_inbound_task_skips_supabase_when_auto_dispatch_off(monkeypatch):
    monkeypatch.delenv("VECTRACLAW_CONNECTOR_INBOUND_AUTO_DISPATCH", raising=False)
    mock_sb = MagicMock()

    with patch("src.api.supabase", mock_sb):
        from src.api_routes.connectors import _dispatch_inbound_task

        task_id = _dispatch_inbound_task(
            company_id=MOCK_CFG["company_id"],
            session={"id": "sess-guard", "channel": "instagram"},
            msg={"content": "oi", "external_id": SENDER},
        )

    assert task_id is None
    mock_sb.table.assert_not_called()


def test_dispatch_inbound_task_skips_non_meta_channel(monkeypatch):
    monkeypatch.setenv("VECTRACLAW_CONNECTOR_INBOUND_AUTO_DISPATCH", "true")
    mock_sb = MagicMock()

    with patch("src.api.supabase", mock_sb):
        from src.api_routes.connectors import _dispatch_inbound_task

        task_id = _dispatch_inbound_task(
            company_id=MOCK_CFG["company_id"],
            session={"id": "sess-email", "channel": "email"},
            msg={"content": "oi", "external_id": "x@y.com"},
        )

    assert task_id is None
    mock_sb.table.assert_not_called()


def test_instagram_webhook_returns_null_task_id_when_auto_dispatch_off(
    client: TestClient, monkeypatch
) -> None:
    """Pipeline completo sem mock de _dispatch_inbound_task — só sessão/histórico."""
    monkeypatch.delenv("VECTRACLAW_CONNECTOR_INBOUND_AUTO_DISPATCH", raising=False)
    body = json.dumps(SAMPLE_PAYLOAD).encode("utf-8")
    session_row = {
        "id": "sess-guard-uuid",
        "company_id": MOCK_CFG["company_id"],
        "channel": "instagram",
        "connector_id": IG_ACCOUNT,
        "external_id": SENDER,
        "status": "open",
        "history": [],
    }

    with (
        patch(
            "src.api_routes.connectors._resolve_instagram_webhook_cfg",
            return_value=MOCK_CFG,
        ),
        patch(
            "src.api_routes.connectors._instagram_hmac_secret_candidates",
            return_value=[APP_SECRET],
        ),
        patch(
            "src.api_routes.connectors._find_instagram_config_by_account_id",
            return_value=MOCK_CFG,
        ),
        patch(
            "src.services.connector_bus.get_or_open_session",
            return_value=session_row,
        ),
        patch(
            "src.services.connector_bus.append_history",
            return_value={**session_row, "history": [{"role": "user", "content": "Smoke guardrail"}]},
        ),
        patch("src.api.supabase", MagicMock()),
    ):
        r = client.post(
            "/api/connectors/instagram/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _sign(body),
            },
        )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("session_id") == "sess-guard-uuid"
    assert data.get("task_id") is None
    assert data.get("had_content") is True
