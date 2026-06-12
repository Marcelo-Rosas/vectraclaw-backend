"""Mnemos — agente curador da memória corporativa (RAG ingestor).

operation_type='rag-ingest' (despachado por agent_daemon).

Pipeline real está em ``src.services.rag.pipeline.ingest_document``;
este módulo é apenas um adapter que configura o prefixo de tabela
("rag") e bucket ("rag-documents") para o corpus operacional.

AGENT_ID: 00000000-0000-0000-0000-000000000003
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from src.agent_ids import MNEMOS_AGENT_ID  # SSOT
from src.services.rag.pipeline import ingest_document

logger = logging.getLogger("Mnemos")

DEFAULT_BUCKET = "rag-documents"


async def entrypoint(task: dict, supabase, *, embedder=None) -> Dict[str, Any]:
    """Handler do daemon para operation_type='rag-ingest'.

    Args:
        task: dict da row vectraclip.tasks.
        supabase: client com service_role.
        embedder: injetável para testes.

    Returns:
        Resultado do pipeline genérico.
    """
    return await ingest_document(
        task,
        supabase,
        table_prefix="rag",
        bucket=os.getenv("RAG_STORAGE_BUCKET", DEFAULT_BUCKET),
        embedder=embedder,
    )
