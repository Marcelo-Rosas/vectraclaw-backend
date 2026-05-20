"""agent_llm — generate provider-agnostic por agente (não-streaming).

Par do oracle_llm_stream (streaming): aqui é o generate single-shot com
suporte a JSON estruturado, pro Athena classify e qualquer handler que hoje
chama gemini_client.generate FIXO. Decisão Marcelo 2026-05-20: todo agente
configurável — handlers não devem hard-codar provider.

generate_for_agent resolve o adapter do agente (provider/model/key/base_url,
W5 hybrid company-primary + vault) e roteia:
- google      → gemini_client.generate (response_mime_type nativo)
- groq / hf    → OpenAI SDK chat.completions (response_format json_object se json)
- anthropic   → messages.create
- fallback    → gemini

Single-tenant dev: resolve por agent_id (limit 1). Multi-tenant passa company_id
no futuro.
"""
from __future__ import annotations

import logging
import time
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger("AgentLLM")


def _resolve_agent_adapter(agent_id: str) -> Dict[str, Any]:
    """provider/model/api_key/base_url do agente via adapter config + W5 hybrid + vault."""
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
            .eq("agent_id", agent_id)
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
        if company_id and adapter_id:
            cv = (
                supabase.table("company_adapter_values")
                .select("field_values_json")
                .eq("company_id", company_id).eq("adapter_id", adapter_id).limit(1).execute()
            )
            if cv.data:
                merged = dict(cv.data[0].get("field_values_json") or {})
                merged.update({k: v for k, v in field_values.items() if v not in (None, "")})
                field_values = merged
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
        logger.warning("resolve_agent_adapter(%s) falhou (fallback gemini): %s", agent_id, exc)
    return out


async def generate_for_agent(
    agent_id: str,
    prompt: str,
    *,
    system_instruction: Optional[str] = None,
    response_mime_type: Optional[str] = None,
    fallback_model: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Generate single-shot pelo provider configurado do agente. Retorna (text, metadata).
    response_mime_type='application/json' → ativa JSON mode no provider."""
    cfg = _resolve_agent_adapter(agent_id)
    provider = cfg.get("provider") or "google"
    model = cfg.get("model") or fallback_model
    want_json = response_mime_type == "application/json"
    t0 = time.monotonic()

    try:
        if provider in ("groq", "huggingface") and cfg.get("base_url"):
            from openai import OpenAI
            client = OpenAI(base_url=cfg["base_url"], api_key=cfg.get("api_key") or "missing")
            messages = []
            if system_instruction:
                # JSON mode em openai exige a palavra "json" no contexto
                sys = system_instruction + ("\nResponda APENAS com JSON válido." if want_json else "")
                messages.append({"role": "system", "content": sys})
            messages.append({"role": "user", "content": prompt})
            kwargs: Dict[str, Any] = {"model": model, "messages": messages}
            if want_json:
                kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**kwargs)
            text = resp.choices[0].message.content or ""
            usage = getattr(resp, "usage", None)
            meta = {
                "provider": provider, "model": model,
                "tokens_input": getattr(usage, "prompt_tokens", 0) if usage else 0,
                "tokens_output": getattr(usage, "completion_tokens", 0) if usage else 0,
                "duration_ms": int((time.monotonic() - t0) * 1000),
            }
            return text, meta

        if provider == "anthropic":
            import os, anthropic
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
            msg = client.messages.create(
                model=model or "claude-sonnet-4-5", max_tokens=2048,
                system=(system_instruction or "") + ("\nResponda APENAS com JSON válido." if want_json else ""),
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
            meta = {"provider": provider, "model": model, "duration_ms": int((time.monotonic() - t0) * 1000)}
            return text, meta
    except Exception as exc:
        logger.warning("generate_for_agent provider=%s falhou, fallback gemini: %s", provider, exc)

    # google ou fallback
    from src.services.gemini_client import generate as gemini_generate, DEFAULT_MODEL
    return await gemini_generate(
        model or DEFAULT_MODEL, prompt,
        system_instruction=system_instruction, response_mime_type=response_mime_type,
    )
