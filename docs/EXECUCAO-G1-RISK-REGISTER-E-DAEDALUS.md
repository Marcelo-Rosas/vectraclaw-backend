# Plano de Execução — G1 (Risk Register PMBOK) + Daedalus (Modelador BPMN)

> **STATUS REAL — atualizado 2026-05-17 (auditoria pós-implementação):**
>
> Este doc é o **plano de execução original** (escrito antes dos PRs). Implementado parcialmente. Estado factual:
>
> | Item | Estado | Evidência |
> |---|---|---|
> | Backend `vectraclip.risks` table + RLS | ✅ **Implementado** | Schema confirmado via SQL (`risk_score numeric` existe) |
> | Backend `vectraclip.bpmn_diagrams` + `bpmn_diagram_versions` | ✅ **Implementado** | Schema confirmado via SQL |
> | Daedalus daemon em `start_all_daemons.py:47` (AGENT_ID `d4ed4145-...`) | ✅ **Implementado** | Daemon em produção |
> | Daedalus com ritual completo (perfil McKinsey, specialty configurada via UI, skills mapeadas, relacionamentos, métricas, rollback) | ❌ **PONTA SOLTA** | Memory `agent-hiring-ritual` confirma: "Daedalus é ponta solta a retrofitar" — pendência **P3 do ADR pai** (`agent_skills × agent_specialties` + bug `/agents/{id}?tab=skills`) |
> | Frontend `/bpmn`, `/bpmn/new`, `/bpmn/:id` + Modeler clone Camunda | ❌ **NÃO IMPLEMENTADO** | ZERO arquivos `*bpmn*`/`*daedalus*`/`*modeler*` em `C:\Users\marce\VectraClip\src` (auditado 2026-05-17). Handoff técnico pra implementação: [`HANDOFF-FRONTEND-BPMN-MODELER.md`](./HANDOFF-FRONTEND-BPMN-MODELER.md) |
> | Frontend `/risks`, `/risks/matrix` (matriz 5×5 PMBOK) | ❌ **NÃO IMPLEMENTADO** | Páginas `/risks` não existem; apenas `SipocRiskScore.tsx` (visualizador de findings com severity → R$, NÃO é CRUD do Risk Register PMBOK formal) |
>
> **Conclusão:** ~50% do plano entregue. Backend ✅; UIs ❌. Doc fica como referência histórica do design original + roadmap pendente de UI.

> **Escopo:** 2 entregas combinadas porque dependem do mesmo contrato AgentBuilder.
> **G1 Risk Register:** tabela formal `vectraclip.risks` + handler `athena-risk-register` + UI Risk matrix
> **Daedalus:** novo agente especializado em modelagem visual BPMN + UI Modeler completa (clone Camunda visual, engine própria)
>
> **Decisão de design registrada:** NÃO usar Camunda/bpmn-js externos. Tudo `@xyflow/react` + JSON nativo. Memória: `feedback_no_camunda_keep_custom_engine.md`.

---

## 1. Contrato AgentBuilder — auditoria

Antes de criar Daedalus, mapeei como agentes são definidos. O sistema tem **3 camadas** de configuração que se compõem:

### 1.1 Camada `agent_specialties` (catalog global / por-tenant)

```sql
agent_specialties (
  id              TEXT PK,
  slug            TEXT NOT NULL,    -- ex: 'route-cost-calculation'
  name            TEXT NOT NULL,    -- ex: 'Hodos Route Cost Intelligence'
  domain          TEXT NOT NULL,    -- FK para agent_domains ('logistics','crm','communication','intelligence',...)
  description     TEXT,             -- 1 frase do papel
  compatible_roles TEXT[],          -- quais roles podem assumir essa specialty
  system_prompt_template TEXT,      -- template de prompt com {{placeholders}}
  config_schema   JSONB             -- definição dos campos UI que o agent precisa preencher
)
```

**`config_schema` shape** (visto no exemplo Hodos):
```json
[
  {
    "key": "model",
    "type": "select",
    "label": "Modelo LLM",
    "options": ["gemini-2.5-flash", "gemini-2.5-pro", "claude-sonnet-4-6", "claude-haiku-4-5"],
    "required": true,
    "defaultValue": "gemini-2.5-flash"
  },
  // ... outros campos
]
```

