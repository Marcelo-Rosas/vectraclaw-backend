# PRD — Nous Hermes Integration (Runtime Interno + MCP + Adapter)

> **Status:** Draft — aprovação pendente
> **Owner:** Marcelo Rosas
> **Criado:** 2026-05-17
> **Escopo:** Fases 1-3 (runtime interno + MCP server + adapter). Canal cliente (Fase 4) e expansão multi-provider de trajectory (Fase 5.2) **fora deste PRD**.
> **PRDs relacionados:** [`PRD-ATHENA-HR-TRAJECTORY-INGEST.md`](./PRD-ATHENA-HR-TRAJECTORY-INGEST.md) (depende da Fase 3 deste)

---

## 1. Context

Hermes-Nous (Nous Research) é um agente autônomo CLI com 70+ tools built-in, MCP bi-direcional, gateway multi-canal (~20+ plataformas), backends de execução isolados (Docker/SSH/Modal/Daytona), aprovação smart e skill creation autônoma. Documentação: https://hermes-agent.nousresearch.com/docs

O usuário identificou 4 casos de uso simultâneos no VectraClaw:
1. Canal cliente (gateway multi-canal pra cotação/status sem dashboard) — **deferido**, ver §10
2. Provider/runtime alternativo (modelos Nous via OpenRouter ou Nous Portal)
3. Skill creation + trajectory pra fine-tune Athena-Vectra — **PRD separado**
4. Substituir/encolher daemons (Kronos cron, runtime hardened pra Playwright)

Este PRD trata de #2 e #4 (uso interno). Direção: **bidirecional** — VectraClaw expõe MCP server e também invoca Hermes como provider.

### Naming e colisão

O nome **Hermes** já ocupa 2 papéis no VectraClaw:
- `Hermes` daemon — AGENT_ID `59b7a69e-cc53-4063-85f9-5dcc5619ac96` — IMAP polling / `email_lead`
- `HermesReporter` daemon — AGENT_ID `360a96cb-b1c3-4b65-b9fa-2b9cbb59dac1` — SMTP send / `oracle-report`

**AGENT_IDs são imutáveis** (FK em `vectraclip.tasks`). Toda referência ao Hermes da Nous neste PRD usa o namespace **`nous-hermes`** (serviço, AGENT_ID novo, AgentAdapterType próprio). Zero realocação dos AGENT_IDs existentes.

---

## 2. Goals

- **G1.** Permitir execução de prompts via runtime Hermes-Nous a partir do backend VectraClaw (Fase 1)
- **G2.** Expor entidades VectraClaw (tasks, quotes, clients, RAG) como tools MCP consumíveis por qualquer agente externo (Fase 2)
- **G3.** Habilitar despacho de tasks aos modelos Nous (Hermes-4, Nomos, Psyche) via OpenRouter no mesmo pipeline dos providers atuais (Anthropic/Gemini/Ollama/HF) (Fase 3)
- **G4.** Zero impacto operacional nos 11 daemons existentes (Morpheus, Oracle, Mnemos, Hermes, Mercator, Plutus, Hodos, HermesReporter, Kronos, Athena, Daedalus — verificado em `start_all_daemons.py:37-47`). Nota: CLAUDE.md raiz lista só 10 — desatualizado. Daedalus está em produção mas em retrofit (memory `agent-hiring-ritual`).

## 3. Non-goals (out of scope)

- ❌ Canal cliente (WhatsApp/Telegram/Discord) — conflita com visão OpenClaw já mapeada (`vectra-mcp-builder/references/openclaw-integration.md`, `commercial_followup_rules.channel = openclaw | email | meta`). Ver §10 e ADR futura
- ❌ Substituição do daemon Kronos por `hermes cron` — backlog pós-F3
- ❌ Adapter Hermes como backend Playwright hardened — backlog pós-F3
- ❌ Fine-tune de modelo Nous custom — depende de trajectory (PRD separado) + dataset substancial
- ❌ Multi-tenant gateway com isolamento per-company — bloqueia canal cliente, não bloqueia uso interno

---

## 4. Decisões já tomadas

> **Convenção de IDs:** decisões deste PRD usam prefixo `NH-D` pra evitar colisão com `D1..D13` do ADR-VEC-MAPEAR-ANALISAR-AUTOMATIZAR §6.

