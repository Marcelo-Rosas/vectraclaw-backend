# Auditoria Consolidada — 2026-05-16

Cruza relatórios de **4 esquadrões paralelos** que rodaram no mesmo dia. Algumas
violações apareceram em mais de um relatório — consolidadas aqui pra evitar
PRs duplicados.

> **Regra do consolidado:** marque `STATUS` quando começar a atacar. Quem entrar
> depois pula esse item. Quando resolver, troque para `RESOLVED-PR-#XXX`.

---

## Squad A — Backend No-Hardcode (22 hits)

> Auditor: Explore subagent VectraClaw `src/`. Fonte: este PR.

| # | Arquivo:linha | Conceito | Catalog | Sev | Status |
|---|---|---|---|---|---|
| A1 | `src/models.py:463` | `AgentExecutionConfig.execution_mode` Literal | `agent_execution_modes` | ALTA | **RESOLVED-PR-AGENT-EXECUTION** |
| A2 | `src/api.py:5938` | Fallback `or "REALTIME"` hardcoded | `agent_execution_modes` | ALTA | **RESOLVED-PR-AGENT-EXECUTION** |
| A3 | `src/api.py:5125` | `AgentExecutionSetupInput.executionMode` Literal | `agent_execution_modes` | ALTA | **RESOLVED-PR-AGENT-EXECUTION** |
| A4 | `src/api.py:2528,6673` | `_to_db` mapping adapter hardcoded (2 locais — drift) | `adapter_catalog` | ALTA | open |
| A5 | `src/api.py:4018-4024` | `_KRONOS_ROUTINE_OPERATIONS` tuple | `operation_types_catalog` | ALTA | open |
| A6 | `src/models.py:102-145` | `Task.operation_type` Literal (41 valores) | `operation_types_catalog` | ALTA | open (gap V6 — frontend já é texto livre) |
| A7 | `src/models.py:23,353` + `api.py:129-133,3170` | `Agent.status` + `AgentStatus` class + `NewHeartbeatInput.status` Literal | _(precisa criar `agent_status_catalog`)_ | MÉDIA | open — ver P6 do CODE-PATTERNS antes |
| A8 | `src/models.py:101` + `api.py:2620-2652` | `Task.status` Literal | `task_tree_status` | ALTA | open — gap V8 (catalog existe mas sem endpoint GET) |
| A9 | `src/api.py:2610-2618` | `NewTaskInput.operation_type` Literal (subset) | `operation_types_catalog` | MÉDIA | open |
| A10 | `src/api.py:3610` | `NewAdapterFieldInput.fieldType` Literal | _(criar `adapter_field_types_catalog`?)_ | MÉDIA | open — decisão antes |
| A11 | `src/api.py:1357` | `valid_types` set SipocComponent.type | (constraint local — ver P6) | BAIXA | manter |
| A12 | `src/api.py:1688` | default `"rascunho"` SipocProcess.status | (local) | BAIXA | manter |
| A13 | `src/api.py:2717,2759` | default `"backlog"` task.status | `task_tree_status` | BAIXA | parametrizar quando A8 fechar |
| A14 | `src/api.py:3873` | default `"active"` Routine.status | (local) | BAIXA | manter |
| A15 | `src/api.py:200-204` | `_zod_user_role()` Literal admin/member | (auth — P6) | BAIXA | manter |
| A16 | `src/models.py:528` | `Routine.status` Literal | (local) | BAIXA | manter |
| A17 | `src/agents/athena.py:28` | `ATHENA_AGENT_ID` hardcoded (15+ refs) | tabela `agents` | MÉDIA | open — lookup por slug |
| A18 | `src/agents/athena.py:37` + `src/services/gemini_client.py:12` | `DEFAULT_MODEL = "gemini-2.5-flash"` | `llm_models` | MÉDIA | open |
| A19 | `src/api.py:2251-2277` | `MOCK_LLM_MODELS` + `MOCK_AGENT_SPECIALTIES` hardcoded | catalogs | BAIXA | mock isolado — manter sync com seed |

---

## Squad B — Frontend No-Hardcode (11 hits)

> Auditor: Explore subagent VectraClip `src/`. Fonte: este PR.

