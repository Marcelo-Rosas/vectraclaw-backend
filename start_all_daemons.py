"""Launcher dos daemons da VectraClaw — catalog-driven (Regra de Ouro #2).

Lista de daemons vem de `vectraclip.agents WHERE is_daemon=true` (migration
20260517160000). Antes era lista hardcoded — bug pré-existente: divergência
entre esta lista e a de `src/api_routes/system.py` causou Daedalus mostrar
"Ocioso" na UI mesmo heartbeating normalmente (2026-05-17 diagnóstico).

Cada daemon roda como subprocess separado:
- AGENT_ID injetado via env
- log redirecionado pra `daemon-<nome>.log` (gitignored)
- lock em `.daemon_locks/<AGENT_ID>.lock` (gerenciado pelo agent_daemon)
- detached do parent (CREATE_NEW_PROCESS_GROUP no Windows) — sobrevive
  se este launcher morrer

Uso:
    python start_all_daemons.py

Pra rodar via Task Scheduler do Windows, basta apontar pra este arquivo
com Python via `pythonw.exe` (sem janela) ou `python.exe` (com console).

Memory refs:
- VEC-414 — daemon spawnado sem `.env` carregado vira no-op silencioso.
  `load_dotenv()` no topo, ANTES de copiar `os.environ` pro subprocess.
- post-merge-live-update-deploy (Regra de Ouro #3) — este arquivo é launcher
  no host (não no container); não exige `docker cp`, mas requer restart do
  launcher (matar processo + `python start_all_daemons.py`) pra pegar
  daemons novos do catálogo.
"""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    print("ERRO: python-dotenv não instalado. Roda `pip install python-dotenv` ou ativa o venv.", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def _load_daemons_from_db() -> list[tuple[str, str]]:
    """Lê (name, id) de `vectraclip.agents WHERE is_daemon=true`. Ordenado por name.

    Falha-segura: se Supabase indisponível ou client não instalado, sai com
    erro EXPLÍCITO (sys.exit 1). NÃO usa fallback hardcoded — mentir sobre
    quem é daemon é pior que parar (Regra de Ouro #2).
    """
    try:
        from supabase import create_client
    except ImportError:
        print(
            "ERRO: pacote `supabase` não instalado. Roda `pip install supabase` ou ativa o venv.",
            file=sys.stderr,
        )
        sys.exit(1)

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print(
            "ERRO: SUPABASE_URL e/ou SUPABASE_SERVICE_ROLE_KEY ausentes no .env.\n"
            f"Path .env: {ROOT / '.env'}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        client = create_client(url, key)
        # Schema da casa é `vectraclip` (NUNCA public — supabase/CLAUDE.md)
        try:
            client = client.schema("vectraclip")  # type: ignore[attr-defined]
        except Exception:
            pass  # cliente antigo já assume schema via header

        res = (
            client.table("agents")
            .select("id,name")
            .eq("is_daemon", True)
            .order("name")
            .execute()
        )
        rows = res.data or []
        if not rows:
            print(
                "ERRO: nenhum agent com is_daemon=true em vectraclip.agents.\n"
                "Migration 20260517160000 foi aplicada? Rode `supabase db push`.",
                file=sys.stderr,
            )
            sys.exit(1)
        return [(str(r["name"]), str(r["id"])) for r in rows]
    except Exception as e:
        print(f"ERRO: falha ao consultar agents.is_daemon do Supabase: {e}", file=sys.stderr)
        sys.exit(1)


DAEMONS: list[tuple[str, str]] = _load_daemons_from_db()


def main() -> int:
    if not os.environ.get("SUPABASE_URL"):
        print("ERRO: SUPABASE_URL ausente. .env carregou? Path:", ROOT / ".env", file=sys.stderr)
        return 1

    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0

    started: list[tuple[str, int]] = []
    for name, agent_id in DAEMONS:
        log_path = ROOT / f"daemon-{name.lower()}.log"
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)
        log_file.write(f"\n--- spawned by start_all_daemons.py (parent PID {os.getpid()}) ---\n")

        env = os.environ.copy()
        env["AGENT_ID"] = agent_id

        proc = subprocess.Popen(
            [sys.executable, "-m", "src.agent_daemon"],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(ROOT),
            creationflags=creation_flags,
        )
        print(f"started {name:<16} pid={proc.pid:>6} agent_id={agent_id}  ->  daemon-{name.lower()}.log")
        started.append((name, proc.pid))

    print(f"\nOK: {len(started)} daemons spawnados (detached). Parent encerra agora.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
