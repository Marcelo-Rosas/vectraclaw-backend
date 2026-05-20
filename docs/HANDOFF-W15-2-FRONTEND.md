# HANDOFF — W15.2 Frontend VectraClip (canvas refatorado)

**Origem**: sessão Claude Code backend VectraClaw, 2026-05-18
**Destino**: sessão frontend VectraClip (`C:\Users\marce\VectraClip`)
**Status backend**: ✅ TUDO PRONTO — 4 endpoints catalog publicados em prod, smoke validado

---

## 1. Contexto cravado por Marcelo (decisão arquitetural)

3 cortes hoje:
1. ❌ **Trigger NÃO mora no agente** — trigger é processo do STEP, varia independente do agente. `agent_execution_modes`/`configs` vão deprecar (W15.3).
2. ❌ **Specialty NÃO é dropdown livre** — specialty é PROPRIEDADE do agente via `agent_specialty_configs`. Combos válidos vêm de catalog joined.
3. ❌ **`TASK_OPERATION_TYPES` hardcoded em `src/lib/display.ts:201` está ERRADO** — backend tem catalog real com 47 rows.

**UX final do canvas** (que W15.2 implementa):
```
┌─ Editar etapa ───────────────────────────────────────┐
│ Nome / Slug / Descrição                              │
│                                                      │
│ Modo de disparo: [Realtime ▼]  ← W15.1.5 endpoint    │
│                  realtime / manual / cron / webhook  │
│                  / event                             │
│                                                      │
│ Responsável: [Agente ▼]                              │
│                                                      │
│ Se Agente:                                           │
│ Agent Skill: [Athena · Charter ▼]  ← W15.1 endpoint  │
│              • Athena · Classify                     │
│              • Athena · Charter                      │
│              • Mercator · Freight Quotation          │
│              • Oracle · Research                     │
│              • Kronos · Financial Audit              │
│              ... (15 combos atual)                   │
│                                                      │
│ Se Humano: texto livre (email/papel)                 │
│ Se Sistema: ferramenta (scheduler/watcher)           │
│                                                      │
│ Lógica: [Simple ▼]  ← W15.1.5 endpoint               │
│         só pra roteamento split/merge/loop           │
└──────────────────────────────────────────────────────┘
```

---

## 2. Backend pronto — 4 endpoints catalog-driven

### `GET /api/workflow-trigger-types`
Catalog do **Modo de disparo** do step. 5 rows.

Payload exemplo:
```json
[
  {"slug":"realtime","name":"Tempo Real","description":"Executa imediato após step anterior (DAG advance). Padrão de fluxo síncrono — não requer config adicional.","icon":null,"display_order":5,"is_active":true},
  {"slug":"manual","name":"Manual","description":"Disparado por ação humana via UI ou API (POST /tasks/from-workflow). Sem agendamento.","display_order":10,"is_active":true},
  {"slug":"cron","name":"Agendado","description":"Disparado por cron expression em janelas fixas. Daemon cron faz dispatch.","display_order":20,"is_active":true},
  {"slug":"webhook","name":"Webhook","description":"Disparado por POST externo em URL única gerada pelo workflow. Não implementado ainda.","display_order":30,"is_active":true},
  {"slug":"event","name":"Evento","description":"Disparado por evento interno do sistema (heartbeat, task done, incident). Não implementado ainda.","display_order":40,"is_active":true}
]
```

### `GET /api/workflow-logic-patterns`
Catalog do **Lógica** (só roteamento). 8 patterns.

Payload exemplo:
```json
[
  {"id":"simple","taxonomy":"simple","category":"simple","name":"Linear (Sucesso/Falha)","description":"Step linear sem condicionais; engine v1 segue on_success_step_id ou on_failure_step_id baseado no outcome.","icon":null,"color":null,"display_order":10,"engine_handler":"workflow_engine.advance_v2","is_active":true},
  {"id":"split-if","taxonomy":"split-if","category":"splitting","name":"SPLIT com IF (binário)","engine_handler":"workflow_engine.advance_v2","is_active":true},
  {"id":"split-switch","category":"splitting","engine_handler":"pending","is_active":true},
  ...
]
```

### `GET /api/companies/{company_id}/agent-skills`
Catalog do **Agent Skill** (combo agente+specialty). Auth: caller_company == path company_id.
Filtro: `?agent_id=<uuid>` opcional.

