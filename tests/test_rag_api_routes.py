"""Testes do submodule api_routes/rag.py com TestClient + mocks."""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _patch_jwt(monkeypatch):
    """Bypass auth: middleware lê VECTRACLAW_AUTH_DISABLED + função no-op."""
    import src.api as api
    monkeypatch.setenv("VECTRACLAW_AUTH_DISABLED", "true")
    monkeypatch.setattr(api, "validate_jwt_company_id", lambda token, cid: None)


def _build_supabase_mock(
    *,
    duplicate_doc=None,
    insert_doc_id="doc-NEW",
    insert_task_id="task-NEW",
    list_data=None,
    get_data=None,
):
    """Mock do client supabase com cadeia .table().select()/.insert()/.update()/.delete()."""
    sb = MagicMock()

    # rag_documents.select(...).eq().eq().limit().execute()
    rd_table = MagicMock()
    rd_select = MagicMock()
    rd_select.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[duplicate_doc] if duplicate_doc else [],
    )
    # Para list: .select().eq().order().limit().execute()
    rd_select.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=list_data or [],
    )
    rd_select.eq.return_value.order.return_value.limit.return_value.eq.return_value.execute.return_value = MagicMock(
        data=list_data or [],
    )
    # Para get single: .select().eq().limit().execute()
    rd_select.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[get_data] if get_data else ([duplicate_doc] if duplicate_doc else []),
    )
    rd_table.select.return_value = rd_select

    rd_table.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": insert_doc_id}],
    )
    rd_table.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    rd_table.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    # tasks.insert(...).execute()
    tasks_table = MagicMock()
    tasks_table.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": insert_task_id}],
    )

    def _table_router(name):
        if name == "rag_documents":
            return rd_table
        if name == "tasks":
            return tasks_table
        return MagicMock()

    sb.table.side_effect = _table_router

    # Storage
    storage_obj = MagicMock()
    storage_obj.upload.return_value = MagicMock()
    storage_obj.remove.return_value = MagicMock()
    sb.storage.from_.return_value = storage_obj

    # rpc (para query)
    sb.rpc.return_value.execute.return_value = MagicMock(data=[])

    return sb, rd_table, tasks_table, storage_obj


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_upload_happy_path(monkeypatch):
    """Upload novo: sha256 calcula, storage upload, DB insert, task criada."""
    import src.api as api
    from fastapi.testclient import TestClient

    _patch_jwt(monkeypatch)
    sb, rd, tasks, storage = _build_supabase_mock()
    monkeypatch.setattr(api, "supabase", sb)
    # Bypass auth_middleware (set request.state.token)
    monkeypatch.setattr(api, "AUTH_DISABLED", True, raising=False)

    client = TestClient(api.app)
    file_content = b"texto para indexar no RAG"
    resp = client.post(
        "/api/companies/cid-A/rag/upload",
        files={"arquivo": ("manual.txt", file_content, "text/plain")},
        headers={"Authorization": "Bearer dev-token"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["document_id"] == "doc-NEW"
    assert body["task_id"] == "task-NEW"
    assert body["status"] == "uploaded"
    assert body["duplicate"] is False
    assert body["filename"] == "manual.txt"
    assert body["size_bytes"] == len(file_content)
    # sha256 calculado corretamente (64 chars hex)
    assert len(body["sha256"]) == 64

    # Storage chamado com bucket+path = {company_id}/{sha256}.txt
    storage.upload.assert_called_once()
    upload_args = storage.upload.call_args
    assert upload_args.args[0].startswith("cid-A/")
    assert upload_args.args[0].endswith(".txt")

    # Task criada com operation_type='rag-ingest' + assigned_to_agent_id=Mnemos
    task_insert = tasks.insert.call_args.args[0]
    assert task_insert["operation_type"] == "rag-ingest"
    assert task_insert["assigned_to_agent_id"] == "00000000-0000-0000-0000-000000000003"
    assert task_insert["input_json"]["document_id"] == "doc-NEW"


def test_upload_duplicate_returns_existing(monkeypatch):
    """Re-upload do mesmo arquivo (sha256 match) → retorna existing sem inserir."""
    import src.api as api
    from fastapi.testclient import TestClient

    _patch_jwt(monkeypatch)
    existing = {
        "id": "doc-EXISTING", "filename": "manual.txt",
        "status": "indexed", "ingest_task_id": "task-OLD",
    }
    sb, rd, tasks, storage = _build_supabase_mock(duplicate_doc=existing)
    monkeypatch.setattr(api, "supabase", sb)

    client = TestClient(api.app)
    resp = client.post(
        "/api/companies/cid-A/rag/upload",
        files={"arquivo": ("manual.txt", b"conteudo", "text/plain")},
        headers={"Authorization": "Bearer dev-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == "doc-EXISTING"
    assert body["task_id"] == "task-OLD"
    assert body["status"] == "indexed"
    assert body["duplicate"] is True

    # NÃO chama storage.upload nem tasks.insert pq é dedup
    storage.upload.assert_not_called()
    tasks.insert.assert_not_called()


def test_upload_unsupported_extension_returns_422(monkeypatch):
    import src.api as api
    from fastapi.testclient import TestClient

    _patch_jwt(monkeypatch)
    sb, *_ = _build_supabase_mock()
    monkeypatch.setattr(api, "supabase", sb)

    client = TestClient(api.app)
    resp = client.post(
        "/api/companies/cid-A/rag/upload",
        files={"arquivo": ("malware.exe", b"binary", "application/octet-stream")},
        headers={"Authorization": "Bearer dev-token"},
    )
    assert resp.status_code == 422
    assert "extensão não suportada" in resp.json()["detail"]


def test_upload_empty_file_returns_422(monkeypatch):
    import src.api as api
    from fastapi.testclient import TestClient

    _patch_jwt(monkeypatch)
    sb, *_ = _build_supabase_mock()
    monkeypatch.setattr(api, "supabase", sb)

    client = TestClient(api.app)
    resp = client.post(
        "/api/companies/cid-A/rag/upload",
        files={"arquivo": ("vazio.txt", b"", "text/plain")},
        headers={"Authorization": "Bearer dev-token"},
    )
    assert resp.status_code == 422


def test_query_calls_retriever_and_returns_matches(monkeypatch):
    """POST /query → embedder + RPC + retornar chunks."""
    import src.api as api
    from fastapi.testclient import TestClient
    from src.services.rag.models import ChunkResult

    _patch_jwt(monkeypatch)
    sb, *_ = _build_supabase_mock()
    monkeypatch.setattr(api, "supabase", sb)

    fake_results = [
        ChunkResult(
            id="chunk-1", document_id="doc-1", chunk_index=0,
            page_number=2, content="Política de garantia: 12 meses.",
            score=0.91, metadata={}, document_filename="manual.pdf",
        ),
    ]

    async def _fake_query_top_k(*args, **kwargs):
        return fake_results

    monkeypatch.setattr(
        "src.services.rag.retriever.query_top_k",
        _fake_query_top_k,
    )

    client = TestClient(api.app)
    resp = client.post(
        "/api/companies/cid-A/rag/query",
        json={"query": "qual o prazo de garantia?", "k": 3, "min_score": 0.5},
        headers={"Authorization": "Bearer dev-token"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "qual o prazo de garantia?"
    assert body["k"] == 3
    assert body["total"] == 1
    assert body["matches"][0]["score"] == 0.91
    assert body["matches"][0]["document_filename"] == "manual.pdf"


def test_query_empty_text_returns_422(monkeypatch):
    import src.api as api
    from fastapi.testclient import TestClient

    _patch_jwt(monkeypatch)
    sb, *_ = _build_supabase_mock()
    monkeypatch.setattr(api, "supabase", sb)

    client = TestClient(api.app)
    resp = client.post(
        "/api/companies/cid-A/rag/query",
        json={"query": "", "k": 5},
        headers={"Authorization": "Bearer dev-token"},
    )
    assert resp.status_code == 422  # Pydantic min_length=1 rejeita


def test_routes_registered():
    """Smoke: RAG routes estão registradas no FastAPI app."""
    import src.api as api
    paths = sorted({str(r.path) for r in api.app.routes if "/rag" in str(r.path)})
    assert "/api/companies/{company_id}/rag/upload" in paths
    assert "/api/companies/{company_id}/rag/documents" in paths
    assert "/api/companies/{company_id}/rag/query" in paths
    assert "/api/rag/documents/{document_id}" in paths
