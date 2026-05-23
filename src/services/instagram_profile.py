"""Perfil do remetente Instagram (IGSID) via Graph API — nome e @username."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("Vectra.instagram_profile")

_META_GRAPH_BASE = "https://graph.facebook.com"
_INSTAGRAM_GRAPH_BASE = "https://graph.instagram.com"


def _profile_url(access_token: str, api_version: str, instagram_scoped_id: str) -> str:
    ver = (api_version or "v21.0").strip()
    if not ver.startswith("v"):
        ver = f"v{ver}"
    base = _INSTAGRAM_GRAPH_BASE if access_token.strip().upper().startswith("IG") else _META_GRAPH_BASE
    return f"{base}/{ver}/{instagram_scoped_id}"


def format_instagram_display_name(name: Optional[str], username: Optional[str]) -> Optional[str]:
    """Label humano para external_name (lista Conversas)."""
    uname = (username or "").strip().lstrip("@")
    nm = (name or "").strip()
    if uname and nm:
        return f"{nm} (@{uname})"
    if uname:
        return f"@{uname}"
    if nm:
        return nm
    return None


def resolve_instagram_user_profile(
    instagram_scoped_id: str,
    *,
    access_token: str,
    api_version: str = "v21.0",
) -> Optional[Dict[str, str]]:
    """Best-effort GET fields=name,username. None se API falhar ou sem dados."""
    sender = (instagram_scoped_id or "").strip()
    token = (access_token or "").strip()
    if not sender or not token:
        return None

    url = _profile_url(token, api_version, sender)
    params = {"fields": "name,username", "access_token": token}

    try:
        import httpx

        with httpx.Client(timeout=8.0) as client:
            resp = client.get(url, params=params)
        if resp.status_code >= 400:
            logger.warning(
                "instagram_profile: GET %s status=%s body=%s",
                sender,
                resp.status_code,
                resp.text[:300],
            )
            return None
        data: Any = resp.json()
        if not isinstance(data, dict):
            return None
        name = str(data.get("name") or "").strip() or None
        username = str(data.get("username") or "").strip() or None
        if not name and not username:
            return None
        display = format_instagram_display_name(name, username)
        out: Dict[str, str] = {}
        if name:
            out["name"] = name
        if username:
            out["username"] = username
        if display:
            out["display"] = display
        return out
    except Exception as e:
        logger.warning("instagram_profile: resolve %s failed: %s", sender, e)
        return None
