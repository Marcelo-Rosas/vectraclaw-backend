"""Testes do chunker token-aware."""
from __future__ import annotations

import pytest

from src.services.rag.chunker import chunk_text
from src.services.rag.models import PageText


def test_chunker_single_short_page_returns_one_chunk():
    pages = [PageText(page_number=1, content="curto texto curto")]
    chunks = chunk_text(pages, max_tokens=500, overlap=100)
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].page_number == 1
    assert chunks[0].content == "curto texto curto"


def test_chunker_long_page_splits_with_overlap():
    # 1000 palavras → ~1333 tokens; com max=500 (~375 palavras), overlap=100 (~75 palavras)
    words = " ".join(f"w{i}" for i in range(1000))
    pages = [PageText(page_number=1, content=words)]
    chunks = chunk_text(pages, max_tokens=500, overlap=100)
    assert len(chunks) >= 3
    # Todos os chunks vêm da mesma página
    assert all(c.page_number == 1 for c in chunks)
    # chunk_index sequencial começando em 0
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    # Overlap: últimas palavras do chunk N aparecem no início do chunk N+1
    for i in range(len(chunks) - 1):
        last_words = chunks[i].content.split()[-50:]
        next_first = chunks[i + 1].content.split()[:50]
        # Pelo menos algumas palavras devem se sobrepor
        assert any(w in next_first for w in last_words)


def test_chunker_does_not_cross_page_boundary():
    pages = [
        PageText(page_number=1, content="alpha " * 50),
        PageText(page_number=2, content="beta " * 50),
    ]
    chunks = chunk_text(pages, max_tokens=500, overlap=100)
    # Cada chunk deve pertencer a uma página específica
    for c in chunks:
        if "alpha" in c.content:
            assert "beta" not in c.content
            assert c.page_number == 1
        if "beta" in c.content:
            assert "alpha" not in c.content
            assert c.page_number == 2


def test_chunker_global_chunk_index_continues_across_pages():
    pages = [
        PageText(page_number=1, content="x " * 10),
        PageText(page_number=2, content="y " * 10),
    ]
    chunks = chunk_text(pages, max_tokens=500, overlap=100)
    assert len(chunks) == 2
    assert chunks[0].chunk_index == 0
    assert chunks[1].chunk_index == 1


def test_chunker_empty_pages_filtered():
    pages = [
        PageText(page_number=1, content=""),
        PageText(page_number=2, content="conteudo"),
        PageText(page_number=3, content="   "),
    ]
    chunks = chunk_text(pages, max_tokens=500, overlap=100)
    assert len(chunks) == 1
    assert chunks[0].page_number == 2


def test_chunker_invalid_overlap_raises():
    pages = [PageText(page_number=1, content="texto")]
    with pytest.raises(ValueError):
        chunk_text(pages, max_tokens=500, overlap=500)
    with pytest.raises(ValueError):
        chunk_text(pages, max_tokens=500, overlap=-1)
    with pytest.raises(ValueError):
        chunk_text(pages, max_tokens=0, overlap=0)


def test_chunker_token_count_approx_matches_word_count():
    # 100 palavras ≈ 134 tokens (1 / 0.75)
    pages = [PageText(page_number=1, content=" ".join(f"w{i}" for i in range(100)))]
    chunks = chunk_text(pages, max_tokens=500, overlap=100)
    assert len(chunks) == 1
    assert 100 < chunks[0].token_count < 200
