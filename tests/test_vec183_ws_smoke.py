"""
VEC-183 smoke — WebSocket em tempo real.

Testa:
1. /ws/companies/{id}          → conecta, recebe "hello", desconecta limpo
2. /ws/companies/{id}?token=X  → token válido aceito (JWT real via login)
3. /ws/companies/{id}?token=X  → após PATCH /api/tasks/{id}, recebe "task_updated"
4. /ws/companies/{id}?token=X  → após pause agent, recebe "agent_updated"
5. /ws (legacy)                → fecha com mensagem de erro

Roda: python tests/test_vec183_ws_smoke.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import websockets
except ImportError:
    print("Instalando websockets...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets", "-q"])
    import websockets  # type: ignore

BASE_HTTP = "http://127.0.0.1:3100"
BASE_WS = "ws://127.0.0.1:3100"
COMPANY = "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c"
AGENT_ID = "a0000000-0000-4000-8000-000000000002"  # Iris (idle)


def login() -> str:
    r = requests.post(
        f"{BASE_HTTP}/api/auth/login",
        json={"email": "marcelo.rosas@vectracargo.com.br", "password": "VectraClaw2026!"},
    )
    r.raise_for_status()
    tok = r.json()["accessToken"]
    print(f"[OK] login token={tok[:24]}...")
    return tok


def http_headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Testes assíncronos
# ---------------------------------------------------------------------------


async def test_hello(tok: str):
    """Conecta sem token → hello é enviado mesmo assim (token opcional)."""
    uri = f"{BASE_WS}/ws/companies/{COMPANY}"
    async with websockets.connect(uri) as ws:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert msg["type"] == "hello", f"esperava hello, got {msg}"
        assert msg["companyId"] == COMPANY
    print("[OK] /ws/companies/{id} → hello recebido, desconecta limpo")


async def test_hello_with_valid_token(tok: str):
    """Conecta com token válido → hello."""
    uri = f"{BASE_WS}/ws/companies/{COMPANY}?token={tok}"
    async with websockets.connect(uri) as ws:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert msg["type"] == "hello"
    print("[OK] /ws/companies/{id}?token=<valid> → hello recebido")


async def test_task_updated_broadcast(tok: str):
    """Conecta WS, faz PATCH de task via HTTP, recebe task_updated no socket."""
    # Cria uma task para patch
    r = requests.post(
        f"{BASE_HTTP}/api/companies/{COMPANY}/tasks",
        json={"title": "WS smoke task", "description": "VEC-183", "budgetLimit": 500},
        headers=http_headers(tok),
    )
    r.raise_for_status()
    task_id = r.json()["id"]

    uri = f"{BASE_WS}/ws/companies/{COMPANY}?token={tok}"
    async with websockets.connect(uri) as ws:
        # consume hello
        await asyncio.wait_for(ws.recv(), timeout=5)

        # PATCH via HTTP (dispara broadcast)
        patch_r = requests.patch(
            f"{BASE_HTTP}/api/tasks/{task_id}",
            json={"status": "queued"},
            headers=http_headers(tok),
        )
        patch_r.raise_for_status()

        # Espera evento WS
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
        assert msg["type"] == "task_updated", f"esperava task_updated, got {msg['type']}"
        assert msg["payload"]["id"] == task_id
        assert msg["payload"]["status"] == "queued"

    print(f"[OK] PATCH task → task_updated recebido (id={task_id[:8]}...)")


async def test_agent_updated_broadcast(tok: str):
    """Pause agent via HTTP → recebe agent_updated no socket."""
    uri = f"{BASE_WS}/ws/companies/{COMPANY}?token={tok}"
    async with websockets.connect(uri) as ws:
        # consume hello
        await asyncio.wait_for(ws.recv(), timeout=5)

        # Pause via HTTP
        r = requests.post(
            f"{BASE_HTTP}/api/agents/{AGENT_ID}/pause",
            headers=http_headers(tok),
        )
        r.raise_for_status()

        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
        assert msg["type"] == "agent_updated", f"esperava agent_updated, got {msg['type']}"
        assert msg["payload"]["id"] == AGENT_ID
        assert msg["payload"]["status"] == "paused"

    # Restore to idle
    requests.post(f"{BASE_HTTP}/api/agents/{AGENT_ID}/resume", headers=http_headers(tok))
    print(f"[OK] pause agent → agent_updated recebido (id={AGENT_ID[:8]}...)")


async def test_legacy_ws():
    """/ws (legacy) fecha com mensagem de erro."""
    uri = f"{BASE_WS}/ws"
    try:
        async with websockets.connect(uri) as ws:
            msg_raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(msg_raw)
            assert msg.get("type") == "error", f"esperava error, got {msg}"
            # Deve fechar logo após
            try:
                await asyncio.wait_for(ws.recv(), timeout=3)
            except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError):
                pass
        print("[OK] /ws (legacy) → erro enviado + conexão fechada")
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"[OK] /ws (legacy) → fechado com código {e.code}")


async def main():
    tok = login()
    await test_hello(tok)
    await test_hello_with_valid_token(tok)
    await test_task_updated_broadcast(tok)
    await test_agent_updated_broadcast(tok)
    await test_legacy_ws()
    print("\nALL OK — VEC-183 WebSocket eventos em tempo real")


if __name__ == "__main__":
    asyncio.run(main())
