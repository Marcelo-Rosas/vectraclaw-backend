"""
Embedding via OpenAI API. Default: text-embedding-3-small com 1536 dims
(parity com schema rag_chunks.embedding vector(1536)).

Wraps SDK openai síncrono via asyncio.to_thread. Padrão alinhado a
src.managed_agents.ollama_agent_client (mesmo SDK, mesmo wrap).

Para mudar para Gemini ou outro provider:
- Criar `GeminiEmbedder` com mesmo contrato (`embed_one`, `embed_batch`)
- Atualizar `rag_chunks.embedding_model` ao salvar
- Garantir dim=1536 OU criar tabela paralela com dim diferente
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional

from openai import OpenAI

logger = logging.getLogger("rag.embedder")

DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_DIMENSIONS = 1536


class OpenAIEmbedder:
    """Embedding client via OpenAI Python SDK (async via to_thread)."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        dimensions: int = DEFAULT_DIMENSIONS,
        api_key: Optional[str] = None,
    ) -> None:
        key = api_key or os.getenv("OPENAI_KEY") or os.getenv("OPENAI_API_KEY") or ""
        if not key:
            logger.warning(
                "OpenAIEmbedder: sem OPENAI_KEY/OPENAI_API_KEY no env. "
                "Embed calls vão falhar com AuthError até configurar."
            )
        self._client = OpenAI(api_key=key or "missing")
        self._has_key = bool(key)
        self.model = model
        self.dimensions = dimensions

    async def embed_one(self, text: str) -> List[float]:
        """Embed um texto único. Retorna lista de floats com `dimensions` items."""
        results = await self.embed_batch([text])
        return results[0] if results else []

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed lote de textos. OpenAI suporta até ~8k tokens por request total."""
        if not texts:
            return []
        if not self._has_key:
            raise RuntimeError(
                "OpenAIEmbedder.embed_batch chamado sem OPENAI_KEY/OPENAI_API_KEY"
            )

        # Filter strings vazias (OpenAI rejeita) — mantém posições com [0.0]*dim
        non_empty_indices = [i for i, t in enumerate(texts) if t and t.strip()]
        non_empty_texts = [texts[i] for i in non_empty_indices]

        out: List[List[float]] = [[0.0] * self.dimensions for _ in texts]
        if not non_empty_texts:
            return out

        kwargs = {
            "model": self.model,
            "input": non_empty_texts,
        }
        # text-embedding-3-* aceita `dimensions` (truncamento via Matryoshka).
        # Para text-embedding-3-small com dimensions=1536 (default), o truncamento
        # é no-op mas ainda assim aceita o param.
        if self.model.startswith("text-embedding-3-"):
            kwargs["dimensions"] = self.dimensions

        resp = await asyncio.to_thread(
            self._client.embeddings.create,
            **kwargs,
        )

        # OpenAI retorna data[i].embedding ordenados pela ordem do input
        for batch_idx, item in enumerate(resp.data):
            original_idx = non_empty_indices[batch_idx]
            out[original_idx] = list(item.embedding)

        logger.info(
            "rag.embedder: %d texts → %d-dim embeddings (model=%s)",
            len(non_empty_texts), self.dimensions, self.model,
        )
        return out