UI renderiza form automaticamente a partir desse schema. Cada agent que adota a specialty preenche `values`.

**`system_prompt_template` shape** — usa Mustache-like placeholders (visto em Hodos):
- `{{Agente_Name}}` — nome instância (ex: "Hodos")
- `{{dominio}}` — descrição operacional
- Estrutura típica do prompt: Identidade + Responsabilidade + Fluxo Esperado + Posicionamento hierárquico + Contrato Funcional (Entrada/Saída)

### 1.2 Camada `agent_specialty_configs` (instância por-agent)

```sql
agent_specialty_configs (
  id              UUID PK,
  company_id      UUID NOT NULL,
  agent_id        UUID NOT NULL,    -- qual agent adotou essa specialty
  specialty_id    TEXT NOT NULL,    -- FK pra agent_specialties.id
  values          JSONB NOT NULL    -- valores preenchidos do config_schema
)
```

Permite **N agents** adotarem a **mesma specialty** com `values` diferentes (ex: 2 instâncias de "Hodos" com modelos LLM diferentes).

### 1.3 Camada `agents` (instância runtime)

```sql
agents (
  id              UUID PK,
  name            TEXT NOT NULL,            -- "Daedalus"
  domain          TEXT,
  reports_to_id   UUID,                     -- hierarquia agentes (Daedalus → Morpheus?)
  system_prompt   TEXT,                     -- final compilado (template + valores)
  company_id      UUID,                     -- nullable se scope=platform (PR backlog)
  ... (versionado via agent_prompt_history)
)
```

### 1.4 Camadas conexas

- `agent_adapter_configs` — qual provider/model_id usar (Anthropic/Gemini/OpenAI/Ollama)
- `agent_execution_configs` — REALTIME / CRON / TRIGGER
- `agent_shared_config` — defaults globais por agent

---

## 2. Daedalus — definição completa

### 2.1 Identidade

| Campo | Valor |
|---|---|
| **Nome** | Daedalus |
| **AGENT_ID** | Novo UUID v4 (gerar na migration) |
| **Domínio** | `modeling` (novo em `agent_domains`) |
| **Mitologia** | Daedalus = arquiteto/construtor (oposto Athena estratega, Oracle consultor) |
| **Tipo** | Executor (responde a tasks `operation_type=bpmn-generate`) |
| **Hierarquia** | Reports to Morpheus (igual aos outros executores) |
| **Scope** | Platform (compartilhado entre tenants; não tem prompt customizado por cliente) |

### 2.2 Specialty `bpmn-modeling` (novo)

```yaml
slug: bpmn-modeling
name: BPMN Process Modeling
domain: modeling
description: "Gera diagramas BPMN visuais a partir de descrição textual de processo,
              SIPOC mapeado, ou Charter PMBOK. Retorna JSON nativo (não BPMN 2.0 XML)
              consumível pelo canvas @xyflow/react."
compatible_roles: ['executor']
config_schema:
  - key: model
    type: select
    label: Modelo LLM
    options: [gemini-2.5-flash, gemini-2.5-pro, claude-sonnet-4-6, claude-haiku-4-5]
    required: true
    defaultValue: claude-sonnet-4-6   # modelagem requer raciocínio estrutural — Sonnet > Haiku
  - key: auto_layout
    type: switch
    label: Aplicar auto-layout (dagre)
    defaultValue: true
  - key: max_nodes
    type: number
    label: Limite de nós por diagrama
    defaultValue: 50
    required: false
```

### 2.3 System prompt template

