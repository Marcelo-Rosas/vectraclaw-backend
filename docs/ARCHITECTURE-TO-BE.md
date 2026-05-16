# Architecture TO-BE — VectraClaw / VectraClip

> **Data:** 2026-05-16  
> **Pré-requisito:** ler `ARCHITECTURE-AS-IS.md` antes deste documento.  
> **Próximo doc derivado:** `ARCHITECTURE-MIGRATION-ROADMAP.md` (Fase 3 — sequência exata de PRs).
>
> Documento normativo: as decisões aqui valem para todo desenho subsequente até nova versão.

---

## 0. Síntese executiva

### Tese de produto

> *"Hoje vendemos a experiência de descoberta e diagnóstico; a execução automatizada existe em fatias (e-mail, auditoria OFX, research) mas ainda não é o produto fechado end-to-end."*

VectraClaw + VectraClip = **plataforma multi-tenant de consultoria digital** vendida em 2 módulos:

| Módulo | O que é | Quando vende | Pricing |
|---|---|---|---|
| **P1 — Consultoria de Mapeamento** | SIPOC discovery + diagnóstico Athena + relatório executivo | Primeiro, standalone (entry point) | Projeto fechado (consultoria) |
| **P2 — Automação Operacional** | Goals → Workflows → Tasks executados por agents contratados | Upsell pós-diagnóstico aprovado | Pass-through tokens + margem por agent |

Vectra Cargo (`01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2`) = **dogfood + showcase** — primeiro caso completo pra usar em demos.

### Decisões consolidadas (refer ao AS-IS para alternativas descartadas)

| Eixo | Decisão |
|---|---|
| **A1 — Venda principal** | Bundle (c) com MVP entrada por Diagnóstico (a); SIPOC é produto, não wizard |
| **B1 — Onboarding** | Híbrido: self-service nos templates + sessão guiada no 1º cliente pago |
| **B2 — Time-to-WOW** | Diagnóstico mesmo dia (led) / 1-2 dias (PLG); execução só 1+ semana |
| **C1 — Integração** | Coexistem uploads/IMAP (sem sistema cliente) + API (com CFN/ERP) |
| **C2 — Conectores** | 3-4 universais + packs verticais (logística/financeiro primeiro) |
| **D1 — Agents** | **Platform agents** (5) compartilhados + **Tenant agents** (5) contratados |
| **D2 — Workflow marketplace** | Sim, templates clonáveis por company |
| **D3 — SIPOC** | Taxonomia híbrida; **obrigatório ligar Activity → operation_type** |
| **E1 — MVP pago** | SIPOC + Diagnóstico + Athena report; automação = fase 2 por processo |

### Modelo de agents: **5 platform + 5 tenant**

| Agente | Scope | Por quê |
|---|---|---|
| Morpheus | **platform** | Orquestração universal |
| Athena | **platform** | PMBOK universal (PMO) |
| Oracle | **platform** | SIPOC metodologia universal |
| Mnemos | **platform** | RAG ingester (mecânica), opera per-task |
| HermesReporter | **platform** | SMTP delivery usando secrets do tenant |
| Hermes (IMAP) | tenant | Inbox específico do cliente |
| Mercator | tenant | Comercial específico do negócio |
| Plutus | tenant | Financeiro específico |
| Hodos | tenant | Logística específica (rotas, QUALP) |
| Kronos | tenant | Audit OFX específico |

### Roadmap macro (4 fases)

```
FASE A   FASE B   FASE C   FASE D
Vectra   Vectra   1º       Upsell P2
dogfood  dogfood  cliente  + Marketplace
P1       P2       externo  público
        (showcase)  P1
─────────────────────────────────────────► time
```

---

## 1. Módulo P1 — Consultoria de Mapeamento (MVP COMERCIAL)

### 1.1 Jornada vendável (8 etapas)

```
1. Sales: contrato de consultoria + cadastro Company
   ↓
2. Onboarding: setup do tenant + upload de documentos para RAG
   ↓
3. Org chart: organograma (setores + cargos + responsáveis)
   ↓
4. Identificação de processos: por setor, lista de tarefas + responsável de cada
   ↓
5. Discovery: cada responsável faz chat com Oracle (Oracle usa RAG da empresa)
   ↓
6. Diagnóstico Athena: gargalos + recomendação de automação por tarefa
   ↓
7. Relatório executivo: PDF + dashboard com ROI estimado
   ↓
8. Decisão do cliente: contratar P2 (modular, por processo)
```

### 1.2 Entidades core do P1

