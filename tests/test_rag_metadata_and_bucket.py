"""Testes Step 11.1: RagUploadMetadata + _ensure_rag_bucket_exists + upload com metadata."""
from __future__ import annotations

import json as _json
from unittest.mock import MagicMock

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# RagUploadMetadata — validações
# ─────────────────────────────────────────────────────────────────────────────

def test_metadata_empty_is_valid():
    from src.api_routes.rag import RagUploadMetadata
    m = RagUploadMetadata()
    d = m.model_dump(exclude_none=True)
    assert d == {"tags": []}


def test_metadata_full_payload():
    from src.api_routes.rag import RagUploadMetadata
    m = RagUploadMetadata(
        categoria="contrato",
        tags=["frete", "Rodoviário", " frete "],  # espera trim+lowercase+dedupe
        departamento="comercial",
        confidencialidade="restrita",
        data_referencia="2026-05",
        vinculo_processo_id="d24fbabc-1234-4567-89ab-cdef01234567",
    )
    d = m.model_dump(exclude_none=True)
    assert d["categoria"] == "contrato"
    assert d["tags"] == ["frete", "rodoviário"]  # dedupe + trim + lowercase
    assert d["departamento"] == "comercial"
    assert d["data_referencia"] == "2026-05"


def test_metadata_invalid_categoria_raises():
    from src.api_routes.rag import RagUploadMetadata
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RagUploadMetadata(categoria="proibido")  # type: ignore


def test_metadata_invalid_data_referencia_format():
    from src.api_routes.rag import RagUploadMetadata
    from pydantic import ValidationError
    # Mês inválido (13)
    with pytest.raises(ValidationError):
        RagUploadMetadata(data_referencia="2026-13")
    # Sem hífen
    with pytest.raises(ValidationError):
        RagUploadMetadata(data_referencia="202605")
    # Empty string vira None (válido)
    m = RagUploadMetadata(data_referencia="")
    assert m.data_referencia is None


def test_metadata_invalid_uuid():
    from src.api_routes.rag import RagUploadMetadata
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RagUploadMetadata(vinculo_processo_id="not-a-uuid")
    # Empty string vira None
    m = RagUploadMetadata(vinculo_processo_id="")
    assert m.vinculo_processo_id is None


def test_metadata_max_tags():
    from src.api_routes.rag import RagUploadMetadata
    from pydantic import ValidationError
    # 21 tags > limite de 20
    with pytest.raises(ValidationError):
        RagUploadMetadata(tags=[f"t{i}" for i in range(21)])


# ─────────────────────────────────────────────────────────────────────────────
# _ensure_rag_bucket_exists
# ─────────────────────────────────────────────────────────────────────────────

def test_ensure_bucket_exists_already_present(monkeypatch):
    """Bucket já existe → True sem criar."""
    from src.api_routes.rag import _ensure_rag_bucket_exists
    sb = MagicMock()
    bucket_obj = MagicMock()
    bucket_obj.name = "rag-documents"
    sb.storage.list_buckets.return_value = [bucket_obj]
    assert _ensure_rag_bucket_exists(sb, "rag-documents") is True
    sb.storage.create_bucket.assert_not_called()


def test_ensure_bucket_exists_disabled_returns_false(monkeypatch):
    """Bucket não existe + RAG_AUTO_PROVISION desligado → False, sem criar."""
    from src.api_routes.rag import _ensure_rag_bucket_exists
    monkeypatch.delenv("RAG_AUTO_PROVISION", raising=False)
    sb = MagicMock()
    sb.storage.list_buckets.return_value = []
    assert _ensure_rag_bucket_exists(sb, "rag-documents") is False
    sb.storage.create_bucket.assert_not_called()


def test_ensure_bucket_exists_auto_provision_creates(monkeypatch):
    """Bucket não existe + RAG_AUTO_PROVISION=true → cria privado."""
    from src.api_routes.rag import _ensure_rag_bucket_exists
    monkeypatch.setenv("RAG_AUTO_PROVISION", "true")
    sb = MagicMock()
    sb.storage.list_buckets.return_value = []
    sb.storage.create_bucket.return_value = MagicMock()
    assert _ensure_rag_bucket_exists(sb, "rag-documents") is True
    sb.storage.create_bucket.assert_called_once_with("rag-documents", options={"public": False})


def test_ensure_bucket_create_already_exists_treated_as_success(monkeypatch):
    """Race condition: outra request criou o bucket → trata 'already exists' como sucesso."""
    from src.api_routes.rag import _ensure_rag_bucket_exists
    monkeypatch.setenv("RAG_AUTO_PROVISION", "1")
    sb = MagicMock()
    sb.storage.list_buckets.return_value = []
    sb.storage.create_bucket.side_effect = Exception("Bucket already exists")
    assert _ensure_rag_bucket_exists(sb, "rag-documents") is True


