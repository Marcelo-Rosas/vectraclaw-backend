import asyncio
import logging
import os
import random
import time
from typing import AsyncIterator, Optional

logger = logging.getLogger("GeminiClient")

_client = None

DEFAULT_MODEL = "gemini-2.5-flash"

# Retryable HTTP status codes: rate-limit (429) and transient server errors (500, 503).
# 403 (billing / permission) is NOT retried — it won't resolve until next billing cycle.
_RETRYABLE_CODES = frozenset({"429", "500", "503", "RESOURCE_EXHAUSTED", "INTERNAL", "UNAVAILABLE"})
_MAX_RETRIES = 3
_BASE_BACKOFF = 1.0  # seconds


def get_client():
    global _client
    if _client is None:
        from google import genai
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY não configurada no ambiente")
        _client = genai.Client(api_key=api_key)
        logger.info("Gemini client inicializado (key=...%s)", api_key[-4:])
    return _client


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc).upper()
    return any(code in msg for code in _RETRYABLE_CODES)


async def _backoff(attempt: int) -> None:
    delay = _BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 0.5)
    logger.warning("Gemini retry attempt=%d backoff=%.1fs", attempt + 1, delay)
    await asyncio.sleep(delay)


async def generate(
    model: str,
    prompt: str,
    *,
    system_instruction: Optional[str] = None,
    response_mime_type: Optional[str] = None,
) -> tuple[str, dict]:
    """Gera texto via Gemini. Retorna (text, metadata). Thinking desativado para custo mínimo em chat."""
    from google.genai import types

    client = get_client()
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type=response_mime_type,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )

    last_exc: Exception = RuntimeError("generate nunca executou")
    t0 = time.monotonic()

    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            duration_ms = int((time.monotonic() - t0) * 1000)
            text = response.text or ""
            usage = response.usage_metadata
            metadata = {
                "model_used": model,
                "tokens": {
                    "input": getattr(usage, "prompt_token_count", 0) if usage else 0,
                    "output": getattr(usage, "candidates_token_count", 0) if usage else 0,
                    "total": getattr(usage, "total_token_count", 0) if usage else 0,
                },
                "duration_ms": duration_ms,
                "tools_used": [],
            }
            logger.debug(
                "Gemini generate: model=%s tokens=%s dur=%dms",
                model, metadata["tokens"]["total"], duration_ms,
            )
            return text, metadata
        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc) or attempt == _MAX_RETRIES:
                raise
            await _backoff(attempt)

    raise last_exc


async def stream_generate(
    model: str,
    prompt: str,
    *,
    system_instruction: Optional[str] = None,
) -> AsyncIterator[str]:
    """Gera texto em streaming. Yielda chunks de texto conforme chegam."""
    from google.genai import types

    client = get_client()
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )

    last_exc: Exception = RuntimeError("stream_generate nunca executou")

    for attempt in range(_MAX_RETRIES + 1):
        try:
            stream = await client.aio.models.generate_content_stream(
                model=model,
                contents=prompt,
                config=config,
            )
            async for chunk in stream:
                if chunk.text:
                    yield chunk.text
            return
        except Exception as exc:
            last_exc = exc
            if not _is_retryable(exc) or attempt == _MAX_RETRIES:
                raise
            await _backoff(attempt)


def extract_metadata(response, duration_ms: int = 0) -> dict:
    """Extrai metadados padronizados de uma resposta Gemini."""
    usage = getattr(response, "usage_metadata", None)
    return {
        "model_used": getattr(response, "model_version", DEFAULT_MODEL),
        "tokens": {
            "input": getattr(usage, "prompt_token_count", 0) if usage else 0,
            "output": getattr(usage, "candidates_token_count", 0) if usage else 0,
            "total": getattr(usage, "total_token_count", 0) if usage else 0,
        },
        "duration_ms": duration_ms,
        "tools_used": [],
    }
