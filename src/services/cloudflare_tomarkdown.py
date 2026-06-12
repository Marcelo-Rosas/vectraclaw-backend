"""Serviço para conversão de arquivos para Markdown via Cloudflare Workers AI."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

_DEFAULT_BASE_URL = "https://api.cloudflare.com/client/v4"


def _client() -> httpx.AsyncClient:
    token = os.getenv("CLOUDFLARE_API_TOKEN", "")
    if not token:
        raise RuntimeError("CLOUDFLARE_API_TOKEN não configurado")
    return httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=120.0,
    )


def _base_url() -> str:
    return os.getenv("CLOUDFLARE_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


async def transform_to_markdown(
    account_id: str,
    *,
    files: List[bytes],
    file_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai/tomarkdown

    Converte arquivos para Markdown. Cloudflare aceita multipart com campo
    'files' (repetido para múltiplos uploads).
    """
    if file_names is None:
        file_names = [f"file_{i}.bin" for i in range(len(files))]

    upload_files = []
    for name, content in zip(file_names, files):
        upload_files.append(("files", (name, content)))

    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai/tomarkdown",
            files=upload_files,
        )
        resp.raise_for_status()
        return resp.json()


async def list_supported_formats(account_id: str) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai/tomarkdown/supported"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai/tomarkdown/supported"
        )
        resp.raise_for_status()
        return resp.json()