| ID | Decisão | Razão |
|---|---|---|
| NH-D1 | **Provider de inferência:** OpenRouter (Hermes-4 / Nomos) na F1, Nous Portal direto deferido | OpenRouter tem os modelos Nous; cadastro de Portal pode ser adicionado depois sem refactor |
| NH-D2 | **Naming:** `nous-hermes` | Zero colisão com daemons existentes |
| NH-D3 | **Aprovação:** modo `smart` (LLM avalia risco) **apenas para prompts internos**; ações via MCP server (F2) caem na tabela `approvals` existente — ver R12 | Equilíbrio entre segurança e fluidez pra POC; ações sensíveis seguem governança do ADR |
| NH-D4 | **Invocação:** HTTP thin wrapper (FastAPI no container Hermes) | Sem docker socket no backend; testa local fácil; health check próprio |
| NH-D5 | **Deploy:** Docker compose local (mesmo do API + daemons) **+ config persistida em `adapter_catalog` / `llm_models` / `agent_adapter_configs`** (per-company); container carrega config do DB no boot via `wrapper.py:bootstrap_config()` — não usa env-vars de produto | Sem custo cloud novo; isolamento via container; cumprimento da regra de ouro #2 (NO HARDCODE) |
| NH-D6 | **Direção:** Bidirecional (Vectra ↔ Hermes via MCP + subprocess HTTP) | Maximiza valor; MCP server da F2 é reaproveitável por qualquer agente externo |

---

## 5. Roadmap

| # | Fase | Entrega | Sprints |
|---|---|---|---|
| **1** | **Foundation** | Container `nous-hermes-runtime` + HTTP thin wrapper + endpoint `/api/nous-hermes/exec` atrás de feature flag | 1 |
| **2** | **MCP Server VectraClaw** | `src/mcp_server/` expondo `list_tasks`, `get_quote`, `query_rag`, `enqueue_task` com filtro implícito por `company_id` | 2 |
| **3** | **Adapter inverso** | `nous_hermes_agent_client.py` em `managed_agents/`, seed em `adapter_catalog`, 1ª specialty cobaia em `document_generation` ou `code_review` (já rotam via CMA — ver §8.4) | 1-2 |

Fase 2 e 3 podem rodar em paralelo. Fase 3 entrega valor end-to-end (task com `provider=nous_hermes` executando via Hermes).

---

## 6. Fase 1 — Foundation (detalhada — primeiro PR shippable)

### 6.1 Arquivos novos

