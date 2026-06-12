"""
Embedding via OpenAI API. Default: text-embedding-3-small com 768 dims
(parity com schema rag_chunks.embedding vector(768) — migration 20260520140000).

Wraps SDK openai síncrono via asyncio.to_thread. Padrão alinhado a
src.managed_agents.ollama_agent_client (mesmo SDK, mesmo wrap).

Para mudar para Gemini ou outro provider:
- Criar `GeminiEmbedder` com mesmo contrato (`embed_one`, `embed_batch`)
- Atualizar `rag_chunks.embedding_model` ao salvar
- Garantir dim=768 OU criar tabela paralela com dim diferente
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional

import math

from openai import OpenAI

logger = logging.getLogger("rag.embedder")

DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_DIMENSIONS = 768
DEFAULT_GEMINI_MODEL = "gemini-embedding-001"


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
        # Para text-embedding-3-small com dimensions=768 (default pós-migration),
        # o truncamento reduz de 1536 nativas para 768.
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


class GeminiEmbedder:
    """Embedding client via Google Gemini API com Matryoshka 768 dims.

    Mantém parity de schema com OpenAIEmbedder (dim=768, vector(768)).
    `gemini-embedding-001` aceita output_dimensionality em [128, 3072];
    para dim < 3072, NÃO normaliza automaticamente — fazemos L2 manual
    pra garantir cosine similarity correta no índice HNSW.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_GEMINI_MODEL,
        dimensions: int = DEFAULT_DIMENSIONS,
        api_key: Optional[str] = None,
    ) -> None:
        key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        self._has_key = bool(key)
        self._client = None
        if key:
            try:
                from google import genai
                self._client = genai.Client(api_key=key)
            except ImportError:
                logger.error(
                    "GeminiEmbedder: google-genai não instalado. "
                    "Adicione `google-genai>=1.0.0` ao requirements.txt."
                )
                self._has_key = False
        if not self._has_key:
            logger.warning(
                "GeminiEmbedder: sem GEMINI_API_KEY/GOOGLE_API_KEY no env. "
                "Embed calls vão falhar até configurar."
            )
        self.model = model
        self.dimensions = dimensions

    async def embed_one(self, text: str) -> List[float]:
        results = await self.embed_batch([text])
        return results[0] if results else []

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if not self._has_key or self._client is None:
            raise RuntimeError(
                "GeminiEmbedder.embed_batch chamado sem GEMINI_API_KEY/GOOGLE_API_KEY"
            )

        non_empty_indices = [i for i, t in enumerate(texts) if t and t.strip()]
        non_empty_texts = [texts[i] for i in non_empty_indices]

        out: List[List[float]] = [[0.0] * self.dimensions for _ in texts]
        if not non_empty_texts:
            return out

        from google.genai import types

        resp = await asyncio.to_thread(
            self._client.models.embed_content,
            model=self.model,
            contents=non_empty_texts,
            config=types.EmbedContentConfig(output_dimensionality=self.dimensions),
        )

        for batch_idx, embed_obj in enumerate(resp.embeddings):
            original_idx = non_empty_indices[batch_idx]
            vec = list(embed_obj.values)
            # gemini-embedding-001 com dim < 3072 NÃO normaliza automático.
            # Schema usa cosine distance (vector_cosine_ops), que assume L2-normalized
            # — sem normalização, o ranking de similaridade fica enviesado por magnitude.
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            out[original_idx] = vec

        logger.info(
            "rag.embedder gemini: %d texts → %d-dim (model=%s, L2-normalized)",
            len(non_empty_texts), self.dimensions, self.model,
        )
        return out


