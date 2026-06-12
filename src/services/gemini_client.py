import asyncio
import logging
import os
import random
import time
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger("GeminiClient")

_api_key_client = None
_vertex_client = None
_vertex_failed_logged = False

# F2 GSD (2026-05-17): catalog-drive defaults — Regra de Ouro #2.
# Handlers de operation_type (athena-*, oracle-research, etc) NÃO USAM mais este
# default — resolvem via `_resolve_model(input_data)` lendo de
# agent_specialty_configs.values / agent_shared_config / specialty defaults.
#
# `DEFAULT_MODEL` permanece como FALLBACK DE PLATAFORMA legado pra:
#   - Oracle chat SSE (`stream_generate` em oracle.py:191, oracle_maker.py:105)
#   - Oracle checker validators (oracle_checker.py:64,84,101)
#   - sipoc_researcher (utility legada)
#
# Esses fluxos recebem `state` langgraph (sem task/input_data) — refator pra
# catalog-driven exige mudança de assinatura em N callers (escopo separado F2b).
# Cai no P6 do CODE-PATTERNS (decisão registrada): fallback técnico SDK, não
# config de negócio per-tenant. Oracle chat hoje é fluxo SIPOC interno Vectra.
#
# TODO F2b: substituir por leitura de agent_shared_config.values["model_id"]
# pro ORACLE_AGENT_ID — Oracle chat fica catalog-driven sem mexer em N callers.
DEFAULT_MODEL = "gemini-flash-lite-latest"

# Retryable HTTP status codes: rate-limit (429) and transient server errors (500, 503).
# 403 (billing / permission) is NOT retried — it won't resolve until next billing cycle.
_RETRYABLE_CODES = frozenset({"429", "500", "503", "RESOURCE_EXHAUSTED", "INTERNAL", "UNAVAILABLE"})
_MAX_RETRIES = 3
_BASE_BACKOFF = 1.0  # seconds


def _get_api_key_client():
    global _api_key_client
    if _api_key_client is None:
        from google import genai
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY não configurada no ambiente")
        _api_key_client = genai.Client(api_key=api_key)
        logger.info("Gemini AI Studio client inicializado (key=...%s)", api_key[-4:])
    return _api_key_client


def _get_vertex_client():
    global _vertex_client, _vertex_failed_logged
    if _vertex_client is not None:
        return _vertex_client

    project = os.getenv("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0106729343")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    # Vertex requer ADC (gcloud auth application-default login) ou service account.
    # Se não houver credenciais, falha silenciosamente e deixa o fallback para AI Studio.
    adc_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not adc_path:
        # Tenta locais padrão do gcloud (Linux/Mac e Windows)
        candidates = [
            os.path.expanduser("~/.config/gcloud/application_default_credentials.json"),
            os.path.expanduser("~/AppData/Roaming/gcloud/application_default_credentials.json"),
        ]
        for default_adc in candidates:
            if os.path.exists(default_adc):
                os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", default_adc)
                adc_path = default_adc
                break
        if not adc_path:
            if not _vertex_failed_logged:
                logger.info("Vertex AI: ADC não encontrado. Fallback para AI Studio.")
                _vertex_failed_logged = True
            return None

    try:
        from google import genai
        _vertex_client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
        )
        logger.info("Gemini Vertex AI client inicializado (project=%s, location=%s)", project, location)
        return _vertex_client
    except Exception as exc:
        if not _vertex_failed_logged:
            logger.warning("Vertex AI falhou ao inicializar (%s). Fallback para AI Studio.", exc)
            _vertex_failed_logged = True
        return None


def get_client():
    """Retorna cliente Vertex AI (prioridade) ou AI Studio (fallback)."""
    vertex = _get_vertex_client()
    if vertex is not None:
        return vertex
    return _get_api_key_client()


# Modelos do AI Studio que nao existem no Vertex AI (ou nomes legacy/errados no banco).
_VERTEX_MODEL_MAP = {
    "gemini-3.5-flash": "gemini-2.5-flash",
    "gemini-3.5-pro": "gemini-2.5-pro",
    "gemini-flash-lite-latest": "gemini-2.5-flash",
    "gemini-flash-latest": "gemini-2.5-flash",
    "gemini-pro-latest": "gemini-2.5-pro",
}


def _resolve_model(model: str) -> str:
    """Normaliza nome do modelo quando usando Vertex AI.
    Se o modelo estiver no mapa de conversao, retorna o equivalente Vertex.
    Caso contrario, retorna o proprio nome (assumindo que ja e valido)."""
    if _get_vertex_client() is None:
        return model
    return _VERTEX_MODEL_MAP.get(model, model)


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
    response_schema: Optional[Any] = None,
    tools: Optional[list] = None,
) -> tuple[str, dict]:
    """Gera texto via Gemini. Retorna (text, metadata). Thinking desativado para custo mínimo em chat."""
    from google.genai import types

    client = get_client()
    resolved_model = _resolve_model(model)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type=response_mime_type,
        response_schema=response_schema,
        tools=tools,
    )

    last_exc: Exception = RuntimeError("generate nunca executou")
    t0 = time.monotonic()

    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = await client.aio.models.generate_content(
                model=resolved_model,
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
    tools: Optional[list] = None,
) -> AsyncIterator[str]:
    """Gera texto em streaming. Yielda chunks de texto conforme chegam."""
    from google.genai import types

    client = get_client()
    resolved_model = _resolve_model(model)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=tools,
    )

    last_exc: Exception = RuntimeError("stream_generate nunca executou")

    for attempt in range(_MAX_RETRIES + 1):
        try:
            stream = await client.aio.models.generate_content_stream(
                model=resolved_model,
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
