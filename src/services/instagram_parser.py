"""Parser de payload Meta Instagram Messaging (object=instagram).

Schema: entry[].messaging[] (não entry[].changes[] do WhatsApp Cloud API).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class InstagramInboundMessage:
    channel: str = "instagram"
    instagram_account_id: str = ""
    sender_id: str = ""
    recipient_id: str = ""
    message_id: str = ""
    text: str = ""
    timestamp: int = 0
    message_type: str = "text"
    media_url: Optional[str] = None


def _detect_message_type(msg_data: Dict[str, Any]) -> str:
    if msg_data.get("attachments"):
        return "media"
    if msg_data.get("is_echo"):
        return "echo"
    return "text"


def _extract_media_url(msg_data: Dict[str, Any]) -> Optional[str]:
    attachments = msg_data.get("attachments") or []
    if not attachments:
        return None
    first = attachments[0] if isinstance(attachments, list) else {}
    if not isinstance(first, dict):
        return None
    if first.get("type") == "image":
        payload = first.get("payload") or {}
        if isinstance(payload, dict):
            url = payload.get("url")
            return str(url) if url else None
    return None


def parse_instagram_payload(payload: Dict[str, Any]) -> List[InstagramInboundMessage]:
    """Extrai mensagens inbound do usuário. Ignora echoes e object != instagram."""
    messages: List[InstagramInboundMessage] = []
    if payload.get("object") != "instagram":
        return messages

    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        instagram_account_id = str(entry.get("id") or "").strip()
        for messaging in entry.get("messaging") or []:
            if not isinstance(messaging, dict):
                continue
            sender = messaging.get("sender") or {}
            sender_id = str(sender.get("id") or "").strip() if isinstance(sender, dict) else ""
            # Echo: mensagem enviada pela própria conta IG
            if sender_id and instagram_account_id and sender_id == instagram_account_id:
                continue
            msg_data = messaging.get("message") or {}
            if not isinstance(msg_data, dict):
                continue
            if msg_data.get("is_echo"):
                continue
            recipient = messaging.get("recipient") or {}
            recipient_id = (
                str(recipient.get("id") or "").strip() if isinstance(recipient, dict) else ""
            )
            text = str(msg_data.get("text") or "").strip()
            ts_raw = messaging.get("timestamp", 0)
            try:
                timestamp = int(ts_raw)
            except (TypeError, ValueError):
                timestamp = 0
            messages.append(
                InstagramInboundMessage(
                    instagram_account_id=instagram_account_id,
                    sender_id=sender_id,
                    recipient_id=recipient_id,
                    message_id=str(msg_data.get("mid") or "").strip(),
                    text=text,
                    timestamp=timestamp,
                    message_type=_detect_message_type(msg_data),
                    media_url=_extract_media_url(msg_data),
                )
            )
    return messages


def instagram_message_to_bus_dict(msg: InstagramInboundMessage) -> Dict[str, Any]:
    """Normaliza para o shape usado por connectors._dispatch_inbound_task."""
    content = msg.text
    if not content and msg.media_url:
        content = f"[media:{msg.message_type}] {msg.media_url}"
    return {
        "instagram_account_id": msg.instagram_account_id,
        "external_id": msg.sender_id,
        "external_name": None,
        "content": content,
        "message_id": msg.message_id,
        "msg_type": msg.message_type,
        "timestamp": msg.timestamp,
        "button_id_hint": None,
    }
