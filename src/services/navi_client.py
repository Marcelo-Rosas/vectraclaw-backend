"""navi_client — client Supabase do projeto NAVI (WhatsApp/Nina).

NAVI é um projeto Supabase SEPARADO do vectraclip. O Claw escreve no `send_queue`
do NAVI pra disparar WhatsApp — NAVI tem o número Meta GREEN e envia com pacing.
Creds via env NAVI_SUPABASE_URL / NAVI_SERVICE_ROLE_KEY (vault em prod).
Retorna None se não configurado — o caller degrada com erro claro (não quebra).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("NaviClient")

_client = None


def get_navi_client() -> Optional[Any]:
    global _client
    if _client is not None:
        return _client
    url = os.getenv("NAVI_SUPABASE_URL", "")
    key = (os.getenv("NAVI_SERVICE_ROLE_KEY", "")
           or os.getenv("NAVI_SUPABASE_SERVICE_KEY", ""))
    if not url or not key:
        logger.warning("NAVI_SUPABASE_URL / NAVI_SERVICE_ROLE_KEY ausentes — outbound NAVI indisponível")
        return None
    try:
        from supabase import create_client, ClientOptions
        _client = create_client(url, key, options=ClientOptions(schema="public", persist_session=False))
        return _client
    except Exception as exc:
        logger.error("NAVI client init falhou: %s", exc)
        return None
