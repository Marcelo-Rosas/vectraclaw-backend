"""Testes do agente Mnemos. Mocks supabase + storage + embedder."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_supabase_mock(doc_row=None, storage_bytes=b"%PDF-1.4 fake", insert_data=None):
    """Constrói mock supabase com cadeia .table().select()/.update()/.insert() + storage."""
    sb = MagicMock()
    table_mock = MagicMock()

    # SELECT chain → returns doc_row (or empty)
    select_chain = MagicMock()
    select_chain.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[doc_row] if doc_row else [],
    )
    table_mock.select.return_value = select_chain

    # UPDATE chain → captures call
    update_chain = MagicMock()
    update_chain.eq.return_value.execute.return_value = MagicMock(data=[])
    table_mock.update.return_value = update_chain

    # INSERT chain → returns insert_data (or empty)
    table_mock.insert.return_value.execute.return_value = MagicMock(
        data=insert_data or [{"id": "chunk-1"}],
    )

    sb.table.return_value = table_mock

    # Storage mock
    storage_obj = MagicMock()
    storage_obj.download.return_value = storage_bytes
    sb.storage.from_.return_value = storage_obj

    return sb, table_mock, storage_obj


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_entrypoint_missing_document_id_returns_errored():
    from src.agents.mnemos import entrypoint
    sb, _, _ = _make_supabase_mock()
    result = entrypoint({"input_json": {}}, sb)
    assert result["status"] == "errored"
    assert "document_id" in result["error"]


def test_entrypoint_doc_not_found_returns_errored():
    from src.agents.mnemos import entrypoint
    sb, _, _ = _make_supabase_mock(doc_row=None)
    result = entrypoint({"input_json": {"document_id": "no-such-id"}}, sb)
    assert result["status"] == "errored"
    assert "not found" in result["error"]


def test_entrypoint_happy_path_marks_indexed_and_inserts_chunks(monkeypatch):
    """Doc → process → download → extract → chunk → embed → insert → indexed."""
    from src.agents.mnemos import entrypoint
    from src.services.rag.models import ExtractedDocument, PageText, ChunkInput

    doc_row = {
        "id": "doc-1",
        "company_id": "cid-A",
        "storage_path": "cid-A/abc123.pdf",
        "filename": "manual.pdf",
        "mime_type": "application/pdf",
    }
    sb, table_mock, storage_obj = _make_supabase_mock(doc_row=doc_row)

    fake_extracted = ExtractedDocument(
        full_text="Texto extraído.",
        pages=[PageText(page_number=1, content="Texto da página 1.")],
        page_count=1,
        mime_type="application/pdf",
    )
    fake_chunks = [
        ChunkInput(chunk_index=0, content="Texto da página 1.", page_number=1, token_count=5),
    ]
    monkeypatch.setattr("src.services.rag.extractor.extract_text", lambda p, mime_type=None: fake_extracted)
    monkeypatch.setattr("src.services.rag.chunker.chunk_text", lambda pages, **kw: fake_chunks)

    fake_embedder = MagicMock()
    fake_embedder.embed_batch = AsyncMock(return_value=[[0.1] * 1536])
    fake_embedder.model = "text-embedding-3-small"

    result = entrypoint(
        {"input_json": {"document_id": "doc-1"}},
        sb,
        embedder=fake_embedder,
    )

    assert result["status"] == "done"
    assert result["chunks_inserted"] == 1
    assert result["page_count"] == 1

    # Storage download chamado com bucket+path corretos
    sb.storage.from_.assert_called_with("rag-documents")
    storage_obj.download.assert_called_with("cid-A/abc123.pdf")

    # rag_documents teve 2 updates: processing + indexed
    update_calls = table_mock.update.call_args_list
    statuses_set = [c.args[0].get("status") for c in update_calls]
    assert "processing" in statuses_set
    assert "indexed" in statuses_set

    # rag_chunks insert com company_id + embedding
    insert_calls = [c for c in table_mock.insert.call_args_list]
    assert len(insert_calls) >= 1
    inserted_rows = insert_calls[0].args[0]
    assert isinstance(inserted_rows, list)
    assert inserted_rows[0]["document_id"] == "doc-1"
    assert inserted_rows[0]["company_id"] == "cid-A"
    assert inserted_rows[0]["embedding_model"] == "text-embedding-3-small"
    assert len(inserted_rows[0]["embedding"]) == 1536


def test_entrypoint_empty_extraction_marks_indexed_with_zero_chunks(monkeypatch):
    """PDF vazio → status=indexed com 0 chunks (não é erro)."""
    from src.agents.mnemos import entrypoint
    from src.services.rag.models import ExtractedDocument

    doc_row = {
        "id": "doc-2",
        "company_id": "cid-A",
        "storage_path": "cid-A/empty.pdf",
        "filename": "empty.pdf",
        "mime_type": "application/pdf",
    }
    sb, table_mock, _ = _make_supabase_mock(doc_row=doc_row)

    monkeypatch.setattr(
        "src.services.rag.extractor.extract_text",
        lambda p, mime_type=None: ExtractedDocument(
            full_text="", pages=[], page_count=0, mime_type="application/pdf",
        ),
    )

    fake_embedder = MagicMock()
    fake_embedder.embed_batch = AsyncMock(return_value=[])
    fake_embedder.model = "text-embedding-3-small"

    result = entrypoint(
        {"input_json": {"document_id": "doc-2"}},
        sb,
        embedder=fake_embedder,
    )

    assert result["status"] == "done"
    assert result["chunks_inserted"] == 0
    assert result["page_count"] == 0
    # Embedder NÃO foi chamado (curto-circuito antes do embed)
    fake_embedder.embed_batch.assert_not_called()
    # Não deve ter inserido nada em rag_chunks (apenas update em rag_documents)
    insert_called_for_chunks = any(
        c.args[0] for c in table_mock.insert.call_args_list
    )
    assert not insert_called_for_chunks


def test_entrypoint_storage_failure_marks_failed(monkeypatch):
    """Erro no download do Storage → status=failed com error_detail."""
    from src.agents.mnemos import entrypoint

    doc_row = {
        "id": "doc-3",
        "company_id": "cid-A",
        "storage_path": "cid-A/missing.pdf",
        "filename": "missing.pdf",
        "mime_type": "application/pdf",
    }
    sb, table_mock, storage_obj = _make_supabase_mock(doc_row=doc_row)
    storage_obj.download.side_effect = Exception("storage 404")

    result = entrypoint(
        {"input_json": {"document_id": "doc-3"}},
        sb,
    )

    assert result["status"] == "errored"
    assert "storage" in result["error"].lower() or "404" in result["error"]
    # Documento marcado como failed
    update_calls = table_mock.update.call_args_list
    final_update = update_calls[-1].args[0]
    assert final_update.get("status") == "failed"
    assert "error_detail" in final_update


def test_entrypoint_extract_failure_marks_failed(monkeypatch):
    """Erro no extract → status=failed."""
    from src.agents.mnemos import entrypoint

    doc_row = {
        "id": "doc-4",
        "company_id": "cid-A",
        "storage_path": "cid-A/corrupt.pdf",
        "filename": "corrupt.pdf",
        "mime_type": "application/pdf",
    }
    sb, table_mock, _ = _make_supabase_mock(doc_row=doc_row)

    def _boom(*args, **kw):
        raise ValueError("PDF corrupto")

    monkeypatch.setattr("src.services.rag.extractor.extract_text", _boom)

    result = entrypoint(
        {"input_json": {"document_id": "doc-4"}},
        sb,
    )

    assert result["status"] == "errored"
    final_update = table_mock.update.call_args_list[-1].args[0]
    assert final_update["status"] == "failed"


def test_mnemos_agent_id_constant():
    from src.agents.mnemos import MNEMOS_AGENT_ID
    assert MNEMOS_AGENT_ID == "00000000-0000-0000-0000-000000000003"
