"""Serviço para descoberta e schema de modelos Cloudflare Workers AI."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

_DEFAULT_BASE_URL = "https://api.cloudflare.com/client/v4"


def _client() -> httpx.AsyncClient:
    token = os.getenv("CLOUDFLARE_API_TOKEN", "")
    if not token:
        raise RuntimeError("CLOUDFLARE_API_TOKEN não configurado")
    return httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=60.0,
    )


def _base_url() -> str:
    return os.getenv("CLOUDFLARE_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


async def search_models(
    account_id: str,
    *,
    author: Optional[str] = None,
    format: Optional[str] = None,  # noqa: A002  # "openrouter"
    hide_experimental: Optional[bool] = None,
    page: Optional[int] = None,
    per_page: Optional[int] = None,
    search: Optional[str] = None,
    source: Optional[int] = None,
    task: Optional[str] = None,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai/models/search"""
    params: Dict[str, Any] = {}
    if author is not None:
        params["author"] = author
    if format is not None:
        params["format"] = format
    if hide_experimental is not None:
        params["hide_experimental"] = str(hide_experimental).lower()
    if page is not None:
        params["page"] = page
    if per_page is not None:
        params["per_page"] = per_page
    if search is not None:
        params["search"] = search
    if source is not None:
        params["source"] = source
    if task is not None:
        params["task"] = task

    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai/models/search",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def get_model_schema(
    account_id: str,
    *,
    model: str,  # noqa: A002
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai/models/schema"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai/models/schema",
            params={"model": model},
        )
        resp.raise_for_status()
        return resp.json()
