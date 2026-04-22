"""
VEC-186 – Meta WhatsApp Cloud API client.

Referência: https://developers.facebook.com/docs/whatsapp/cloud-api/messages

Suporta dois modos:
  - text     → mensagem de texto livre (válida dentro da janela de 24 h de conversa)
  - template → mensagem via template aprovado (proativo, fora da janela)

Configuração via .env:
  META_WA_TOKEN           – System User Token permanente
  META_WA_PHONE_NUMBER_ID – ID do número de origem (ex: 910223578841229)
  META_WA_API_VERSION     – versão da Graph API (ex: v25.0)
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

import requests

logger = logging.getLogger("whatsapp.meta_client")

_BASE_URL = "https://graph.facebook.com/{version}/{phone_number_id}/messages"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _token() -> str:
    v = os.getenv("META_WA_TOKEN", "")
    if not v:
        raise RuntimeError("META_WA_TOKEN não configurado no .env")
    return v


def _phone_number_id() -> str:
    v = os.getenv("META_WA_PHONE_NUMBER_ID", "")
    if not v:
        raise RuntimeError("META_WA_PHONE_NUMBER_ID não configurado no .env")
    return v


def _api_version() -> str:
    return os.getenv("META_WA_API_VERSION", "v25.0")


def _endpoint() -> str:
    return _BASE_URL.format(
        version=_api_version(),
        phone_number_id=_phone_number_id(),
    )


# ---------------------------------------------------------------------------
# Phone normalization
# ---------------------------------------------------------------------------

def normalize_phone_e164(phone: str, default_country: str = "55") -> str:
    """
    Normaliza qualquer string de telefone para o formato E.164 (+DDDDNNNNNNNNN).

    Exemplos aceitos:
      "47 99999-0000"    → "+5547999990000"
      "+55 47 99999-0000" → "+5547999990000"
      "0047999990000"    → "+5547999990000"
      "5547999990000"    → "+5547999990000"
    """
    digits = re.sub(r"\D", "", phone)

    # Remove prefixo de discagem internacional (00 + DDI)
    if digits.startswith("00"):
        digits = digits[2:]

    # Adiciona DDI padrão se ausente
    if not digits.startswith(default_country):
        digits = default_country + digits

    return "+" + digits


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def _build_text_payload(to: str, message: str) -> dict:
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": message},
    }


def _build_template_payload(
    to: str,
    template_name: str,
    language: str,
    components: Optional[list] = None,
) -> dict:
    payload: dict = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
        },
    }
    if components:
        payload["template"]["components"] = components
    return payload


# ---------------------------------------------------------------------------
# HTTP dispatch
# ---------------------------------------------------------------------------

def _post(payload: dict, timeout: int = 10) -> dict:
    """Envia a requisição à Cloud API e retorna o JSON de resposta."""
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
    }
    resp = requests.post(_endpoint(), json=payload, headers=headers, timeout=timeout)

    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}

    if not resp.ok:
        error_info = body.get("error", body)
        logger.error("Meta API error %s: %s", resp.status_code, error_info)
        raise WhatsAppAPIError(
            status_code=resp.status_code,
            detail=error_info,
        )

    logger.info("WhatsApp enviado → %s | msg_id=%s", payload.get("to"), _extract_msg_id(body))
    return body


def _extract_msg_id(body: dict) -> str:
    try:
        return body["messages"][0]["id"]
    except (KeyError, IndexError):
        return "?"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class WhatsAppAPIError(Exception):
    def __init__(self, status_code: int, detail: dict | str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Meta API {status_code}: {detail}")


def send_text(phone: str, message: str) -> dict:
    """
    Envia mensagem de texto livre.
    Válida apenas dentro da janela de 24 h após última interação do usuário.

    Args:
        phone:   número de destino (qualquer formato; será normalizado)
        message: corpo da mensagem (até 4096 chars)

    Returns:
        Resposta JSON da Meta API (contém `messages[0].id`)
    """
    to = normalize_phone_e164(phone)
    payload = _build_text_payload(to, message)
    logger.info("send_text → %s", to)
    return _post(payload)


def send_template(
    phone: str,
    template_name: str,
    language: str = "pt_BR",
    components: Optional[list] = None,
) -> dict:
    """
    Envia mensagem via template aprovado (proativo, sem restrição de janela).

    Args:
        phone:         número de destino
        template_name: nome exato do template aprovado na conta Meta
        language:      código de idioma do template (ex: "pt_BR", "en_US")
        components:    lista de componentes (header, body, buttons) com parâmetros

    Exemplo de components:
        [
          {
            "type": "body",
            "parameters": [
              {"type": "text", "text": "MAEU1234567"},
              {"type": "text", "text": "Navegantes/BR"}
            ]
          }
        ]

    Returns:
        Resposta JSON da Meta API
    """
    to = normalize_phone_e164(phone)
    payload = _build_template_payload(to, template_name, language, components)
    logger.info("send_template '%s' → %s", template_name, to)
    return _post(payload)