# ─────────────────────────────────────────────────────────────────────────────
# Upload endpoint integração — metadata Form field
# ─────────────────────────────────────────────────────────────────────────────

def _build_upload_supabase_mock():
    sb = MagicMock()
    rd_table = MagicMock()
    rd_table.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    rd_table.insert.return_value.execute.return_value = MagicMock(data=[{"id": "doc-NEW"}])
    rd_table.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    tasks_table = MagicMock()
    tasks_table.insert.return_value.execute.return_value = MagicMock(data=[{"id": "task-NEW"}])

    def _route(name):
        return rd_table if name == "rag_documents" else tasks_table

    sb.table.side_effect = _route

    storage_obj = MagicMock()
    storage_obj.upload.return_value = MagicMock()
    sb.storage.from_.return_value = storage_obj
    bucket_obj = MagicMock(); bucket_obj.name = "rag-documents"
    sb.storage.list_buckets.return_value = [bucket_obj]

    return sb, rd_table, tasks_table


def test_upload_with_metadata_persists_in_insert(monkeypatch):
    import src.api as api
    from fastapi.testclient import TestClient

    monkeypatch.setenv("VECTRACLAW_AUTH_DISABLED", "true")
    monkeypatch.setattr(api, "validate_jwt_company_id", lambda token, cid: None)
    sb, rd_table, _ = _build_upload_supabase_mock()
    monkeypatch.setattr(api, "supabase", sb)

    metadata_payload = {
        "categoria": "manual",
        "tags": ["operacao", "frete"],
        "departamento": "operacao",
        "confidencialidade": "interna",
    }

    client = TestClient(api.app)
    resp = client.post(
        "/api/companies/cid-A/rag/upload",
        files={"arquivo": ("manual.txt", b"conteudo do manual", "text/plain")},
        data={"metadata": _json.dumps(metadata_payload)},
        headers={"Authorization": "Bearer dev-token"},
    )
    assert resp.status_code == 200, resp.text

    # Verifica que metadata foi para o insert
    insert_call = rd_table.insert.call_args.args[0]
    assert "metadata" in insert_call
    assert insert_call["metadata"]["categoria"] == "manual"
    assert insert_call["metadata"]["departamento"] == "operacao"
    assert insert_call["metadata"]["tags"] == ["operacao", "frete"]


def test_upload_invalid_metadata_returns_422(monkeypatch):
    import src.api as api
    from fastapi.testclient import TestClient

    monkeypatch.setenv("VECTRACLAW_AUTH_DISABLED", "true")
    monkeypatch.setattr(api, "validate_jwt_company_id", lambda token, cid: None)
    sb, _, _ = _build_upload_supabase_mock()
    monkeypatch.setattr(api, "supabase", sb)

    client = TestClient(api.app)
    resp = client.post(
        "/api/companies/cid-A/rag/upload",
        files={"arquivo": ("manual.txt", b"x", "text/plain")},
        data={"metadata": _json.dumps({"categoria": "PROIBIDO"})},
        headers={"Authorization": "Bearer dev-token"},
    )
    assert resp.status_code == 422


def test_upload_metadata_invalid_json_returns_422(monkeypatch):
    import src.api as api
    from fastapi.testclient import TestClient

    monkeypatch.setenv("VECTRACLAW_AUTH_DISABLED", "true")
    monkeypatch.setattr(api, "validate_jwt_company_id", lambda token, cid: None)
    sb, _, _ = _build_upload_supabase_mock()
    monkeypatch.setattr(api, "supabase", sb)

    client = TestClient(api.app)
    resp = client.post(
        "/api/companies/cid-A/rag/upload",
        files={"arquivo": ("manual.txt", b"x", "text/plain")},
        data={"metadata": "{not valid json"},
        headers={"Authorization": "Bearer dev-token"},
    )
    assert resp.status_code == 422
    assert "JSON" in resp.json()["detail"]


def test_upload_no_bucket_returns_503(monkeypatch):
    """Sem bucket + auto-provision desligado → 503 com mensagem instrutiva."""
    import src.api as api
    from fastapi.testclient import TestClient

    monkeypatch.setenv("VECTRACLAW_AUTH_DISABLED", "true")
    monkeypatch.delenv("RAG_AUTO_PROVISION", raising=False)
    monkeypatch.setattr(api, "validate_jwt_company_id", lambda token, cid: None)

    sb = MagicMock()
    sb.storage.list_buckets.return_value = []
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    monkeypatch.setattr(api, "supabase", sb)

    client = TestClient(api.app)
    resp = client.post(
        "/api/companies/cid-A/rag/upload",
        files={"arquivo": ("manual.txt", b"x", "text/plain")},
        headers={"Authorization": "Bearer dev-token"},
    )
    assert resp.status_code == 503
    assert "bucket" in resp.json()["detail"].lower()
