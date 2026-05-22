"""URLs de envio DM Instagram (IGAA vs EAA)."""
from src.services.connector_bus import _build_instagram_messages_url

IG_ACCOUNT = "17841472518839486"


def test_build_instagram_messages_url_igaa() -> None:
    url = _build_instagram_messages_url("IGAAtest", "v25.0", IG_ACCOUNT)
    assert url == "https://graph.instagram.com/v25.0/me/messages"


def test_build_instagram_messages_url_eaa() -> None:
    url = _build_instagram_messages_url("EAAtest", "v21.0", IG_ACCOUNT)
    assert url == f"https://graph.facebook.com/v21.0/{IG_ACCOUNT}/messages"
