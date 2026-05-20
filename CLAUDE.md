# VectraClaw — Mapa do projeto

> Este repositório é uma **fork de [`claw-code`](https://github.com/instructkr/claw-code)** (Python rewrite scaffolding do Claude Code) que **hospeda** a aplicação VectraClaw.
>
> **Tudo o que está neste documento e nos demais `CLAUDE.md` se refere à aplicação VectraClaw**, não ao scaffolding upstream.

---

## O que é VectraClaw

Backend FastAPI + 8 daemons que servem o frontend **VectraClip** (dashboard Vectra Cargo). Coordena agentes (Anthropic, Gemini, Ollama, HuggingFace) que executam tasks de natureza logística e administrativa — cotação de frete, leitura de inbox, auditoria financeira (OFX × Planner), pesquisa SIPOC, etc.

- **API:** `src/api.py` em `:3100`
- **Worker:** `src/agent_daemon.py` (1 processo por agente; lock em `.daemon_locks/<AGENT_ID>.lock`)
- **WS pub/sub:** `src/ws_manager.py` (`hello`, `heartbeat`, `task_updated`, `agent_updated`, `incident_updated`)
- **Frontend separado:** `frontend/` (não incluso no escopo deste backend) ou `cargo-flow-navigator` (repo à parte)

---

## Como **distinguir código VectraClaw vs scaffolding upstream**

A pasta `src/` contém os dois universos. **Para trabalho VectraClaw, considere apenas:**

| VectraClaw (foco) | claw-code upstream (ignorar) |
|---|---|
| `src/api.py`, `src/agent_daemon.py`, `src/__init__.py` | `src/QueryEngine.py`, `src/Tool.py` |
| `src/agents/` | `src/cli/`, `src/screens/`, `src/dialogLaunchers.py`, `src/keybindings/` |
| `src/managed_agents/` | `src/assistant/`, `src/buddy/`, `src/coordinator/` |
| `src/services/` | `src/native_ts/`, `src/outputStyles/`, `src/plugins/` |
| `src/models.py`, `src/m3_tools.py`, `src/ws_manager.py` | `src/command_graph.py`, `src/commands.py`, `src/cost_tracker.py` |
| `src/jwt_helper.py`, `src/sipoc_*.py` | `src/reference_data/`, `src/schemas/`, `src/migrations/` (a de claw-code, **não** `supabase/migrations/`) |
| `start_*.py`, `tests/test_*.py` (com prefixo VEC ou domínio Vectra) | `tests/test_*.py` herdados do upstream (raros) |
| `supabase/`, `docs/PRD-*`, `docs/VEC-*`, `frontend/` | `assets/omx/`, `assets/wsj-*` |

Critério rápido: se o arquivo importa `src.api`, `src.agents.*`, `src.managed_agents.*`, `src.services.*`, `src.models`, `src.ws_manager` ou alude a SIPOC/Vectra/Cargo/CT-e/frete — é VectraClaw. O resto é scaffolding.

---

## Os 10 daemons

| Nome | AGENT_ID | Operation types principais | Log |
|---|---|---|---|
| Morpheus | `00000000-0000-0000-0000-000000000001` | orquestração, route-cost-calculation (excluded) | `daemon-morpheus.log` |
| Oracle | `00000000-0000-0000-0000-000000000002` | `oracle-research`, SIPOC chat | `daemon-oracle.log` |
| Mnemos | `00000000-0000-0000-0000-000000000003` | `rag-ingest` (curator de corpus RAG) | `daemon-mnemos.log` |
| Hermes | `59b7a69e-cc53-4063-85f9-5dcc5619ac96` | `email_lead`, IMAP polling | `daemon-hermes.log` |
| Mercator | `c7de1b0f-7c74-42f1-9de4-7210349e668e` | comercial / cotações | `daemon-mercator.log` |
| Plutus | `80fd6d0e-53ab-4638-b6e9-05cbbd121092` | financeiro | `daemon-plutus.log` |
| Hodos | `0d6e56cc-28b6-4382-96cd-1952b890d412` | qualp / rotas | `daemon-hodos.log` |
| HermesReporter | `360a96cb-b1c3-4b65-b9fa-2b9cbb59dac1` | `oracle-report`, envio SMTP | `daemon-hermesreporter.log` |
| Kronos | `9c8d7e6f-5a4b-4321-9876-543210fedcba` | `scrape-backlog`, `entrypoint-backlog`, `conciliacao-backlog`, `audit`, `apply` | `daemon-kronos.log` |
| Athena | `ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d` | `athena-classify`, `athena-charter`, `athena-rag-ingest`, demais `athena-*` | `daemon-athena.log` |

**AGENT_IDs são imutáveis** — são FK em `vectraclip.tasks.assigned_to_agent_id`.

---

## Boot flow

```powershell
cd C:\Users\marce\VectraClaw
docker compose up -d                          # API em :3100 (container) + tunnel Cloudflare
python start_all_daemons.py                   # sobe os 10 daemons (lock por AGENT_ID)
```

**Auto-start no logon (Windows):** task `VectraClaw-Daemons` no Task Scheduler dispara `pythonw.exe start_all_daemons.py` em todo logon do user. Gerenciar via:
```powershell
Start-ScheduledTask  -TaskName VectraClaw-Daemons   # rodar agora (idempotente — locks vivos abortam respawn)
Disable-ScheduledTask -TaskName VectraClaw-Daemons  # pausar auto-start
Get-ScheduledTaskInfo -TaskName VectraClaw-Daemons  # last run / next run
```

**Versão mínima no host:** o launcher precisa de `supabase>=2.5` no Python que executa (mesmo gap do `requirements.txt` do container). Atualizar com:
```powershell
python -m pip install --user --upgrade --only-binary=:all: "supabase>=2.5.0,<3"
```

Health interno: `curl http://localhost:3100/api/health`. Externo via tunnel: `https://api-vectraclip.vectracargo.com.br/api/health`. Resposta esperada: `{"status":"online"}`.

Detalhes operacionais completos (matar processo, reenfileirar task, smoke SMTP, etc.): **`COMANDOS.md`** na raiz.

---

## Disciplina de PR (padrão)

Branch → commit → push → `gh pr create` → checks → `gh pr merge --squash --delete-branch` → monitor.

- **Escopo pequeno por PR.** Não bundlar features distintas.
- **Feature WIP grande?** Quebra em 5-8 PRs por subsistema (managed_agents, hermes, oracle, workflow, api.py, etc.).
- **Migrations:** seguir `supabase/CLAUDE.md`. **Regra de Ouro #6:** nunca MCP/SQL Editor para DDL — só `supabase/migrations/` + `db push` (`docs/CODE-PATTERNS.md` P9).
- **Daemons rodando durante merge:** rebaseline OK; mas restart de daemon é manual e exige confirmação do usuário (downtime ~3-5s).
- **Pré-merge:** `git diff --stat`, `git status --short`, rodar tests do escopo, monitor `daemon-*.log` por erros.

---

## Convenções globais

- **Schema Supabase:** `vectraclip` (NÃO `public`). Project ref: `epgedaiukjippepujuzc`.
- **company_id:** UUID; toda task/agent/heartbeat carrega `company_id`. Vectra Cargo é mock fixo no dev.
- **Datas:** dd/mm/aaaa em UI; ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ`) em API/DB.
- **Português brasileiro** em logs, mensagens de erro, prompts dos agentes, comentários de código novo.
- **Pydantic 2.x** instalado (apesar de `requirements.txt` ainda dizer `<2.0.0` em ramos antigos — corrigido nas WIPs).
- **Schema namespace nas migrations:** sempre prefixar `vectraclip.` em `CREATE TABLE`, `INSERT INTO`, etc.

---

## Pointers úteis

- `COMANDOS.md` — operações: kill server, reenfileirar task, smoke SMTP, daemon logs, supabase CLI cheatsheet
- `supabase/MIGRATIONS.md` — drift handling, repair seguro, fluxo de `db pull`/`db push`
- `docs/PRD-*` — specs de agentes e features (Hodos QUALP, Oracle, Workflow Builder)
- `docs/VEC-*` — issues Linear documentadas
- `docs/ADR-VEC-237-*.md` — Architecture Decision Records
- Auto-memory do usuário: `~/.claude/projects/C--Users-marce-VectraClaw/memory/MEMORY.md`
