# Architecture AS-IS — VectraClaw / VectraClip

> Auditoria realizada em **2026-05-16**. Schema real lido de `epgedaiukjippepujuzc` (Supabase).
> Mapeia **51 tabelas** no schema `vectraclip`, todos endpoints REST do backend, e as 38 rotas + 30 entradas de sidebar do frontend `VectraClip`.
>
> Próximos docs derivados desta auditoria: `ARCHITECTURE-TO-BE.md` (Fase 2) e `ARCHITECTURE-MIGRATION-ROADMAP.md` (Fase 3).

---

## TL;DR — 5 achados que explicam o sintoma "preciso de CLI pra criar tarefa"

1. **A hierarquia de trabalho (Goal → Project → Routine → Task) está modelada mas não vinculada.** Tasks só conhecem `goal_id`; **não há FK pra `project_id` nem `routine_id`**. Projects não declaram `goal_id`. Routines não declaram `project_id`. Cada entidade sabe a empresa e o agente, mas não a iniciativa.
2. **As tabelas-pai estão vazias.** `routines` = 0 rows, `workflow_steps` = 0, `projects` = 1, `goals` = 2. O sistema teórico nunca virou prático — então tasks viraram a única coisa criada, ad-hoc, via CLI.
3. **3 sistemas paralelos de execução** convivem sem coordenação: Routines (com scheduler + cron) ; Workflows (definition + steps) ; Tasks ad-hoc. Não competem, **coexistem em silo**.
4. **SIPOC mapeia processos mas não conversa com o resto.** 41 `sipoc_components` + 26 `sipoc_edges` mapeados, **zero FKs out** pra Goal/Project/Routine/Task/Workflow/Agent. Trabalho de modelagem inerte.
5. **Telemetria explodindo sem retention.** 139.405 heartbeats e 36.660 incidents/incident_audit. Em 1 ano vira ~125M rows.

E **3 tabelas sem RLS** = risco de segurança (`kronos_rules` com 113 rows, `tasks_block_log`, `agent_domains`).

---

## 1. Inventário de tabelas por domínio (51 tabelas, contagens reais)

### 1.1 Hierarquia de Trabalho (a que importa pra criar task pela UI)
| Tabela | Rows | Sintoma |
|---|---|---|
| `goals` | **2** | Mal usado, sem entry point claro |
| `projects` | **1** | Praticamente abandonado |
| `routines` | **0** | **VAZIA** — explica o uso de CLI |
| `workflow_definitions` | **1** | 1 def, 0 steps |
| `workflow_steps` | **0** | **VAZIA** |
| `tasks` | 13 | Existem mas órfãs |
| `runs` | 43 | Wrapper de execução (provavelmente CMA-origin) |
| `run_transcript_entries` | 0 | Não usado |

### 1.2 NAV ADMIN (definição dos agentes — base sólida)
| Tabela | Rows | Função |
|---|---|---|
| `agents` | 10 | 1 por daemon |
| `agent_specialties` | 23 | Catálogo de capabilities |
| `agent_specialty_configs` | 16 | Specialty atribuída a agent + cfg |
| `agent_adapter_configs` | 10 | Adapter + model_id por agent (1:1) |
| `agent_execution_configs` | 10 | Mode + cfg por agent (1:1) |
| `agent_shared_config` | 1 | Config compartilhada por agent |
| `agent_prompt_history` | 2 | Versionamento append-only |
| `agent_domains` | 7 ⚠️ | Catálogo de domínios (**SEM RLS**) |
| `agent_execution_modes` | 3 | REALTIME, CRON, TRIGGER |

### 1.3 Catálogos canônicos
| Tabela | Rows | Função |
|---|---|---|
| `adapter_catalog` | 10 | Providers (Anthropic, OpenAI, Ollama, …) |
| `adapter_field_definitions` | 24 | Schemas de config por adapter |
| `llm_models` | 39 | Catálogo de modelos LLM |
| `operation_types_catalog` | 39 | operation_types válidos (alimenta dropdown) |
| `workflow_logic_patterns` | 8 | splitting/merging/looping/waiting/subworkflow/error/simple/parallel |
| `workflow_trigger_types` | 4 | Tipos de trigger |

### 1.4 SIPOC (mapeamento de processo — em silo)
| Tabela | Rows |
|---|---|
| `sipoc_companies` | 2 |
| `sipoc_sectors` | 5 |
| `sipoc_processes` | 9 |
| `sipoc_components` | 41 |
| `sipoc_edges` | 26 |
| `sipoc_sector_baselines` | 7 |
| `sipoc_positions` | 0 |
| `sipoc_raci` | 0 |

