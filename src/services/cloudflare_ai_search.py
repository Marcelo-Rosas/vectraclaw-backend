"""Serviço para AI Search da Cloudflare.

Gerenciamento de tokens para AI Search.
"""
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
        timeout=60.0,
    )


def _base_url() -> str:
    return os.getenv("CLOUDFLARE_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


# ── Tokens ────────────────────────────────────────────────────────────────────

async def list_tokens(
    account_id: str,
    *,
    page: Optional[int] = None,
    per_page: Optional[int] = None,
    search: Optional[str] = None,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-search/tokens"""
    params: Dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if per_page is not None:
        params["per_page"] = per_page
    if search is not None:
        params["search"] = search

    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-search/tokens",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def create_token(
    account_id: str,
    *,
    cf_api_id: str,
    cf_api_key: str,
    name: str,
    legacy: Optional[bool] = None,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai-search/tokens"""
    payload: Dict[str, Any] = {
        "cf_api_id": cf_api_id,
        "cf_api_key": cf_api_key,
        "name": name,
    }
    if legacy is not None:
        payload["legacy"] = legacy

    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai-search/tokens",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def get_token(
    account_id: str,
    token_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-search/tokens/{id}"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-search/tokens/{token_id}",
        )
        resp.raise_for_status()
        return resp.json()


async def update_token(
    account_id: str,
    token_id: str,
    *,
    cf_api_id: str,
    cf_api_key: str,
    name: str,
    legacy: Optional[bool] = None,
) -> Dict[str, Any]:
    """PUT /accounts/{account_id}/ai-search/tokens/{id}"""
    payload: Dict[str, Any] = {
        "cf_api_id": cf_api_id,
        "cf_api_key": cf_api_key,
        "name": name,
    }
    if legacy is not None:
        payload["legacy"] = legacy

    async with _client() as client:
        resp = await client.put(
            f"{_base_url()}/accounts/{account_id}/ai-search/tokens/{token_id}",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def delete_token(
    account_id: str,
    token_id: str,
) -> Dict[str, Any]:
    """DELETE /accounts/{account_id}/ai-search/tokens/{id}"""
    async with _client() as client:
        resp = await client.delete(
            f"{_base_url()}/accounts/{account_id}/ai-search/tokens/{token_id}",
        )
        resp.raise_for_status()
        return resp.json()