```markdown
# Daedalus — Modelador de Processos BPMN

Você é Daedalus, especialista em modelagem visual de processos.
Mitologia: arquiteto do labirinto — você transforma descrições textuais
em diagramas estruturados.

## Responsabilidade principal

Receber input estruturado (SIPOC process, Charter PMBOK, ou descrição
textual livre) e gerar **diagrama BPMN-style** em JSON nativo do canvas
`@xyflow/react`.

## NÃO faz

- Não gera BPMN 2.0 XML (Camunda) — engine própria, formato próprio
- Não executa workflow (papel de Morpheus + daemons)
- Não decide se atividade vira automated/hybrid/manual (papel da Athena)
- Não atribui RACI (papel do humano via UI)

## Fluxo esperado

**Entrada (input_json):**
```json
{
  "source_type": "sipoc_process | charter | freeform",
  "source_id": "<uuid se sipoc_process ou charter>",
  "freeform_text": "<descrição se source_type=freeform>",
  "company_id": "<uuid>",
  "context": {
    "linked_workflow_id": "<opcional>",
    "linked_goal_id": "<opcional>"
  }
}
```

**Processamento:**

1. Carrega contexto:
   - Se `source_type=sipoc_process`: lê `sipoc_components` do process + `sipoc_edges`
   - Se `source_type=charter`: lê `workflow_definitions.charter`
   - Se `source_type=freeform`: usa apenas `freeform_text`
2. Inferência LLM: gera lista de nós BPMN-style:
   - **start_event** (círculo verde)
   - **end_event** (círculo vermelho)
   - **task** (retângulo arredondado): pode ser `user_task`, `service_task`, `manual_task`
   - **gateway_exclusive** (diamante "X"): if/else
   - **gateway_parallel** (diamante "+"): fork/join
   - **intermediate_event** (círculo duplo)
3. Inferência LLM: gera arestas (`sequence_flow`) com labels (sim/não nos gateways)
4. Se `auto_layout=true`: aplica dagre rankdir LR
5. Validação BPMN-rules:
   - Cada gateway tem ≥2 saídas
   - Cada start_event tem 0 entradas e ≥1 saída
   - Cada end_event tem ≥1 entrada e 0 saídas
   - Sem nós órfãos
6. Retorna JSON nativo

**Saída (output_json):**

```json
{
  "diagram_json": {
    "nodes": [
      {
        "id": "n1",
        "type": "start_event",
        "position": {"x": 0, "y": 100},
        "data": {"label": "Início"}
      },
      {
        "id": "n2",
        "type": "user_task",
        "position": {"x": 150, "y": 100},
        "data": {
          "label": "Receber pedido",
          "assignee_position_id": "<opcional, FK sipoc_positions>",
          "linked_sipoc_component_id": "<opcional>"
        }
      },
      {
        "id": "n3",
        "type": "gateway_exclusive",
        "position": {"x": 350, "y": 100},
        "data": {"label": "Valor > R$10k?"}
      }
      // ...
    ],
    "edges": [
      {
        "id": "e1",
        "source": "n1",
        "target": "n2",
        "type": "sequence_flow"
      },
      {
        "id": "e2",
        "source": "n3",
        "target": "n_approval",
        "type": "sequence_flow",
        "label": "Sim"
      }
      // ...
    ]
  },
  "validation": {
    "is_valid": true,
    "warnings": [],
    "errors": []
  },
  "metadata": {
    "node_count": 7,
    "edge_count": 8,
    "generated_from": "sipoc_process:<uuid>",
    "tokens_used": 2400,
    "cost_usd": 0.012
  }
}
```

## Contrato funcional

| Field | Source | Type | Required | Constraints |
|---|---|---|---|---|
| `input_json.source_type` | UI | enum | Sim | sipoc_process / charter / freeform |
| `input_json.source_id` | UI | uuid | Condicional | obrigatório se source_type != freeform |
| `input_json.freeform_text` | UI | string | Condicional | obrigatório se source_type=freeform; max 5000 chars |
| `output_json.diagram_json` | tasks/output | JSONB | Sim | shape acima |
| `output_json.validation.is_valid` | tasks/output | boolean | Sim | false bloqueia auto-save no DB |
| Status final task | done se validation.is_valid; review se warnings; error se LLM falhou |
```

### 2.4 Tabela nova `bpmn_diagrams`