### 1.5 Telemetria & Observabilidade (sem retention)
| Tabela | Rows | Crescimento |
|---|---|---|
| `heartbeats` | **139.405** | ~14k/h global, ~125M/ano sem TTL |
| `incidents` | **36.660** | Indica muitos erros silenciosos |
| `incident_audit` | **36.660** | Espelho/audit dos incidents |
| `tasks_block_log` | 0 ⚠️ | **SEM RLS**, parece legado |

### 1.6 Inteligência & Conhecimento (4 sistemas paralelos)
| Sistema | Tabelas | Rows | Função |
|---|---|---|---|
| RAG Mnemos | `rag_documents`, `rag_chunks` | 6, 31 | Corpus geral |
| RAG Athena | `athena_documents`, `athena_chunks` | 1, 1 | Corpus PMBOK isolado |
| Recomendações | `athena_recommendations` | 1 | Sugestões com tracking de origem ✓ |
| Templates | `research_templates` | 4 | Prompt templates pra oracle-research |

### 1.7 CRM (Hermes / Mercator)
| Tabela | Rows |
|---|---|
| `prospect_profiles` | 4 |
| `hermes_sender_whitelist` | 1 |

### 1.8 Governance (modelada, sem uso)
| Tabela | Rows |
|---|---|
| `approvals` | 0 |

### 1.9 CMA — Claude Managed Agents (vazio em prod)
| Tabela | Rows |
|---|---|
| `managed_agent_sessions` | 0 |
| `managed_agent_turn_logs` | 0 |

### 1.10 Rules engine (Kronos)
| Tabela | Rows |
|---|---|
| `kronos_rules` | 113 ⚠️ (**SEM RLS** — 113 regras expostas a anon) |

### 1.11 Identidade & Multi-tenant
| Tabela | Rows |
|---|---|
| `companies` | 1 |
| `app_users` | 1 |
| `company_secrets` | 1 |

---

## 2. Grafo de dependências (FKs reais — só os elos relevantes)

```
companies ◄────────────── (quase todas as tabelas) [multi-tenant root]

goals
  ├─ parent_goal_id ───► goals (auto-ref, hierarquia de objetivos)
  └─ company_id ───► companies

projects
  ├─ lead_agent_id ───► agents
  └─ company_id ───► companies
  [❌ SEM goal_id]

routines
  ├─ agent_id ───► agents
  ├─ workflow_definition_id ───► workflow_definitions
  └─ company_id ───► companies
  [❌ SEM project_id, SEM goal_id]

workflow_definitions
  ├─ trigger_type ───► workflow_trigger_types.slug
  └─ company_id ───► companies
  [❌ SEM project_id, SEM goal_id]

workflow_steps
  ├─ workflow_id ───► workflow_definitions
  ├─ on_success_step_id ───► workflow_steps (auto-ref)
  └─ logic_pattern ───► workflow_logic_patterns.taxonomy
  [❌ SEM assigned_to_agent_id — step não declara executor!]

tasks
  ├─ goal_id ───► goals                         ✓
  ├─ parent_task_id ───► tasks (auto-ref)        ✓ (sub-tasks)
  ├─ workflow_step_id ───► workflow_steps        ✓
  ├─ assigned_to_agent_id ───► agents            ✓
  └─ company_id ───► companies                   ✓
  [❌ SEM project_id]
  [❌ SEM routine_id — task gerada por routine não sabe quem a originou!]

runs
  ├─ task_id ───► tasks                          ✓
  ├─ routine_id ───► routines                    ✓ (BOA: runs sabem a origem)
  ├─ agent_id ───► agents
  └─ company_id ───► companies

heartbeats
  ├─ task_id ───► tasks
  └─ agent_id ───► agents

athena_recommendations  [exemplar de FKs bem amarradas]
  ├─ triggered_by_goal_id ───► goals             ✓
  ├─ triggered_by_task_id ───► tasks             ✓
  ├─ target_agent_id ───► agents                 ✓
  └─ applied_history_id ───► agent_prompt_history (tracking de aplicação)

SIPOC (silo — zero FKs outbound pra fora do próprio domínio SIPOC)
  sipoc_companies
    └─ sipoc_sectors (parent_sector_id auto-ref)
        ├─ sipoc_processes
        │   ├─ sipoc_components (Suppliers/Inputs/Outputs/Customers/Activities)
        │   └─ sipoc_edges (source_id → target_id)
        └─ sipoc_positions (reports_to_id auto-ref) [0 rows]
            └─ sipoc_raci [0 rows]
  [❌ NADA aponta pra Goal/Project/Routine/Task/Workflow/Agent]
```

