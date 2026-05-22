"""E2E do webhook Instagram (rota + assinatura + bus mockado)."""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api import app

IG_ACCOUNT = "17841472518839486"
SENDER = "123456"
APP_SECRET = "3b5920c8fb61dd4b1bbfc416595d4f43"  # 32 hex — contrato _normalize_meta_app_secret
VERIFY_TOKEN = "verify_token_e2e"

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
                    "message": {"mid": "mid.e2e", "text": "Olá E2E"},
                }
            ],
        }
    ],
}

MOCK_CFG = {
    "company_id": "01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2",
    "adapter_id": "adapter-ig-e2e",
    "instagram_account_id": IG_ACCOUNT,
    "app_secret": APP_SECRET,
    "webhook_verify_token": VERIFY_TOKEN,
}


def _sign(body: bytes, secret: str = APP_SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_instagram_webhook_verify_handshake(client: TestClient) -> None:
    with patch(
        "src.api_routes.connectors._find_any_meta_config_with_verify_token",
        return_value=MOCK_CFG,
    ):
        r = client.get(
            "/api/connectors/instagram/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "challenge_xyz",
            },
        )
    assert r.status_code == 200
    assert r.text == "challenge_xyz"


def test_instagram_webhook_post_full_pipeline(client: TestClient) -> None:
    body = json.dumps(SAMPLE_PAYLOAD).encode("utf-8")
    session_row = {
        "id": "sess-e2e-uuid",
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
        ) as open_sess,
        patch(
            "src.services.connector_bus.append_history",
            return_value={**session_row, "history": [{"role": "user", "content": "Olá E2E"}]},
        ) as append_hist,
        patch(
            "src.api_routes.connectors._dispatch_inbound_task",
            return_value="task-e2e-uuid",
        ) as dispatch,
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
    assert data.get("session_id") == "sess-e2e-uuid"
    assert data.get("task_id") == "task-e2e-uuid"
    assert data.get("had_content") is True
    assert data.get("external_id") == SENDER

    open_sess.assert_called_once()
    call_kw = open_sess.call_args.kwargs
    assert call_kw["channel"] == "instagram"
    assert call_kw["connector_id"] == IG_ACCOUNT
    assert call_kw["external_id"] == SENDER

    append_hist.assert_called_once()
    dispatch.assert_called_once()


def test_instagram_webhook_accepts_second_hmac_candidate(client: TestClient) -> None:
    """Meta pode assinar com app_secret do app pai, não só meta_instagram."""
    body = json.dumps(SAMPLE_PAYLOAD).encode("utf-8")
    cfg = {
        **MOCK_CFG,
        "meta_instagram": "wrong_secret_32_chars_xxxxxxxx",
        "app_secret": APP_SECRET,
    }
    with (
        patch(
            "src.api_routes.connectors._resolve_instagram_webhook_cfg",
            return_value=cfg,
        ),
        patch(
            "src.api_routes.connectors._find_instagram_config_by_account_id",
            return_value=cfg,
        ),
        patch(
            "src.api_routes.connectors._instagram_hmac_secret_candidates",
            return_value=[cfg["meta_instagram"], cfg["app_secret"]],
        ),
        patch("src.services.connector_bus.get_or_open_session", return_value={"id": "s1"}),
        patch("src.services.connector_bus.append_history", return_value={"id": "s1"}),
        patch("src.api_routes.connectors._dispatch_inbound_task", return_value=None),
    ):
        r = client.post(
            "/api/connectors/instagram/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _sign(body, APP_SECRET),
            },
        )
    assert r.status_code == 200, r.text


def test_instagram_webhook_requires_hmac_before_empty_messaging(client: TestClient) -> None:
    """Payload sem messaging mas object=instagram ainda exige HMAC válido."""
    payload = {
        "object": "instagram",
        "entry": [{"id": IG_ACCOUNT, "messaging": []}],
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    with (
        patch(
            "src.api_routes.connectors._resolve_instagram_webhook_cfg",
            return_value=MOCK_CFG,
        ),
        patch(
            "src.api_routes.connectors._instagram_hmac_secret_candidates",
            return_value=[APP_SECRET],
        ),
    ):
        r = client.post(
            "/api/connectors/instagram/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=deadbeef",
            },
        )
    assert r.status_code == 401


def test_instagram_webhook_rejects_bad_signature(client: TestClient) -> None:
    body = json.dumps(SAMPLE_PAYLOAD).encode("utf-8")
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
    ):
        r = client.post(
            "/api/connectors/instagram/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=deadbeef",
            },
        )
    assert r.status_code == 401
