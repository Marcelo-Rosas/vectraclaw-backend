"""
Token-aware chunker com overlap. Preserva page_number para citação.

Aproximação de tokens: 1 token ≈ 0.75 palavras (parecido com cl100k_base).
Não usa tiktoken para evitar dep extra; aproximação é suficiente para
controlar tamanho de prompt + chunks.

Estratégia:
- Itera por página (chunks nunca cruzam fronteira de página)
- Splita por palavras
- Agrupa em janelas de max_tokens com overlap palavras finais
- Cada chunk preserva o page_number da fonte
"""
from __future__ import annotations

import logging
import re
from typing import List, Sequence

from .models import ChunkInput, PageText

logger = logging.getLogger("rag.chunker")

# 1 token ≈ 0.75 palavras (média ptBR/en para cl100k_base)
_WORDS_PER_TOKEN = 0.75


def _approx_tokens(word_count: int) -> int:
    return int(word_count / _WORDS_PER_TOKEN) + 1


def chunk_text(
    pages: Sequence[PageText],
    *,
    max_tokens: int = 500,
    overlap: int = 100,
) -> List[ChunkInput]:
    """Splita pages em ChunkInput[] com overlap. Não cruza fronteira de página.

    Args:
        pages: PageText[] do extractor.
        max_tokens: tamanho máximo por chunk em tokens (default 500).
        overlap: tokens de overlap entre chunks consecutivos da mesma página (default 100).

    Returns:
        Lista de ChunkInput com chunk_index sequencial global (não por página).
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens deve ser > 0")
    if overlap < 0 or overlap >= max_tokens:
        raise ValueError(f"overlap deve estar em [0, max_tokens). Got: {overlap}")

    # Convert max_tokens / overlap → palavras (aproximação inversa)
    max_words = int(max_tokens * _WORDS_PER_TOKEN)
    overlap_words = int(overlap * _WORDS_PER_TOKEN)
    step = max_words - overlap_words
    if step <= 0:
        raise ValueError("overlap muito alto: max_tokens - overlap deve ser > 0")

    chunks: List[ChunkInput] = []
    chunk_idx = 0

    for page in pages:
        words = re.findall(r"\S+", page.content)
        if not words:
            continue

        # Caso página inteira menor que max_words → 1 chunk
        if len(words) <= max_words:
            chunks.append(ChunkInput(
                chunk_index=chunk_idx,
                content=page.content.strip(),
                page_number=page.page_number,
                token_count=_approx_tokens(len(words)),
            ))
            chunk_idx += 1
            continue

        # Janela deslizante por palavras
        i = 0
        while i < len(words):
            window = words[i : i + max_words]
            if not window:
                break
            content = " ".join(window)
            chunks.append(ChunkInput(
                chunk_index=chunk_idx,
                content=content,
                page_number=page.page_number,
                token_count=_approx_tokens(len(window)),
            ))
            chunk_idx += 1
            if i + max_words >= len(words):
                break
            i += step

    logger.info("rag.chunker: %d pages → %d chunks (max_tokens=%d, overlap=%d)",
                len(pages), len(chunks), max_tokens, overlap)
    return chunks