| Entidade | Tabela | Função |
|---|---|---|
| Company | `companies` | Tenant root |
| Usuários | `app_users` + roles novos | Consultor / decisor / responsável setorial |
| Setor | `sipoc_sectors` | Org chart |
| Cargo/Posição | `sipoc_positions` (hoje 0 rows!) | Quem responde por quê |
| Processo | `sipoc_processes` | Agrupador de atividades |
| Atividade | `sipoc_components` (kind=activity) | Tarefa específica + RACI + 5W2H |
| Edges | `sipoc_edges` | Fluxo entre componentes |
| RAG | `rag_documents` + `rag_chunks` | Contexto da empresa pro Oracle |
| Sessão Oracle | `_OracleSession` in-memory + `runs` persist | Chat de discovery (já existe state machine) |
| Diagnóstico | `athena_recommendations` | Output da Athena (já existe schema) |

### 1.3 Gap vs AS-IS

| Capability | AS-IS | TO-BE Gap |
|---|---|---|
| Cadastro de responsável por atividade | `sipoc_raci` (0 rows) | UI + flow de RACI obrigatório por activity |
| Login do responsável vê só suas atividades | RLS por company ✓ | RBAC role `tenant_user_sector` com filtro por position_id |
| Oracle chat com escopo de tarefa | Oracle chat existe genérico | Endpoint `/api/oracle/chat?activity_id=X` que pré-carrega contexto |
| RAG com upload massivo + tagging | `rag_documents` existe | UI de upload em lote (drag-drop), tagging por setor/processo |
| Relatório executivo PDF | `vectra-pdf` skill mencionada | Template PDF Athena: cover + sumário executivo + gargalos por setor + ROI por automação |
| Activity → operation_type | sem FK | `sipoc_components.suggested_operation_type` (sugerido por Athena no diagnóstico) |
| Classificação "automatizável/híbrido/manual" | `tasks.executor_type` existe pra task | `sipoc_components.automation_status` ∈ {automated, hybrid, manual, undefined} |
| Marketplace de templates SIPOC | hardcoded em Python (`SIPOC_TEMPLATES`) | Tabela `sipoc_taxonomy_global` (sem company_id) + UI de import |

### 1.4 Migrations específicas P1

```sql
-- 1. Responsável da atividade (RACI no campo + relação)
ALTER TABLE vectraclip.sipoc_components
  ADD responsible_position_id UUID REFERENCES vectraclip.sipoc_positions(id),
  ADD automation_status TEXT
    CHECK (automation_status IN ('undefined', 'manual', 'hybrid', 'automated')),
  ADD suggested_operation_type TEXT
    REFERENCES vectraclip.operation_types_catalog(slug),
  ADD diagnostic_metadata JSONB DEFAULT '{}';

-- 2. SIPOC taxonomy global (marketplace)
CREATE TABLE vectraclip.sipoc_taxonomy_global (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  vertical TEXT NOT NULL,  -- 'logistica', 'financeiro', 'fitness', ...
  category TEXT NOT NULL,  -- 'Contas a Pagar', 'Captação Leads', ...
  activity_name TEXT NOT NULL,
  default_5w2h JSONB,
  suggested_operation_type TEXT REFERENCES vectraclip.operation_types_catalog(slug),
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Track de clones do template (auditoria)
ALTER TABLE vectraclip.sipoc_components
  ADD cloned_from_template_id UUID REFERENCES vectraclip.sipoc_taxonomy_global(id);

-- 4. Diagnóstico Athena fica em athena_recommendations (já existe, só adicionar tipo)
ALTER TABLE vectraclip.athena_recommendations
  ADD recommendation_kind TEXT
    CHECK (recommendation_kind IN ('diagnose_gap', 'suggest_automation', 'suggest_hire_agent', 'prompt_adjust'))
    DEFAULT 'prompt_adjust';

-- 5. Responsável da app_users (role + scope)
ALTER TABLE vectraclip.app_users
  ADD role TEXT
    CHECK (role IN ('consultant', 'company_admin', 'sector_responsible', 'viewer'))
    DEFAULT 'company_admin',
  ADD assigned_position_id UUID REFERENCES vectraclip.sipoc_positions(id);
```

### 1.5 UI specs por tela (P1)

#### 1.5.1 `/onboarding` — Wizard inicial
```
Step 1: Dados da empresa (nome, vertical, tamanho)
Step 2: Upload de documentos (org chart PDF, manuais, descrições de cargos)
        → Mnemos ingest em background
Step 3: Convidar usuários iniciais (consultor, decisor)
Step 4: Selecionar templates de processos do marketplace (por vertical)
        → cria sipoc_processes + components inicial
Step 5: "Pronto — agora monte seu organograma"
```

#### 1.5.2 `/org-chart` — Organograma (substitui ou unifica com `/sipoc/setup`)
- Drag-drop hierárquico de setores → cargos → pessoas
- Cada cargo tem `assigned_user_id` (responsável)
- Botão "+ Setor" / "+ Cargo" em cada nó
- Visualização orgchart estilo Lucidchart

