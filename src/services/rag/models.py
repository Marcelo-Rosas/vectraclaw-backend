"""
Pydantic models do pipeline RAG. Inputs/outputs entre extract → chunk → embed → retrieve.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PageText(BaseModel):
    """Página única de um documento extraído. page_number é 1-indexed."""
    page_number: int = Field(..., ge=1)
    content: str


class ExtractedDocument(BaseModel):
    """Saída do extractor. Inclui full_text para chunking simples + pages para citação."""
    full_text: str
    pages: List[PageText] = Field(default_factory=list)
    page_count: int = 0
    mime_type: str
    # Metadados detectados durante extração (autor PDF, sheet name XLSX, etc.)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChunkInput(BaseModel):
    """Chunk pré-embedding. Saída do chunker. Token count é aproximado (palavras × 1.3)."""
    chunk_index: int = Field(..., ge=0)
    content: str
    page_number: Optional[int] = None
    token_count: int = 0
    # Metadados livres por chunk (sheet, section, paragraph index, etc.)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChunkResult(BaseModel):
    """Chunk retornado pelo retriever (com score). content + page_number = citação direta."""
    id: str
    document_id: str
    chunk_index: int
    page_number: Optional[int] = None
    content: str
    score: float = Field(..., ge=0.0, le=1.0)  # cosine similarity 0..1
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # Filename do documento fonte — preenchido se retriever fizer JOIN
    document_filename: Optional[str] = None
