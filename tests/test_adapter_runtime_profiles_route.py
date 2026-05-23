"""GET /api/adapter-runtime-profiles — catálogo wizard Connectors."""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VECTRACLAW_AUTH_DISABLED", "true")
    from src.api import app

    return TestClient(app)


def test_adapter_runtime_profiles_not_404(client: TestClient) -> None:
    r = client.get(
        "/api/adapter-runtime-profiles",
        headers={"Origin": "https://app.vectraclip.vectracargo.com.br"},
    )
    assert r.status_code != 404
    assert r.headers.get("access-control-allow-origin") == (
        "https://app.vectraclip.vectracargo.com.br"
    )
