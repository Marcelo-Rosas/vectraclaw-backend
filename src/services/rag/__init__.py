"""
src.services.rag — Pipeline RAG do VectraClaw.

Substitui o RAG PHP standalone por uma stack Python integrada:
- Extract: PDF/TXT/HTML/JSON/XLSX → texto + páginas
- Chunk: split em segmentos (default 500 tokens, 100 overlap)
- Embed: OpenAI text-embedding-3-small (1536 dim — locked pelo schema)
- Retrieve: pgvector HNSW cosine via Supabase RPC

Schema: vectraclip.rag_documents + vectraclip.rag_chunks (PR #18).
Tool externa para o CMA: query_rag em src/m3_tools.py (PR 5/5).
Daemon ingestor: Mnemos (PR 3/5).
"""
from .models import (
    ChunkInput,
    ChunkResult,
    ExtractedDocument,
    PageText,
)
from .extractor import extract_text
from .chunker import chunk_text
from .embedder import OpenAIEmbedder
from .retriever import query_top_k

__all__ = [
    "ChunkInput",
    "ChunkResult",
    "ExtractedDocument",
    "PageText",
    "extract_text",
    "chunk_text",
    "OpenAIEmbedder",
    "query_top_k",
]