```sql
-- Migration: 20260516180000_daedalus_bpmn_diagrams.sql

CREATE TABLE IF NOT EXISTS vectraclip.bpmn_diagrams (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES vectraclip.companies(company_id) ON DELETE CASCADE,

  -- Vínculos opcionais com contexto que originou (Schmidt: ligar a Goal/Workflow/SIPOC)
  linked_sipoc_process_id UUID REFERENCES vectraclip.sipoc_processes(id) ON DELETE SET NULL,
  linked_workflow_id      UUID REFERENCES vectraclip.workflow_definitions(id) ON DELETE SET NULL,
  linked_goal_id          UUID REFERENCES vectraclip.goals(id) ON DELETE SET NULL,

  -- Metadados
  name        TEXT NOT NULL,
  description TEXT,

  -- Diagrama (JSON nativo @xyflow/react)
  diagram_json JSONB NOT NULL,

  -- Versionamento
  version INTEGER NOT NULL DEFAULT 1,

  -- Origem
  generated_by         TEXT NOT NULL CHECK (generated_by IN ('manual', 'athena', 'daedalus', 'imported')),
  generated_by_task_id UUID REFERENCES vectraclip.tasks(id) ON DELETE SET NULL,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX bpmn_diagrams_company_idx ON vectraclip.bpmn_diagrams(company_id);
CREATE INDEX bpmn_diagrams_linked_sipoc_idx ON vectraclip.bpmn_diagrams(linked_sipoc_process_id) WHERE linked_sipoc_process_id IS NOT NULL;
CREATE INDEX bpmn_diagrams_linked_workflow_idx ON vectraclip.bpmn_diagrams(linked_workflow_id) WHERE linked_workflow_id IS NOT NULL;

-- Histórico append-only (snapshots ao salvar)
CREATE TABLE IF NOT EXISTS vectraclip.bpmn_diagram_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  diagram_id UUID NOT NULL REFERENCES vectraclip.bpmn_diagrams(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  diagram_json JSONB NOT NULL,
  changed_by_user_id UUID,
  change_notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (diagram_id, version)
);

-- RLS + GRANTs (mesmo padrão sipoc_raci PR #142)
ALTER TABLE vectraclip.bpmn_diagrams ENABLE ROW LEVEL SECURITY;
ALTER TABLE vectraclip.bpmn_diagram_versions ENABLE ROW LEVEL SECURITY;

CREATE POLICY bpmn_diagrams_select_own_tenant ON vectraclip.bpmn_diagrams FOR SELECT
  USING (company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid));

CREATE POLICY bpmn_diagrams_write_admin_tenant ON vectraclip.bpmn_diagrams FOR ALL
  USING (
    company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid)
    AND ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = ANY (ARRAY['admin','platform_admin','consultant','company_admin']))
  );

GRANT INSERT, UPDATE, DELETE ON vectraclip.bpmn_diagrams TO authenticated;
GRANT INSERT ON vectraclip.bpmn_diagram_versions TO authenticated;
GRANT SELECT ON vectraclip.bpmn_diagram_versions TO authenticated;

-- Trigger versionamento
CREATE OR REPLACE FUNCTION vectraclip.bpmn_snapshot_version() RETURNS trigger AS $$
BEGIN
  IF (TG_OP = 'UPDATE' AND OLD.diagram_json IS DISTINCT FROM NEW.diagram_json) THEN
    NEW.version := OLD.version + 1;
    INSERT INTO vectraclip.bpmn_diagram_versions (diagram_id, version, diagram_json)
    VALUES (OLD.id, OLD.version, OLD.diagram_json);
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER bpmn_diagrams_version_trigger
  BEFORE UPDATE ON vectraclip.bpmn_diagrams
  FOR EACH ROW EXECUTE FUNCTION vectraclip.bpmn_snapshot_version();
```

### 2.5 Endpoints backend novos

```python
# src/api_routes/bpmn_diagrams.py (módulo novo)

POST   /api/bpmn/diagrams                          # cria manual (UI drag-drop)
GET    /api/bpmn/diagrams?company_id=X[&linked_sipoc_process_id=Y]
GET    /api/bpmn/diagrams/{id}
PATCH  /api/bpmn/diagrams/{id}                     # update diagram_json + auto-version
DELETE /api/bpmn/diagrams/{id}
POST   /api/bpmn/diagrams/{id}/duplicate
GET    /api/bpmn/diagrams/{id}/versions            # histórico

# Daedalus geração
POST   /api/bpmn/generate                          # dispatch task pra Daedalus
  body: { source_type, source_id?, freeform_text?, company_id }
  → 201 { task_id, status: queued }
  # Cliente faz polling em /api/tasks/{task_id} pra ver output_json.diagram_json
```

