# AGENTS.md

Guidance for AI agents working in this repository. See also `CLAUDE.md` for the VectraClaw product map.

## Cursor Cloud specific instructions

### What runs here

- **VectraClaw API (FastAPI):** `python3 -m src.main serve --port 3100` — health at `GET http://localhost:3100/api/health` → `{"status":"online","service":"VectraClaw Agent Engine"}`.
- **Agent daemons:** `python3 start_all_daemons.py` or `AGENT_ID=<uuid> python3 -m src.agent_daemon` — requires real Supabase credentials and daemon rows in `vectraclip.agents`.
- **VectraClip UI:** separate repo; not in this workspace.
- **Docker Compose** (`docker-compose.yml`): optional full stack (backend + nous-hermes + tunnel). Host dev usually runs API + daemons directly on Python.

### First-time `.env`

Copy `.env.example` → `.env`. For local API smoke without Supabase Auth, set `VECTRACLAW_AUTH_DISABLED=true`. Real DB/task flows need valid `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`, and `SUPABASE_SCHEMA=vectraclip`.

### Commands (from repo root)

| Action | Command |
|--------|---------|
| Install deps | `python3 -m pip install --user -r requirements.txt` (ensure `~/.local/bin` on `PATH`) |
| Run API | `python3 -m src.main serve --port 3100` |
| Tests (offline subset) | `python3 -m pytest tests/test_kronos_categorizer.py tests/test_intelligence_dashboard.py -q` |
| Full test suite | `python3 -m pytest tests/ -q` (many tests need Supabase / running API) |
| Docker image | `docker build -f Dockerfile .` (CI: `.github/workflows/docker-image.yml`) |

There is no project-wide ruff/mypy/pre-commit config in this tree; rely on `pytest` for verification.

### Gotchas

- **`main` may reference modules documented as unmerged WIP** (e.g. `src/postgrest_coerce.py`, `src/services/company_profile.py`). If `import src.api` fails with `ModuleNotFoundError`, restore or add those modules before serving.
- **Python 3.12** works on Cloud VMs; `Dockerfile` targets **3.11** for production images.
- **Playwright** is in `requirements.txt` but Chromium install (`playwright install chromium`) is only required for browser/Kronos paths—not for API health or most unit tests.
- **Compose `daemon` service** runs a single `agent_daemon` without `AGENT_ID`; production uses `start_all_daemons.py` on the host for all agents.
- Hot reload is off (`reload=False` in `src/main.py`); restart the server after dependency or code changes.

### Long-running processes

Use **tmux** (portal config at `/exec-daemon/tmux.portal.conf`) for dev servers, e.g. session name `vectraclaw-api`.