Payload exemplo (15 combos hoje na Vectra Cargo):
```json
[
  {
    "id":"ddbda310-906d-4ba8-81a3-e3c2ef93d2e3",
    "agentId":"ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d",
    "agentName":"Athena",
    "specialtySlug":"oracle-rag",
    "specialtyName":"Oracle RAG",
    "operationTypes":["athena-classify","athena-charter","athena-stakeholder-map","athena-risk-register","athena-evm","athena-audit","athena-recommend","athena-rag-ingest"],
    "values":{"domain":"project_management","rag_corpus":"athena","methodology":"PMBOK 5e / Kim Heldman","operation_types":[...]}
  },
  {
    "id":"7714fa8b-...",
    "agentId":"00000000-0000-0000-0000-000000000003",
    "agentName":"Mnemos",
    "specialtySlug":"oracle-rag",
    "specialtyName":"Oracle RAG",
    "operationTypes":[],
    "values":{"role":"curator"}
  },
  ...
]
```

**Pattern N:M**: quando `operationTypes.length > 1` (caso Athena oracle-rag com 8 athena-* embutidos), frontend precisa sub-seletor "Qual operação?" condicional.

### `GET /api/operation-types-catalog`
Catalog do `operation_type` legado (47 rows). Substitui `TASK_OPERATION_TYPES` hardcoded.
Filtro: `?primary_agent_id=<uuid>` opcional.

Payload exemplo (recortado):
```json
[
  {"id":"athena-charter","name":"Athena Project Charter","description":"Gera Project Charter.","category":"athena","icon":"scroll","color":"text-rose-600","display_order":610,"primary_agent_id":"ad4fc1ad-...","default_specialty_slug":"athena-charter","is_active":true,"routing_score":60},
  {"id":"freight-quotation","name":"Cotação de Frete","category":"commercial","icon":"truck","color":"text-blue-600","display_order":110,"primary_agent_id":"c7de1b0f-...","default_specialty_slug":"freight-quotation","routing_score":80},
  ...
]
```

Distribuição por categoria (smoke real):
```
athena: 9   commercial: 9   crm: 3   finance: 2   governance: 1
kronos: 3   kronos-planner: 2   mnemos: 1   modeling: 1
oracle: 7   system: 9
```

---

## 3. Schema novo de workflow_steps (já aplicado)

