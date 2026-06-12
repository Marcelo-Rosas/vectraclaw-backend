"""Serviço para inferência direta via Cloudflare Workers AI.

Os três endpoints (run, embeddings, image-generation) usam internamente
POST /accounts/{account_id}/ai/run/{model}, mas expomos rotas separadas
para validação de schema e documentação claras.
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
        timeout=120.0,
    )


def _base_url() -> str:
    return os.getenv("CLOUDFLARE_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


# ── Text-generation / chat (run) ────────────────────────────────────────────

async def run_inference(
    account_id: str,
    *,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    seed: Optional[int] = None,
    repetition_penalty: Optional[float] = None,
    frequency_penalty: Optional[float] = None,
    presence_penalty: Optional[float] = None,
    raw: Optional[bool] = None,
    stream: Optional[bool] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai/run/{model} — texto/chat."""
    payload: Dict[str, Any] = {"messages": messages}
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if temperature is not None:
        payload["temperature"] = temperature
    if top_p is not None:
        payload["top_p"] = top_p
    if top_k is not None:
        payload["top_k"] = top_k
    if seed is not None:
        payload["seed"] = seed
    if repetition_penalty is not None:
        payload["repetition_penalty"] = repetition_penalty
    if frequency_penalty is not None:
        payload["frequency_penalty"] = frequency_penalty
    if presence_penalty is not None:
        payload["presence_penalty"] = presence_penalty
    if raw is not None:
        payload["raw"] = raw
    if stream is not None:
        payload["stream"] = stream
    if tools is not None:
        payload["tools"] = tools

    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai/run/{model}",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ── Embeddings ────────────────────────────────────────────────────────────────

async def create_embeddings(
    account_id: str,
    *,
    model: str,
    text: List[str],
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai/run/{model} — embeddings."""
    payload = {"text": text}
    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai/run/{model}",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ── Image generation ──────────────────────────────────────────────────────────

async def generate_image(
    account_id: str,
    *,
    model: str,
    prompt: str,
    num_steps: Optional[int] = None,
    guidance: Optional[float] = None,
    strength: Optional[float] = None,
) -> bytes:
    """POST /accounts/{account_id}/ai/run/{model} — imagem (retorna bytes PNG/JPEG)."""
    payload: Dict[str, Any] = {"prompt": prompt}
    if num_steps is not None:
        payload["num_steps"] = num_steps
    if guidance is not None:
        payload["guidance"] = guidance
    if strength is not None:
        payload["strength"] = strength

    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai/run/{model}",
            json=payload,
        )
        resp.raise_for_status()
        return resp.content
