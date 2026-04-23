"""
VEC-199b smoke — insert_incident + get_incident_by_id + undo-window T7.

Exercita três cenários:
1. insert + get_by_id (round-trip básico do store)
2. undo OK (janela +5min no futuro)
3. undo EXPIRED (janela -1min no passado) → HTTP 400 `undo_window_expired`

Roda direto: `python tests/test_store_smoke.py` (precisa de SUPABASE_URL e
SUPABASE_SERVICE_ROLE_KEY no .env).
"""

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Windows cp1252 console não desenha `→`; força utf-8 no stdout antes de qualquer print.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from src.services.heartbeat_doctor import store as incident_store

COMPANY_ID = "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c"
AGENT_ID = "a0000000-0000-4000-8000-000000000001"
BASE_URL = "http://127.0.0.1:3100"
LOGIN_EMAIL = "marcelo.rosas@vectracargo.com.br"
LOGIN_PASSWORD = "vectra123"


def _base_row(undo_expires_at=None, decision="auto_healed"):
    return {
        "id": str(uuid.uuid4()),
        "company_id": COMPANY_ID,
        "agent_id": AGENT_ID,
        "symptom": "heartbeat_gap",
        "fix_applied": "reset_hb_loop",
        "severity": "medium",
        "severity_score": 3,
        "agent_snapshot": {"smoke": True},
        "decision": decision,
        "undo_expires_at": undo_expires_at,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def _roundtrip() -> None:
    row = _base_row(
        undo_expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    )
    inserted = await incident_store.insert_incident(row)
    assert inserted is not None, "insert_incident returned None (supabase client down?)"
    fetched = await incident_store.get_incident_by_id(inserted.id, COMPANY_ID)
    assert fetched is not None, "get_incident_by_id returned None"
    assert str(fetched.id) == str(inserted.id), "id mismatch"
    assert str(fetched.company_id) == COMPANY_ID, "company_id mismatch"
    print(f"[OK] roundtrip id={inserted.id} decision={fetched.decision}")


def _login() -> str:
    res = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD},
        timeout=10,
    )
    res.raise_for_status()
    return res.json()["accessToken"]


async def _undo_expired_t7() -> None:
    """T7: incidente auto_healed com janela JÁ expirada → endpoint deve devolver 400."""
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    row = _base_row(undo_expires_at=past)
    inserted = await incident_store.insert_incident(row)
    assert inserted is not None, "insert for T7 returned None"

    token = _login()
    res = requests.post(
        f"{BASE_URL}/api/incidents/{inserted.id}/undo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
    assert res.status_code == 400, f"T7 expected 400, got {res.status_code} body={body}"
    assert body.get("detail") == "undo_window_expired", (
        f"T7 expected detail=undo_window_expired, got {body}"
    )
    print(f"[OK] T7 expired window → 400 detail={body.get('detail')}")


async def _undo_ok() -> None:
    """Contraparte positiva de T7: janela futura → 200 decision=undone."""
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    row = _base_row(undo_expires_at=future)
    inserted = await incident_store.insert_incident(row)
    assert inserted is not None

    token = _login()
    res = requests.post(
        f"{BASE_URL}/api/incidents/{inserted.id}/undo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    assert res.status_code == 200, f"undo OK expected 200, got {res.status_code} body={res.text}"
    data = res.json()
    assert data.get("decision") == "undone", f"expected decision=undone, got {data}"
    print(f"[OK] undo OK (future window) → 200 decision={data.get('decision')}")


async def main() -> int:
    try:
        await _roundtrip()
        # Os cenários de undo precisam do uvicorn rodando. Se cair, avisa mas não quebra o roundtrip.
        try:
            await _undo_ok()
            await _undo_expired_t7()
        except requests.ConnectionError:
            print("[SKIP] undo scenarios: uvicorn não está em :3100 (inicie `python -m uvicorn src.api:app --port 3100`)")
    except AssertionError as exc:
        print(f"[FAIL] {exc}")
        return 1
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        return 2
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