#### 1.5.3 `/sipoc/setor/:sector_id` — Processos de um setor
- Lista de `sipoc_processes` do setor
- Cada processo tem N atividades
- Coluna "Responsável" (do RACI)
- Coluna "Status discovery": não iniciado / em chat / mapeado
- Botão "Importar template" → seleciona `sipoc_taxonomy_global` por vertical

#### 1.5.4 `/sipoc/atividade/:activity_id` — Discovery individual
- Header: nome da atividade, setor, processo
- Quem pode acessar: responsável da atividade (role `sector_responsible` + position_id match) OU consultant
- Botão grande: **"💬 Discutir com Oracle"** → abre chat
- Oracle injeta no system prompt:
  - Contexto da empresa (RAG)
  - Setor + processo
  - 5W2H já preenchido (se houver)
  - Componentes vizinhos (suppliers/inputs/outputs/customers)
- Output progressivo: 5W2H + RACI + estimativa de tempo + frequência
- Botão "Salvar e voltar"

#### 1.5.5 `/diagnostico` — Athena entrega o veredito
- Trigger: consultant clica "Gerar diagnóstico" quando >80% atividades mapeadas
- Athena roda: `athena-audit` em todas activities → `athena-recommend` agregado
- Visualização:
  - Sumário executivo no topo (KPIs: # processos, # automatizáveis, ROI total estimado)
  - Lista por setor: cada activity com badge (automatizável/híbrido/manual) + custo atual vs custo automatizado
  - Botão "📄 Exportar PDF executivo" (template via `vectra-pdf`)
  - CTA: "Contratar P2 — Automação por processo →"

#### 1.5.6 `/marketplace/sipoc` — Templates universais
- Filtros: por vertical, por setor
- Card de cada template: nome, número de atividades, # empresas que usaram
- Botão "Importar pra minha empresa" → clona pro tenant
- Acesso: consultant + company_admin

### 1.6 SIPOC Marketplace (lançado com P1)

| Aspecto | Decisão |
|---|---|
| Sourcing | Inicial: você popula manualmente baseado em consultorias passadas. Depois: clientes contribuem (curated) |
| Modelo | Free pra uso, atribuição opcional |
| Verticais MVP | Logística + Financeiro (já tem hardcoded) + 1 escolha (Fitness?) |
| Atualização | Pull-based — clientes podem importar versão nova com merge manual |

### 1.7 Definition of Done — P1 vendável

- [ ] Onboarding wizard (5 steps) funcionando
- [ ] Org chart com setores + cargos + responsáveis (UI + DB)
- [ ] Marketplace SIPOC com 10+ templates universais
- [ ] Oracle chat per-atividade com RAG da empresa
- [ ] Login do responsável vê só suas atividades (RBAC)
- [ ] Diagnóstico Athena agregado
- [ ] Export PDF executivo
- [ ] Demo end-to-end na Vectra Cargo (Fase A do roadmap)

---

## 2. Módulo P2 — Automação Operacional (UPSELL)

### 2.1 Jornada (post-diagnóstico)

```
1. Cliente aprova diagnóstico do P1
   ↓
2. Per-automação aprovada:
   a. Athena recomenda agent (skill match + custo estimado)
   b. Cliente "contrata" agent → provisioning per-tenant
   c. Athena gera Goal a partir da activity
   d. Goal classificado: project (one-shot) ou routine (recorrente)
   e. Workflow montado (do zero OU clonado do marketplace)
   f. Steps configurados com agent + operation_type + inputs
   ↓
3. Operação rodando:
   - Workflow ativo → cria tasks → daemon executa → output
   - Telemetria de custo agregada por workflow, por goal
   - Dashboard com cost burn vs orçamento
   ↓
4. Ciclo de melhoria:
   - Athena monitora outputs + custos
   - Gera athena_recommendations (ajuste prompt, swap agent, etc.)
   - Cliente aprova via UI → mark-applied
```

### 2.2 Hierarquia (Goal → Workflow{kind} → Task)

```
GOAL
  ├─ Athena classifica via athena-classify (já implementado)
  ├─ Output: kind ∈ {project, routine}
  ↓
WORKFLOW (1:1 com Goal, exceto em casos especiais)
  ├─ kind herdado do goal
  ├─ steps com agent_id + operation_type
  ├─ trigger: scheduler (kind=routine) ou manual (kind=project)
  ↓
TASK (instância gerada pelo workflow step)
  ├─ workflow_definition_id ← FK nova
  ├─ workflow_step_id ← FK existente
  ├─ goal_id ← FK existente (denormalizada do workflow)
  ├─ company_id ← multi-tenant
```

**Resultado:** elimina `projects` como entidade separada. Project = Workflow com `kind=project` + charter no metadata. Reduz hierarquia de 4 níveis (Goal/Project/Routine/Workflow) pra 2 (Goal/Workflow).

### 2.3 Gap vs AS-IS

| Capability | AS-IS | TO-BE Gap |
|---|---|---|
| Goal vinculado a Workflow | sem FK | `workflow_definitions.goal_id` |
| Workflow classificado (project/routine) | sem campo | `workflow_definitions.kind` |
| Task aponta pro workflow inteiro | só `workflow_step_id` | `tasks.workflow_definition_id` |
| Step declara executor | inferido | `workflow_steps.assigned_to_agent_id` |
| Athena recomenda agent pra contratar | parcial | endpoint `POST /api/athena/suggest-hire` com input=activity_id, output=specialty + cost_estimate |
| Provisioning de agent per-tenant | criação manual | endpoint + UI `POST /api/agents/provision` |
| Workflow templates clonáveis | hardcoded | tabela `workflow_templates_global` + clone flow |
| Cost por workflow / por goal | só por task | views agregadas + dashboard |
| Routine "deprecada" como entity | `routines` table | refactor pra view sobre `workflow_definitions WHERE kind='routine'` (ou manter pra schedule fields) |

### 2.4 Migrations específicas P2

```sql
-- 1. Workflow vinculado a Goal + classificação
ALTER TABLE vectraclip.workflow_definitions
  ADD goal_id UUID REFERENCES vectraclip.goals(id),
  ADD kind TEXT CHECK (kind IN ('project', 'routine')),
  ADD charter JSONB,  -- escopo, milestones (kind=project)
  ADD schedule JSONB; -- cron + tz (kind=routine), migrar de routines.schedule

-- 2. Task aponta pro workflow inteiro
ALTER TABLE vectraclip.tasks
  ADD workflow_definition_id UUID REFERENCES vectraclip.workflow_definitions(id);

-- 3. Step declara executor
ALTER TABLE vectraclip.workflow_steps
  ADD assigned_to_agent_id UUID REFERENCES vectraclip.agents(id);

-- 4. Workflow templates (marketplace P2)
CREATE TABLE vectraclip.workflow_templates_global (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  vertical TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  recommended_kind TEXT CHECK (recommended_kind IN ('project', 'routine')),
  steps_definition JSONB NOT NULL,  -- array de steps com placeholders
  variable_schema JSONB,  -- JSON Schema das variáveis customizáveis
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. Track de clones
ALTER TABLE vectraclip.workflow_definitions
  ADD cloned_from_template_id UUID REFERENCES vectraclip.workflow_templates_global(id);

-- 6. Routines: manter como mecanismo de schedule, MAS adicionar workflow_definition_id obrigatório
--    (já existe! confirmar via list_tables verbose)
--    Se já existe, só garantir NOT NULL após backfill.

-- 7. Athena suggest-hire histórico
CREATE TABLE vectraclip.athena_hire_suggestions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES vectraclip.companies(company_id),
  triggered_by_activity_id UUID REFERENCES vectraclip.sipoc_components(id),
  triggered_by_goal_id UUID REFERENCES vectraclip.goals(id),
  suggested_specialty_id UUID REFERENCES vectraclip.agent_specialties(id),
  cost_estimate_usd NUMERIC,
  reasoning TEXT,
  status TEXT CHECK (status IN ('pending', 'approved', 'rejected', 'provisioned')) DEFAULT 'pending',
  approved_at TIMESTAMPTZ,
  provisioned_agent_id UUID REFERENCES vectraclip.agents(id),
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 2.5 UI specs P2

#### 2.5.1 `/goals` (rework) — Kanban estratégico
- Substituir lista plana atual por kanban por estado: `defined` / `classifying` / `in_execution` / `achieved` / `abandoned`
- Cada goal card: KPI, % progresso, kind badge, workflow ativo (se houver)
- Botão `+` em cada goal: "Adicionar workflow"

#### 2.5.2 `/goals/:id` — Detalhe + classificação Athena
- Form do Goal (nome, KPI, contexto)
- Card "Classificação Athena":
  - Se nunca classificado: botão "🤖 Classificar com Athena"
  - Se classificado: badge kind + confidence + business_case_strength
  - Action "Re-classificar"
- Card "Workflows vinculados": lista, com botão "+ Novo workflow"

#### 2.5.3 `/workflows/:id` — Canvas (já em construção VEC-381)
- Reusar canvas existente
- Adicionar: sidebar com `steps_definition` quando importado de template
- Botão "🤖 Athena: sugerir agent pra este step" → endpoint `suggest-hire`
- Validação: step não pode salvar sem `assigned_to_agent_id`

#### 2.5.4 `/marketplace/workflows` — Templates clonáveis
- Filtro por vertical + recommended_kind
- Card de cada template: passos, variáveis, estimativa de custo (média histórica)
- Botão "Importar" → modal preenche `variable_schema` → cria workflow no tenant

#### 2.5.5 `/agents/hire` — Provisionamento via Athena
- Lista de `athena_hire_suggestions` pendentes
- Cada card: specialty, custo estimado/mês, justificativa
- Botão "Contratar" → cria registro em `agents` (scope=tenant) + spawna daemon
- Botão "Rejeitar" → status=rejected, Athena aprende

#### 2.5.6 `/cost-analytics` (rework de `/analytics/cost`)
- Filtros: por goal, por workflow, por agent, por período
- Gráficos: cost over time, top operations, projection
- Alertas: "rotina X excedeu budget", "agent Y ficou ocioso 30 dias"

### 2.6 Workflow Marketplace (lançado com P2)

Aproveita estrutura criada pro SIPOC marketplace. Diferenças:
- Workflow templates **têm steps com placeholders** (varáveis substituídas no clone)
- `variable_schema` define o que precisa preencher pra usar
- Mostra histórico de uso (quantos clientes usaram, ROI médio)

### 2.7 Definition of Done — P2 vendável

- [ ] Workflow canvas funcional com `goal_id`, `kind`, agent atribuído em cada step
- [ ] `tasks.workflow_definition_id` populado em todas tasks novas (backfill nas antigas)
- [ ] `routines` migradas pra `workflow_definitions WHERE kind='routine'` (ou refactor cleaner)
- [ ] Endpoint `athena-suggest-hire` retorna specialty + cost estimate
- [ ] UI `/agents/hire` com provisioning fluxo completo
- [ ] Dashboard cost-analytics agregado por goal/workflow
- [ ] Marketplace de workflow templates com 5+ templates funcionais
- [ ] Demo end-to-end na Vectra Cargo (Fase B do roadmap)

---

## 3. Plataforma Transversal

### 3.1 Multi-tenant + RLS

**Estado atual:** maduro, com 3 gaps:

**P0 — RLS desabilitado em 3 tabelas (segurança):**
```sql
-- Tarefa: desenhar policies adequadas (NÃO rodar ENABLE sem policies)
ALTER TABLE vectraclip.kronos_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE vectraclip.agent_domains ENABLE ROW LEVEL SECURITY;
ALTER TABLE vectraclip.tasks_block_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_kronos ON vectraclip.kronos_rules
  USING (company_id = (
    SELECT company_id FROM vectraclip.app_users
    WHERE auth_user_id = auth.uid()
  ));

CREATE POLICY platform_read_agent_domains ON vectraclip.agent_domains FOR SELECT
  USING (auth.role() = 'authenticated');
```

**P1 — Telemetria sem retention:**
```sql
-- heartbeats: TTL 30d (sample retained), incidents: 90d (todos), incident_audit: arquivo trimestral
-- Implementar via pg_cron + procedure de archive
```

**P2 — Suporte a platform agents (company_id nullable + scope):**
ver Seção 3.2.

### 3.2 Agents: platform vs tenant (5+5)

**Migration central:**
```sql
ALTER TABLE vectraclip.agents
  ALTER COLUMN company_id DROP NOT NULL,
  ADD scope TEXT NOT NULL DEFAULT 'tenant'
    CHECK (scope IN ('platform', 'tenant')),
  ADD billing_model TEXT
    CHECK (billing_model IN ('included', 'per_token', 'flat_monthly')),
  ADD provisioned_from_suggestion_id UUID
    REFERENCES vectraclip.athena_hire_suggestions(id);

-- Tag dos 5 platform agents
UPDATE vectraclip.agents
  SET company_id = NULL, scope='platform', billing_model='included'
  WHERE id IN (
    '00000000-0000-0000-0000-000000000001', -- Morpheus
    '00000000-0000-0000-0000-000000000002', -- Oracle
    '00000000-0000-0000-0000-000000000003', -- Mnemos
    'ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d', -- Athena
    '360a96cb-b1c3-4b65-b9fa-2b9cbb59dac1'  -- HermesReporter
  );

-- RLS pra agents (permitir leitura de platform + tenant próprio)
DROP POLICY IF EXISTS tenant_isolation_agents ON vectraclip.agents;
CREATE POLICY agents_visibility ON vectraclip.agents FOR SELECT USING (
  scope = 'platform' OR
  company_id = (SELECT company_id FROM vectraclip.app_users WHERE auth_user_id = auth.uid())
);
```

**Implicações operacionais:**

| Aspecto | Platform agents | Tenant agents |
|---|---|---|
| Quantidade de processos | 1 daemon global por agent (5 total) | N daemons (1 por tenant) |
| Lock | `.daemon_locks/<AGENT_ID>.lock` único | `.daemon_locks/<AGENT_ID>-<company_id>.lock` |
| Cost attribution | `tasks.cost_usd` por `company_id` da task | Idem (consistente) |
| Throttling | Fila per-tenant ou rate-limit por company_id | Natural (cada tenant tem seu) |
| Prompt customization | Imutável via UI (PR no repo) | Editável via NAV ADMIN |
| Onboarding | Sempre disponível ao novo tenant | Provisionado on-demand via `/agents/hire` |

**Backend changes:**
- `agent_daemon.py` precisa diferenciar platform vs tenant na hora de fetchar task (platform daemon polla `WHERE company_id IS NOT NULL` agnostic; tenant daemon polla `WHERE company_id = $1`)
- `start_all_daemons.py` precisa lógica: spawna 5 platform globais + N×5 tenant por cliente

### 3.3 NAV ADMIN (já existe — só ajuste de hierarquia visual)

Páginas atuais (`/admin/*`) são corretas em escopo. Ajustes:

| Mudança | Por quê |
|---|---|
| Adicionar coluna "scope" em `/admin/agent-builder` | Distingue platform vs tenant na UI |
| Esconder platform agents do "Hire Dialog" tenant-side | Cliente não "contrata" Morpheus |
| Adicionar tab "Templates" em `/admin/specialties` | Ver quais specialties tem template global vs custom |
| `/admin/cost-policies` (nova) | Configurar billing_model + token budget por agent |

### 3.4 Athena PMO (motor central)

**Endpoints novos:**
- `POST /api/athena/diagnose/{sector_id}` — agregação de todas activities do setor + recommendations
- `POST /api/athena/suggest-hire` — entrada: activity_id ou goal_id; saída: specialty + cost_estimate + reasoning
- `POST /api/athena/charter/{goal_id}` — gera charter PMBOK (kind=project)
- `POST /api/athena/monitor` — job periódico, analisa heartbeats + outputs, gera recommendations

**Operation types adicionais:**
- `athena-suggest-hire`
- `athena-monitor` (background)
- `athena-cost-review`

### 3.5 Telemetria & Cost

**Hoje:** `heartbeats` (139k), `incidents` (36k), `tasks.cost_usd` per-task.

**TO-BE:**
- Views materializadas `vw_cost_by_goal`, `vw_cost_by_workflow`, `vw_cost_by_agent_period`
- Retention: heartbeats 30d (sample), incidents 90d, audit archive trimestral
- Alerts via Athena monitor:
  - Rotina excede 120% do budget
  - Agent ocioso 30+ dias
  - Operation_type com >10% incident rate
  - Cost trending up >15% MoM

### 3.6 Auth & RBAC

**Roles novos em `app_users.role`:**

| Role | Pode | Não pode |
|---|---|---|
| `platform_admin` | Tudo (você) | — |
| `consultant` | Acesso multi-tenant (sessões guiadas) | — |
| `company_admin` | CRUD completo do próprio tenant | Ver outros tenants |
| `sector_responsible` | Ver/editar atividades do próprio setor/cargo (`position_id`) | Outros setores |
| `viewer` | Read-only do próprio tenant | Editar |

**JWT claims (Supabase):**
```json
{
  "sub": "user_uuid",
  "company_id": "tenant_uuid",  // null se platform_admin
  "role": "sector_responsible",
  "position_id": "uuid"  // só se sector_responsible
}
```

**RLS policies que dependem disso:**
```sql
-- Activities: sector_responsible só vê do próprio cargo
CREATE POLICY activity_sector_scope ON vectraclip.sipoc_components FOR SELECT
  USING (
    auth.jwt()->>'role' IN ('platform_admin', 'consultant', 'company_admin') OR
    (auth.jwt()->>'role' = 'sector_responsible' AND
     responsible_position_id = (auth.jwt()->>'position_id')::uuid)
  );
```

---

## 4. Roadmap de migração (4 fases)

### Fase A — Vectra dogfood P1 (3-4 semanas)
**Objetivo:** ter SIPOC discovery + Athena diagnostic + relatório PDF rodando end-to-end pra Vectra Cargo.

| PR | Escopo | Crítico |
|---|---|---|
| 1 | Migration: schema RLS (kronos_rules, agent_domains, tasks_block_log) | Segurança |
| 2 | Migration P1 (sipoc_components extra cols + sipoc_taxonomy_global + app_users role) | Base estrutural |
| 3 | Backend: endpoints SIPOC taxonomy + clone-to-tenant | Marketplace base |
| 4 | Backend: Oracle chat scoped per-activity (?activity_id=X) | Discovery UX |
| 5 | Frontend: `/org-chart` melhorado | Onboarding UX |
| 6 | Frontend: `/sipoc/setor/:id` + `/sipoc/atividade/:id` | Discovery UX |
| 7 | Frontend: RBAC `sector_responsible` (rota guards) | Multi-user |
| 8 | Frontend: `/marketplace/sipoc` + import flow | Marketplace |
| 9 | Backend: Athena agregador `/api/athena/diagnose/{sector_id}` | Diagnóstico |
| 10 | Frontend: `/diagnostico` page + PDF export | Entrega |
| 11 | Seed: 10+ templates universais (vertical logística + financeiro + fitness) | Marketplace |
| 12 | Vectra Cargo: rodar workflow completo + ajustes | Validação |

### Fase B — Vectra dogfood P2 (3-4 semanas)
**Objetivo:** automatizar ao menos 2 processos da Vectra com Workflow → Task → Cost.

| PR | Escopo |
|---|---|
| 1 | Migration P2 (workflow_definitions.goal_id, .kind, tasks.workflow_definition_id, etc.) |
| 2 | Migration: agents.scope + 5 platform tag |
| 3 | Backend: athena-suggest-hire endpoint |
| 4 | Backend: agent provisioning endpoint |
| 5 | Frontend: `/goals` rework kanban + classify button |
| 6 | Frontend: workflow canvas finalização (VEC-381) + suggest-hire |
| 7 | Frontend: `/agents/hire` page |
| 8 | Frontend: `/cost-analytics` rework |
| 9 | Backend: views materializadas de cost |
| 10 | Backend: Athena monitor (job periódico) |
| 11 | Marketplace workflow templates seed (5+) |
| 12 | Vectra Cargo: 2 automações end-to-end (ex: audit OFX + lead enrich) |

### Fase C — Primeiro cliente externo P1 (2-3 semanas)
**Objetivo:** vender P1 standalone pra cliente novo + sessão guiada.

| PR | Escopo |
|---|---|
| 1 | Sales site/landing pra P1 |
| 2 | Onboarding wizard polido (5 steps) |
| 3 | Email templates onboarding + reminders |
| 4 | Audit log + compliance básico (LGPD) |
| 5 | Billing integration (Stripe? Asaas?) — projeto-fechado |
| 6 | Deploy stack pro novo tenant (provisioning script) |
| 7 | Sessão guiada com 1º cliente externo |

### Fase D — Upsell P2 + Marketplace público (4-6 semanas)
**Objetivo:** converter P1 em P2 + abrir marketplace pra comunidade.

| PR | Escopo |
|---|---|
| 1 | Upsell flow (do `/diagnostico` pro `/agents/hire` direto) |
| 2 | Marketplace público (SIPOC + Workflow templates submissões) |
| 3 | Curadoria de templates (approval flow) |
| 4 | Atribuição/contribuição (autor + clones count) |
| 5 | Cost forecasting Athena (pré-aprovação automação) |
| 6 | 2º+ cliente externo (full P1+P2) |

---

## 5. Schema changes consolidados (ordem de execução)

```sql
-- ============================
-- FASE A (P1 + Plataforma P0)
-- ============================

-- A1. Segurança RLS (PR1)
ALTER TABLE vectraclip.kronos_rules     ENABLE ROW LEVEL SECURITY;
ALTER TABLE vectraclip.agent_domains    ENABLE ROW LEVEL SECURITY;
ALTER TABLE vectraclip.tasks_block_log  ENABLE ROW LEVEL SECURITY;
-- + policies por table (ver Seção 3.1)

-- A2. P1 core (PR2)
ALTER TABLE vectraclip.sipoc_components
  ADD responsible_position_id UUID REFERENCES vectraclip.sipoc_positions(id),
  ADD automation_status TEXT CHECK (automation_status IN ('undefined','manual','hybrid','automated')),
  ADD suggested_operation_type TEXT REFERENCES vectraclip.operation_types_catalog(slug),
  ADD diagnostic_metadata JSONB DEFAULT '{}',
  ADD cloned_from_template_id UUID;

CREATE TABLE vectraclip.sipoc_taxonomy_global (...);

ALTER TABLE vectraclip.athena_recommendations
  ADD recommendation_kind TEXT CHECK (...) DEFAULT 'prompt_adjust';

ALTER TABLE vectraclip.app_users
  ADD role TEXT CHECK (role IN ('platform_admin','consultant','company_admin','sector_responsible','viewer')) DEFAULT 'company_admin',
  ADD assigned_position_id UUID REFERENCES vectraclip.sipoc_positions(id);

-- ============================
-- FASE B (P2 + Plataforma P1+P2)
-- ============================

-- B1. Hierarquia Goal→Workflow→Task
ALTER TABLE vectraclip.workflow_definitions
  ADD goal_id UUID REFERENCES vectraclip.goals(id),
  ADD kind TEXT CHECK (kind IN ('project','routine')),
  ADD charter JSONB,
  ADD schedule JSONB,
  ADD cloned_from_template_id UUID;

ALTER TABLE vectraclip.tasks
  ADD workflow_definition_id UUID REFERENCES vectraclip.workflow_definitions(id);

ALTER TABLE vectraclip.workflow_steps
  ADD assigned_to_agent_id UUID REFERENCES vectraclip.agents(id);

-- B2. Marketplace P2
CREATE TABLE vectraclip.workflow_templates_global (...);

-- B3. Agents platform vs tenant
ALTER TABLE vectraclip.agents
  ALTER COLUMN company_id DROP NOT NULL,
  ADD scope TEXT NOT NULL DEFAULT 'tenant' CHECK (scope IN ('platform','tenant')),
  ADD billing_model TEXT CHECK (billing_model IN ('included','per_token','flat_monthly')),
  ADD provisioned_from_suggestion_id UUID;

CREATE TABLE vectraclip.athena_hire_suggestions (...);

-- B4. Cost views
CREATE MATERIALIZED VIEW vectraclip.vw_cost_by_goal AS ...
CREATE MATERIALIZED VIEW vectraclip.vw_cost_by_workflow AS ...

-- ============================
-- FASE C (multi-tenant prod)
-- ============================
-- TTL e archive policies, audit_log extension, billing integration
```

---

## 6. Sidebar TO-BE reorganizado

```
─── Estratégia ───
  📊 Goals
  🎯 Diagnóstico Athena

─── Discovery ───
  🏢 Organograma
  🗺️ Processos SIPOC
  📚 Knowledge Base (RAG)

─── Operação ───
  ⚙️ Workflows (canvas)
  ✅ Tasks
  💰 Cost Analytics

─── Marketplace ───
  📋 Templates SIPOC
  🔄 Templates Workflows
  🤝 Hire Agent

─── Setor / Time (visível conforme role) ───
  📥 Inbox (sector_responsible)
  📊 Meu Setor (sector_responsible)

─── Admin (platform_admin + company_admin) ───
  🤖 Agent Builder
  🧠 LLM Models
  🎓 Especialidades
  🔌 Conectores

─── Dev (hidden em prod) ───
  Themes / DesignPreview / FlowLogic patterns docs
```

**Tirado:** Workflow / Workflow 2 / Workflow Ops (consolida em "Workflows"). 6 entries de flow-logic vai pra docs. Templates de pesquisa fica em Marketplace.

---

## 7. Riscos, trade-offs e decisões em aberto

### Riscos prioritários

| # | Risco | Impacto | Mitigação |
|---|---|---|---|
| 1 | Vectra Cargo dogfood toma tempo de feature dev | Atrasa P1 vendável | Definir cap de horas/semana em Vectra |
| 2 | Telemetria explode em prod multi-tenant | DB cresce sem controle | Retention policies já na Fase B |
| 3 | Athena cost attribution errada entre tenants | Cliente disputa fatura | Auditoria + dashboard transparente |
| 4 | Workflow canvas (VEC-381) não fica pronto | Bloqueia P2 | Plano B: forms wizard sem canvas |
| 5 | Marketplace vazio = não vende valor | P1 perde diferencial | Seed manual de 10+ templates antes de lançar |

### Trade-offs aceitos

| Decisão | Trade-off |
|---|---|
| Eliminar tabela `projects` (vira Workflow kind=project) | Perde hipótese de Project sem Workflow. Aceitamos: todo project tem ao menos 1 workflow |
| 5 platform agents | Mais throttling/contenção. Vale pela simplicidade comercial |
| Marketplace junto com P1 | Mais escopo no MVP. Vale pelo social proof na venda |
| Sidebar reorganizado tira coisas que existem | Devs precisam reaprender navegação. Vale pela clareza |

### Decisões ainda em aberto

| Decisão | Quando decidir |
|---|---|
| Conector CFN: SDK próprio ou via HTTP genérico? | Quando 2º cliente externo entrar (ver se padrão se repete) |
| Pricing P1: projeto fechado vs success fee? | Antes do 1º cliente externo |
| Pricing P2: token-pass-through vs flat + cap? | Antes da Fase D |
| Marketplace público: governance/curadoria? | Antes da Fase D |
| Substituir/extender Workflow Canvas (VEC-381) ou aproveitar n8n embed? | Início da Fase B |
| Deprecar tabela `projects` agora ou manter view de compat? | Início da Fase B |
| Mnemos opera per-task ou per-tenant? | Validar com load real |

---

## Apêndice — checklist de validação do desenho

- [ ] As 5 decisões A1-E1 estão refletidas em todas seções
- [ ] Platform vs tenant agents (5+5) documentado em pelo menos 3 lugares
- [ ] Cada Capability tem migration + UI + endpoint
- [ ] Roadmap 4 fases não tem gaps lógicos
- [ ] RLS issues do AS-IS tratados na Fase A
- [ ] Marketplace lançado no P1 (não fica pra depois)
- [ ] Hierarchy Goal → Workflow → Task substitui Goal → Project → Routine → Task
- [ ] Documentado o que se elimina (projects table) e o que ganha (workflow.kind)

**Aprovação necessária antes de começar PRs:**
- Sócio/decisor: roadmap macro (4 fases)
- Você (técnico): migrations consolidadas (Seção 5)
- Designer/UI (se houver): sidebar reorganizado + UI specs P1 (Seção 1.5)
