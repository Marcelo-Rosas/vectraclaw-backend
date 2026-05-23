"""Correlation-id e métricas estruturadas por request HTTP."""
from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("api.observability")

# Contadores simples em memória (exportar para Prometheus em PR futuro)
_metrics: dict[str, int] = {
    "http_4xx": 0,
    "http_5xx": 0,
    "cors_preflight": 0,
    "ws_upgrade_attempt": 0,
}


def get_http_metrics() -> dict[str, int]:
    return dict(_metrics)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Propaga X-Correlation-Id / X-Request-Id e log estruturado por request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        incoming = (
            request.headers.get("X-Correlation-Id")
            or request.headers.get("X-Request-Id")
        )
        correlation_id = incoming or str(uuid.uuid4())
        request.state.correlation_id = correlation_id

        if request.method == "OPTIONS":
            _metrics["cors_preflight"] += 1

        path = request.url.path
        if path.startswith("/ws/") or path.startswith("/api/ws/"):
            _metrics["ws_upgrade_attempt"] += 1

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        status = response.status_code
        if 400 <= status < 500:
            _metrics["http_4xx"] += 1
        elif status >= 500:
            _metrics["http_5xx"] += 1

        response.headers["X-Correlation-Id"] = correlation_id
        response.headers["X-Request-Id"] = correlation_id

        origin = request.headers.get("Origin", "-")
        logger.info(
            "http_request correlation_id=%s method=%s path=%s status=%s duration_ms=%.1f origin=%s",
            correlation_id,
            request.method,
            path,
            status,
            elapsed_ms,
            origin,
        )
        return response
