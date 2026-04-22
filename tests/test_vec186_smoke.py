"""
VEC-186 Smoke Test – send_whatsapp_webhook via Meta Cloud API.

Testa:
  T1 – normalize_phone_e164: formatos variados → E.164
  T2 – send_whatsapp_webhook sem phone → success=False, error informativo
  T3 – send_whatsapp_webhook type=text sem message → success=False
  T4 – send_whatsapp_webhook type=template sem template_name → success=False
  T5 – POST /api/tools/send-whatsapp sem phone → 422 (validação Pydantic)
  T6 – POST /api/tools/send-whatsapp type=template sem template_name → 422
  T7 – send_whatsapp_webhook REAL (type=text) → success=True, message_id presente
       (requer META_WA_TOKEN válido e número de destino em META_WA_TEST_PHONE)
  T8 – send_whatsapp_webhook REAL (type=template) → success=True
       (requer META_WA_TEST_TEMPLATE e META_WA_TEST_PHONE)

  T7/T8 são pulados automaticamente se META_WA_TEST_PHONE não estiver no .env.
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import os
import requests as _requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "http://localhost:3100"
TEST_PHONE    = os.getenv("META_WA_TEST_PHONE", "")
TEST_TEMPLATE = os.getenv("META_WA_TEST_TEMPLATE", "")


def ok(label: str):
    print(f"  PASS  {label}")

def fail(label: str, info: str = ""):
    print(f"  FAIL  {label}" + (f": {info}" if info else ""))
    sys.exit(1)

def skip(label: str, reason: str):
    print(f"  SKIP  {label} ({reason})")

def check(condition: bool, label: str, info: str = ""):
    if condition:
        ok(label)
    else:
        fail(label, info)


# ---------------------------------------------------------------------------
# T1 – normalize_phone_e164
# ---------------------------------------------------------------------------
print("\n[T1] normalize_phone_e164 — formatos variados")
from src.services.whatsapp.meta_client import normalize_phone_e164

cases = [
    ("47999990000",       "+5547999990000"),
    ("5547999990000",     "+5547999990000"),
    ("+5547999990000",    "+5547999990000"),
    ("47 9 9999-0000",    "+5547999990000"),
    ("0047999990000",     "+5547999990000"),
    ("+55 (47) 99999-0000", "+5547999990000"),
]
for raw, expected in cases:
    result = normalize_phone_e164(raw)
    check(result == expected, f"{raw!r} → {expected}", result)


# ---------------------------------------------------------------------------
# T2 – send_whatsapp_webhook sem phone
# ---------------------------------------------------------------------------
print("\n[T2] send_whatsapp_webhook sem phone")
from src.m3_tools import send_whatsapp_webhook

out = json.loads(send_whatsapp_webhook("{}"))
check(out.get("success") is False, "success=False")
check("error" in out, "error presente")

# ---------------------------------------------------------------------------
# T3 – type=text sem message
# ---------------------------------------------------------------------------
print("\n[T3] type=text sem message")
out = json.loads(send_whatsapp_webhook(json.dumps({"phone": "+5547000000000", "type": "text"})))
check(out.get("success") is False, "success=False")

# ---------------------------------------------------------------------------
# T4 – type=template sem template_name
# ---------------------------------------------------------------------------
print("\n[T4] type=template sem template_name")
out = json.loads(send_whatsapp_webhook(json.dumps({"phone": "+5547000000000", "type": "template"})))
check(out.get("success") is False, "success=False")

# ---------------------------------------------------------------------------
# Auth helper (Bearer para endpoints protegidos)
# ---------------------------------------------------------------------------
def _login() -> str:
    r = _requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "marcelo.rosas@vectracargo.com.br", "password": "vectra123"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["accessToken"]

tok = _login()
auth = {"Authorization": f"Bearer {tok}"}

# ---------------------------------------------------------------------------
# T5 – POST /api/tools/send-whatsapp sem phone → 422
# ---------------------------------------------------------------------------
print("\n[T5] POST /api/tools/send-whatsapp sem phone → 422")
r = _requests.post(f"{BASE_URL}/api/tools/send-whatsapp", json={"message": "teste"}, headers=auth, timeout=10)
check(r.status_code == 422, "422 sem phone", str(r.status_code))

# ---------------------------------------------------------------------------
# T6 – POST type=template sem template_name → 422
# ---------------------------------------------------------------------------
print("\n[T6] POST type=template sem template_name → 422")
r = _requests.post(
    f"{BASE_URL}/api/tools/send-whatsapp",
    json={"phone": "+5547000000000", "type": "template"},
    headers=auth,
    timeout=10,
)
check(r.status_code == 422, "422 sem template_name", str(r.status_code))

# ---------------------------------------------------------------------------
# T7 – Envio REAL type=text (opcional)
# ---------------------------------------------------------------------------
print("\n[T7] Envio real type=text")
if not TEST_PHONE:
    skip("T7", "META_WA_TEST_PHONE não definido no .env")
else:
    r = _requests.post(
        f"{BASE_URL}/api/tools/send-whatsapp",
        json={"phone": TEST_PHONE, "message": "VEC-186 smoke test ✓ — mensagem de teste VectraClaw"},
        headers=auth,
        timeout=15,
    )
    check(r.status_code == 200, "HTTP 200", str(r.status_code))
    body = r.json()
    check(body.get("success") is True, "success=True", str(body))
    check(bool(body.get("message_id")), "message_id presente", str(body))

# ---------------------------------------------------------------------------
# T8 – Envio REAL type=template (opcional)
# ---------------------------------------------------------------------------
print("\n[T8] Envio real type=template")
if not TEST_PHONE or not TEST_TEMPLATE:
    skip("T8", "META_WA_TEST_PHONE ou META_WA_TEST_TEMPLATE não definidos")
else:
    r = _requests.post(
        f"{BASE_URL}/api/tools/send-whatsapp",
        json={"phone": TEST_PHONE, "type": "template", "template_name": TEST_TEMPLATE, "language": "pt_BR"},
        headers=auth,
        timeout=15,
    )
    check(r.status_code == 200, "HTTP 200", str(r.status_code))
    body = r.json()
    check(body.get("success") is True, "success=True", str(body))
    check(bool(body.get("message_id")), "message_id presente", str(body))

print("\n✓ Todos os testes concluídos (VEC-186)\n")