| Caminho | Propósito |
|---|---|
| `nous-hermes-runtime/Dockerfile` | Base `node:20-bookworm-slim` + Python 3.11 + ripgrep + ffmpeg + clone de `NousResearch/hermes-agent` + `pip install fastapi uvicorn httpx` pro wrapper |
| `nous-hermes-runtime/wrapper.py` | FastAPI minimalista. `POST /exec {prompt, model?, max_turns?, ignore_user_config?}` → `subprocess.run(["hermes", "-z", prompt, ...])` com timeout configurável → retorna `{success, content, exit_code, duration_ms}`. `GET /health` valida que `hermes --version` responde |
| `nous-hermes-runtime/entrypoint.sh` | **Apenas** `exec uvicorn wrapper:app --host 0.0.0.0 --port 9120`. Config do hermes-cli (provider, model, api_key, approval_mode, max_turns) é carregada pelo `wrapper.py` no startup via SELECT em `adapter_catalog` + `llm_models` + `agent_adapter_configs` (regra de ouro #2 — ver §11.1). NÃO usar `hermes config set X=$ENV_VAR` em série |
| `nous-hermes-runtime/wrapper.py` (expandido) | Além de `POST /exec` + `GET /health`, adicionar `bootstrap_config()` chamado no startup: faz SELECT (via cliente Supabase) em `adapter_catalog WHERE slug='nous_hermes' AND is_active=true` JOIN `llm_models` JOIN `agent_adapter_configs.field_values_json`; monta dict de config; chama `hermes config set ...` programaticamente antes do servidor aceitar requests |

### 6.2 Arquivos modificados

| Caminho | Mudança |
|---|---|
| `docker-compose.yml` | +1 serviço `nous-hermes-runtime` com `build: ./nous-hermes-runtime`, `env_file: .env`, volume nomeado `nous-hermes-config:/root/.hermes`, healthcheck em `:9120/health`. Backend ganha `depends_on: nous-hermes-runtime: service_healthy`. +1 named volume no topo |
| `.env.example` | **Apenas variáveis de infraestrutura:** +`NOUS_HERMES_RUNTIME_URL=http://nous-hermes-runtime:9120` (service discovery). **NÃO adicionar** `OPENROUTER_API_KEY` / `HERMES_INFERENCE_PROVIDER` / `HERMES_INFERENCE_MODEL` / `HERMES_APPROVAL_MODE` / `HERMES_MAX_TURNS` / `NOUS_HERMES_ENABLED` — viola regra de ouro #2 (NO HARDCODE). Esses valores vivem em `adapter_catalog` + `llm_models` + `agent_adapter_configs` (ver §11.1) |
| `src/api.py` | +endpoint `POST /api/nous-hermes/exec` atrás de check no DB: `SELECT 1 FROM vectraclip.adapter_catalog WHERE slug='nous_hermes' AND is_active=true AND company_id=<caller>`. Validação: JWT autenticado + requires admin role. Chama `httpx.post(f"{NOUS_HERMES_RUNTIME_URL}/exec", json={...}, timeout=120)`. Retorna `content` + metadata. Endpoint retorna 503 quando adapter não está ativo na company (regra de ouro #2 — feature flag em catálogo, não env) |

**Atenção:** `Dockerfile` (raiz) está visivelmente corrompido na linha 79 (`CMD [...]a código-fonte` — copy-paste accident). **NÃO corrigir neste PR** — abrir issue separada. F1 não rebuilda a image principal.

### 6.3 Patterns existentes a reusar

| Pattern | Onde | Como aproveitar |
|---|---|---|
| Feature flag em catálogo (regra de ouro #2) | Não há env-var de produto novo. Pattern: `adapter_catalog.is_active` per-company (consistente com Ollama, HuggingFace etc.) | Endpoint verifica `adapter_catalog WHERE slug='nous_hermes' AND is_active=true` antes de servir |
| JWT validation | Middleware em `src/api.py:795-797` setta `request.state.user_id` + `request.state.company_id`; fallback `MOCK_USER` quando `VECTRACLAW_AUTH_DISABLED=true` (memory `start_server_auth_bypass`) | Reusar exatamente — não criar auth nova nem usar `Depends(get_current_user)` (pattern inexistente) |
| HTTP client async | `src/services/gemini_interactions.py` (async) | Template pro httpx no novo endpoint |
| Logger nomeado | Convenção `logging.getLogger("Vectra.<área>")` (ver `src/services/CLAUDE.md`) | `logging.getLogger("Vectra.NousHermes")` |
| Container `env_file: .env` | `docker-compose.yml:8-9` (backend) e `:24-25` (daemon) | Replicar |
| Healthcheck pattern | `docker-compose.yml:12-17` (backend curl `/api/health`) | Replicar com `/health` no wrapper |

### 6.4 UI mínima (cumprir D13 do ADR — UI é fonte de dados)

Sem UI = backend órfão no MVP (memory `ui-is-source-of-truth-no-cli`; ADR §8). F1 entrega painel admin junto com o endpoint:

| Item | Onde | Como |
|---|---|---|
| Rota | Nova aba "Runtimes" em `AdminConnectors.tsx` ou nova página `/admin/runtimes` | Espelhar layout de `AdminConnectors.tsx` / `AdminModels.tsx` (já cobrem provider config) |
| Card "Status do container" | Componente novo `RuntimeHealthCard.tsx` | Lê `GET /api/nous-hermes/health` (proxy do healthcheck do wrapper) |
| Toggle "Adapter ativo" | Reusar `AdapterActiveToggle.tsx` de `AdminConnectors.tsx` (ou similar existente) | Escreve direto em `adapter_catalog.is_active` per-company via mutation existente — sem env-var (cumprimento da regra de ouro #2) |
| Form de smoke prompt | `RuntimeSmokeForm.tsx` | `POST /api/nous-hermes/exec` + textarea de input + área de output |
| Tabela últimas N execs | Reusar `TasksTable.tsx` (existe) com filtro `provider='nous_hermes'` | Query `tasks WHERE provider='nous_hermes' ORDER BY created_at DESC LIMIT 50` |
| Endpoint TS | `src/lib/api/endpoints/nousHermes.ts` (novo) | `exec()`, `health()` |
| React Query hooks | `src/lib/queries/nousHermes.ts` (novo) | `useNousHermesHealth()`, `useNousHermesExecMutation()` |

**Critério bloqueante:** F1 sem essa UI viola D13 (UI é fonte de dados) e não é mergeável no MVP.

### 6.5 Verification (Fase 1)

```powershell
# 1. Subir só o runtime
docker compose up --build -d nous-hermes-runtime

# 2. Health do container
docker compose logs nous-hermes-runtime --tail 50
# esperar: "hermes config set" lines + "Uvicorn running on http://0.0.0.0:9120"

# 3. Health do wrapper
docker compose exec backend curl -fs http://nous-hermes-runtime:9120/health
# esperar: {"status":"ok","hermes_version":"x.y.z","provider":"openrouter","model":"..."}

# 4. Smoke exec via wrapper diretamente
docker compose exec backend curl -X POST http://nous-hermes-runtime:9120/exec `
  -H "Content-Type: application/json" `
  -d '{"prompt":"Diga apenas: SMOKE OK","max_turns":3}'
# esperar: {"success":true,"content":"SMOKE OK",...}

# 5. Smoke via endpoint da API (ativar adapter no DB — não env)
# Via UI: AdminConnectors → toggle "nous_hermes" → on. Ou via SQL:
# UPDATE vectraclip.adapter_catalog SET is_active=true WHERE slug='nous_hermes' AND company_id='<seu_company_id>';
docker compose up -d backend  # reinício opcional se houver cache
$token = "..."  # JWT admin
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:3100/api/nous-hermes/exec" `
  -Headers @{ Authorization = "Bearer $token" } `
  -ContentType "application/json" `
  -Body '{"prompt":"Quanto é 17 * 23?"}'

# 6. Confirmar zero regressão nos daemons
Get-Content daemon-hermes.log -Tail 20         # IMAP continua polling
Get-Content daemon-hermesreporter.log -Tail 20 # SMTP continua disponível
docker compose ps  # tudo healthy
```

### 6.6 Critério de aceite (Fase 1)

- ✅ `nous-hermes-runtime` healthy no `docker compose ps`
- ✅ Smoke prompt retorna `content` não vazio em < 30s
- ✅ Smoke roda com `--ignore-user-config` e `approval.mode=smart` sem pedir confirmação humana pra prompt trivial
- ✅ Daemons `Hermes` e `HermesReporter` continuam com heartbeat normal (zero regressão)
- ✅ Sem `adapter_catalog.is_active=true` pra `slug='nous_hermes'` na company do caller, endpoint `/api/nous-hermes/exec` retorna 503 (feature flag em DB, não env — regra de ouro #2)
- ✅ **UI mínima (§6.4) entregue no mesmo PR** — sem ela, F1 não é mergeável (cumprimento de D13)

---

## 7. Fase 2 — MCP Server VectraClaw (roadmap)

### 7.1 Escopo

Criar `src/mcp_server/` (novo dir) expondo MCP tools consumíveis por qualquer agente externo (Hermes, ChatGPT, Claude Desktop, etc.):

| Tool | Input | Output | Side-effect |
|---|---|---|---|
| `list_tasks` | `{status?, operation_type?, limit?}` | Lista de tasks da company do caller | Nenhum |
| `get_quote` | `{quote_id}` | Detalhe da quote | Nenhum |
| `list_clients` | `{limit?, search?}` | Lista de clients da company | Nenhum |
| `query_rag` | `{corpus_id, query, top_k?}` | Chunks relevantes (reusa `src/services/athena_rag.py` se aplicável) | Nenhum |
| `enqueue_task` | `{operation_type, payload, assigned_to_agent_id?}` | `{task_id}` | Cria row em `vectraclip.tasks` |
| `read_workflow` | `{workflow_id}` | Estrutura serializada | Nenhum |

### 7.2 Auth

- **Herda 100% do middleware atual** (`src/api.py:795-797`): JWT valida → `request.state.user_id` + `request.state.company_id` settados; fallback `MOCK_USER` em dev. Sem `Depends(get_current_user)` (pattern inexistente).
- `company_id` filtra **automaticamente** todo SELECT/INSERT — caller não pode acessar dados de outra company.
- **Sem RBAC novo** — ações sensíveis (`enqueue_task`) reusam a tabela `approvals` existente (`approval_request_type='enqueue_task_from_mcp'`). Aprovação por humano via fluxo `Council.tsx` / `ApprovalsList.tsx` já existente. ADR P3 (agent_skills × agent_specialties) e P9 (encerramento legal — Themis ou humano) ainda abertas: até decisão, MCP segue regra conservadora (toda ação write = approval).

### 7.3 Decisões abertas

1. **Transport:** stdio (local) vs streamable HTTP (remoto)? Recomendação: HTTP no MVP (Hermes consome via `hermes mcp add --url`), stdio depois pra Claude Desktop
2. **Granularidade do approval pra `enqueue_task`:** todo `operation_type` requer humano, ou alguns `operation_type` whitelisted no `approvals.request_type` autoaprovam? Decisão amarrada a ADR P3 — manter conservador (humano sempre) até P3 decidir
3. **Rate limiting** — necessário em F2 ou deferido?

### 7.4 Dependências

- Fase 1 entregue (runtime existe pra consumir o MCP)
- MCP Python SDK (`pip install mcp`) — adicionar a `requirements.txt`

---

## 8. Fase 3 — Adapter inverso (roadmap)

### 8.1 Escopo

Permitir despachar tasks ao Hermes-Nous via mesmo pipeline dos providers atuais. Pattern documentado em `src/managed_agents/CLAUDE.md` (linhas 100-106 — passo a passo de adicionar provider).

### 8.2 Arquivos

| Caminho | Tipo |
|---|---|
| `src/managed_agents/nous_hermes_agent_client.py` | Novo — `class NousHermesAgentClient: async def execute_task(...) -> ExecutionResult`. Chama `httpx.post(NOUS_HERMES_RUNTIME_URL/exec)` |
| `src/managed_agents/agent_client_factory.py` | Modificar — `PROVIDER_CLIENT_MAP["nous_hermes"] = NousHermesAgentClient` |
| `src/managed_agents/__init__.py` | Modificar — export |
| `src/managed_agents/router.py` | Modificar — whitelist em `_emit_run_heartbeat` (`provider in ("anthropic", "ollama", "huggingface", "nous_hermes")`) |
| `src/managed_agents/decision_engine.py` | Eventualmente — score per provider, mas v0 reusa scoring por operation_type |
| `supabase/migrations/YYYYMMDDHHMMSS_nous_hermes_adapter.sql` | Migration — seed `adapter_catalog` (1 row por company) + `adapter_field_definitions` + **`llm_models`** (rows pra `hermes-4`, `nomos-1`, `psyche-1`). **Atenção:** `model_capabilities` **não existe** no schema `vectraclip` (verificado 2026-05-17); usar `llm_models` que é a tabela versionada (gerenciada por `AdminModels.tsx`) |

### 8.3 ExecutionResult contract

```python
ExecutionResult(
    success=True,
    content="...",            # texto final do hermes -z
    tool_calls=[],            # Hermes usa tools próprias internas — não translatáveis pro nosso formato
    turn_count=0,             # parse do hermes logs se quiser; v0 = 0
    tokens_input=0,           # idem (Hermes não devolve usage estruturado em -z)
    tokens_output=0,
    execution_time_seconds=duration_ms / 1000,
    tokens_per_second=0.0,    # eval-only, deixar 0
    error=None,
)
```

`tokens_*` ficam 0 em v0 — Fase 5 (PRD trajectory) extrai via `hermes sessions export`.

### 8.3.1 Caso de uso adicional — Hermes como fallback de scraping (nível 4 de cascata)

**Decisão cravada 2026-05-17 (P15 sub-decisão Opção I):** Hermes-Nous é cobaia adicional como **nível 4 da cascata de scraping** do A3c CompetitorMapper do GymSite Intelligence (e padrão reusável para qualquer scraper VectraClaw):

```
Cascata padrão de scraping:
  1. API pública estruturada (ex: SearchAPI free tier)
  2. Lib determinística (ex: popular_times)
  3. Playwright sync_api (DOM conhecido + regex/aria-label estável)
  4. Hermes-Nous (LLM-driven browse — DOM novo, captcha, site nunca mapeado)
```

**Por que isso é importante:**
- Não compromete custo/latência do caso comum (≥80% dos sites caem em 1–3)
- Captura long-tail de fontes não-padronizadas (cliente novo, concorrente regional)
- Aproveita as 70+ tools built-in do Hermes (Vision como fallback se DOM falhar)

**Trade-off explícito:** custo do Hermes via OpenRouter é 3–10x maior por execução do que Playwright; cabe APENAS no nível 4, nunca substituindo Playwright primário (PRD-NOUS-HERMES §9 R13 explicita: hermes -z retorna texto livre — incompatível com JSON canônico estrito necessário em níveis 1–3).

**Implementação:** quando F2 (MCP Server) entregar `enqueue_task`, scrapers VectraClaw chamam Hermes via task com `operation_type=hermes_fallback_scrape` quando níveis 1–3 retornam erro/empty. Caching agressivo do output Hermes (TTL ≥ 7d) compensa custo.

### 8.4 1ª specialty cobaia

**Escolha:** `document_generation` **ou** `code_review` — ambas já rotam via CMA (score `75` e `65` em `_OPERATION_TYPE_SCORES` ≥ threshold 50). Permite A/B Hermes vs Anthropic **dentro da mesma arquitetura**.

**Por que NÃO `oracle-research`:** verificado em `src/agent_daemon.py:517,624` — `oracle-research` é **tratado nativamente pelo daemon Oracle** (polling loop específico, sync fallback do Deep Research Gemini), **não passa pelo CMA**. Clonar como `oracle-research-nous` compararia CMA (Hermes) vs daemon nativo (Gemini) — arquiteturas diferentes, não modelo vs modelo.

**Por que NÃO criar `operation_type` novo:** ADR Fase A.2 vai aposentar as 3 listas hardcoded de `operation_type` (Pydantic Literal + DB CHECK + dispatch). Criar `oracle-research-nous` agora obriga adicionar em 3 lugares e triplica débito que A.2 vai resolver. **Provider é configurado em `adapter_catalog` / `agent_adapter_configs`, não em `operation_type`.** A specialty cobaia ganha um `agent_specialty_configs` com `provider=nous_hermes` no `field_values_json` — sem novo op_type.

### 8.5 Critério de aceite (Fase 3)

- ✅ Task com `operation_type=document_generation` (ou `code_review`) executando via Hermes quando `agent_specialty_configs.provider='nous_hermes'`
- ✅ `ExecutionResult.success=true` em ≥ 80% das execuções de smoke
- ✅ Zero impacto em handlers atuais — specialty `nous_hermes` é opt-in via `agent_adapter_configs`
- ✅ **Tasks `provider=nous_hermes` NÃO entram nos cálculos de `tokens_per_second` / burn rate em `CostAnalytics.tsx` até parser de `hermes sessions export` estar implementado** (depende do PRD-ATHENA-HR-TRAJECTORY-INGEST). Exclusão explícita no `router._emit_run_heartbeat` ou nos handlers de telemetria
- ✅ Lista de handlers compatíveis em v0 (não exigem JSON estruturado): `document_generation`, `code_review`. **Handlers que NÃO podem usar Hermes em v0** (exigem JSON estruturado): Athena PMBOK (9 handlers), oracle-research, classify v2 — ver R13

---

## 9. Riscos e dívidas técnicas

1. **Slug exato do model no OpenRouter** (`nousresearch/hermes-4-405b` é estimativa). Validar antes do PR
2. **OpenRouter pricing** — Hermes-4 405B não é barato. Adicionar nota no PR com custo estimado por 1k execs F1
3. **Dockerfile principal corrompido** (linha 79) — issue separada, não bloqueia F1
4. **Hermes-Nous escreve em `~/.hermes/`** durante execução (skills aprendidas, sessions). Volume nomeado preserva — mas em ambiente multi-instance esse estado vira problema (Fase 4 vai precisar resolver isolation per-company)
5. **`hermes -z` em modo subprocess não devolve `tokens_input/output` estruturados** — Fase 3 popula com 0; PRD trajectory recupera via session export
6. **`CLAUDE.md` raiz desatualizado:** menciona `src/jwt_helper.py` que não existe (auth real em `src/api.py:795-797`) **+** lista apenas 10 daemons quando há 11 (Daedalus em `start_all_daemons.py:47`). Atualizar fora do escopo deste PRD
7. **Sem testes automatizados em F1** — smoke manual via verification §6.5 é suficiente pro POC. Test suite vira F3 (quando adapter entra no fluxo crítico)
8. **MCP server expondo `enqueue_task` é escalação de privilégio** — F2 reusa tabela `approvals` existente (ver §7.2 / §7.3); decisão fina de granularidade amarrada a ADR P3
9. **Skill creation autônoma do Hermes** paralela ao `_SPECIALTY_DISPATCH` interno da Athena — sem ownership claro até ADR P3 (`agent_skills` × `agent_specialties`) decidir. Governança precisa estar definida antes de F1 entrar produção (memory `feedback_athena_specialties_not_in_table`)
10. **Persistência `~/.hermes/` per-container** conflita com ADR P6 (multi-tenant pós-D). Em 10+ companies, 10+ runtimes Hermes — footprint cresce linear. Aceitável pré-D; revisar antes de venda externa
11. ~~`OPENROUTER_API_KEY` em env~~ — **RESOLVIDO em §11.1 H5**: key vive em `agent_adapter_configs.field_values_json.api_key` per-company (regra de ouro #2), não em env compartilhado. Anti-pattern de keys multi-ponto (memory `gemini-keys-unified`) deixa de aplicar
12. **Approval `smart` (NH-D3) é APENAS para prompts internos** — ações via MCP server (F2) caem em `approvals` table (humano aprova). Diferenciação explicitada em NH-D3 atualizado; risco de inversão durante implementação
13. **`hermes -z` retorna texto livre — incompatível com handlers que exigem JSON estruturado** (Athena PMBOK 9 handlers, oracle-research, classify v2 do ADR Fase A.1). Adapter Hermes em v0 serve só pra prompts free-form — lista de handlers compatíveis explicitada em §8.5
14. **Hermes hardened como backend Playwright** (§3 non-goal #3) — sem ROI vs Playwright nativo já mapeado (memory `kronos-planner-dom-pitfalls`). Manter como non-goal a menos que dor concreta apareça
15. **Telemetria Athena HR (Fase E do ADR) depende de tokens estruturados** — tasks `nous_hermes` com tokens=0 poluem agregações estatísticas. Critério §8.5 exclui essas tasks dos cálculos até F5/trajectory parser estar

---

## 10. OpenClaw × Hermes-Nous (referência, sem decisão neste PRD)

O usuário tem visão de **OpenClaw** documentada (skill `vectra-mcp-builder/references/openclaw-integration.md` + `commercial_followup_rules.channel = openclaw | email | meta` reservado no schema) — gateway TypeScript próprio com 14 agentes nomeados (main, brain, cotacao, financeiro, motorista, inbox, …), deploy Cloudflare Workers, branding 100% Vectra.

**Hermes-Nous Gateway** (~20 canais nativos, pairing DM, skill creation autônoma) é alternativa terceira. Comparação resumida:

| Dimensão | OpenClaw (build próprio) | Hermes Gateway (third-party) |
|---|---|---|
| Multi-tenant | Desenho próprio (1 worker por company ou tenant resolution) | Sem RBAC nativo → 1 container por company → escala mal em 50+ |
| Branding | 100% Vectra | "Powered by Nous" visível |
| Time-to-value | 2-3 sprints | 1 sprint |
| Skill creation | Manual | Autônoma |
| Trajectory export | Você implementa | Nativo |

**Decisão deste PRD:** não escolher canal cliente agora. Este PRD entrega valor interno (runtime + MCP + adapter) que serve **qualquer** consumidor futuro (OpenClaw OU Hermes Gateway). A escolha do canal cliente vira ADR posterior:

> `docs/ADR-VEC-CANAL-CLIENTE-OPENCLAW-VS-HERMES.md` (criar depois da Fase 3)

---

## 11. Amarração com ADR-VEC-MAPEAR-ANALISAR-AUTOMATIZAR

Mapa de cumprimento das decisões/pendências do ADR pai:

| Item ADR | Tema | Cumprido neste PRD? | Onde |
|---|---|---|---|
| D13 + §8 | UI é fonte de dados (não-CLI) | ✅ após §6.4 (UI mínima bloqueante) | §6.4 + §6.6 critério |
| §7.5 | Aposentar 3 listas hardcoded de `operation_type` | ✅ — F3 NÃO cria op_type novo, usa `agent_specialty_configs.provider` | §8.4 |
| §7.6 | NÃO criar `agent_skills` separado | ⚠️ pendente — depende de R9 (skill creation autônoma do Hermes) e ADR P3 | §9 R9 |
| P3 | `agent_skills` × `agent_specialties` + bug skills tab | ⚠️ aguardando — MCP server adota fluxo conservador até decisão | §7.3 #2 |
| P6 | Multi-tenant primeira venda externa | ⚠️ aceitável pré-D; revisar antes | §9 R10 |
| P9 | Encerramento legal — Themis ou checklist humano | N/A pra este PRD | — |
| Fase A.2 | Migrar `operation_type` pra `operation_types_catalog` | Compatível — F3 não adiciona op_types | §8.4 |
| Fase A.4 / P13 | `routing_score` em `operation_types_catalog` | Compatível — `nous_hermes` herda score do op_type da task | — |
| Fase E | Telemetria + recomendação de modelo | ⚠️ R15 — exclusão temporária de `nous_hermes` dos cálculos até trajectory parser | §8.5 + §9 R15 |
| Memory `agent-hiring-ritual` | Agente novo exige ritual completo | ⚠️ se `nous-hermes` ganhar AGENT_ID e rodar tasks com `assigned_to_agent_id`, vira agente — precisa de hiring ritual via `HireAgentDialog` + `Council.tsx` + `approvals.request_type='hire_agent'`. **Decisão pendente:** ver §10 e abrir P14 no ADR |
| Memory `metadata-driven-no-hardcode` (**REGRA DE OURO #2**) | NÃO PODE EXISTIR NADA HARDCODADO | ✅ após §11.1 — 7 hardcodes em `.env`/entrypoint removidos; config vive em `adapter_catalog` + `llm_models` + `agent_adapter_configs`; container lê do DB no boot via `wrapper.py:bootstrap_config()` |
| Memory `mirror-before-create` (**REGRA DE OURO #1**) | SELECT antes de propor schema | ✅ — verificado 2026-05-17: `model_capabilities` não existe (fix F4); `adapter_catalog` tem 10 rows com slugs `claude_code, codex, gemini, huggingface, mcp-github, mcp-gmail, mcp-imap, mcp-slack, meta-whatsapp, ollama` (não providers); `commercial_followup_rules.channel` **tem CHECK** `('openclaw','email','meta')` em 3 tabelas (re-auditado quando do ADR-CANAL — auditoria primeira tinha dito "text livre", errado) |

**Pendências propostas pro ADR (re-verificadas contra P1-P13 — 2026-05-17):**

- **P14 (nova, mas DEPENDE de P3 + P2):** Decidir se `nous-hermes` é provider puro (`adapter_catalog` row) ou agente (com AGENT_ID + ritual hiring). NH-D6 diz bidirecional — implica ambos. Só pode ser respondida depois de P3 (schema de specialty) e P2 (mapeamento de perfis).
- ~~P15 (governança skills Hermes autonomous)~~ — **REMOVIDA**: duplica P3 do ADR (`agent_skills` × `agent_specialties` + bug `/agents/{id}?tab=skills`). Skill criada por agente externo é uma **faceta** de P3, não pendência separada. Endereçamento: expandir P3 com cenário "skill creation por providers externos" (ver edição proposta no ADR).
- ℹ️ **Nota:** o slot P15 do ADR pai foi reaproveitado pra outra decisão (GymSite ADK vs migrar) — **fechada em 2026-05-17 como Opção C (Híbrido progressivo)**. Hermes-Nous ganhou caso de uso adicional como **nível 4 da cascata de scraping** (ver §8.3.1 deste PRD). Pré-requisito: F1+F2 deste PRD.
- ~~P16 (OPENROUTER_API_KEY em llm_models vs env)~~ — **REMOVIDA**: coberta pela Fase A.3 do ADR (`_GEMINI_PRO_COST_PER_TOKEN` → `llm_models` versionado). TODA key/model/cost vem de `llm_models` por regra de ouro #2 (NO HARDCODE). Não vira pendência — vira **correção bloqueante deste PRD** (ver §11.1 abaixo).

### 11.1 Violações da Regra de Ouro #2 (NO HARDCODE) no próprio PRD

Re-varredura à luz de [[metadata-driven-no-hardcode]] revelou 7 violações em `.env.example` (§6.2) e entrypoint (§6.1). Todas têm tabela espelho. **Bloqueantes pra F1** — sem correção, PRD viola o pilar arquitetural do projeto.

| # | Hardcode atual no PRD | Tabela espelho que deveria ser fonte | Fix proposto |
|---|---|---|---|
| H1 | `HERMES_INFERENCE_PROVIDER=openrouter` em `.env` | `adapter_catalog` (10 rows com slugs: `claude_code`, `codex`, `gemini`, `huggingface`, `mcp-github`, `mcp-gmail`, `mcp-imap`, `mcp-slack`, `meta-whatsapp`, `ollama` — verificado via SQL 2026-05-17; auditoria anterior listou erradamente os **providers** em vez dos **slugs**) | Seed row `adapter_catalog` slug=`nous-hermes` (kebab-case consistente com convenção atual) com provider=`nous_research` no `provider` column; runtime lê do DB no boot |
| H2 | `HERMES_INFERENCE_MODEL=nousresearch/hermes-4-405b` em `.env` | `llm_models` (versionado, gerenciado por `AdminModels.tsx`) | Seed rows `llm_models` pra hermes-4 / nomos / psyche (PRD §8.2 já planeja — F1 antecipa o seed pra usar desde o início) |
| H3 | `HERMES_APPROVAL_MODE=smart` em `.env` | `agent_adapter_configs.field_values_json.approval_mode` (pattern existente em `src/managed_agents/CLAUDE.md`) | Campo configurável por adapter/specialty na UI |
| H4 | `HERMES_MAX_TURNS=90` em `.env` | `agent_specialty_configs.field_values_json.max_turns` (pattern existente — `OllamaAgentClient` lê config dict) | Campo configurável por specialty |
| H5 | `OPENROUTER_API_KEY=` em `.env` (todos os daemons leem do env) | `agent_adapter_configs.field_values_json.api_key` (pattern existente do adapter) | Key vive no adapter config (per-company); container runtime herda via injection no startup, não hardcode |
| H6 | `NOUS_HERMES_ENABLED=false` em `.env` | `adapter_catalog.is_active` (per-company) | Toggle UI em `AdminConnectors.tsx` (consistente com pattern atual de habilitar/desabilitar adapters) |
| H7 | `entrypoint.sh` faz `hermes config set X=$ENV_VAR` em série (§6.1) | Wrapper.py carrega do DB no startup | `wrapper.py` ganha função `bootstrap_config()` que faz SELECT em `adapter_catalog` JOIN `llm_models` pra company ativa, monta config do hermes-cli antes de servir |

**Único env-var legítimo (não viola NO HARDCODE):**
- `NOUS_HERMES_RUNTIME_URL=http://nous-hermes-runtime:9120` — endereço de infraestrutura (service discovery), não config de produto. Aceito.

**Impacto da correção:**
- F1 deixa de ser "endpoint atrás de env flag" e vira "adapter configurável via UI" — alinha com D13 do ADR (UI é fonte) e §6.4 (UI mínima)
- Mudar modelo de hermes-4 pra nomos vira UPDATE em `llm_models` + select na UI, não edit de `.env` + restart container
- Multi-tenant pós-D (P6) fica trivial — cada company tem seu próprio adapter config

**NH-D5 reescrita necessária:** "Deploy: Docker compose local + adapter config persistido em `adapter_catalog` (per-company); container runtime carrega config do DB no boot via wrapper.py."

---

## 12. Glossário

- **CMA (Continuous Managed Agent):** abstração do VectraClaw que executa tasks via SDK do provider (vs daemon nativo). Ver `src/managed_agents/CLAUDE.md`
- **Specialty:** unidade de configuração que define como uma task é executada (prompt template + provider + model + thinking budget). Ver `agent_specialties` table
- **AgentAdapterType:** texto livre desde VEC-319 — provider name (ex: `anthropic`, `nous_hermes`)
- **`hermes -z`:** modo headless do Hermes CLI — retorna só o texto final, sem UI

---

## 13. Anexos

- Plano de execução interno: `~/.claude/plans/graceful-sparking-flamingo.md`
- Documentação Hermes-Nous: https://hermes-agent.nousresearch.com/docs
- CLI Reference: https://hermes-agent.nousresearch.com/docs/reference/cli-commands
- Security model: https://hermes-agent.nousresearch.com/docs/user-guide/security
