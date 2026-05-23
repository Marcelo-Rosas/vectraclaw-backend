"""CORS preflight, headers em erro, e rota intelligence (VEC-168)."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

PROD_ORIGIN = "https://app.vectraclip.vectracargo.com.br"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VECTRACLAW_AUTH_DISABLED", "true")
    from src.api import app

    return TestClient(app)


def test_cors_preflight_prod_origin(client: TestClient) -> None:
    r = client.options(
        "/api/sipoc/sectors",
        headers={
            "Origin": PROD_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == PROD_ORIGIN
    assert r.headers.get("access-control-allow-credentials") == "true"
    assert "origin" in (r.headers.get("vary") or "").lower()


def test_cors_headers_on_401_without_auth(client: TestClient) -> None:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv("VECTRACLAW_AUTH_DISABLED", raising=False)
    try:
        from src.api import app

        c = TestClient(app)
        r = c.get(
            "/api/agents",
            headers={"Origin": PROD_ORIGIN},
        )
        assert r.status_code == 401
        assert r.headers.get("access-control-allow-origin") == PROD_ORIGIN
    finally:
        monkeypatch.undo()


def test_cors_rejects_unknown_origin(client: TestClient) -> None:
    r = client.get(
        "/api/health",
        headers={"Origin": "https://evil.example.com"},
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") is None


def test_intelligence_dashboard_not_404(client: TestClient) -> None:
    r = client.get("/api/intelligence/dashboard")
    assert r.status_code != 404


def test_intelligence_dashboard_alias_path(client: TestClient) -> None:
    r = client.get("/intelligence/dashboard")
    assert r.status_code != 404


def test_health_metrics_endpoint(client: TestClient) -> None:
    r = client.get("/api/health/metrics")
    assert r.status_code == 200
    body = r.json()
    assert "metrics" in body
    assert "cors_preflight" in body["metrics"]


def test_build_cors_allow_origins_includes_prod() -> None:
    from src.middleware.cors_policy import build_cors_allow_origins

    origins = build_cors_allow_origins()
    assert PROD_ORIGIN in origins
