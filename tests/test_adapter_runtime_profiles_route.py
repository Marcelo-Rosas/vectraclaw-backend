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


def test_adapter_runtime_profile_options_json_list_ok() -> None:
    """Seed DB usa list em options_json (ex.: enum de modelos) — não pode 500."""
    from src.models import AdapterRuntimeProfile

    row = AdapterRuntimeProfile(
        id="test",
        name="Test",
        default_provider="groq",
        field_definitions_template=[
            {
                "field_key": "model_id",
                "field_label": "Model",
                "field_type": "select",
                "is_required": True,
                "options_json": ["sonnet", "haiku", "opus"],
                "sort_order": 1,
            }
        ],
        created_at="2026-05-22T12:00:00+00:00",
        updated_at="2026-05-22T12:00:00+00:00",
    )
    wire = row.to_zod_dict()
    assert wire["fieldDefinitionsTemplate"][0]["optionsJson"] == [
        "sonnet",
        "haiku",
        "opus",
    ]
