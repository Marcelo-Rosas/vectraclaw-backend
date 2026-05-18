"""
Cliente HTTP do runtime Nous Hermes + resolução de config catalog-driven.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger("Vectra.NousHermes")

NOUS_HERMES_SLUG = "nous-hermes"
# Infraestrutura (Regra #2): única env permitida para este adapter.
DEFAULT_RUNTIME_URL = "http://nous-hermes-runtime:9120"


class NousHermesConfigError(ValueError):
    """Config de produto ausente ou inválida no catálogo (adapter/company values)."""


def runtime_base_url() -> str:
    return (os.getenv("NOUS_HERMES_RUNTIME_URL") or DEFAULT_RUNTIME_URL).rstrip("/")


def is_adapter_active(supabase_client, company_id: str) -> bool:
    if not supabase_client or not company_id:
        return False
    try:
        res = (
            supabase_client.table("adapter_catalog")
            .select("id")
            .eq("company_id", company_id)
            .eq("slug", NOUS_HERMES_SLUG)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception as exc:
        logger.warning("is_adapter_active failed company=%s: %s", company_id, exc)
        return False


def get_adapter_id(supabase_client, company_id: str) -> Optional[str]:
    if not supabase_client:
        return None
    try:
        res = (
            supabase_client.table("adapter_catalog")
            .select("id")
            .eq("company_id", company_id)
            .eq("slug", NOUS_HERMES_SLUG)
            .limit(1)
            .execute()
        )
        if res.data:
            return str(res.data[0]["id"])
    except Exception as exc:
        logger.warning("get_adapter_id failed: %s", exc)
    return None


def resolve_nous_hermes_config(
    supabase_client,
    company_id: str,
    agent_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Monta hermes_config + api_key resolvidos (company + override agente).
    Import lazy de api helpers para evitar circular import no load do módulo.
    """
    from src.api import get_company_adapter_values, resolve_adapter_field_value

    adapter_id = get_adapter_id(supabase_client, company_id)
    if not adapter_id:
        return {}, None

    company_values = get_company_adapter_values(company_id, adapter_id) or {}
    agent_values: Dict[str, Any] = {}
    if agent_id and supabase_client:
        try:
            res = (
                supabase_client.table("agent_adapter_configs")
                .select("field_values_json")
                .eq("company_id", company_id)
                .eq("adapter_id", adapter_id)
                .eq("agent_id", agent_id)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            if res.data:
                agent_values = res.data[0].get("field_values_json") or {}
        except Exception as exc:
            logger.warning("agent_adapter_configs lookup failed: %s", exc)

    def _r(field: str) -> Optional[str]:
        return resolve_adapter_field_value(field, agent_values, company_values, company_id)

    inference_provider = (_r("inference_provider") or "").strip().lower()
    if not inference_provider:
        raise NousHermesConfigError(
            "inference_provider não configurado — preencha em Admin → Connectors (nous-hermes)"
        )

    model_id = (_r("model_id") or "").strip()
    if not model_id:
        raise NousHermesConfigError("model_id não configurado para adapter nous-hermes")

    approval_mode = (_r("approval_mode") or "").strip().lower()
    if not approval_mode:
        raise NousHermesConfigError("approval_mode não configurado para adapter nous-hermes")

    raw_turns = (_r("max_turns") or "").strip()
    if not raw_turns:
        raise NousHermesConfigError("max_turns não configurado para adapter nous-hermes")
    try:
        max_turns = int(raw_turns)
    except (TypeError, ValueError) as exc:
        raise NousHermesConfigError(f"max_turns inválido: {raw_turns!r}") from exc
    max_turns = max(1, min(max_turns, 90))

    ollama_base_url = (_r("ollama_base_url") or "").strip()
    if inference_provider == "ollama" and not ollama_base_url:
        raise NousHermesConfigError(
            "ollama_base_url obrigatório quando inference_provider=ollama"
        )

    raw_timeout = (_r("timeout_seconds") or "").strip()
    if not raw_timeout:
        raise NousHermesConfigError("timeout_seconds não configurado para adapter nous-hermes")
    try:
        timeout_seconds = int(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise NousHermesConfigError(f"timeout_seconds inválido: {raw_timeout!r}") from exc
    timeout_seconds = max(30, min(timeout_seconds, 600))

    cfg: Dict[str, Any] = {
        "inference_provider": inference_provider,
        "model_id": model_id,
        "approval_mode": approval_mode,
        "max_turns": max_turns,
        "timeout_seconds": timeout_seconds,
    }
    if ollama_base_url:
        cfg["ollama_base_url"] = ollama_base_url

    api_key = _r("api_key")
    if inference_provider in ("openrouter", "anthropic") and not api_key:
        raise NousHermesConfigError(
            f"api_key obrigatória quando inference_provider={inference_provider}"
        )
    return cfg, api_key


async def runtime_health() -> Dict[str, Any]:
    url = f"{runtime_base_url()}/health"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def runtime_exec(
    *,
    prompt: str,
    hermes_config: Dict[str, Any],
    api_key: Optional[str] = None,
    max_turns: Optional[int] = None,
    timeout_seconds: int = 180,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "prompt": prompt,
        "hermes_config": hermes_config,
        "api_key": api_key,
        "ignore_user_config": True,
        "timeout_seconds": timeout_seconds,
    }
    if max_turns is not None:
        payload["max_turns"] = max_turns

    url = f"{runtime_base_url()}/exec"
    async with httpx.AsyncClient(timeout=float(timeout_seconds) + 30.0) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code >= 400:
            detail = resp.text[:500]
            return {
                "success": False,
                "content": "",
                "exit_code": resp.status_code,
                "duration_ms": 0,
                "error": detail,
            }
        return resp.json()
