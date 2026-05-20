"""Oracle LLM stream — dispatcher provider-agnostic pro chat SIPOC.

Antes o oracle_maker chamava gemini_client.stream_generate FIXO → Oracle preso
no Gemini (403 PERMISSION_DENIED travava o chat inteiro). Decisão Marcelo
2026-05-20: todo agente configurável (adapter/MCP/Skill) — o chat tem que
respeitar o adapter do agente, não hard-codar provider.

stream_oracle_response resolve o adapter do agente Oracle (provider/model/key,
W5 hybrid company-primary + vault) e roteia o streaming:
- google      → gemini_client.stream_generate
- groq / huggingface (openai-compatible) → OpenAI SDK chat stream
- anthropic   → messages.stream
- fallback    → gemini (retrocompat)

Single-tenant dev: resolve a config do Oracle por agent_id (limit 1). Multi-tenant
real deveria passar company_id pelo state — TODO quando o chat virar multi-company.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Dict, Any, Optional

logger = logging.getLogger("OracleLLMStream")

ORACLE_AGENT_ID = "00000000-0000-0000-0000-000000000002"


def _resolve_oracle_adapter() -> Dict[str, Any]:
    """Resolve (provider, model, api_key, base_url) do Oracle via adapter config
    + W5 hybrid (company_adapter_values) + vault. Retorna dict; provider='google'
    como fallback retrocompat."""
    out: Dict[str, Any] = {"provider": "google", "model": None, "api_key": None, "base_url": None}
    try:
        from src.api import supabase, resolve_secret_ref
    except Exception:
        return out
    if not supabase:
        return out
    try:
        res = (
            supabase.table("agent_adapter_configs")
            .select("field_values_json, company_id, adapter_id, adapter_catalog!inner(provider)")
            .eq("agent_id", ORACLE_AGENT_ID)
            .limit(1)
            .execute()
        )
        if not res.data:
            return out
        row = res.data[0]
        provider = (row.get("adapter_catalog") or {}).get("provider") or "google"
        field_values = dict(row.get("field_values_json") or {})
        company_id = row.get("company_id")
        adapter_id = row.get("adapter_id")
        # W5 hybrid: company_adapter_values PRIMARY, agent override por cima
        if company_id and adapter_id:
            cv = (
                supabase.table("company_adapter_values")
                .select("field_values_json")
                .eq("company_id", company_id)
                .eq("adapter_id", adapter_id)
                .limit(1)
                .execute()
            )
            if cv.data:
                merged = dict(cv.data[0].get("field_values_json") or {})
                merged.update({k: v for k, v in field_values.items() if v not in (None, "")})
                field_values = merged
        # resolve vault:// refs
        if company_id:
            field_values = {
                k: (resolve_secret_ref(v, str(company_id)) if isinstance(v, str) and v.startswith("vault://") else v)
                for k, v in field_values.items()
            }
        out["provider"] = provider
        out["model"] = field_values.get("model_id") or field_values.get("model")
        out["api_key"] = field_values.get("api_key") or field_values.get("hf_token") or field_values.get("token")
        out["base_url"] = field_values.get("base_url")
    except Exception as exc:
        logger.warning("resolve_oracle_adapter falhou (fallback gemini): %s", exc)
    return out


async def _stream_openai_compatible(
    base_url: str, api_key: str, model: str, system: Optional[str], user_prompt: str
) -> AsyncIterator[str]:
    """Stream via OpenAI SDK (groq / HF router / qualquer openai-compatible)."""
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=api_key or "missing")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_prompt})
    stream = client.chat.completions.create(model=model, messages=messages, stream=True)
    for chunk in stream:
        try:
            delta = chunk.choices[0].delta.content
        except (IndexError, AttributeError):
            delta = None
        if delta:
            yield delta


async def _stream_anthropic(model: str, system: Optional[str], user_prompt: str) -> AsyncIterator[str]:
    """Stream via Anthropic messages API (key do env ANTHROPIC_API_KEY)."""
    import os
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    with client.messages.stream(
        model=model, max_tokens=1024,
        system=system or "", messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for text in stream.text_stream:
            if text:
                yield text


async def stream_oracle_response(
    user_prompt: str, *, system_instruction: Optional[str] = None
) -> AsyncIterator[str]:
    """Dispatcher: resolve adapter do Oracle + streama pelo provider configurado.
    Mesma assinatura conceitual de gemini_client.stream_generate (drop-in)."""
    from src.services.gemini_client import DEFAULT_MODEL, stream_generate

    cfg = _resolve_oracle_adapter()
    provider = cfg.get("provider") or "google"
    model = cfg.get("model")

    try:
        if provider in ("groq", "huggingface") and cfg.get("base_url"):
            async for c in _stream_openai_compatible(
                cfg["base_url"], cfg.get("api_key") or "", model or "", system_instruction, user_prompt
            ):
                yield c
            return
        if provider == "anthropic":
            async for c in _stream_anthropic(model or "claude-sonnet-4-5", system_instruction, user_prompt):
                yield c
            return
    except Exception as exc:
        logger.warning("stream_oracle_response provider=%s falhou, fallback gemini: %s", provider, exc)

    # google ou fallback
    async for c in stream_generate(model or DEFAULT_MODEL, user_prompt, system_instruction=system_instruction):
        yield c