3 colunas adicionadas em prod (PR #219):
```sql
ALTER TABLE vectraclip.workflow_steps
  ADD trigger_type text REFERENCES workflow_trigger_types(slug) DEFAULT 'realtime',
  ADD trigger_config jsonb NOT NULL DEFAULT '{}',
  ADD agent_specialty_config_id uuid REFERENCES agent_specialty_configs(id);
```

`workflow_steps` tem **0 rows hoje** — zero risco de regressão.

Pydantic `WorkflowStepRich` (em `src/models.py` backend, espelhar no frontend):
```ts
type WorkflowStepRich = {
  stepCode: string
  slug?: string
  name?: string
  // ... campos existentes
  triggerType?: string             // NOVO — FK workflow_trigger_types.slug
  triggerConfig: Record<string, unknown>  // NOVO — default {}
  agentSpecialtyConfigId?: string  // NOVO — FK agent_specialty_configs.id
}
```

---

## 4. O que mudar — frontend (arquivos exatos)

### NOVO arquivo `src/lib/api/endpoints/agentSkills.ts`
```ts
import { api } from '../client'
import type { AgentSkill, OperationTypeCatalogItem, WorkflowTriggerType, WorkflowLogicPattern } from '@/types/api'

export function listAgentSkills(companyId: string, agentId?: string) {
  const q = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ''
  return api.get<AgentSkill[]>(`/companies/${encodeURIComponent(companyId)}/agent-skills${q}`)
}

export function listOperationTypesCatalog(primaryAgentId?: string) {
  const q = primaryAgentId ? `?primary_agent_id=${encodeURIComponent(primaryAgentId)}` : ''
  return api.get<OperationTypeCatalogItem[]>(`/operation-types-catalog${q}`)
}

export function listWorkflowTriggerTypes() {
  return api.get<WorkflowTriggerType[]>('/workflow-trigger-types')
}

export function listWorkflowLogicPatterns() {
  return api.get<WorkflowLogicPattern[]>('/workflow-logic-patterns')
}
```

### NOVO arquivo `src/lib/queries/agentSkills.ts`
```ts
import { useQuery } from '@tanstack/react-query'
import * as endpoints from '../api/endpoints/agentSkills'

export function useAgentSkills(companyId: string | null, agentId?: string) {
  return useQuery({
    queryKey: ['agent-skills', companyId, agentId],
    queryFn: () => endpoints.listAgentSkills(companyId!, agentId),
    enabled: !!companyId,
    staleTime: 60_000,
  })
}

export function useOperationTypesCatalog(primaryAgentId?: string) {
  return useQuery({
    queryKey: ['operation-types-catalog', primaryAgentId],
    queryFn: () => endpoints.listOperationTypesCatalog(primaryAgentId),
    staleTime: 5 * 60_000,
  })
}

export function useWorkflowTriggerTypes() {
  return useQuery({
    queryKey: ['workflow-trigger-types'],
    queryFn: () => endpoints.listWorkflowTriggerTypes(),
    staleTime: 5 * 60_000,
  })
}

export function useWorkflowLogicPatterns() {
  return useQuery({
    queryKey: ['workflow-logic-patterns'],
    queryFn: () => endpoints.listWorkflowLogicPatterns(),
    staleTime: 5 * 60_000,
  })
}
```

### Editar `src/types/api.ts`
Adicionar tipos:
```ts
export type AgentSkill = {
  id: string                              // agent_specialty_configs.id (UUID)
  agentId: string
  agentName: string
  specialtySlug: string
  specialtyName: string
  operationTypes: string[]                // de values.operation_types — pattern N:M
  values?: Record<string, unknown>        // raw jsonb
}

export type OperationTypeCatalogItem = {
  id: string                              // slug (ex: athena-charter, freight-quotation)
  name: string
  description?: string | null
  category: string                        // athena/commercial/crm/finance/...
  icon?: string | null
  color?: string | null
  display_order: number
  primary_agent_id?: string | null
  default_specialty_slug?: string | null
  is_active: boolean
  routing_score: number
}

export type WorkflowTriggerType = {
  slug: string                            // realtime/manual/cron/webhook/event
  name: string
  description?: string | null
  icon?: string | null
  display_order: number
  is_active: boolean
}

export type WorkflowLogicPattern = {
  id: string                              // simple/split-if/...
  taxonomy: string
  category: string
  name: string
  description?: string | null
  icon?: string | null
  color?: string | null
  display_order: number
  engine_handler: string                  // workflow_engine.advance_v2 | pending
  is_active: boolean
}

// Estender WorkflowStepRich (3 campos novos):
export type WorkflowStepRich = {
  // ... campos existentes
  triggerType?: string
  triggerConfig?: Record<string, unknown>
  agentSpecialtyConfigId?: string
}
```

### REMOVER `src/lib/display.ts:201` — `TASK_OPERATION_TYPES`
Deletar a constante hardcoded **e todas as importações**. Buscar callers:
```bash
grep -rE "TASK_OPERATION_TYPES" src
```
Esperado encontrar em:
- `src/components/tasks/EditTaskSheet.tsx`
- `src/components/tasks/NewTaskSheet.tsx`
- `src/components/workflow/canvas/panels/NodeConfigPanel.tsx`

Substituir cada uso por `useOperationTypesCatalog()` retornando array de `OperationTypeCatalogItem`. Onde a UI mostrava `formatTaskOperationType(op)`, mostrar `item.name` (catalog já trás nome formatado).

### REFATOR `src/components/workflow/canvas/panels/NodeConfigPanel.tsx`
Substituir 3 dropdowns atuais por nova UX:

| Atual (REMOVER) | Novo (ADICIONAR) |
|---|---|
| `Label "Tipo de operação *"` + `Select draft.defaultOperationType` com `TASK_OPERATION_TYPES` hardcoded (linhas 398-423) | `Label "Modo de disparo"` + `Select draft.triggerType` consumindo `useWorkflowTriggerTypes()` |
| `Select` separado de `specialty_slug` livre | `Label "Responsável" [Agente/Humano/Sistema]` |
| | Quando `Agente`: `Select "Agent Skill"` consumindo `useAgentSkills(companyId)` — value = `skill.id`, label = `\`${skill.agentName} · ${skill.specialtyName}\`` |
| `Select` de logic_pattern (linhas 480+) | Manter, **mas trocar source** pra `useWorkflowLogicPatterns()` em vez de prop drilling |

**Salvar `draft.agentSpecialtyConfigId`** (FK pra agent_specialty_configs) em vez de `specialty_slug` livre.

`default_operation_type` deixa de ser preenchido pelo usuário — vai ser derivado no W15.5 (task_factory backend). Mas pra compatibilidade durante transição: enquanto o user escolhe Agent Skill, gravar `defaultOperationType = skill.operationTypes[0] ?? skill.specialtySlug` se houver — sem dropdown manual.

**Quando `skill.operationTypes.length > 1`** (Athena oracle-rag com 8 athena-*), adicionar sub-seletor condicional "Qual operação executar?".

### NÃO MEXER neste PR
- `AgentExecutionCard.tsx` — DELETAR vai pro W15.3 (depende deprecar endpoints backend)
- `agent_execution_modes` queries/endpoints — idem W15.3
- `workflow_steps.specialty_slug` referências antigas — só remover quando task_factory refator (W15.5)

---

## 5. Bugs cravados que W15.2 resolve junto

| Bug | Onde | Como resolve |
|---|---|---|
| Dropdown "Tipo de operação" hardcoded | `src/lib/display.ts:201` | DELETE + hook |
| Dropdown "Especialidade" livre permite combos absurdos | `NodeConfigPanel.tsx` | SUBSTITUI por Agent Skill combo |
| `filterAdapterFieldsForAgentUi` passthrough sem filtro (memory) | `src/lib/agents/adapterFields.ts:67` | DELETAR; backend já filtra via `?scope=agent\|company` (W11 PR1) |
| `AgentExecutionCard:218-245` 3 campos hardcoded fora do schema | `src/components/agents/detail/AgentExecutionCard.tsx` | NÃO neste PR — vai W15.3 |

---

## 6. Regras de ouro aplicáveis (obrigatórias)

- **#1 Espelhar antes de criar**: rodar curl nos 4 endpoints e logar shape exato antes de declarar types. Backend pode ter diferenças sutis (camelCase vs snake_case nos campos).
- **#2 Metadata-driven NO HARDCODE**: zero array/enum literal de operation_type, trigger_type, logic_pattern, specialty no frontend. Tudo via hook.
- **#4 Auditor antes de implementar**: invocar `hardcode-auditor` com o plano completo W15.2 antes de mexer em código.
- **#5 Docker ephemeral pra tooling**: typecheck via `docker run --rm -v $PWD:/app -w /app node:20-alpine sh -c "npm ci && npm run typecheck"` — NÃO instalar deps na máquina do Marcelo.

---

## 7. Critérios de smoke pós-merge

- [ ] `npm run typecheck` passa em VectraClip (ephemeral docker)
- [ ] Build dev passa (`npm run build`)
- [ ] Canvas abre `/workflow/<id>` → cria/edita step → todos 3 dropdowns funcionam:
   - Modo de disparo: 5 opções
   - Responsável: 3 opções (Agente/Humano/Sistema)
   - Agent Skill (quando Agente): 15 combos
   - Lógica: 8 patterns
- [ ] Step salva → `workflow_steps` row tem `trigger_type`, `agent_specialty_config_id`, `trigger_config` populados
- [ ] EditTaskSheet/NewTaskSheet ainda mostram dropdown de operation_type (mas catalog-driven agora)

---

## 8. Próximas frentes W15.3-5 (contexto)

| | Frente | Bloqueado por |
|---|---|---|
| W15.2 | (este PR) frontend canvas | — |
| W15.3 | Backfill 10 agents + deprecate `agent_execution_configs`/`modes` (deleta AgentExecutionCard) | W15.2 |
| W15.4 | `agent_daemon` + `workflow_engine` consomem `trigger_type` | W15.2 + W15.3 |
| W15.5 | `task_factory` deriva `op_type` via FK `agent_specialty_config_id` | W15.4 |

---

## 9. PRs backend já mergeados (referência)

| PR | Branch | O que entregou |
|---|---|---|
| #219 | `feat/w15-1-step-trigger-agent-skill` | Schema workflow_steps +3 cols + Pydantic AgentSkill + 2 endpoints (agent-skills + operation-types-catalog) |
| #220 | `feat/w15-1-5-trigger-types-logic-patterns-endpoints` | +2 endpoints catalog (workflow-trigger-types + workflow-logic-patterns) |

---

**Pré-condição validada em prod 2026-05-18**: backend smoke OK, 5 trigger types + 8 logic patterns + 15 agent skills + 47 operation types respondendo via API.
