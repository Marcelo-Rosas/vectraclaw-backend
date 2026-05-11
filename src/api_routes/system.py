"""
src.api_routes.system — System Management endpoints.

Endpoints sysadmin para iniciar/parar/reiniciar daemons e o servidor pelo
dashboard. Todos sob o prefixo /api/system/.

Endpoints:
- GET   /api/system/daemons                          system_list_daemons
- POST  /api/system/daemons/{agent_id}/start         system_start_daemon
- POST  /api/system/daemons/{agent_id}/stop          system_stop_daemon
- POST  /api/system/daemons/{agent_id}/restart       system_restart_daemon
- POST  /api/system/daemons/stop-all                 system_stop_all_daemons
- POST  /api/system/daemons/start-all                system_start_all_daemons
- POST  /api/system/daemons/restart-all              system_restart_all_daemons
- POST  /api/system/server/restart                   system_restart_server

Helpers privados (`_sys_*`) ficam neste submodule.

⚠️ SEGURANÇA: este módulo NÃO contém credenciais. Daemons spawnados via
`_sys_start_daemon` herdam o ambiente do servidor pai — garanta que
`.env` esteja carregado antes de iniciar a API (start_server.py faz isso).
Nunca hardcoded API keys aqui.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("api.system")
router = APIRouter(tags=["system"])

_SYS_BASE_DIR = Path(__file__).parent.parent.parent
_SYS_LOCK_DIR = _SYS_BASE_DIR / ".daemon_locks"

# Lista canônica de daemons gerenciáveis. UUIDs são públicos (FK em vectraclip.agents).
_DAEMON_AGENTS = [
    ("00000000-0000-0000-0000-000000000001", "Morpheus"),
    ("00000000-0000-0000-0000-000000000002", "Oracle"),
    ("00000000-0000-0000-0000-000000000003", "Mnemos"),
    ("59b7a69e-cc53-4063-85f9-5dcc5619ac96", "Hermes"),
    ("c7de1b0f-7c74-42f1-9de4-7210349e668e", "Mercator"),
    ("80fd6d0e-53ab-4638-b6e9-05cbbd121092", "Plutus"),
    ("0d6e56cc-28b6-4382-96cd-1952b890d412", "Hodos"),
    ("360a96cb-b1c3-4b65-b9fa-2b9cbb59dac1", "HermesReporter"),
    ("9c8d7e6f-5a4b-4321-9876-543210fedcba", "Kronos"),
    ("ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d", "Athena"),  # VEC-388 PR1
]


def _sys_pid_alive(pid: int) -> bool:
    """Returns True iff PID is alive AND the process is python (anti-PID-reuse)."""
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True,
        )
        if str(pid) not in r.stdout:
            return False
        row = r.stdout.strip().lower()
        return "python" in row
    except Exception:
        return False


def _sys_daemon_status(agent_id: str, name: str) -> dict:
    lock = _SYS_LOCK_DIR / f"{agent_id}.lock"
    if not lock.exists():
        return {"agentId": agent_id, "name": name, "running": False, "pid": None}
    try:
        pid = int(lock.read_text().strip())
        alive = _sys_pid_alive(pid)
        if not alive:
            try:
                lock.unlink()
            except Exception:
                pass
        return {"agentId": agent_id, "name": name, "running": alive, "pid": pid if alive else None}
    except Exception:
        return {"agentId": agent_id, "name": name, "running": False, "pid": None}


def _sys_build_env(agent_id: str) -> dict:
    """Daemon inherits parent process env + AGENT_ID. NÃO hardcoded keys aqui."""
    env = dict(os.environ)
    env["AGENT_ID"] = agent_id
    return env


def _sys_start_daemon(agent_id: str, name: str) -> dict:
    log_path = _SYS_BASE_DIR / f"daemon-{name.lower()}.log"
    log_file = open(str(log_path), "w", buffering=1)
    p = subprocess.Popen(
        [sys.executable, "-m", "src.agent_daemon"],
        cwd=str(_SYS_BASE_DIR),
        env=_sys_build_env(agent_id),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return {"agentId": agent_id, "name": name, "running": True, "pid": p.pid}


def _sys_stop_daemon(agent_id: str, name: str) -> dict:
    s = _sys_daemon_status(agent_id, name)
    if s["running"]:
        subprocess.run(["taskkill", "/F", "/PID", str(s["pid"])], capture_output=True)
    lock = _SYS_LOCK_DIR / f"{agent_id}.lock"
    if lock.exists():
        try:
            lock.unlink()
        except Exception:
            pass
    return {"agentId": agent_id, "name": name, "running": False, "pid": None}


@router.get("/api/system/daemons")
async def system_list_daemons(request: Request):
    return [_sys_daemon_status(aid, name) for aid, name in _DAEMON_AGENTS]


@router.post("/api/system/daemons/{agent_id}/start")
async def system_start_daemon(request: Request, agent_id: str):
    entry = next(((aid, n) for aid, n in _DAEMON_AGENTS if aid == agent_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="agent_id não está na lista de daemons")
    aid, name = entry
    s = _sys_daemon_status(aid, name)
    if s["running"]:
        return {"ok": True, "message": f"Daemon {name} já rodando (PID {s['pid']})", **s}
    result = _sys_start_daemon(aid, name)
    logger.info("system.start_daemon agent=%s pid=%s", name, result["pid"])
    return {"ok": True, "message": f"Daemon {name} iniciado (PID {result['pid']})", **result}


@router.post("/api/system/daemons/{agent_id}/stop")
async def system_stop_daemon(request: Request, agent_id: str):
    entry = next(((aid, n) for aid, n in _DAEMON_AGENTS if aid == agent_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="agent_id não está na lista de daemons")
    aid, name = entry
    result = _sys_stop_daemon(aid, name)
    logger.info("system.stop_daemon agent=%s", name)
    return {"ok": True, "message": f"Daemon {name} encerrado", **result}


@router.post("/api/system/daemons/{agent_id}/restart")
async def system_restart_daemon(request: Request, agent_id: str):
    entry = next(((aid, n) for aid, n in _DAEMON_AGENTS if aid == agent_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="agent_id não está na lista de daemons")
    aid, name = entry
    _sys_stop_daemon(aid, name)
    time.sleep(0.5)
    result = _sys_start_daemon(aid, name)
    logger.info("system.restart_daemon agent=%s pid=%s", name, result["pid"])
    return {"ok": True, "message": f"Daemon {name} reiniciado (PID {result['pid']})", **result}


@router.post("/api/system/daemons/stop-all")
async def system_stop_all_daemons(request: Request):
    results = [_sys_stop_daemon(aid, name) for aid, name in _DAEMON_AGENTS]
    logger.info("system.stop_all_daemons count=%d", len(results))
    return {"ok": True, "daemons": results}


@router.post("/api/system/daemons/start-all")
async def system_start_all_daemons(request: Request):
    results = []
    for aid, name in _DAEMON_AGENTS:
        results.append(_sys_start_daemon(aid, name))
        time.sleep(0.2)
    logger.info("system.start_all_daemons count=%d", len(results))
    return {"ok": True, "daemons": results}


@router.post("/api/system/daemons/restart-all")
async def system_restart_all_daemons(request: Request):
    for aid, name in _DAEMON_AGENTS:
        _sys_stop_daemon(aid, name)
    time.sleep(0.5)
    results = []
    for aid, name in _DAEMON_AGENTS:
        r = _sys_start_daemon(aid, name)
        results.append(r)
        time.sleep(0.3)
    logger.info("system.restart_all_daemons count=%d", len(results))
    return {"ok": True, "daemons": results}


@router.post("/api/system/server/restart")
async def system_restart_server(request: Request):
    server_script = str(_SYS_BASE_DIR / "start_server.py")
    subprocess.Popen(
        [sys.executable, server_script],
        cwd=str(_SYS_BASE_DIR),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    import asyncio as _asyncio
    _asyncio.get_event_loop().call_later(1.5, lambda: os._exit(0))
    logger.info("system.restart_server — new process launched, exiting in 1.5s")
    return {"ok": True, "message": "Servidor reiniciando..."}
