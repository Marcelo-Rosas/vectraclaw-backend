"""Serviço para gerenciar finetunes da Cloudflare Workers AI.

REST client leve via httpx. Auth e account_id vêm do adapter config
(cloudflare_ai) ou das env vars CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

_DEFAULT_BASE_URL = "https://api.cloudflare.com/client/v4"


def _client() -> httpx.AsyncClient:
    token = os.getenv("CLOUDFLARE_API_TOKEN", "")
    if not token:
        raise RuntimeError("CLOUDFLARE_API_TOKEN não configurado")
    return httpx.AsyncClient(
        headers={
            "Authorization": f"Bearer {token}",
        },
        timeout=120.0,
    )


def _base_url() -> str:
    return os.getenv("CLOUDFLARE_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


# ── Finetunes ───────────────────────────────────────────────────────────────

async def list_finetunes(account_id: str) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai/finetunes"""
    async with _client() as client:
        resp = await client.get(f"{_base_url()}/accounts/{account_id}/ai/finetunes")
        resp.raise_for_status()
        return resp.json()


async def create_finetune(
    account_id: str,
    *,
    model: str,
    name: str,
    description: Optional[str] = None,
    public: Optional[bool] = None,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai/finetunes"""
    payload: Dict[str, Any] = {"model": model, "name": name}
    if description is not None:
        payload["description"] = description
    if public is not None:
        payload["public"] = public
    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai/finetunes",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ── Assets ──────────────────────────────────────────────────────────────────

async def upload_asset(
    account_id: str,
    finetune_id: str,
    *,
    file_bytes: bytes,
    file_name: str,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai/finetunes/{finetune_id}/finetune-assets"""
    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai/finetunes/{finetune_id}/finetune-assets",
            data={"file_name": file_name},
            files={"file": (file_name, file_bytes)},
        )
        resp.raise_for_status()
        return resp.json()


# ── Public ──────────────────────────────────────────────────────────────────

async def list_public_finetunes(
    account_id: str,
    *,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    order_by: Optional[str] = None,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai/finetunes/public"""
    params: Dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    if order_by is not None:
        params["order_by"] = order_by
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai/finetunes/public",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()