### Mapa das **6 FKs faltantes** mais críticas

| Falta | Impacto | Migration sugerida |
|---|---|---|
| `tasks.project_id` | Tasks ad-hoc órfãs de iniciativa | `ALTER TABLE tasks ADD project_id UUID REFERENCES vectraclip.projects(id);` |
| `tasks.routine_id` | Não dá pra rastrear qual routine gerou a task (só via `runs.routine_id`, que é wrapper opcional) | `ALTER TABLE tasks ADD routine_id UUID REFERENCES vectraclip.routines(id);` |
| `projects.goal_id` | Project não declara qual goal serve | `ALTER TABLE projects ADD goal_id UUID REFERENCES vectraclip.goals(id);` |
| `routines.project_id` | Routine não sabe qual project pertence | `ALTER TABLE routines ADD project_id UUID REFERENCES vectraclip.projects(id);` |
| `workflow_definitions.project_id` | Workflow vive em silo | `ALTER TABLE workflow_definitions ADD project_id UUID REFERENCES vectraclip.projects(id);` |
| `workflow_steps.assigned_to_agent_id` | Step não declara executor (vem de convenção?) | `ALTER TABLE workflow_steps ADD assigned_to_agent_id UUID REFERENCES vectraclip.agents(id);` |

Todas devem ser **nullable** pra não quebrar dados existentes (backfill incremental).

---

## 3. API surface (resumo — 50+ endpoints)

Backend já expõe CRUD pra **todas** as entidades-pai da hierarquia:

| Domínio | Endpoints (sample) |
|---|---|
| Goals | `GET/POST/PATCH/DELETE /api/[companies/{cid}/]goals` |
| Projects | `GET/POST/PATCH/DELETE /api/[companies/{cid}/]projects` |
| Routines | `GET/POST/PATCH/DELETE /api/[companies/{cid}/]routines` + **`POST /api/routines/{id}/run-now`** |
| Tasks | `GET/POST/PATCH/DELETE /api/[companies/{cid}/]tasks` + lifecycle (claim, complete, execute, approve, reject, evaluate) |
| Workflows | `GET/POST/PATCH/DELETE /api/companies/{cid}/workflows[/{slug}]` + steps + `run-orchestrator` |
| Agents (NAV ADMIN) | CRUD + adapter-config + execution-config + specialty-config + inbox + routines + shared-config |
| Specialties | CRUD em `/api/agent-specialties` |
| LLM Models | CRUD em `/api/llm-models` |
| Adapters | catálogo + fields |
| SIPOC | companies, sectors, positions, processes, components |
| RAG (Mnemos) | documents/chunks + ingest |
| Athena | documents + recommendations |
| Catálogos | `/api/operation-types`, `/api/workflow-logic-patterns`, `/api/workflow-trigger-types`, `/api/agent-domains`, `/api/agent-execution-modes` |

**Backend não é o gargalo**. O bloqueio é orquestração de UI + dados não vinculados.

---

## 4. Frontend AS-IS — 38 rotas, 30 sidebar entries

### 4.1 Sidebar atual (sintoma do "empilhamento")
Ordem real do `Sidebar.tsx`:
```
Inbox / Dashboard / Agentes / Recomendações Athena / Organograma /
Tarefas / Knowledge Base / Objetivos / Projetos /
Workflow / Workflow 2 / Workflow Ops / Rotinas /
Prospects / Templates pesquisa /
Sipoc Builder / Processos / Métricas /
Council / Audit / Temas /
Splitting / Merging / Looping / Waiting / Sub-workflows / Error Handling /
Custos / Plugins / Inteligência
```
**Problemas visíveis:**
- Goals/Projects/Routines/Tasks no **mesmo nível visual** (sem hierarquia)
- **3 entries de Workflow** (`Workflow`, `Workflow 2`, `Workflow Ops`) — migração em curso ou duplicação?
- **6 entries `flow-logic/*`** são docs de patterns, não features — poluem o menu
- SIPOC em 3 entries paralelas (Builder, Processos, Métricas) — em silo do resto
- "Recomendações Athena" vs "Inteligência" — possível overlap