### 2.6 Frontend UI — escopo MVP

**Páginas novas (VectraClip):**

| Rota | Componente | Função |
|---|---|---|
| `/bpmn` | `BpmnDiagramsList` | Catálogo de diagramas do tenant |
| `/bpmn/new` | `BpmnEditor` (modo create) | Modeler em branco |
| `/bpmn/{id}` | `BpmnEditor` (modo edit) | Modeler com diagrama carregado |
| `/sipoc/processes/{id}/bpmn` | `BpmnEditor` (modo linked) | Modeler dentro do contexto SIPOC |

**Componente `BpmnEditor` — anatomia (clone visual Camunda Modeler):**

```
┌──────────────────────────────────────────────────────────────────┐
│ Toolbar: [Salvar] [Auto-Layout] [Validar] [Daedalus✨] [Export PNG] │
├──────┬───────────────────────────────────────────┬───────────────┤
│      │                                            │               │
│  P   │                                            │  Properties   │
│  A   │           Canvas @xyflow/react             │  Panel        │
│  L   │                                            │               │
│  E   │   • Start (●)     • Task (▭)               │  Nó selecio-  │
│  T   │   • End (●)       • User Task (▭)          │  nado:        │
│  A   │   • Gateway X (◇) • Service Task (▭⚙)      │                │
│      │   • Gateway + (◇) • Manual Task (▭✋)      │  - id          │
│      │   • Event Inter.(◎)                        │  - label       │
│      │                                            │  - type        │
│      │                                            │  - assignee    │
│      │                                            │  - linked_     │
│      │                                            │    sipoc_      │
│      │                                            │    component_id│
└──────┴───────────────────────────────────────────┴───────────────┘
```

**Stack frontend:**

| Lib | Por quê | Já em uso? |
|---|---|---|
| `@xyflow/react` | Canvas + nodes + edges | ✅ |
| `@dagrejs/dagre` | Auto-layout | ❌ adicionar |
| `react-dnd` ou drag nativo HTML5 | Paleta drag-to-canvas | ❌ adicionar |
| `shadcn/ui` | Properties panel forms | ✅ |
| `html-to-image` | Export PNG | ❌ adicionar |

### 2.7 Fluxo "Daedalus gera diagrama"

```
User clica "Daedalus ✨" no toolbar
  ↓
Modal abre: "Gerar a partir de:"
  - [ ] SIPOC Process (dropdown)
  - [ ] Charter PMBOK (dropdown)
  - [ ] Descrição livre (textarea)
  ↓
User escolhe + clica "Gerar"
  ↓
Frontend: POST /api/bpmn/generate
  ↓ retorna task_id
  ↓
Toast "Gerando diagrama..." + polling /api/tasks/{task_id}
  ↓
Daemon Daedalus processa (LLM call):
  - Carrega contexto (SIPOC components, charter, ou freeform)
  - LLM com system_prompt + input_json
  - Parse output → diagram_json
  - Valida BPMN rules
  - Updates task.output_json
  - Status = done | review | error
  ↓
Frontend detecta status=done:
  - Canvas carrega diagram_json
  - Toast "Diagrama gerado!"
  - Auto-layout aplicado se config.auto_layout=true
  ↓
User edita visualmente (drag, conectar, properties)
  ↓
User salva: PATCH /api/bpmn/diagrams/{id}
  ↓ trigger snapshot em bpmn_diagram_versions
```

---

## 3. G1 (Risk Register PMBOK) — definição completa

### 3.1 Tabela `vectraclip.risks`