class FallbackEmbedder:
    """Tenta `primary` primeiro; em qualquer exceção tenta `fallbacks` na ordem.

    Cenário típico: OpenAI primary, Gemini fallback. Se OpenAI estourar quota
    (429) ou key inválida (401), o Mnemos não trava — usa Gemini transparente.

    O atributo `model` reflete o último embedder que **conseguiu** retornar
    embeddings. Mnemos lê isso depois de `embed_batch` para popular
    `rag_chunks.embedding_model` corretamente (importante para queries
    futuras saberem qual modelo gerou cada vetor).

    Limitação: presume que todos os embedders compartilham `dimensions`
    (caso contrário, schema vector(N) quebra). Se quiser dims diferentes,
    use tabelas paralelas (`rag_chunks_<dim>`) e roteamento por
    `embedding_model`.
    """

    def __init__(
        self,
        primary: object,
        fallbacks: List[object],
    ) -> None:
        self.primary = primary
        self.fallbacks = fallbacks
        # Snapshot da dim/model do primary para inicialização. `self.model`
        # é atualizado dinamicamente após cada embed_batch bem-sucedido.
        self.dimensions = getattr(primary, "dimensions", DEFAULT_DIMENSIONS)
        self.model = getattr(primary, "model", DEFAULT_MODEL)

    async def embed_one(self, text: str) -> List[float]:
        results = await self.embed_batch([text])
        return results[0] if results else []

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        last_err: Optional[Exception] = None
        for embedder in [self.primary, *self.fallbacks]:
            try:
                result = await embedder.embed_batch(texts)
                self.model = getattr(embedder, "model", self.model)
                return result
            except Exception as e:
                last_err = e
                logger.warning(
                    "FallbackEmbedder: %s falhou (%s) — tentando próximo",
                    embedder.__class__.__name__, e,
                )
                continue
        raise RuntimeError(
            f"FallbackEmbedder: todos {1 + len(self.fallbacks)} embedders falharam. "
            f"Último erro: {last_err!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# OllamaEmbedder — embedding LOCAL (sem API key, sem 403/quota). nomic-embed-text
# = 768 dim. Não normaliza → L2 manual (schema cosine vector_cosine_ops).
# ─────────────────────────────────────────────────────────────────────────────

OLLAMA_DEFAULT_MODEL = "nomic-embed-text"
OLLAMA_DEFAULT_DIM = 768
OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaEmbedder:
    def __init__(
        self,
        *,
        model: str = OLLAMA_DEFAULT_MODEL,
        dimensions: int = OLLAMA_DEFAULT_DIM,
        base_url: str = OLLAMA_DEFAULT_BASE_URL,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self.base_url = (base_url or OLLAMA_DEFAULT_BASE_URL).rstrip("/")

    async def embed_one(self, text: str) -> List[float]:
        r = await self.embed_batch([text])
        return r[0] if r else []

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        import requests

        def _one(t: str) -> List[float]:
            if not t or not t.strip():
                return [0.0] * self.dimensions
            resp = requests.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": t},
                timeout=60,
            )
            resp.raise_for_status()
            vec = resp.json().get("embedding") or []
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            return vec

        out = [await asyncio.to_thread(_one, t) for t in texts]
        logger.info(
            "rag.embedder ollama: %d texts → %d-dim (model=%s, L2-normalized, base=%s)",
            len(texts), self.dimensions, self.model, self.base_url,
        )
        return out


def resolve_embedder(agent_id: Optional[str] = None):
    """Catalog-driven (Regra #2): resolve o embedder pelo adapter do agente
    (default Mnemos). Lê agent_adapter_configs + W5 company values + vault →
    provider/model/base_url/dimensions. ollama→OllamaEmbedder; google→Gemini;
    openai→OpenAI. Sem config → fallback Ollama local (nomic).

    Single-tenant dev: resolve por agent_id (limit 1)."""
    if agent_id is None:
        from src.agent_ids import MNEMOS_AGENT_ID
        agent_id = MNEMOS_AGENT_ID
    provider = None
    model = None
    base_url = None
    dimensions = None
    try:
        from src.api import supabase, resolve_secret_ref
        if supabase:
            res = (
                supabase.table("agent_adapter_configs")
                .select("field_values_json, company_id, adapter_id, adapter_catalog!inner(provider)")
                .eq("agent_id", agent_id).limit(1).execute()
            )
            if res.data:
                row = res.data[0]
                provider = (row.get("adapter_catalog") or {}).get("provider")
                fv = dict(row.get("field_values_json") or {})
                cid, aid = row.get("company_id"), row.get("adapter_id")
                if cid and aid:
                    cv = (
                        supabase.table("company_adapter_values")
                        .select("field_values_json").eq("company_id", cid).eq("adapter_id", aid).limit(1).execute()
                    )
                    if cv.data:
                        merged = dict(cv.data[0].get("field_values_json") or {})
                        merged.update({k: v for k, v in fv.items() if v not in (None, "")})
                        fv = merged
                if cid:
                    fv = {k: (resolve_secret_ref(v, str(cid)) if isinstance(v, str) and v.startswith("vault://") else v) for k, v in fv.items()}
                model = fv.get("model_id") or fv.get("model")
                base_url = fv.get("base_url")
                dimensions = int(fv["dimensions"]) if fv.get("dimensions") else None
    except Exception as e:
        logger.warning("resolve_embedder(%s) falhou (fallback ollama local): %s", agent_id, e)

    if provider == "ollama":
        return OllamaEmbedder(
            model=model or OLLAMA_DEFAULT_MODEL,
            dimensions=dimensions or OLLAMA_DEFAULT_DIM,
            base_url=base_url or OLLAMA_DEFAULT_BASE_URL,
        )
    if provider == "google":
        return GeminiEmbedder(model=model or DEFAULT_GEMINI_MODEL, dimensions=dimensions or DEFAULT_DIMENSIONS)
    if provider == "openai":
        return OpenAIEmbedder(model=model or DEFAULT_MODEL, dimensions=dimensions or DEFAULT_DIMENSIONS)
    # default: Ollama local (nomic) — sem dep de API key/quota
    return OllamaEmbedder()
