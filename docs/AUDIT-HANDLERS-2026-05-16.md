# Auditoria de Handlers — Bottom-up (2026-05-16)

> **Objetivo:** mapear do nível mais baixo (governance) ao mais alto (estratégia) **o que cada handler executa, o que entrega, e com quem conversa**. Insumo: 4 esquadrões Explore em paralelo, um por camada.
>
> **Camadas:** 1 Governance → 2 Admin → 3 Comercial/Operações → 4 Estratégia.

---

## Sumário executivo (4 camadas)

| Camada | Componentes | Status médio | Bloqueio crítico |
|---|---|---|---|
| **1 — Governance** | Approvals, RBAC, RACI, Risks PMBOK, Audit log | ~40% (modelado, **subutilizado**) | Audit_log nunca alimentado; risks/raci com 0 rows; nenhum dispara workflow downstream |
| **2 — Admin** | Companies, App Users, Agents catalog, Specialties+Configs, Adapters+Fields, LLM Models, Domains, Execution Modes, Secrets | ~85% (funcional) | RLS grant faltante em `app_users` (service_role bypass); execution_mode cache sem fallback se stale |
| **3 — Comercial/Operações** | Prospects, Mercator, Hodos, Plutus, Hermes, HermesReporter, Kronos | Misto (Kronos 100%, Hermes 95%, Mercator/Plutus/Hodos 0%) | `route-cost-calculation` EXCLUDED em Morpheus; 3 handlers (Mercator/Plutus/Hodos) ainda em especificação; SMTP bloqueado por Cloudflare WARP |
| **4 — Estratégia** | Morpheus, Oracle (6 ops), Mnemos, Athena (9 ops), Daedalus (1 op) | ~70% (R1 Gemini 403 paralisa LLM) | 7 handlers Athena bloqueados; Oracle research idem; **Mnemos + Daedalus funcionam** (fallback) |

### Bug novo descoberto durante auditoria (2026-05-16 ~23h)

**POST `/api/sipoc/components`** rejeita payload com `processId` (camelCase). O helper `_normalize_sipoc_payload_to_snake` cobre 17 keys mas **esqueceu `processId → process_id`**, então payload do frontend cai em "process_id obrigatório". Workaround atual: mandar snake_case direto. Fix em `src/api.py` no dict do normalizer — vai sair em PR separado deste audit.

---

## Tabela cross-camadas — quem fala com quem

| Origem | Operation/Endpoint | Destino | Camada → Camada |
|---|---|---|---|
| Routine cron Kronos | `planner-import-ofx` | TaskFactory → 5 fases → `oracle-report` | 3 → 3 → 4 |
| Hermes IMAP polling | `email_lead` | Plutus `crm-fill` (TODO) ou Oracle `oracle-research` | 3 → 3 → 4 |
| Mercator (TODO) | `freight-quotation` | Hodos `route-cost-calculation` (EXCLUDED!) | 3 → 3 |
| UI `/sipoc/diagnose` | `athena-diagnose` (athena_recommendations.kind='diagnose_gap') | UI `/agents/recommendations` (⏸️ intentional broken) | 4 → 1 → UI |
| `athena-risk-register` | INSERT `risks` com `detected_by_athena=true` | UI Risk Matrix (não construída) + athena-recommend downstream | 4 → 1 → 4 |
| `athena-recommend` | INSERT `athena_recommendations` (kind=hire/add_specialty/rewrite) | UI approval → ❌ executor real **não existe** | 4 → 1 → ✋ manual |
| `athena-audit` | scorecards agents + recommendations | `athena-recommend` para applying | 4 → 4 |
| Athena recommendation `hire_agent` approved | trigger `_auto_create_agent_from_approval` | INSERT `agents` | 1 → 2 |
| Oracle SSE chat | SIPOC state machine (in-memory) | UI `/sipoc/wizard` | 4 → UI |
| UI hire agent | `POST /companies/{cid}/agents` atomic | INSERT agents + adapter_config + specialty_config (cascade) | 2 → 2 |
| Mnemos `rag-ingest` | `rag_chunks` populated | Oracle `oracle-rag` queries | 4 → 4 |
| Athena `athena-rag-ingest` | `athena_chunks` populated | Athena handlers (classify/charter/risk-register) RAG context | 4 → 4 |