### 4.2 Páginas implementadas (46 .tsx no `src/pages/`)
**Já existentes** (entry point disponível):
- `/goals` (`Goals.tsx`) + `/goals/:id` (`GoalDetail.tsx`)
- `/projects` (`Projects.tsx`) + `/projects/:id` (`ProjectDetail.tsx`)
- `/routines` (`Routines.tsx`) + `/routines/new` + `/routines/:id` (`RoutineEditor.tsx`)
- `/tasks` (`Tasks.tsx`)
- `/workflow`, `/workflow_2`, `/workflow/ops` (3 versões)
- `/agents` + `/agents/:id` + `/agents/:id/workspace`
- `/admin/agent-builder`, `/admin/models`, `/admin/specialties`, `/admin/connectors`
- Sipoc: `/sipoc/wizard`, `/sipoc/management`, `/sipoc/settings`, `/sipoc/analytics`, `/sipoc/setup`

**Componente exemplar de UX já pronto:** `components/agents/detail/AgentRoutinesCard.tsx` tem botão **"Executar agora"** funcional, com toast de feedback. Hooks `useAgentRoutines`, `useRunRoutineNow` ativos. Esse padrão deve ser replicado nas páginas-pai (Goal, Project).

---

## 5. Matriz cobertura CRUD-via-UI (gap analysis)

Pra cada entidade-pai, marca o que está disponível **sem CLI**:

| Entidade | List UI | Create UI | Edit UI | Delete UI | Executar/Disparar UI | Criar filho a partir daqui |
|---|---|---|---|---|---|---|
| Goal | ✓ `/goals` | ? a confirmar em `Goals.tsx` | ? | ? | n/a | ❌ **falta**: "+ Project" ou "+ Task" no contexto |
| Project | ✓ `/projects` | ? a confirmar em `Projects.tsx` | ? | ? | n/a | ❌ **falta**: "+ Routine" ou "+ Task" no contexto |
| Routine | ✓ `/routines` | ✓ `/routines/new` | ✓ `/routines/:id` | ? | ✓ `runNow` em AgentRoutinesCard | ❌ Routine standalone — sem botão pra criar vinculada a Project |
| Workflow | ✓ (3 entradas) | ? | ? | ? | ? `run-orchestrator` no backend | ❌ Não cria task isolada |
| Task | ✓ `/tasks` | ❌ **GAP** (origem da pergunta original) | ? | ? | n/a (é executada por daemon) | n/a |
| Agent | ✓ `/agents` | ✓ HireAgentDialog | ✓ EditAgentDialog | ✓ KillAgentConfirm | n/a | ✓ AgentRoutinesCard tem "+ Nova rotina" |
| Specialty | ✓ `/admin/specialties` | ✓ Create…Dialog | ✓ Edit…Dialog | ✓ | n/a | n/a |
| LLM Model | ✓ `/admin/models` | ✓ Create…Dialog | ✓ Edit…Dialog | ✓ | n/a | n/a |
| Adapter | ✓ `/admin/connectors` | ✓ ConnectorFormDialog | ✓ | ✓ | n/a | n/a |
| SIPOC Process | ✓ `/sipoc/management` | ✓ wizard | ? | ? | n/a | ❌ Activity não vira Operation/Task |

**Conclusão:** o CRUD baixo nível está bem coberto **isoladamente**. O que falta são **ações de criação no contexto da entidade-pai** (botão "+ Task" dentro de Goal, etc.) e a **vinculação automática** (preenche goal_id/project_id/routine_id ao criar).

---

## 6. Sistemas paralelos detectados — overlap a resolver

| # | Sistemas | Sintoma | Decisão pendente |
|---|---|---|---|
| 1 | Routines + Workflows + Tasks ad-hoc | 3 caminhos de execução sem hierarquia comum | Definir: Workflow é uma forma de Routine? Routine é uma forma de Workflow? Tasks ad-hoc são exceção ou regra? |
| 2 | `/workflow` + `/workflow_2` + `/workflow/ops` | 3 entries no sidebar | Identificar qual é o canônico e deprecar os outros |
| 3 | RAG Mnemos + RAG Athena | 2 corpus separados (`rag_*` e `athena_*`) | Manter separação isolada por design? Ou unificar com tags? |
| 4 | Athena Recommendations + Inteligência | 2 entries de "AI sugere coisas" | Verificar se são a mesma feature renomeada |
| 5 | SIPOC silo | Modelagem sem ligação operacional | Decidir: Activity gera Operation? Ou SIPOC é só documentação? |
| 6 | CMA tables vazias | `managed_agent_*` modeladas, não usadas | Deprecar ou ativar (depende de prioridade) |

