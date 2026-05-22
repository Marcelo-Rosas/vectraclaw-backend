"""Parser Instagram Messaging (object=instagram)."""
from src.services.instagram_parser import (
    instagram_message_to_bus_dict,
    parse_instagram_payload,
)


def test_parse_instagram_text_message():
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "17841472518839486",
                "messaging": [
                    {
                        "sender": {"id": "123456"},
                        "recipient": {"id": "17841472518839486"},
                        "timestamp": 1710000000,
                        "message": {
                            "mid": "mid.abc",
                            "text": "Olá!",
                        },
                    }
                ],
            }
        ],
    }
    msgs = parse_instagram_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].sender_id == "123456"
    assert msgs[0].instagram_account_id == "17841472518839486"
    assert msgs[0].text == "Olá!"

    bus = instagram_message_to_bus_dict(msgs[0])
    assert bus["external_id"] == "123456"
    assert bus["content"] == "Olá!"
    assert bus["instagram_account_id"] == "17841472518839486"


def test_parse_ignores_echo_and_wrong_object():
    assert parse_instagram_payload({"object": "whatsapp_business_account"}) == []
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "17841472518839486",
                "messaging": [
                    {
                        "sender": {"id": "17841472518839486"},
                        "message": {"text": "echo", "is_echo": True},
                    }
                ],
            }
        ],
    }
    assert parse_instagram_payload(payload) == []