```sql
-- Migration: 20260516170000_risk_register.sql

CREATE TABLE IF NOT EXISTS vectraclip.risks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES vectraclip.companies(company_id) ON DELETE CASCADE,

  -- Vínculos opcionais (Schmidt: risk pode ser de goal/project/activity)
  linked_goal_id          UUID REFERENCES vectraclip.goals(id) ON DELETE SET NULL,
  linked_workflow_id      UUID REFERENCES vectraclip.workflow_definitions(id) ON DELETE SET NULL,
  linked_sipoc_process_id UUID REFERENCES vectraclip.sipoc_processes(id) ON DELETE SET NULL,
  linked_sipoc_component_id UUID REFERENCES vectraclip.sipoc_components(id) ON DELETE SET NULL,

  -- Identidade do risco (PMBOK)
  name        TEXT NOT NULL,
  description TEXT,
  category    TEXT NOT NULL CHECK (category IN (
    'technical',     -- tecnologia, performance, qualidade
    'external',      -- mercado, fornecedor, regulatório
    'organizational',-- recursos, financiamento, prioridade
    'project_mgmt'   -- estimativa, planning, control
  )),

  -- Análise quantitativa
  probability NUMERIC NOT NULL CHECK (probability BETWEEN 0 AND 1),     -- 0.0 - 1.0
  impact      NUMERIC NOT NULL CHECK (impact BETWEEN 1 AND 10),         -- 1-10
  -- Risk score = probability * impact (computed)
  risk_score  NUMERIC GENERATED ALWAYS AS (probability * impact) STORED,

  -- Resposta (PMBOK)
  response_strategy TEXT CHECK (response_strategy IN (
    'avoid', 'transfer', 'mitigate', 'accept', 'escalate'
  )),
  mitigation_actions TEXT,
  contingency_plan   TEXT,

  -- Ownership
  owner_position_id UUID REFERENCES vectraclip.sipoc_positions(id) ON DELETE SET NULL,

  -- Status lifecycle
  status TEXT NOT NULL DEFAULT 'identified' CHECK (status IN (
    'identified', 'analyzing', 'planned', 'monitoring', 'occurred', 'closed'
  )),

  -- Athena fields
  detected_by_athena BOOLEAN DEFAULT FALSE,
  athena_recommendation_id UUID REFERENCES vectraclip.athena_recommendations(id) ON DELETE SET NULL,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index pra queries comuns
CREATE INDEX risks_company_status_idx ON vectraclip.risks(company_id, status);
CREATE INDEX risks_owner_idx ON vectraclip.risks(owner_position_id) WHERE owner_position_id IS NOT NULL;
CREATE INDEX risks_score_idx ON vectraclip.risks(risk_score DESC);
CREATE INDEX risks_linked_goal_idx ON vectraclip.risks(linked_goal_id) WHERE linked_goal_id IS NOT NULL;
CREATE INDEX risks_linked_component_idx ON vectraclip.risks(linked_sipoc_component_id) WHERE linked_sipoc_component_id IS NOT NULL;

-- RLS tenant-aware (mesmo padrão PR #142)
ALTER TABLE vectraclip.risks ENABLE ROW LEVEL SECURITY;

CREATE POLICY risks_select_own_tenant ON vectraclip.risks FOR SELECT
  USING (company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid));

CREATE POLICY risks_write_admin_tenant ON vectraclip.risks FOR ALL
  USING (
    company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid)
    AND ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = ANY (ARRAY['admin','platform_admin','consultant','company_admin']))
  );

GRANT INSERT, UPDATE, DELETE ON vectraclip.risks TO authenticated;
```

### 3.2 Handler `athena-risk-register`

Já existe em `agent_specialties` (foi planejado mas não implementado). Vou apenas listar o que falta:

```python
# src/agents/athena.py — adicionar handler

async def handle_athena_risk_register(task: dict, supabase) -> dict:
    """Gera lista de riscos identificados pro contexto (goal/workflow/sipoc).

    Input: input_json = {
      "context_type": "goal" | "workflow" | "sipoc_process",
      "context_id": "<uuid>",
      "use_rag": true   # se true, busca em athena_documents (PMBOK)
    }

    Output: output_json = {
      "risks_identified": [
        {
          "name": "Atraso de fornecedor crítico",
          "description": "...",
          "category": "external",
          "probability": 0.4,
          "impact": 8,
          "response_strategy": "mitigate",
          "mitigation_actions": "Manter 2 fornecedores backup",
          "owner_position_suggestion": "<position_id se houver match>"
        },
        ...
      ],
      "metadata": {"total_risks": N, "high_risk_count": M}
    }

    Side-effect: insert em vectraclip.risks com detected_by_athena=true
    e cria athena_recommendation kind='diagnose_gap' linkando os risks.
    """
```

