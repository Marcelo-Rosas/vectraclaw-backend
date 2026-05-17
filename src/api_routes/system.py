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

# Lista canônica de daemons gerenciáveis: catalog-driven via `agents.is_daemon`
# (migration 20260517160000). Regra de Ouro #2 (NO HARDCODE) — antes era lista
# hardcoded de 10 entries que esqueceu Daedalus → UI mostrava Daedalus "Ocioso"
# mesmo heartbeating normalmente. Diagnóstico 2026-05-17.
_DAEMON_AGENTS_CACHE: list = []
_DAEMON_AGENTS_CACHE_FETCHED_AT: float = 0.0
_DAEMON_AGENTS_CACHE_TTL_S: float = 60.0


def _load_daemon_agents() -> list:
    """Lê lista canônica de daemons de `vectraclip.agents WHERE is_daemon=true`.

    Cache TTL 60s (espelha padrão de `_load_execution_mode_ids` em api.py).
    Retorna lista de tuplas (id, name) ordenadas por name. Vazio se Supabase
    indisponível (fail-safe: endpoint /api/system/daemons retornará [] em vez
    de crashar).
    """
    global _DAEMON_AGENTS_CACHE, _DAEMON_AGENTS_CACHE_FETCHED_AT
    now = time.time()
    if _DAEMON_AGENTS_CACHE and (now - _DAEMON_AGENTS_CACHE_FETCHED_AT) < _DAEMON_AGENTS_CACHE_TTL_S:
        return _DAEMON_AGENTS_CACHE

    try:
        from src.api import supabase
        if not supabase:
            return _DAEMON_AGENTS_CACHE  # devolve cache antigo (pode ser vazio)
        res = (
            supabase.table("agents")
            .select("id,name")
            .eq("is_daemon", True)
            .order("name")
            .execute()
        )
        rows = res.data or []
        new_list = [(str(r["id"]), str(r["name"])) for r in rows if r.get("id")]
        previous = _DAEMON_AGENTS_CACHE
        if previous != new_list:
            logger.info(
                "daemon_agents cache refreshed: count=%d names=%s",
                len(new_list), [n for _, n in new_list],
            )
        _DAEMON_AGENTS_CACHE = new_list
        _DAEMON_AGENTS_CACHE_FETCHED_AT = now
        return new_list
    except Exception as e:
        logger.warning("_load_daemon_agents fallback (returning cached=%d): %s", len(_DAEMON_AGENTS_CACHE), e)
        return _DAEMON_AGENTS_CACHE


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


# Janela em que heartbeat conta como "running". Default 60s = 2× o idle heartbeat
# interval (VEC-377, DAEMON_IDLE_HEARTBEAT_SECONDS default 30s) — evita flapping
# false-negative quando heartbeat atrasa por jitter de rede ou contenção de lock.
_HEARTBEAT_FRESH_SECONDS = int(os.getenv("DAEMON_FRESH_HEARTBEAT_SECONDS", "60"))


def _sys_daemon_status(agent_id: str, name: str) -> dict:
    """PR6.1 — Status do daemon via heartbeat no DB (não via PID local).

    Pós-Docker, daemons rodam no host (Task Scheduler) enquanto a API roda
    em container Linux. PID-based check via `tasklist` (Windows-only) +
    `.daemon_locks` (não-mounted) sempre falha. Fonte de verdade canônica
    pós-Docker é o heartbeat no DB: se existe heartbeat de < 30s, daemon
    está vivo, independente de onde estiver rodando.

    Fallback: se Supabase indisponível, retorna running=False.
    """
    try:
        # Lazy import: evita circular se api.py ainda não importou este módulo.
        from src.api import supabase
        if not supabase:
            return {"agentId": agent_id, "name": name, "running": False, "pid": None, "lastHeartbeatAgeSeconds": None}

        from datetime import datetime, timezone
        res = (
            supabase.table("heartbeats")
            .select("created_at")
            .eq("agent_id", agent_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not res.data:
            return {"agentId": agent_id, "name": name, "running": False, "pid": None, "lastHeartbeatAgeSeconds": None}

        ts = res.data[0]["created_at"]
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        running = age < _HEARTBEAT_FRESH_SECONDS
        return {
            "agentId": agent_id,
            "name": name,
            "running": running,
            "pid": None,  # heartbeat-based: PID não disponível
            "lastHeartbeatAgeSeconds": int(age),
        }
    except Exception as e:
        logger.warning("_sys_daemon_status heartbeat lookup failed agent=%s: %s", name, e)
        return {"agentId": agent_id, "name": name, "running": False, "pid": None, "lastHeartbeatAgeSeconds": None}


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
    return [_sys_daemon_status(aid, name) for aid, name in _load_daemon_agents()]


@router.post("/api/system/daemons/{agent_id}/start")
async def system_start_daemon(request: Request, agent_id: str):
    entry = next(((aid, n) for aid, n in _load_daemon_agents() if aid == agent_id), None)
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
    entry = next(((aid, n) for aid, n in _load_daemon_agents() if aid == agent_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="agent_id não está na lista de daemons")
    aid, name = entry
    result = _sys_stop_daemon(aid, name)
    logger.info("system.stop_daemon agent=%s", name)
    return {"ok": True, "message": f"Daemon {name} encerrado", **result}


@router.post("/api/system/daemons/{agent_id}/restart")
async def system_restart_daemon(request: Request, agent_id: str):
    entry = next(((aid, n) for aid, n in _load_daemon_agents() if aid == agent_id), None)
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
    results = [_sys_stop_daemon(aid, name) for aid, name in _load_daemon_agents()]
    logger.info("system.stop_all_daemons count=%d", len(results))
    return {"ok": True, "daemons": results}


@router.post("/api/system/daemons/start-all")
async def system_start_all_daemons(request: Request):
    results = []
    for aid, name in _load_daemon_agents():
        results.append(_sys_start_daemon(aid, name))
        time.sleep(0.2)
    logger.info("system.start_all_daemons count=%d", len(results))
    return {"ok": True, "daemons": results}


@router.post("/api/system/daemons/restart-all")
async def system_restart_all_daemons(request: Request):
    for aid, name in _load_daemon_agents():
        _sys_stop_daemon(aid, name)
    time.sleep(0.5)
    results = []
    for aid, name in _load_daemon_agents():
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
