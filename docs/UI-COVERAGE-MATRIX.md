# UI Coverage Matrix — o que ainda precisa de CLI/SQL para o MVP

> **Objetivo:** mapear cada mutação (POST/PATCH/PUT/DELETE) do backend contra a UI atual.
> Identificar **fluxos que ainda exigem CLI/SQL/Postman** — esses são os gaps a fechar pro MVP P1 vendável **100% UI-first**.

---

## TL;DR — 4 lacunas críticas

🔴 Fluxos vitais que **só funcionam via CLI/SQL hoje**:
1. **Criar component SIPOC standalone** (sem template) — Gap 3 do dogfood
2. **Criar/editar/deletar `sipoc_sectors`** — só GET/POST existem; sem PATCH; DELETE recém-criado (PR #144 pendente merge)
3. **Criar/editar/deletar `sipoc_processes`** — idem
4. **Criar/editar/deletar `sipoc_raci`** — endpoints existem, mas **sem componente de UI** ainda

🟡 Configurável mas com UI parcial (precisa hover/scroll/teclado):
- `agent_specialty_configs` — botão Salvar com `opacity-0` (bug reportado)
- `agent_adapter_configs` — UI sem teste real (zero runs há 4 dias)
- `agent_shared_config` — endpoint existe, UI provavelmente parcial
- `workflow_steps` — `suggest-sipoc-element` existe, UI canvas em construção

🟢 Coberto end-to-end via UI (sem CLI):
- Routines, Goals, Projects, Tasks, Prospects, RAG, Athena documents, Companies, app_users

---

## 1. Matriz completa (76 mutações)

### Legenda
- ✅ UI cobre 100% — usuário leigo opera sem CLI
- 🟡 UI parcial — funciona mas com atrito (botão escondido, falta confirm dialog, sem campos)
- ❌ UI ausente — só funciona via CLI/SQL/Postman/curl
- 🔌 UI não-end-user — admin de plataforma (dev tool)

### Auth (3)
| Endpoint | UI? |
|---|---|
| POST /auth/login | ✅ Login page |
| POST /auth/logout | ✅ Botão sair |
| POST /auth/refresh | ✅ Automático no client |

### Companies / Tenant (4)
| Endpoint | UI? | Onde / Gap |
|---|---|---|
| POST /companies | 🔌 | Provisioning admin platform — não precisa de UI no MVP |
| PATCH /companies/{id} | ✅ | CompanySettings |
| DELETE /companies/{id} | 🔌 | Admin platform — não no MVP |
| POST /companies/{cid}/secrets | 🟡 | CompanySettings tem alguns campos; talvez incompleto |

### App Users (1)
| Endpoint | UI? | Onde / Gap |
|---|---|---|
| PATCH /app_users/{id} | ✅ | Org.tsx ManageUsersDialog (PR #16) — atribui role + position_id |

### Agents (10)
| Endpoint | UI? | Onde / Gap |
|---|---|---|
| POST /companies/{cid}/agents | ✅ | HireAgentDialog em /agents |
| PATCH /agents/{id} | ✅ | EditAgentDialog |
| DELETE /agents/{id} | ✅ | KillAgentConfirm |
| POST /agents/{id}/pause | ✅ | Botão pause no card |
| POST /agents/{id}/resume | ✅ | Botão resume |
| POST /agents/{id}/kill | ✅ | KillAgentConfirm |
| POST /agents/{id}/abort-task | ✅ | Botão abort no detail |
| PUT /agents/{id}/adapter-config | 🟡 | /agents/{id}?tab=configuration — bug persist (zero runs há 4 dias confirma) |
| PUT /agents/{id}/specialty-config | 🟡 | /agents/{id}?tab=skills — botão Salvar com `opacity-0` (bug investigado) |
| PUT /agents/{id}/execution-setup | 🟡 | Provavelmente mesmo padrão CSS |
| PUT /agents/{id}/shared-config | ❓ | Verificar — talvez sem UI ainda |

### Agent Specialties + Adapters + LLM Models (catalog NAV ADMIN) (10)
| Endpoint | UI? |
|---|---|
| POST /agent-specialties | ✅ /admin/specialties — CreateAgentSpecialtyDialog |
| PATCH /agent-specialties/{id} | ✅ EditAgentSpecialtyDialog |
| DELETE /agent-specialties/{id} | ✅ DangerConfirm |
| POST /companies/{cid}/adapters | ✅ /admin/connectors — ConnectorFormDialog |
| PUT /adapters/{id} | ✅ ConnectorFormDialog edit mode |
| DELETE /adapters/{id} | ✅ DangerConfirm |
| POST /adapters/{id}/fields | ✅ ManageConnectorFieldsDialog |
| PUT /adapters/fields/{id} | ✅ ManageConnectorFieldsDialog edit |
| DELETE /adapters/fields/{id} | ✅ ManageConnectorFieldsDialog delete |
| POST /llm-models, PATCH, DELETE | ✅ /admin/models |

### Goals + Projects (6)
| Endpoint | UI? |
|---|---|
| POST /companies/{cid}/goals | ✅ /goals New button |
| PATCH /goals/{id} | ✅ GoalDetail edit |
| DELETE /goals/{id} | ✅ DangerConfirm |
| POST /companies/{cid}/projects | ✅ /projects New |
| PATCH /projects/{id} | ✅ ProjectDetail edit |
| DELETE /projects/{id} | ✅ (existe deleteProject hook) |

### Routines (5) — tem mais que projects
| Endpoint | UI? |
|---|---|
| POST /companies/{cid}/routines | ✅ /routines/new |
| PATCH /routines/{id} | ✅ /routines/{id} edit |
| DELETE /routines/{id} | ✅ deleteRoutine hook |
| POST /routines/{id}/run-now | ✅ AgentRoutinesCard Executar |
| POST /routines/{id}/reset-ofx-cursor | ❌ **Sem botão visível** — só CLI |

### Tasks (3)
| Endpoint | UI? |
|---|---|
| POST /companies/{cid}/tasks | ✅ /tasks New + via wizard |
| PATCH /tasks/{id} | ✅ Edit Task dialog |
| DELETE /tasks/{id} | ✅ deleteTask hook |
| POST /tasks/dispatch | ✅ dispatchTask hook |
| POST /tasks/{id}/execute | ✅ Botão Execute |
| POST /companies/{cid}/tasks/from-workflow | ✅ Workflow runner |

### SIPOC (10) — onde dói mais
| Endpoint | UI? | Onde / Gap |
|---|---|---|
| POST /sipoc/sectors | 🟡 | SipocWizard cria, mas SipocManagement não tem edit standalone |
| **PATCH /sipoc/sectors/{id}** | ❌ | **NÃO EXISTE endpoint** — só DELETE (PR #144 ainda aberto). Editar nome do sector = SQL |
| **DELETE /sipoc/sectors/{id}** | 🟡 | Backend pronto (PR #144 aberto), UI sem botão Delete |
| POST /sipoc/processes | 🟡 | SipocWizard cria via auto-flow; sem CRUD standalone na UI |
| **PATCH /sipoc/processes/{id}** | ❌ | **NÃO EXISTE endpoint** |
| **DELETE /sipoc/processes/{id}** | 🟡 | Backend pronto (PR #144), UI sem botão |
| **POST /sipoc/components** (criar activity standalone) | ❌ | **Gap 3 dogfood** — endpoint dedicado não existe |
| **PATCH /sipoc/components/{id}** | ❌ | Idem |
| **DELETE /sipoc/components/{id}** | 🟡 | Backend pronto (PR #144), UI sem botão |
| POST /sipoc/raci (upsert) | ❌ | **Endpoint existe (PR #142), mas sem componente UI matrix** |
| DELETE /sipoc/raci/{comp}/{pos} | ❌ | Idem |
| POST /sipoc/positions | ✅ | Org.tsx CreatePositionDialog |
| PATCH /sipoc/positions/{id} | 🟡 | Org.tsx — **bug Gap 4** ("Reporta a" não persiste, hierarquia não desenha) |
| DELETE /sipoc/positions/{id} | ✅ | Org.tsx (PR #136 implementou) |

### Workflows (6)
| Endpoint | UI? |
|---|---|
| POST /companies/{cid}/workflows | ✅ Workflow canvas |
| DELETE /companies/{cid}/workflows/{slug} | ✅ Workflow canvas delete |
| POST /companies/{cid}/workflows/import | 🟡 Pouco testado |
| POST /companies/{cid}/workflow-steps | 🟡 Canvas em construção (VEC-381) |
| PUT /workflow-steps/{id} | 🟡 Canvas |
| DELETE /workflow-steps/{id} | 🟡 Canvas |
| POST /workflow-steps/suggest-sipoc-element | 🟡 Provavelmente sem botão UI direto |

### Athena / RAG (8)
| Endpoint | UI? |
|---|---|
| POST /companies/{cid}/athena/upload | ✅ AthenaDocuments upload |
| POST /companies/{cid}/athena/query | ✅ Query page |
| DELETE /athena/documents/{id} | ✅ Delete button |
| POST /companies/{cid}/rag/upload | ✅ KnowledgeBase upload |
| POST /companies/{cid}/rag/query | ✅ Query |
| DELETE /rag/documents/{id} | ✅ |
| PATCH /athena/recommendations/{id} | ✅ /agents/recommendations approve/reject |
| POST /athena/recommendations/{id}/mark-applied | ✅ Idem |
| POST /sipoc/diagnose/{sector_id} | ❌ **Sem botão "Gerar diagnóstico"** na UI (endpoint PR #139, frontend PR #18 só mostra diagnose pre-existente) |
| GET /sipoc/diagnose/{sector_id}/pdf | ❌ **Sem botão "Exportar PDF"** (endpoint PR #140) |

### Approvals (2)
| Endpoint | UI? |
|---|---|
| POST /approvals/{id}/approve | ❓ /council page provavelmente — não testado |
| POST /approvals/{id}/reject | ❓ Idem |

### Hermes Whitelist (3)
| Endpoint | UI? |
|---|---|
| POST /companies/{cid}/hermes/whitelist | ❓ Pode estar em CompanySettings |
| PATCH /companies/{cid}/hermes/whitelist/{id} | ❓ |
| DELETE /companies/{cid}/hermes/whitelist/{id} | ❓ |

### Prospects (3)
| Endpoint | UI? |
|---|---|
| POST /companies/{cid}/prospects | ✅ Prospects page |
| PATCH /prospects/{id} | ✅ |
| DELETE /prospects/{id} | ✅ |
| POST /companies/{cid}/prospects/{id}/research | ✅ Research button |
| POST /companies/{cid}/prospects/{id}/research/cancel | ✅ Cancel button |
| POST /companies/{cid}/lookup-cnpj | ✅ |
| POST /companies/{cid}/qualify | ✅ |

### Research Templates (3)
| Endpoint | UI? |
|---|---|
| POST /companies/{cid}/research-templates | ✅ /research-templates |
| PATCH .../{id} | ✅ |
| DELETE .../{id} | ✅ |

### SIPOC Templates (Marketplace) (1)
| Endpoint | UI? |
|---|---|
| POST /sipoc/processes/{pid}/import-template/{tid} | ✅ SipocSettings (PR #17 renomeou pra Templates) |

---

## 2. Sumário por área — onde focar

### 🔴 Bloqueia MVP UI-first (precisa de PR frontend novo)

**Área SIPOC operacional (impacto direto na jornada P1):**

| Bug/Gap | PR backend | PR frontend |
|---|---|---|
| Editar nome do setor | ❌ falta PATCH backend | Depois do backend |
| Editar nome do processo | ❌ falta PATCH backend | Depois |
| Criar activity standalone | ❌ falta POST `/sipoc/processes/{pid}/components` | Depois |
| Botão Delete setor/process/activity na UI | ✅ PR #144 aberto | Falta UI consumir |
| RACI matrix UI (R/A/C/I por activity) | ✅ PR #142 mergeado | **Sem componente UI** |
| Botão "Gerar diagnóstico" | ✅ PR #139 mergeado | **Sem botão** |
| Botão "Exportar PDF" | ✅ PR #140 mergeado | **Sem botão** |

**Org chart (impacto na jornada P1 também):**
| Gap | Status |
|---|---|
| Tree view top-down (não lista flat) | ❌ Gap 4 dogfood |
| Form "Reporta a:" persiste | ❌ Gap 4 dogfood |
| Form criar cargo cross-cutting (sem sector) | ❌ Gap 5 dogfood |

**Tab visibilidade buttons agent detail:**
| Gap | Status |
|---|---|
| `/agents/{id}?tab=skills` botão Salvar com `opacity-0` | ❌ bug identificado |
| Provavelmente `?tab=configuration` mesmo bug | ❓ |

### 🟡 Backend pronto, UI parcial (precisa polimento)

- `agent_specialty_configs` — apenas CSS
- `agent_adapter_configs` — provavelmente apenas CSS
- `agent_execution_configs` — verificar
- `agent_shared_config` — verificar se UI existe

### 🟢 Não bloqueia MVP

- Approvals (`/council`) — feature governance, não-crítico P1
- Hermes whitelist — feature avançada
- Reset OFX cursor — admin tool Kronos

---

## 3. Sequência sugerida pra zerar gaps UI no MVP

### Lote 1 — Backend que falta (3 PRs pequenos)

| PR | Escopo | Esforço |
|---|---|---|
| BE-A | `PATCH /api/sipoc/sectors/{id}` + `PATCH /api/sipoc/processes/{id}` | 30min |
| BE-B | `POST /api/sipoc/processes/{pid}/components` (criar activity standalone) | 1h |
| BE-C | `PATCH /api/sipoc/components/{id}` (editar activity) | 30min |

### Lote 2 — Frontend SIPOC + Org (1 PR grande ou 3 pequenos)

| PR | Escopo |
|---|---|
| FE-A | SipocManagement: botões Delete em sector/process/activity card + dialog confirm + toast cascade |
| FE-B | SipocManagement: botões Edit (PATCH) + form inline |
| FE-C | SipocManagement: **componente RACI matrix** (consumir endpoints PR #142) |
| FE-D | SipocReport: botão "Gerar diagnóstico" + botão "Exportar PDF" |
| FE-E | Org chart: tree view top-down + Gap 4+5 (form reports_to + cross-cutting) |

### Lote 3 — Polimento (fix CSS rápido)

| PR | Escopo |
|---|---|
| FE-F | `/agents/{id}?tab=skills` e `?tab=configuration`: trocar `opacity-0` → sempre visível |

### Lote 4 — Catálogo Marketplace (nice-to-have)

| PR | Escopo |
|---|---|
| FE-G | SipocSettings: botão "Criar template global" (admin platform) |

---

## 4. Estimativa total pra MVP UI-first 100%

| Lote | Backend (horas) | Frontend (horas) | Total |
|---|---|---|---|
| Lote 1 (BE) | 2h | — | 2h |
| Lote 2 (FE SIPOC + Org) | — | 8-12h | 8-12h |
| Lote 3 (CSS fix) | — | 30min | 30min |
| Lote 4 (Marketplace) | — | 2h | 2h |
| **Total MVP UI-first** | **2h backend** | **10-14h frontend** | **~13-16h** |

**Plano realista:** backend (BE-A/B/C) em 1 sessão minha (~2h). Frontend em 3-4 sessões VectraClip separadas (~3-4h cada).

---

## 5. Princípio Schmidt + metadata-driven aplicado

Cada fluxo acima respeita:
- **Fonte de verdade:** tabela do schema (nada hardcoded)
- **Workflow descoberta → execução:** UI guia user passo a passo (Wizard → SIPOC → RACI → Diagnose → Recomendação → Approve → Execute)
- **Sem CLI:** todo botão visível, todo confirm explícito, toda mensagem de erro em PT

Quando todos lotes acima estiverem em main, **o MVP P1 pode ser vendido pra cliente leigo sem treinamento técnico**.

---

## 6. PRs já mergeados que não precisam refazer

- Validation backend (PR #138) → toasts no SipocWizard ✓ (PR #17)
- RBAC sector_responsible (PR #135) → sidebar esconde admin ✓ (PR #17)
- Admin endpoints (PR #136) → Org.tsx ManageUsersDialog ✓ (PR #16)
- Diagnose backend (PR #139) → falta botão UI no Report

---

## 7. Pendência adicional: bugs já reportados nesta sessão

| Bug | Onde | Solução |
|---|---|---|
| `/agents/{id}?tab=skills` botão Salvar invisível | AgentDetail.tsx linha 1240 | Trocar `opacity-0` → `opacity-100` |
| Zero runs reais há 4 dias mesmo com adapter configurado | Possível continuação do bug CSS acima (user nunca confirmou save) | Validar fluxo end-to-end após fix CSS |

---

## 8. Próximo comando esperado

Você decide:

- **"Executa Lote 1 (backend BE-A/B/C)"** → faço 3 PRs pequenos (~2h)
- **"Gera prompt frontend Lote 2"** → preparo handoff completo pro VectraClip
- **"Foca no CSS fix Lote 3 primeiro"** → quick win 30min
- **"Outra ordem"** → você define