### 3.3 Endpoints backend `risks`

```python
# src/api_routes/risks.py (módulo novo)

POST   /api/risks                                  # criar manual
GET    /api/risks?company_id=X[&status=Y&category=Z]
GET    /api/risks/{id}
PATCH  /api/risks/{id}
DELETE /api/risks/{id}

# Contexto-specific
GET    /api/goals/{goal_id}/risks
GET    /api/sipoc/processes/{process_id}/risks
GET    /api/sipoc/components/{component_id}/risks

# Athena-trigger
POST   /api/athena/risks/identify
  body: {context_type, context_id, use_rag}
  → dispatch task athena-risk-register
```

### 3.4 Frontend UI

```
/risks                  → RiskRegisterPage (tabela completa company-wide)
/risks/matrix           → RiskMatrix (5x5 probability × impact heatmap)
/goals/{id}/risks       → tab dentro de GoalDetail
/sipoc/processes/{id}   → tab "Riscos" dentro de SipocManagement
```

---

## 4. Pré-requisitos pra executar com maestria

### 4.1 Decisões tomadas (gravar em memória se ainda não)

- ✅ Modelo Risk Register = **PMBOK puro** (tabela formal)
- ✅ Daedalus = **agente separado** (não specialty da Athena)
- ✅ BPMN visual = **clone Camunda visual** com canvas próprio
- ✅ Localização BPMN = **ambos** (modal independente `/bpmn` + aba dentro de `/sipoc/processes/{id}`)
- ⏳ Pendente: você confirma escopo MVP do BPMN (shapes essenciais vs full BPMN 2.0)

### 4.2 Habilidades técnicas necessárias

