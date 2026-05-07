"""Testes do OpenAIEmbedder. Mock do SDK — sem rede real."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _mock_response(num_inputs: int, dim: int = 1536):
    resp = MagicMock()
    resp.data = []
    for i in range(num_inputs):
        item = MagicMock()
        item.embedding = [float(i + 1) / dim] * dim
        resp.data.append(item)
    return resp


@pytest.fixture
def mock_openai(monkeypatch):
    mock_client = MagicMock()
    monkeypatch.setattr(
        "src.services.rag.embedder.OpenAI",
        lambda **kw: mock_client,
    )
    monkeypatch.setenv("OPENAI_KEY", "sk-test")
    return mock_client


@pytest.mark.asyncio
async def test_embed_one_returns_dim_floats(mock_openai):
    from src.services.rag.embedder import OpenAIEmbedder
    mock_openai.embeddings.create.return_value = _mock_response(1, dim=1536)
    e = OpenAIEmbedder()
    vec = await e.embed_one("uma pergunta")
    assert len(vec) == 1536
    assert all(isinstance(x, float) for x in vec)


@pytest.mark.asyncio
async def test_embed_batch_preserves_order(mock_openai):
    from src.services.rag.embedder import OpenAIEmbedder
    mock_openai.embeddings.create.return_value = _mock_response(3)
    e = OpenAIEmbedder()
    vecs = await e.embed_batch(["a", "b", "c"])
    assert len(vecs) == 3
    # Embeddings retornados na ordem dos inputs
    assert vecs[0][0] != vecs[1][0]


@pytest.mark.asyncio
async def test_embed_batch_filters_empty_strings(mock_openai):
    from src.services.rag.embedder import OpenAIEmbedder
    # Apenas 2 inputs não-vazios → API chamada com 2; resposta mockada com 2
    mock_openai.embeddings.create.return_value = _mock_response(2)
    e = OpenAIEmbedder()
    vecs = await e.embed_batch(["text 1", "", "text 2"])
    # 3 outputs; índice 1 (vazio) recebe vetor zero
    assert len(vecs) == 3
    assert all(x == 0.0 for x in vecs[1])
    # Índices 0 e 2 têm dados reais
    assert any(x != 0.0 for x in vecs[0])
    assert any(x != 0.0 for x in vecs[2])


@pytest.mark.asyncio
async def test_embed_batch_empty_input_returns_empty(mock_openai):
    from src.services.rag.embedder import OpenAIEmbedder
    e = OpenAIEmbedder()
    vecs = await e.embed_batch([])
    assert vecs == []
    mock_openai.embeddings.create.assert_not_called()


@pytest.mark.asyncio
async def test_embed_passes_dimensions_for_v3_models(mock_openai):
    from src.services.rag.embedder import OpenAIEmbedder
    mock_openai.embeddings.create.return_value = _mock_response(1)
    e = OpenAIEmbedder(model="text-embedding-3-small", dimensions=1536)
    await e.embed_one("texto")
    call_kwargs = mock_openai.embeddings.create.call_args.kwargs
    assert call_kwargs["model"] == "text-embedding-3-small"
    assert call_kwargs["dimensions"] == 1536


@pytest.mark.asyncio
async def test_embed_no_api_key_raises_runtime_error(monkeypatch):
    from src.services.rag.embedder import OpenAIEmbedder
    monkeypatch.delenv("OPENAI_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("src.services.rag.embedder.OpenAI", lambda **kw: MagicMock())
    e = OpenAIEmbedder()
    with pytest.raises(RuntimeError, match="OPENAI_KEY"):
        await e.embed_batch(["texto"])