---

## 7. ⚠️ Alerta de segurança (Supabase Advisor)

**3 tabelas com RLS desabilitado — qualquer um com anon key lê/modifica:**

| Tabela | Rows | Por quê é grave |
|---|---|---|
| `vectraclip.kronos_rules` | **113** | Regras de classificação de planner OFX expostas |
| `vectraclip.agent_domains` | **7** | Catálogo de domínios expostos |
| `vectraclip.tasks_block_log` | 0 | Vazia, mas exposta |

**Remediação (NÃO rodar sem desenhar policies primeiro — habilitar RLS sem policies bloqueia tudo):**
```sql
-- 1) Reabilitar RLS
ALTER TABLE vectraclip.kronos_rules     ENABLE ROW LEVEL SECURITY;
ALTER TABLE vectraclip.agent_domains    ENABLE ROW LEVEL SECURITY;
ALTER TABLE vectraclip.tasks_block_log  ENABLE ROW LEVEL SECURITY;

-- 2) Policies (exemplo — adaptar ao padrão multi-tenant existente)
CREATE POLICY "tenant_isolation_kronos_rules"
  ON vectraclip.kronos_rules
  USING (company_id = (SELECT company_id FROM vectraclip.app_users WHERE auth_user_id = auth.uid()));

-- agent_domains é catálogo global → leitura authenticated, escrita só service_role
CREATE POLICY "authenticated_read_agent_domains"
  ON vectraclip.agent_domains FOR SELECT
  USING (auth.role() = 'authenticated');
```

`tasks_block_log` está vazio + sem RLS — **candidato a deletar** se for legado.

---

## 8. Candidatos a "lixo" (rever antes de remover)

| Tabela / Feature | Razão |
|---|---|
| `managed_agent_sessions` (0) | CMA não usado em prod, feature dormente |
| `managed_agent_turn_logs` (0) | Idem |
| `tasks_block_log` (0, sem RLS) | Provável legado |
| `run_transcript_entries` (0) | Wrapper sem dados |
| `approvals` (0) | Governance modelada, nunca exercitada |
| `sipoc_raci` (0) | Submodel sem uso |
| Rotas `/workflow_2` e `/workflow/ops` | Sidebar tem 3 entries pra Workflow — pelo menos 1 é deprecável |
| Páginas `Themes`, `DesignPreview` | Provavelmente dev-only, esconder do sidebar prod |
| 6 rotas `/flow-logic/*` | Documentação inline; mover pra docs/ ou esconder de prod |

---

## 9. Próximos passos (pra Fase 2 — TO-BE)

Perguntas-chave que o desenho TO-BE precisa responder:

1. **Workflows vs Routines**: são níveis diferentes (Routine = trigger; Workflow = execução) ou alternativos?
2. **Tasks ad-hoc continuam existindo** como entrada paralela, ou tudo passa por Routine/Workflow?
3. **SIPOC**: Activity vira operation_type ou virou só documentação?
4. **Goals hierárquicos** (parent_goal_id existe): mostrar como árvore no UI?
5. **Project tem milestones**? (não vi tabela `milestones`, mas pode estar em `metadata`)
6. **Approvals**: ressuscitar com policy clara, ou deprecar?
7. **Athena Recommendations**: virar entry point de primeira classe (sidebar) ou continuar inline em agents?

Outputs esperados da Fase 2:
- `docs/ARCHITECTURE-TO-BE.md` com diagrama de hierarquia canônica
- Sidebar reorganizado (Inbox / Estratégia [Goals→Projects] / Operação [Routines/Workflows/Tasks] / Conhecimento [RAG/SIPOC] / Admin)
- Migration plan (qual ordem, quais FKs adicionar, quais backfills)
- Specs de UI por nível (cada entidade-pai com sua ação "+ filho")

---

## 10. Apêndice — comando para reproduzir este levantamento

```sql
-- contagem real por tabela
SELECT relname AS table_name, n_live_tup AS rows
FROM pg_stat_user_tables
WHERE schemaname = 'vectraclip'
ORDER BY n_live_tup DESC;

-- grafo de FKs
SELECT tc.table_name, kcu.column_name, ccu.table_name AS ref_table, ccu.column_name AS ref_column
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'vectraclip'
ORDER BY tc.table_name, kcu.column_name;

-- RLS status
SELECT schemaname, tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'vectraclip'
ORDER BY rowsecurity, tablename;
```
