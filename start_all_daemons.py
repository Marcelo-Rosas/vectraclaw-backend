"""Launcher para os 10 daemons da VectraClaw.

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

Memory ref: VEC-414 — daemon spawnado sem `.env` carregado vira no-op
silencioso. Por isso o `load_dotenv()` no topo, ANTES de copiar
`os.environ` pro subprocess.
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

DAEMONS: list[tuple[str, str]] = [
    ("Morpheus",       "00000000-0000-0000-0000-000000000001"),
    ("Oracle",         "00000000-0000-0000-0000-000000000002"),
    ("Mnemos",         "00000000-0000-0000-0000-000000000003"),
    ("Hermes",         "59b7a69e-cc53-4063-85f9-5dcc5619ac96"),
    ("Mercator",       "c7de1b0f-7c74-42f1-9de4-7210349e668e"),
    ("Plutus",         "80fd6d0e-53ab-4638-b6e9-05cbbd121092"),
    ("Hodos",          "0d6e56cc-28b6-4382-96cd-1952b890d412"),
    ("HermesReporter", "360a96cb-b1c3-4b65-b9fa-2b9cbb59dac1"),
    ("Kronos",         "9c8d7e6f-5a4b-4321-9876-543210fedcba"),
    ("Athena",         "ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d"),
    ("Daedalus",       "d4ed4145-0000-4000-8000-000000000005"),
]


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