---

## Camada 1 — Governance

### Resumo
- **5 componentes:** Approvals/Council, RBAC, RACI matrix, Risks PMBOK (G1), Audit log
- **Status:** 🟡 Parcial — governance **modelada mas subutilizada**: tabelas criadas (PR #142–151), endpoints funcionais, **mas zero dados operacionais** (approvals=0, raci=0, risks=0)

### 1.1 Approvals / Council
- **Handler:** `src/api.py:7280–7375` (endpoints `/api/approvals`, `/approve`, `/reject`)
- **Executa:** valida status transition (pending → approved/rejected), UPDATE, side-effect especial para `request_type='hire_agent'` (trigger `_auto_create_agent_from_approval` cria row em `agents`)
- **Entrega:** response JSON; ❌ **sem WS broadcast**; ❌ **sem audit log**
- **Conversa com:** UI `/council`; downstream apenas `hire_agent` tem consumer
- **Tabelas:** READ `approvals`, `agents`; WRITE `approvals.status`; INSERT `agents` (somente hire_agent)
- **Estado:** ⏸️ esqueleto funcional, sem fluxo real (0 rows em prod)

### 1.2 RBAC / Roles
- **Handler:** `src/api.py:352–433` (`get_user_scope`, `require_role_not`, `assert_activity_in_scope`)
- **Executa:** extrai JWT claims, lookup `app_users.assigned_position_id` para sector_responsible, bloqueia ações por role
- **Entrega:** scope dict ou HTTPException 403
- **Conversa com:** middleware em **todos endpoints**; RLS policies em todas tabelas SIPOC/risks/RACI
- **Tabelas:** READ `app_users`
- **Estado:** ✅ funcional. **Gap:** roles hardcoded em fonte (não há tabela `roles_catalog` → impossível CRUD via UI)

### 1.3 RACI matrix
- **Handler:** `src/api.py:1513–1630`
- **Executa:** UPSERT (process_id, component_id, position_id, role) com CHECK `role IN ('R','A','C','I')`
- **Entrega:** GET retorna `{matrix, stats}` — `stats` vem de `calculate_raci_stats()` (`src/services/sipoc_raci.py`) com 3 indicadores: `overloaded_positions`, `missing_accountable`, `multiple_accountable`. ❌ **sem WS broadcast**
- **Conversa com:** UI SIPOC builder (não persiste hoje → 0 rows). Service `calculate_raci_stats` é chamado dentro do GET `/raci` (correção 2026-05-16 G1.3)
- **Tabelas:** WRITE `sipoc_raci`; READ `sipoc_processes`, `sipoc_components`, `sipoc_positions`
- **Estado:** 🟡 backend pronto + stats já expostos, **UI não persiste matriz nem consome stats**

### 1.4 Risks PMBOK (G1)
- **Handler:** `src/api.py:1663–1968` (REST CRUD) + `src/agents/athena.py:1090` (`athena-risk-register`)
- **Executa:** valida categoria/probabilidade/impacto/strategy; persiste com `risk_score = probability × impact` (GENERATED); Athena handler insere bulk com `detected_by_athena=true`
- **Entrega:** response JSON com snake/camel; output_json Athena tem citations RAG
- **Conversa com:** REST → UI Risk Matrix (não construída); Athena → INSERT `risks` + `athena_recommendations(kind=diagnose_gap)`
- **Tabelas:** WRITE `risks`; READ `goals,workflow_definitions,sipoc_processes,sipoc_components,athena_recommendations,athena_chunks`
- **Estado:** 🟡 tabela criada (0 rows em prod); workflow lifecycle `status` nunca passa de `identified` (não há "review step")

### 1.5 Audit log
- **Handler:** `src/api.py:3868–3887` (apenas GET)
- **Executa:** SELECT últimos 100 entries
- **Entrega:** lista AuditLogEntry
- **Conversa com:** ❌ **ZERO INSERTs no código** — tabela criada mas nunca alimentada. Helper `generate_audit_log()` existe em `sipoc_approvals.py` mas nunca chamado
- **Estado:** ❌ esqueleto. Compliance gap real (mudanças críticas não auditadas)

### Gaps consolidados Camada 1

| Item | Sev |
|---|---|
| Zero dados operacionais (approvals/raci/risks/audit_log) | 🔴 ALTA |
| Approvals sem audit trail | 🟡 MÉDIA |
| Risks criam mas não fluem (status fixo `identified`) | 🟡 MÉDIA |
| RBAC hardcoded (sem CRUD UI) | 🟠 BAIXA |
| Audit log nunca alimentado | 🔴 ALTA |
| ~~RACI analysis service existe mas sem endpoint~~ | ✅ INVALIDADO PR #171 (endpoint já chama `calculate_raci_stats` em `api.py:1528`) |
| WS broadcast ausente em todos endpoints da camada | 🟠 INFO |

---

## Camada 2 — Admin

### Resumo
- **9 dominios:** Companies, App Users, Agents catalog, Specialties+Configs, Adapter catalog+Fields+Configs, LLM Models, Agent Domains, Agent Execution Modes, Secrets
- **Status:** ~85% funcional. Catálogos catalog-driven (caches TTL), upserts com composite keys, response camelCase via `.to_zod_dict()`

### 2.1 Companies / Tenants
- **Handler:** `src/api.py:3020–3100` (GET/PATCH)
- **Executa:** valida cross_tenant; atualiza `name, subscription_plan, settings_json`
- **Entrega:** JSON camelCase; WS broadcast `company_settings_updated` via `broadcast_company()`
- **Tabelas:** `companies` (R/U)
- **Estado:** ✅ RBAC aplicado

### 2.2 App Users
- **Handler:** `src/api_routes/admin.py:179–280`
- **Executa:** PATCH atualiza role + assigned_position_id (FK `sipoc_positions`); validação de `_VALID_ROLES`
- **Entrega:** JSON camelCase via `_user_to_dict()`; **sem broadcast**
- **Conversa com:** Auth Supabase; SIPOC organograma; Frontend admin
- **Tabelas:** R/U `app_users`; R `sipoc_positions`
- **Estado:** ⚠️ **CRÍTICO** — service_role bypass no PATCH (linha 240) porque RLS GRANT em `app_users` ausente pra `authenticated`. Documentado em PR #137 hotfix mas não 100% resolvido

### 2.3 Agents catalog
- **Handler:** `src/api.py:3121–3171`
- **Executa:** POST cria Agent com enum normalization adapter_type (`claude_code|codex|shell|webhook → claude_code|cursor|bot|bot`)
- **Entrega:** Agent camelCase
- **Conversa com:** UI dashboard; daemon polling; FK `tasks.assigned_to_agent_id`
- **Estado:** ✅ atomic insert; sem broadcast explícito

### 2.4 Agent Specialties + Configs
- **Handler:** `src/api.py:5870–6120`
- **Executa:** UPSERT (agent_id, specialty_id) composite key + values JSONB
- **Entrega:** defensive empty array em vez de 404
- **Estado:** ✅ funcional

### 2.5 Adapter Catalog + Fields + Configs
- **Handler:** `src/api.py:4220–4433`
- **Executa:** CRUD catálogos (slug, displayName, provider, isActive) + fields com Literal hardcoded `field_type` (P1 violação — A10 do AUDIT-CONSOLIDADO)
- **Estado:** ⚠️ field_type Literal não vem de catalog

### 2.6 LLM Models
- **Handler:** `src/api.py:7821–7873`
- **Executa:** PK composta `(id, effective_from)` permite versionamento de preço
- **Caching:** `_refresh_llm_price_cache()` TTL 24h
- **Estado:** ✅ effective dating

### 2.7 Agent Domains
- **Handler:** GET catálogo (`/api/agent-domains`); POST não claro
- **Estado:** ⚠️ catálogo read-only assumido; sem handler POST/PATCH visível

### 2.8 Agent Execution Modes
- **Handler:** `src/api.py:5728–5867`
- **Executa:** catalog-driven (PR #146); validator UPPER + `_load_execution_mode_ids()` cache 60s; fallback default = REALTIME se row missing
- **Estado:** ⚠️ P1 — fallback silencioso sem log warning se cache stale

### 2.9 Secrets
- **Handler:** `src/api.py:5661–5719`
- **Executa:** UPSERT via RPC `upsert_company_secret`; **values NUNCA expostos em response**
- **Estado:** ✅ abstração Vault encapsulada

### Mapa dependências Camada 2
```
Company (tenant isolation)
  ├─> app_users (assigned_position_id → sipoc_positions)
  ├─> agents (adapter_type → adapter_catalog; domain_id → agent_domains)
  │   ├─> agent_specialty_configs (specialty_id → agent_specialties)
  │   ├─> agent_adapter_configs (adapter_id → adapter_catalog)
  │   ├─> agent_execution_configs (execution_mode → agent_execution_modes)
  │   └─> company_secrets (authSecretRef backref)
```

### Gaps consolidados Camada 2

| Sev | Onde | Issue | Status |
|---|---|---|---|
| 🔴 P0 | app_users PATCH | service_role bypass; RLS GRANT incompleto | ✅ **RESOLVED** PR #168 (G2.1) — escopo expandido pra companies + llm_models |
| 🟡 P1 | execution-config validator | fallback silencioso sem warning se cache 60s stale | ✅ **RESOLVED** PR #168 (G2.2) — log INFO/WARNING explícito |
| 🟡 P1 | adapter_field_definitions field_type | Literal hardcoded (deveria FK catalog) | ✅ **DECIDED — não é gap (P6)**. Cada tipo vira componente React diferente; adicionar tipo = code change inevitável. CODE-PATTERNS P6 atualizado |
| 🟠 P2 | agent_domains | sem CRUD visível | ✅ **ACCEPTED — workaround SQL é o pattern correto**. Domains são vocabulário curado (Logistics/Finance/etc.) — criar via UI sem alinhar com produto = risco de explosão de domains paralelos |
| 🟠 P2 | secrets vault backend | rotation/encryption não auditados | 📋 **ADR criado** — `docs/ADR-VEC-VAULT-AUDIT.md` com checklist compliance; auditoria efetiva agendada |

---

## Camada 3 — Comercial e Operações

### Resumo
- **7 agentes tenant:** Prospects (via SipocResearcher service), Mercator, Hodos, Plutus, Hermes, HermesReporter, Kronos
- **Estado:** Kronos 100% (pivot VEC-416), Hermes 95%, HermesReporter 100%, **Mercator/Plutus/Hodos 0%** (em ARCHITECTURE-TO-BE.md P2)

### 3.1 Prospects + Research
- **Componentes:** `src/api_routes/prospects.py` + `src/agents/sipoc_researcher.py` (não é agente, é service sem AGENT_ID)
- **Endpoints:** `GET/POST /api/companies/{cid}/prospects`, `POST .../research`, `POST /qualify`, `POST /lookup-cnpj`
- **Executa:** Research dispatch cria task `oracle-research`; CNPJ lookup via BrasilAPI; enrichment LinkedIn/Instagram via Playwright opcional
- **Tabelas:** `prospect_profiles`, `research_templates`, `tasks`
- **Estado:** ✅ funcional

### 3.2 Mercator (`freight-quotation`, `freight-quotation-approval`)
- **AGENT_ID:** `c7de1b0f-7c74-42f1-9de4-7210349e668e`
- **Status:** **TODO** — handler `src/agents/mercator.py` NÃO existe ainda. Em ARCHITECTURE-TO-BE.md P2
- **Esperado:** receber briefing → consultar veículos → sugerir + criar task de aprovação humana → enviar pra Hodos

### 3.3 Hodos (`route-cost-calculation`) ⚠️ EXCLUDED
- **AGENT_ID:** `0d6e56cc-28b6-4382-96cd-1952b890d412`
- **Status:** **TODO** + **EXCLUDED em `morpheus_dispatcher.py:18-22`** (`MORPHEUS_EXCLUDED_TYPES`)
- **Razão:** "tipos que Morpheus jamais deve disparar como predecessores; têm próprio orquestrador". Quebrado em transição
- **Esperado:** receber vehicle + rota → QUALP API → distance/duration/tolls
- **Ação necessária:** implementar handler + remover do EXCLUDED após validar

### 3.4 Plutus (`crm-fill*`)
- **AGENT_ID:** `80fd6d0e-53ab-4638-b6e9-05cbbd121092`
- **Status:** **TODO**. AGENT_ID definido, handler não existe
- **Esperado:** Pipedrive/HubSpot/custom CRM API; recebe prospect → cria/atualiza CRM record

### 3.5 Hermes (IMAP polling + `email_lead`)
- **AGENT_ID:** `59b7a69e-cc53-4063-85f9-5dcc5619ac96`
- **Split em 3 papéis:**
  - Daemon polling IMAP em `src/api.py` (scheduler contínuo)
  - `src/services/hermes_imap.py` (wrapper puro)
  - `src/services/hermes_smtp.py` (wrapper puro)
- **Executa:** conecta IMAP via `agent_adapter_configs` (`_resolve_imap_field`), busca inbox, cria task `email_lead`
- **Estado:** 🟡 **95%** — polling OK, side-effects OK, **`email_lead` handler não localizado** (handoff downstream pra Plutus não implementado)
- **Risco:** memory `project_hermes_pipeline_fix.md` — Cloudflare WARP bloqueia GoDaddy SMTP

### 3.6 HermesReporter (`oracle-report`)
- **AGENT_ID:** `360a96cb-b1c3-4b65-b9fa-2b9cbb59dac1`
- **Handler:** `src/agents/hermes_reporter.py`
- **Executa:** parse `task.description` (RECIPIENT/SUBJECT/PARENT_TASK_ID + markdown body) → converte markdown→HTML CSS-inline → SMTP TLS
- **Conversa com:** Kronos pipeline final + Oracle research summary + qualquer agente que precisa reportar
- **Estado:** ✅ funcional; **risco WARP SMTP**

### 3.7 Kronos — Pipeline 5 fases + Pivot VEC-416
- **AGENT_ID:** `9c8d7e6f-5a4b-4321-9876-543210fedcba`
- **Arquivos:** `kronos.py, kronos_scrape.py, kronos_apply.py, kronos_categorizer.py, kronos_planner.py, kronos_audit.py, kronos_browser.py, kronos_pdf_enricher.py, kronos_apply_corrections.py`
- **Pipeline visual:**
```
[Routine cron]
   → scrape-backlog (Playwright login → pending entries)
   → planner-import-ofx (read OFX + normalize)
   → planner-categorize-pendings (match YAML rules + flag anomalies)
   → kronos-audit-historico (cross 3 sources, output_json com suggestions)
   → audit-review (status=review, HUMAN APPROVAL GATE)
   → planner-apply-corrections (Playwright clique)
   → oracle-report (cria task pra HermesReporter)
   → email
```
- **Workflow Factory:** TaskFactory.materialize_workflow cria DAG a partir de `workflow_definition`
- **Cursor OFX:** `routines.metadata.lastProcessedOfx` previne reprocessing
- **Estado:** ✅ **100% + pivot VEC-416 em curso**

### Mapa pipeline visual Camada 3

```
Hermes IMAP → email_lead → Plutus CRM (TODO) → Oracle follow-up
Frontend → freight-quotation → Mercator (TODO) → route-cost-calculation → Hodos (EXCLUDED!)
Routine cron → Kronos 5 fases → oracle-report → HermesReporter → SMTP → Email
Oracle research → oracle-report → HermesReporter → Email
```

### Gaps consolidados Camada 3

| Item | Sev | Onde |
|---|---|---|
| `route-cost-calculation` EXCLUDED | 🔴 ALTA | morpheus_dispatcher.py:18-22 |
| Mercator/Plutus/Hodos handlers missing | 🟡 MÉDIA | src/agents/ (TODO P2) |
| `email_lead` handler não localizado | 🟡 MÉDIA | Hermes downstream |
| Cloudflare WARP bloqueia SMTP | 🔴 ALTA | HermesReporter |
| heartbeats sem retention TTL | 🟡 MÉDIA | 14k/h → 125M/ano |
| Routines table vazia | 🟡 MÉDIA | Kronos pivot começa a popular |

---

## Camada 4 — Estratégia e Inteligência

### Resumo
- **5 agentes core:** Morpheus, Oracle (6 ops), Mnemos, Athena (9 handlers), Daedalus
- **18+ operation_types:** 9 Athena + 6 Oracle + 1 Mnemos + 1 Daedalus + 1 Morpheus
- **Tabelas-chave:** `goals, athena_recommendations, risks (PR #151), bpmn_diagrams (PR #159), athena_documents/chunks`
- **Estado crítico:** R1 Gemini 403 bloqueia **7 handlers Athena + 1 Oracle**. Mnemos + Daedalus funcionais (fallbacks)

### 4.1 Morpheus (`orchestration`)
- **AGENT_ID:** `00000000-0000-0000-0000-000000000001`
- **Handler:** `src/agent_daemon.py` (dispatcher passivo, sem LLM call)
- **EXCLUDED_TYPES:** `workflow-orchestrator, followup-dispatcher, route-cost-calculation` (este último = bug Hodos)
- **Estado:** ✅ funcional; **sem bloqueio R1**

### 4.2 Oracle (6 handlers)
- **AGENT_ID:** `00000000-0000-0000-0000-000000000002`
- **Arquivos:** `oracle.py, oracle_maker.py, oracle_checker.py, oracle_runner.py`

| Op type | Pipeline | Saída | Bloqueado R1? |
|---|---|---|---|
| `oracle-extract` | Gemini extract → JSON struct | envelope I/T/O | ⚠️ sim (LLM) |
| `oracle-summarize` | Gemini summarize → markdown (default handler) | envelope I/T/O | ⚠️ sim |
| `oracle-rag` | vector search `rag_chunks` → top-K + citations | envelope I/T/O | ❌ não |
| `oracle-vision` | Gemini Vision → JSON → markdown | envelope I/T/O | ⚠️ sim |
| `oracle-research` | Gemini research + structured sections + enrich `companies.context_json` + cria `prospect_profiles` | envelope I/T/O | 🔴 **bloqueado** |
| `oracle-report` | (executado por HermesReporter, não por Oracle daemon) | email enviado | ❌ não |

**SIPOC chat SSE (`/api/oracle/chat`):** state machine via langgraph (maker/checker), session **in-memory** (`_OracleSession` em `oracle_session.py`), GC manual `gc_inactive_sessions(max_age_hours=2.0)`. **Restart = perda de sessão ativa.**

### 4.3 Mnemos (`rag-ingest`)
- **AGENT_ID:** `00000000-0000-0000-0000-000000000003`
- **Handler:** `src/agents/mnemos.py:53` `entrypoint(task, supabase, embedder=None)`
- **Pipeline:** load `rag_documents` row → bucket download (`rag-documents/{company_id}/{sha256}.{ext}`) → extract text (pdfplumber + ocr) → chunk (RecursiveCharacterTextSplitter 1200/200) → **FallbackEmbedder** (OpenAI `text-embedding-3-small` 1536 dim, fallback Gemini `gemini-embedding-001` se 429/401) → bulk insert `rag_chunks` (trigger `sync_chunk_company_id` valida) → status='indexed'
- **Estado:** ✅ **funcional** (embedding fallback mitiga R1)

### 4.4 Athena — 9 handlers (`_SPECIALTY_DISPATCH` em `athena.py:3432`)

| # | Handler | Pipeline curto | Persiste em | Bloqueado R1? |
|---|---|---|---|---|
| 1 | `athena-classify` (VEC-388) | goal → RAG Heldman → Gemini struct → `goals.kind/confidence/business_case_strength` | goals (UPDATE) | 🔴 sim |
| 2 | `athena-charter` (VEC-388) | pré-req kind=project+conf≥0.7 → Gemini Charter PMBOK → `goals.charter_json` | goals | 🔴 sim |
| 3 | `athena-stakeholder-map` | charter context → Gemini stakeholders + RACI | `goals.stakeholders_json` ou tabela `stakeholder_maps` | 🔴 sim |
| 4 | `athena-risk-register` (PR #151) | charter context → Gemini RBS → ⭐ **PERSISTE `risks` + `athena_recommendations(kind=diagnose_gap)`** | risks, athena_recommendations | 🔴 sim |
| 5 | `athena-evm` | **Python calcula PV/EV/AC/CPI/SPI/EAC** (determinístico) → Gemini só narra | `goals.evm_metrics` | ⚠️ parcial (Python OK, narração bloqueada) |
| 6 | `athena-rag-ingest` (VEC-394) | espelho Mnemos pra corpus próprio | `athena_documents`, `athena_chunks` | ❌ não (embedding fallback) |
| 7 | `athena-audit` (VEC-389) | scores agents → Gemini scorecards → INSERT `athena_recommendations` | athena_recommendations | 🔴 sim |
| 8 | `athena-recommend` (VEC-408) | guardrails (target != Athena/system) → idempotência → Gemini → INSERT `athena_recommendations(pending)` | athena_recommendations | 🔴 sim |
| 9 | `athena-prioritize` (VEC-390) | Gemini scoring → Python weighted → UPDATE `goals.priority_rank` | goals | 🔴 sim |

**Ciclo `athena-recommend` → aplicado:**
1. Athena gera recomendação (status='pending')
2. UI mostra em `/agents/recommendations` (⚠️ **B7-bis broken intencionalmente**)
3. Human aprova → status='approved'
4. POST `/mark-applied` → status='applied'
5. ✋ **Executor real NÃO EXISTE** — humano copia `proposed_changes_json` à mão pra `/agents/{id}/edit`

### 4.5 Daedalus (`bpmn-generate`)
- **AGENT_ID:** `d4ed4145-0000-4000-8000-000000000005`
- **Handler:** `src/agents/daedalus.py` (PR #159)
- **Pipeline fallback estatístico:** input source_type ∈ {sipoc_process, freeform} → gera diagrama LINEAR (start → user_task[] → end) → persiste em `bpmn_diagrams` com `generated_by='daedalus'`
- **Layout:** horizontal hardcoded; frontend pode reaplicar dagre
- **Estado:** ✅ **funcional via fallback**; LLM branch deferred (futuro)

### Mapa Estratégia (com R1 bloqueio)

```
Goal created
  ↓
athena-classify [🔴 R1]
  ↓
athena-charter [🔴 R1]
  ├─→ athena-stakeholder-map [🔴 R1]
  ├─→ athena-risk-register [🔴 R1] → risks + recommendations(diagnose_gap)
  └─→ daedalus bpmn-generate [✅ fallback]

Paralelo:
  athena-audit [🔴 R1] → recommendations(add_specialty, rewrite_prompt, etc.)
    ↓ human approves
    ↓ executor real NOT IMPL
  athena-evm [⚠️ parcial — Python OK, Gemini narra]
  athena-prioritize [🔴 R1]

Corpora RAG:
  athena-rag-ingest [✅] → athena_documents/chunks → handlers acima
  Mnemos rag-ingest [✅] → rag_documents/chunks → oracle-rag
```

### Gaps consolidados Camada 4

| Item | Sev | Onde |
|---|---|---|
| R1 Gemini 403 paralisa 7 Athena + 1 Oracle | 🔴 CRÍTICA | global |
| Executor `athena-recommend` não existe (broken window intencional) | ⏸️ INTENTIONAL | AUDIT-CONSOLIDADO §B7-bis |
| Oracle SIPOC session não persiste (restart=perda) | 🟠 MÉDIA | oracle_session.py |
| `ATHENA_DEFAULT_MODEL` hardcoded `gemini-2.5-flash` | 🟢 BAIXA | athena.py:37 / gemini_client.py:12 |
| RAG embedding fallback não testado end-to-end | 🟡 MÉDIA | mnemos.py, athena_rag.py |
| Risk Register `_persist_athena_risks` sem upsert (duplicatas possíveis) | 🟡 MÉDIA | athena.py:1381 |

---

## Riscos transversais consolidados (top 10)

| # | Risco | Sev | Camada | Bloqueio? |
|---|---|---|---|---|
| 1 | **R1 Gemini 403** paralisa Camada 4 LLM | 🔴 CRÍTICA | 4 | Sim, dependência externa Google Cloud |
| 2 | `route-cost-calculation` EXCLUDED em Morpheus → Hodos não roda | 🔴 ALTA | 3 | Sim, código próprio |
| 3 | RLS GRANT incompleto em `app_users` (service_role bypass) | 🔴 P0 | 2 | Sim, parcial PR #137 |
| 4 | Audit log nunca alimentado (compliance gap) | 🔴 ALTA | 1 | Helper existe, não chamado |
| 5 | Cloudflare WARP bloqueia GoDaddy SMTP | 🔴 ALTA | 3 | Infra externa |
| 6 | Executor `athena-recommend` não existe (intentional broken) | ⏸️ INTENTIONAL | 4 | Decisão produto |
| 7 | Mercator/Plutus/Hodos handlers TODO (em TO-BE P2) | 🟡 MÉDIA | 3 | Roadmap |
| 8 | `email_lead` handler não localizado | 🟡 MÉDIA | 3 | Pipeline Hermes incompleto |
| 9 | Heartbeats sem retention (125M rows/ano projetado) | 🟡 MÉDIA | 3 | Escala futura |
| 10 | **NEW — POST `/sipoc/components` rejeita `processId`** | 🟡 MÉDIA | 2 | Workaround snake_case; fix trivial pendente |

### Bug NEW reportado durante a auditoria (2026-05-16 ~23h)

**Onde:** `POST /api/sipoc/components` em `src/api.py`

**Sintoma:** payload com `processId` (camelCase) rejeitado; activities falham mesmo com sector+process criados OK. Workaround: mandar `process_id` (snake_case).

**Causa:** `_normalize_sipoc_payload_to_snake` (criado no PR #146 com 17 keys mapeadas — `companyId, sectorId, reportsToId, automationStatus, suggestedOperationType, responsiblePositionId, diagnosticMetadata, validationStatus, validationNotes, parentSectorId, executionMode, etc.`) **NÃO inclui `processId → process_id`**. Endpoint `POST /sipoc/components` consome `process_id` direto e cai em validação obrigatória.

**Fix:** adicionar 1 entry no dict do helper. Vai sair em PR cirúrgico imediatamente após este merge.

**Lição:** quando o normalizer foi criado, foram cobertas as keys conhecidas naquele momento (FE-A/B do Lote 1). `processId` é usado em endpoint diferente do que estava sendo testado. **A próxima vez que alguém estender este helper, deveria fazer `grep "_normalize_sipoc_payload_to_snake" + cross-check com todos endpoints `/api/sipoc/*` que recebem payload**. Vou adicionar isso no comentário do helper no PR de fix.

---

## Próximos movimentos sugeridos (ordem PMO)

1. **Hotfix `processId` no normalizer** (5min, vai sair logo após este merge)
2. **Resolver R1 Gemini 403** (você no Google Cloud Console) — destrava 70% da Camada 4
3. **Lote 2 Frontend** continua em andamento por outra sessão (FE-A #24, FE-B #25 merged, FE-C `feat/sipoc-raci-matrix-pmbok` ativo)
4. **Decisão produto:** executor `athena-recommend` real (destrava B7-bis intentional + completa ciclo PMBOK)
5. **Decisão produto:** Mercator/Plutus/Hodos handlers (P2 fase 2 da TO-BE)
6. **Compliance:** alimentar `audit_log` em endpoints críticos (mudança role, hire agent, approval, risk created)