| # | Arquivo:linha | Conceito | Catalog | Sev | Status |
|---|---|---|---|---|---|
| B1 | `src/components/agents/detail/AgentExecutionCard.tsx:129-131` | `<SelectItem>` hardcoded REALTIME/CRON/TRIGGER | `agent_execution_modes` | ALTA | **RESOLVED-PR-AGENT-EXECUTION** |
| B2 | `src/types/api.ts:104` | `AgentExecutionMode` union literal | idem | ALTA | **RESOLVED-PR-AGENT-EXECUTION** |
| B3 | `src/lib/api/schemas.ts:105-107` | `z.enum(['REALTIME','CRON','TRIGGER'])` | idem | ALTA | **RESOLVED-PR-AGENT-EXECUTION** |
| B4 | `src/components/shared/NotificationsBell.tsx:48-53` | `typeLabels` hardcoded | _(council_request_types — VERIFICAR se existe)_ | ALTA | open — investigar catalog |
| B5 | `src/pages/Council.tsx:54-78` | `REQUEST_TYPE_CONFIG` hardcoded | idem B4 | ALTA | open |
| B6 | `src/pages/Council.tsx:80-96` | `STATUS_CONFIG` hardcoded approvals | _(council_approval_statuses — VERIFICAR)_ | ALTA | open |
| B7 | `src/lib/api/schemas.ts:94-178` | Múltiplos `z.enum()` (agentStatus, taskStatus, councilRequestType, userRole, councilApprovalStatus, **recommendationKind**) | vários | **🔴 CRÍTICA** (era MÉDIA) | **OPEN — VISÍVEL EM PROD** |
| B7-bis | `src/lib/api/schemas.ts` `recommendationKindSchema` | `z.enum([hire_new_agent, add_specialty, rewrite_system_prompt, create_specialty, consolidate_agents])` | `athena_kind_catalog` (PR #141 canonicalizou 8 valores incluindo `diagnose_gap`) | **⏸️ INTENTIONAL** (era 🔴 CRÍTICA) | **NÃO CONSERTAR até executor existir** — ver decisão abaixo |
| B8 | `src/lib/display.ts:28-356` | `AGENT_STATUSES`, `ADAPTER_TYPES`, `TASK_STATUSES`, `TASK_OPERATION_TYPES`, etc. | múltiplos | MÉDIA | open — refactor maior |
| B9 | `src/pages/Council.tsx:235-244` | `PayloadRenderer` switch hardcoded | idem B4 | MÉDIA | open |
| B10 | `src/lib/display.ts:439-495` | `RAG_CATEGORIAS`, `RAG_DEPARTAMENTOS`, `RAG_CONFIDENCIALIDADES` | _(catalog não existe — criar?)_ | MÉDIA | decisão Product |
| B11 | `src/mocks/fixtures/seed.ts` | Mock isolado | — | BAIXA | manter |

---

## Squad C — Botões Fantasmas (14 hits)

> Auditor: sessão paralela do user. Reportado em 2026-05-16. **Não atacar daqui — owner: outra sessão.**

### P0 — CSS escondendo CRUD (`opacity-0 group-hover:opacity-100`)

| # | Arquivo:linha | Botões | Status |
|---|---|---|---|
| C1 | `src/components/goals/GoalTree.tsx:103` | Editar / Deletar / Link | open — Batida 1 outra sessão |
| C2 | `src/components/tasks/TaskCard.tsx:239` | Editar / Deletar | open — Batida 1 |
| C3 | `src/components/workflow/canvas/nodes/StepNode.tsx:94` | Editar (Pencil) | open — Batida 1 |
| C4 | `src/pages/SipocSettings.tsx:97` | Duplicar template | open — Batida 1 |
| C5 | `src/pages/SipocSettings.tsx:106` | Download template | open — Batida 1 |

### P0 — Botões mortos

| # | Arquivo:linha | Cheiro | Status |
|---|---|---|---|
| C6 | `src/pages/SipocManagement.tsx:119` | `<Button><Plus/></Button>` zero handler | open — Batida 2 outra sessão |

### P1 — Botões falsos

| # | Arquivo:linha | Promessa | Status |
|---|---|---|---|
| C7 | `src/components/shared/UserMenu.tsx:75` | toast "Perfil disponível em breve" | open — Batida 3 outra sessão (aguarda decisão A/B/C) |
| C8 | `src/components/shared/UserMenu.tsx:80` | toast "Configurações disponíveis em breve" | open — idem |
| C9 | `src/pages/SipocReport.tsx:498` | "Detalhes em breve" — placeholder consciente PR #18 | manter |
| C10 | `src/pages/SipocSettings.tsx:48` | "Exportar RACI consolidada" backend missing | decisão (remover ou manter) |
| C11 | `src/pages/CompanySettings.tsx:150` | "Convidar" disabled sem explicação | open — investigar |

### P2 — Cheiros menores

| # | Arquivo:linha | Suspeita | Status |
|---|---|---|---|
| C12 | `src/components/sipoc/SipocDiagnosticCard.tsx:75` | opacity-0 em ícone Info cosmético | open — Batida 1 candidato |
| C13 | `src/pages/SipocWizard.tsx:801` | `AlertDialogTrigger` aninhado em `DropdownMenuContent` | open |

### P3 — Showcases legítimos (ignorar)

`DesignPreview.tsx:185`, `Themes.tsx:236`, `CronSelector.tsx:120`.

---

## Squad D — models.py Literal Triage (23 ocorrências)

> Auditor: Explore subagent — leitura dirigida só de `models.py`.

- **2 VIOLAM HARD:** linhas 102 (`Task.operation_type`) e 463 (`AgentExecutionConfig.execution_mode`)
- **3 DUVIDOSOS:** `Task.executor_type`, `CouncilApproval.request_type`, `User.role`
- **18 OK:** máquinas de estado locais — ver P6 do CODE-PATTERNS

**Endpoint GAP:** `adapter_catalog` e `task_tree_status` têm tabela mas
**não têm endpoint GET** — bloqueia o frontend largar `z.enum`. Criar antes de
B7/B8.

---

## Sobreposições (mesmos arquivos em squads diferentes)

| Arquivo | Squads | Decisão |
|---|---|---|
| `SipocSettings.tsx` | C (botões C4/C5/C10) | Atacar tudo num PR só (outra sessão) |
| `SipocManagement.tsx` | C (botão C6) | Atacar isolado (outra sessão) |
| `models.py` | A + D | Convergem — usar lista de D como fonte (mais conservadora em "OK") |
| `Council.tsx` | B (B5/B6/B9) | PR único quando endpoint council catalog existir |

---

## ⏸️ Decisão registrada: B7-bis fica quebrada propositalmente

**Data:** 2026-05-16 · **Owner:** Marcelo (chat session) · **Tipo:** Broken Window Intencional (P8 do CODE-PATTERNS).

**Decisão:** **NÃO consertar** `recommendationKindSchema` (o `z.enum` que rejeita `diagnose_gap`) até existir um **executor real** que aplique recommendation aprovada sem humano editar à mão em `/agents/{id}/edit`.

**Razão:** a página `/agents/recommendations` é display-only após `mark-applied` — o sistema NÃO executa nada, apenas muda `status='applied'`. UI funcionando bonita criaria **dívida invisível**: humano aprova achando que "Athena vai aplicar", quando na real precisa copiar `proposed_changes_json` à mão, ir em outra tela, editar prompt, voltar e marcar. Erro vermelho = sinal honesto.

**Quando reverter (condição de saída):** quando existir endpoint tipo `POST /api/athena/recommendations/{id}/execute` que de fato:
- `rewrite_system_prompt`: faz `PUT /agents/{id}` com `proposed_changes_json.prompt` e grava em `agent_prompt_history`
- `hire_new_agent`: dispara wizard de provisioning OU executa o atomic create
- `add_specialty` / `create_specialty`: insere em `agent_specialty_configs` / `agent_specialties` automaticamente
- `consolidate_agents`: merge real com cuidado pra FKs

Sem isso, o ciclo PMBOK fica em "Execução = manual" (gap mapeado na seção "Mapa PMBOK do fluxo atual" do diagnóstico Athena hoje).

**Sinal de violação:** se você está prestes a abrir PR `fix(frontend): recommendationKindSchema z.string()`, **pare e volte aqui**. Não é bug — é débito de produto sinalizando.

---

## Backlog priorizado (ordem sugerida)

0. ~~B7-bis~~ → **movida pra ⏸️ INTENTIONAL acima** (ver decisão)
1. **CRIAR catalog GET endpoints faltantes** (`adapter_catalog`, `task_tree_status`) — destrava B7/B8 inteiros
2. **A4** — Consolidar adapter mapping (`_to_db` duplicado)
3. **A5+A6+A9** — `operation_type` catalog-driven (Pydantic + Kronos tuple)
4. **A8** — `Task.status` catalog-driven (depende do 1)
5. **A17+A18** — Athena IDs/models lookup por slug
6. **B4+B5+B6+B9** — Council UI catalog-driven (depende de endpoint council novo)
7. **B8** — display.ts massive refactor (último — mais arquivo tocado)

A7 (Agent.status) e A10 (NewAdapterFieldInput.fieldType) precisam **decisão antes** de implementar: vira catálogo ou fica local (P6 do CODE-PATTERNS)?

---

## ⏸️ INTENTIONAL BROKEN — "Gerar rascunho de resposta" Hermes (2026-05-17)

**Componente:** `VectraClip/src/components/agents/InboxDigest.tsx`
**Sintoma original (relatado por Marcelo 2026-05-17):** botão "Gerar rascunho de resposta" mostrava toast `"Rascunho gerado para '<subject>'"` mas NÃO criava rascunho real — UI mentia ao usuário.

**Diagnóstico:**
- Frontend: função `generateDraft()` era `toast.success(...)` puro, zero backend call
- Backend: NÃO existe `POST /api/hermes/inbox/{email_id}/draft` (grep confirmado)
- Feature foi planejada na UI sem nunca conectar executor real

**Decisão (P8 do CODE-PATTERNS — Broken windows intencionais):**
Botão fica **desabilitado** com `<Tooltip>` explicando "Feature aguardando executor real no backend Hermes". Preserva sinal de feature planejada (vs apagar) e para de mentir (vs manter toast falso).

**Condição de reverter:** implementar `POST /api/hermes/inbox/{email_id}/draft` que:
1. Resolve modelo via specialty config (mesma cadeia catalog do oracle-extract)
2. Gera resposta via LLM com prompt: `<email_subject> + <email_excerpt> + system_instruction PT-BR`
3. Persiste como rascunho IMAP via `hermes_imap.create_draft()` OU retorna texto pra usuário copiar

Quando endpoint existir, remover `disabled` + Tooltip do botão e implementar `useGenerateHermesDraft` hook que chama endpoint.

**Sem ticket Linear ainda** — abrir VEC-NNN quando priorizar.