| Habilidade | Onde aplico | Tenho/conheço? |
|---|---|---|
| FastAPI + Pydantic | endpoints novos | ✅ provado em 20 PRs hoje |
| Supabase migrations + RLS | risks, bpmn_diagrams | ✅ provado (PR #141, #142, #144) |
| @xyflow/react custom nodes | BPMN shapes | ⚠️ conheço API, nunca fiz BPMN-shapes |
| @dagrejs/dagre auto-layout | Daedalus output | ⚠️ conheço API, nunca usei |
| LLM prompt engineering pra structured output | Daedalus | ✅ provado em athena.py handlers |
| BPMN 2.0 semântica (mesmo sem usar XML) | regras de validação | ✅ conheço PMBOK + BPMN |

**Onde tenho 80% confiança:** backend (specialty + agent + endpoints + handler stub + migrations).
**Onde tenho 60% confiança:** UI Modeler completo (canvas + paleta + properties + auto-layout). É escopo grande, vai exigir 2-3 sub-PRs frontend.
**Onde tenho 70% confiança:** Daedalus LLM output structured (precisa testar várias iterações de prompt — Gemini 403 ainda bloqueia testes reais; com Claude funciona).

### 4.3 Garantia: o que entrego com maestria

| Item | Confiança | Justificativa |
|---|---|---|
| **G1 Risk Register backend** (migration + endpoints + handler stub) | **95%** | Padrão repetido 5x hoje (PR #142, #144 etc). Schema simples. Sem Gemini bloqueante |
| **Daedalus agent setup** (specialty + agent row + adapter config + execution config) | **90%** | Bem documentado no contrato auditado. Falta só inserts |
| **Daedalus handler estatístico fallback** (sem LLM) | **85%** | Quando source_type=sipoc_process, posso gerar BPMN básico (1 start + N tasks lineares + 1 end) sem LLM. Funciona mesmo com Gemini 403 |
| **Daedalus handler LLM** | **65%** | Depende de Gemini voltar OU usar Claude (Anthropic key disponível?). Sem isso, só fallback estatístico funciona end-to-end |
| **UI BPMN backend endpoints** (CRUD bpmn_diagrams + versions) | **95%** | CRUD padrão |
| **UI BPMN canvas full** (Modeler clone Camunda) | **60%** | Escopo grande. Vou propor MVP minimalista (5 shape types) primeiro, expansão depois |

### 4.4 Não-garantias (transparente)

- ❌ NÃO garanto LLM gerando BPMN perfeito de primeira (Gemini 403 + prompt vai precisar várias iterações)
- ❌ NÃO garanto UI BPMN tão polida quanto Camunda Modeler real (eles têm anos de UX research)
- ❌ NÃO garanto compatibilidade com BPMN 2.0 XML (não é o objetivo — JSON nativo)
- ❌ NÃO garanto execução do diagrama (Daedalus modela; Morpheus+daemons executam — execução do BPMN é Fase B/C separada)

---

## 5. Ordem de execução recomendada (sequência de PRs)

| # | PR | Escopo | Dependências | Esforço |
|---|---|---|---|---|
| **A** | `feat(schema): risks table + RLS + GRANTs` | Migration + verificação smoke | Nada | 30min |
| **B** | `feat(api): risks CRUD endpoints + Pydantic models` | `src/api_routes/risks.py` | A | 1h |
| **C** | `feat(api): athena-risk-register handler (stub estatístico)` | `src/agents/athena.py` + operation_type catalog | B | 1h |
| **D** | `feat(schema): bpmn_diagrams + versions + trigger` | Migration | Nada | 30min |
| **E** | `feat(api): bpmn_diagrams CRUD + version history` | `src/api_routes/bpmn_diagrams.py` | D | 1h |
| **F** | `feat(agent): Daedalus — specialty + agent provisioning` | Seed migration + agent_specialty_configs | D, E | 45min |
| **G** | `feat(api): bpmn-generate dispatch + Daedalus handler (fallback)` | `src/agents/daedalus.py` (novo) | F | 1h30 |
| **H** | `feat(launcher): start_all_daemons.py inclui Daedalus` | Editar `start_all_daemons.py` | F | 15min |
| **I** | Frontend: doc handoff pra criar UI BPMN MVP | Doc pro outro repo | A-H | 30min |

**Total backend:** ~7h. **Frontend BPMN UI:** sessão separada, ~12-16h.

---

## 6. Onde Schmidt entra explicitamente

- **G1 Risk** = Pergunta 3 Schmidt "Que condições devem existir?". Faltava handler, agora terá.
- **Daedalus** = Pergunta 4 Schmidt "Como chegará lá?". `athena-charter` (PR4) já existe mas é texto. Daedalus complementa com **visual**.
- **Risk × LogFrame** = cada risco vincula a 1 dos níveis (goal/workflow/sipoc_process/sipoc_component) — espelha Schmidt §"riscos em cada nível objetivo".
- **BPMN visual dentro do SIPOC** = Schmidt usa diagramas extensivamente; PMBOK exige WBS visualizada.

---

## 7. O que SAI desta PR de planejamento

Esta PR entrega só o **doc** acima. Implementação real começa quando você aprovar a ordem (PRs A-H). Cada PR vai ser commit + smoke + push + merge como nos PRs anteriores.

**Próximo comando esperado seu:**
- "Aprovado, executa PR A" → começo migration risks
- "Reordena, faz Daedalus primeiro" → começo PR D
- "Pula G1, foca só em Daedalus" → começo PR D (sem A-C)
- "Ajusta X no plano" → você diz o ajuste

---

## 8. Sinceridade final

Você perguntou "tem entendimento? se garante?".

**Sim, tenho entendimento.** Auditei contrato real do AgentBuilder, vi 3 specialties exemplo, mapeei FK chain do tenant, validei que sipoc_companies é tabela órfã (descobri hoje), vi como Hodos foi configurado, sei que `system_prompt_template` aceita Mustache, sei que `config_schema` é JSON validado pelo frontend. Daedalus segue exatamente o mesmo padrão.

**Sim, me garanto** nos 7 PRs backend (95% confiança).

**Não me garanto** em entregar o UI Modeler completo de Camunda em uma sessão — é trabalho de várias sessões frontend coordenadas, e Camunda Modeler tem complexidade que justifica isso.

**Plano realista:** backend (A-H) entregue por mim. Frontend BPMN entregue em 2-3 sessões VectraClip separadas (prompts detalhados pra cada uma).
