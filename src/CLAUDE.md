# `src/` — Mapa do código VectraClaw

> Esta pasta contém **dois universos misturados**: a aplicação VectraClaw e o scaffolding upstream `claw-code`.
> Para trabalho VectraClaw, considere apenas os arquivos/diretórios listados abaixo. Tudo o que não estiver aqui é scaffolding e pode ser ignorado.

---

## Entry points

| Arquivo | Papel |
|---|---|
| `api.py` | FastAPI server em `:3100`. ~7700 linhas. Endpoints REST, WS, Oracle chat, dispatch para CMA, IMAP helpers, reactor de heartbeats. **É o único módulo que toca Supabase fora dos daemons.** |
| `agent_daemon.py` | Loop de polling de tasks. 1 processo por `AGENT_ID`. Adquire lock em `.daemon_locks/<id>.lock`. Roteia por `operation_type` para handlers em `agents/`. |
| `__init__.py` | Vazio (package marker). |

Não há outros entry points VectraClaw em `src/` (top-level). Os arquivos que parecem entry points (`commands.py`, `main.py`, `direct_modes.py`) são do **scaffolding upstream**.

---

## Diretórios VectraClaw

| Diretório | Papel | Detalhe |
|---|---|---|
| `agents/` | Implementação de cada agente (Oracle, Kronos, Hermes, Hodos, Mercator, Plutus, etc.) | Ver `agents/CLAUDE.md` |
| `managed_agents/` | Abstração de provider (Anthropic, Ollama, HuggingFace) e Decision Engine CMA × Harness | Ver `managed_agents/CLAUDE.md` |
| `services/` | Camada de serviços puros (sem Supabase): IMAP/SMTP, Gemini, Playwright capture, freight calculator, heartbeat doctor | Ver `services/CLAUDE.md` |

---

## Top-level helpers (relevantes)

| Arquivo | Papel |
|---|---|
| `models.py` | Pydantic v2 models. `Agent`, `Task`, `Heartbeat`, `Incident`, `NewHeartbeatInput`, `TaskDispatchInput`, etc. **Toda mutação API recebe input model.** |
| `m3_tools.py` | Funções tool dispatcháveis pelo CMA: `calculate_cbm`, `extract_bl_pl`, `infer_vehicle_capacity`. Cada uma aceita JSON string e devolve JSON string (`{success, ...}`). |
| `ws_manager.py` | Singleton `manager` para pub/sub WS. `dict[company_id] -> List[WebSocketLike]`. Helpers: `broadcast_company`, `broadcast_heartbeat`, etc. Importa em api.py + qualquer service que precise emitir evento. |
| `jwt_helper.py` | Validação de JWT do Supabase Auth (rota protegida). `VECTRACLAW_AUTH_DISABLED=true` no `.env` desliga em dev. |
| `sipoc_*.py` (se existir) | Endpoints SIPOC builder específicos. |

---

## Padrões de código

- **Logger naming:** `logging.getLogger("VECTRA CLAW")` no daemon, `logging.getLogger("ManagedAgents.<X>")` em managed_agents, `logging.getLogger("<AgentName>")` em agentes (ex: "Kronos", "HermesReporter").
- **Async vs sync:**
  - `api.py` é async (FastAPI). Operações Supabase rodam via `asyncio.to_thread` quando necessário (Supabase client é sync).
  - `agent_daemon.py` é sync. Handlers de agente expostos como funções sync.
  - `managed_agents/*.py` é async (`async def execute_task`). SDKs sync (anthropic, openai) chamados via `asyncio.to_thread`.
- **Import lazy entre `api.py` ↔ outros módulos:** para evitar circular import, `from src.api import ...` é feito dentro de funções (ex: em `tool_translator._read_hermes_inbox`, `router._emit_run_heartbeat`).
- **Erro silencioso vs explícito:** heartbeats, métricas, e dispatch de side-effects são best-effort (`try/except + log`). Mutações de dados (task status, agent fields) são fail-loud.
- **Pydantic v2:** Use `model_dump()`, `model_validate()`, `field_validator`. Ramos antigos usam `dict()` e `@validator` (deprecated mas funcional).

---

## Onde novos arquivos VectraClaw devem ir

| Tipo | Diretório |
|---|---|
| Lógica de negócio de um agente específico | `src/agents/<agent>.py` |
| Cliente para um novo provider LLM | `src/managed_agents/<provider>_agent_client.py` |
| Serviço puro reutilizável (parser, calculator, integração externa) | `src/services/<area>/<service>.py` |
| Pydantic input/output | `src/models.py` (não criar arquivos paralelos) |
| Tool callable pelo CMA | `src/m3_tools.py` (definição) + registrar em `src/managed_agents/tool_translator.py` |
| Migration | `supabase/migrations/YYYYMMDDHHMMSS_<slug>.sql` |
| Test | `tests/test_<modulo>.py` |

**Não crie:** novos `commands.py`, `tools.py`, `assistant/*`, `cli/*`, `screens/*` no top-level — são namespaces upstream e podem confundir.
