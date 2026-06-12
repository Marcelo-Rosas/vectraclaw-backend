"""CORS allowlist centralizada — multi-tenant API (VectraClip ↔ VectraClaw)."""
from __future__ import annotations

import os
import re
from typing import Iterable, List, Optional

# Origens sempre permitidas (dev + produção Clip)
_CORE_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3100",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:3100",
    "https://app.vectraclip.vectracargo.com.br",
)

_DEFAULT_ORIGIN_REGEX = (
    r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    r"|^https://app\.vectraclip\.vectracargo\.com\.br$"
    r"|^https://[a-f0-9]+\.vectraclip-frontend\.pages\.dev$"
)


def build_cors_allow_origins() -> List[str]:
    """Lista explícita: core + extras de CORS_ALLOW_ORIGINS (CSV), deduplicada."""
    extra_env = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    extras = [o.strip() for o in extra_env.split(",") if o.strip()] if extra_env else []
    seen: set[str] = set()
    out: List[str] = []
    for origin in (*_CORE_CORS_ORIGINS, *extras):
        if origin not in seen:
            seen.add(origin)
            out.append(origin)
    return out


def build_cors_origin_regex() -> str:
    return os.getenv("CORS_ALLOW_ORIGIN_REGEX", _DEFAULT_ORIGIN_REGEX).strip()


def _origin_allowed(origin: Optional[str], allow_origins: Iterable[str], origin_regex: str) -> bool:
    if not origin:
        return False
    if origin in allow_origins:
        return True
    try:
        return bool(re.fullmatch(origin_regex, origin))
    except re.error:
        return False


def cors_headers_for_request(
    origin: Optional[str],
    *,
    allow_origins: Optional[List[str]] = None,
    origin_regex: Optional[str] = None,
) -> dict[str, str]:
    """
    Headers CORS para respostas (incluindo 4xx/5xx).
    Só ecoa Access-Control-Allow-Origin se a origin estiver na allowlist.
    """
    origins = allow_origins if allow_origins is not None else build_cors_allow_origins()
    regex = origin_regex if origin_regex is not None else build_cors_origin_regex()
    headers: dict[str, str] = {
        "Vary": "Origin",
        "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Request-Id, X-Correlation-Id",
        "Access-Control-Expose-Headers": "Content-Length, Content-Type, X-Request-Id, X-Correlation-Id",
        "Access-Control-Max-Age": "600",
    }
    if _origin_allowed(origin, origins, regex):
        headers["Access-Control-Allow-Origin"] = origin  # type: ignore[assignment]
        headers["Access-Control-Allow-Credentials"] = "true"
    return headers
