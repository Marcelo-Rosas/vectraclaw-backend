# Handoff Frontend — BPMN Modeler (Daedalus UI)

> **Repo destino:** VectraClip (`C:\Users\marce\VectraClip` — vectra-dashboard)
> **Repo backend (ref):** VectraClaw (este) — endpoints CRUD prontos em `src/api.py:2157-2430`
> **Origem:** [`EXECUCAO-G1-RISK-REGISTER-E-DAEDALUS.md`](./EXECUCAO-G1-RISK-REGISTER-E-DAEDALUS.md) §2 (plano original)
> **Data:** 2026-05-17 — gerado após auditoria que confirmou backend ✅ pronto e UI ❌ não implementada

---

## 1. Contexto

A UI de modelagem BPMN (clone visual do Camunda, mas com **engine própria e JSON nativo** — decisão `feedback_no_camunda_keep_custom_engine`) **não foi entregue ainda**. O backend está 100% pronto e em produção. Este doc é a especificação completa pra o agente do frontend implementar a UI.

**Princípio arquitetural a respeitar:**
- Engine PRÓPRIA — não usar Camunda/bpmn-js externos
- Canvas via `@xyflow/react` (já em uso no `/workflow`)
- Auto-layout via `@dagrejs/dagre` (já instalado, `package.json:^3.0.0`)
- Multi-tenant via JWT — `company_id` resolvido pelo backend

---

## 2. Estado real verificado (2026-05-17)

### 2.1 Backend ✅ pronto

| Endpoint | Verbo | Função | Linha em `api.py` |
|---|---|---|---|
| `/api/bpmn/diagrams` | POST | Criar diagrama (manual ou Daedalus) | 2219 |
| `/api/companies/{company_id}/bpmn/diagrams` | GET | Listar diagramas do tenant | 2260 |
| `/api/bpmn/diagrams/{diagram_id}` | GET | Detalhe (com `diagram_json` completo) | 2295 |
| `/api/bpmn/diagrams/{diagram_id}` | PATCH | Update (trigger DB versiona automaticamente) | 2312 |
| `/api/bpmn/diagrams/{diagram_id}` | DELETE | Remove + CASCADE em `bpmn_diagram_versions` | 2347 |
| `/api/bpmn/diagrams/{diagram_id}/duplicate` | POST | Clona diagrama existente | 2366 |
| `/api/bpmn/diagrams/{diagram_id}/versions` | GET | Histórico append-only | 2412 |

> ⚠️ **POST `/api/bpmn/generate`** (dispatch task pra Daedalus) **NÃO está no backend ainda**. Sai do escopo deste handoff — MVP entrega CRUD manual primeiro; Daedalus generation vira fase 2.

### 2.2 Tabelas confirmadas (verificado via SQL)

```sql
vectraclip.bpmn_diagrams (
  id UUID PK,
  company_id UUID NOT NULL,
  linked_sipoc_process_id UUID NULL,
  linked_workflow_id UUID NULL,
  linked_goal_id UUID NULL,
  name TEXT NOT NULL,
  description TEXT,
  diagram_json JSONB NOT NULL,  -- formato @xyflow/react nativo
  version INTEGER NOT NULL DEFAULT 1,
  generated_by TEXT NOT NULL CHECK IN ('manual','athena','daedalus','imported'),
  generated_by_task_id UUID NULL,
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ
)

vectraclip.bpmn_diagram_versions (
  id UUID PK,
  diagram_id UUID NOT NULL CASCADE,
  version INTEGER NOT NULL,
  diagram_json JSONB NOT NULL,
  changed_by_user_id UUID NULL,
  change_notes TEXT,
  created_at TIMESTAMPTZ
)
```

**Trigger automático:** PATCH em `diagram_json` faz `bpmn_snapshot_version()` snapshot antes do update. Frontend NÃO precisa manualmente versionar.

### 2.3 Stack frontend (verificado via `package.json`)

| Lib | Versão | Status | Uso BPMN |
|---|---|---|---|
| `@xyflow/react` | `^12.10.2` | ✅ Em uso | Canvas + nodes + edges (mesmo do `/workflow`) |
| `@dagrejs/dagre` | `^3.0.0` | ✅ Instalado | Auto-layout (rankdir LR) |
| `react-hook-form` | `^7.51.1` | ✅ Em uso | Properties panel forms |
| `zod` | `^3.22.4` | ✅ Em uso | Validação BPMN rules |
| `@tanstack/react-query` | `^5.28.4` | ✅ Em uso | CRUD hooks |
| `react-router-dom` | `^6.22.3` | ✅ Em uso | Rotas |
| `lucide-react` | `^0.363.0` | ✅ Em uso | Ícones nos shapes |
| `shadcn/ui` | `^4.5.0` | ✅ Em uso | Properties panel + dialogs |
| `tailwindcss` | `^3.4.1` | ✅ Em uso | Estilo |

**Falta adicionar:**
- `html-to-image` — opcional, só pro Export PNG (pode ficar pra fase 2)

### 2.4 Canvas atual a REUSAR (regra de ouro #1)

`VectraClip/src/components/workflow/canvas/` já tem:
- `WorkflowCanvas.tsx` — wrapper do ReactFlow
- `nodes/StepNode.tsx`, `nodes/TriggerNode.tsx` — exemplos de custom node
- `edges/`, `panels/`, `utils/`

**NÃO criar canvas separado.** Espelhar o pattern do WorkflowCanvas e criar `BpmnCanvas.tsx` no mesmo nível, reusando estilo de node/edge.

---

## 3. O que entregar (escopo MVP)

### 3.1 Rotas novas

| Rota | Componente | Função |
|---|---|---|
| `/bpmn` | `BpmnDiagramsList` | Catálogo de diagramas do tenant (tabela + filtros) |
| `/bpmn/new` | `BpmnEditor` (modo create) | Modeler em branco |
| `/bpmn/:id` | `BpmnEditor` (modo edit) | Modeler com diagrama carregado |
| `/sipoc/processes/:id/bpmn` | `BpmnEditor` (modo linked) | Aba/sheet dentro do contexto SIPOC |

### 3.2 Estrutura de arquivos esperada

```
VectraClip/src/
├── pages/
│   ├── Bpmn.tsx                          # /bpmn (lista)
│   └── BpmnEditor.tsx                    # /bpmn/new + /bpmn/:id (mesmo componente, query param)
├── components/bpmn/
│   ├── BpmnCanvas.tsx                    # wrapper ReactFlow (espelha WorkflowCanvas)
│   ├── BpmnPalette.tsx                   # paleta drag-to-canvas
│   ├── BpmnPropertiesPanel.tsx           # painel direito (node selecionado)
│   ├── BpmnToolbar.tsx                   # [Salvar] [Auto-Layout] [Validar] [Daedalus✨ (disabled)] [Export]
│   ├── BpmnDiagramsList.tsx              # tabela de diagramas
│   ├── BpmnVersionHistory.tsx            # sheet com versions
│   ├── nodes/
│   │   ├── StartEventNode.tsx            # ● verde
│   │   ├── EndEventNode.tsx              # ● vermelho
│   │   ├── IntermediateEventNode.tsx     # ◎
│   │   ├── TaskNode.tsx                  # ▭ (variants: user/service/manual)
│   │   ├── GatewayExclusiveNode.tsx      # ◇ X
│   │   └── GatewayParallelNode.tsx       # ◇ +
│   ├── edges/
│   │   └── SequenceFlowEdge.tsx          # com label opcional (sim/não)
│   └── utils/
│       ├── autoLayout.ts                 # dagre rankdir LR
│       └── bpmnValidation.ts             # regras Zod
├── lib/api/endpoints/
│   └── bpmnDiagrams.ts                   # NOVO — CRUD endpoints TS
├── lib/queries/
│   └── bpmnDiagrams.ts                   # NOVO — hooks React Query
└── types/
    └── bpmn.ts                            # NOVO — types do diagram_json
```

### 3.3 Schema do `diagram_json` (canônico)

```ts
// types/bpmn.ts
export type BpmnNodeType =
  | 'start_event' | 'end_event' | 'intermediate_event'
  | 'task' | 'user_task' | 'service_task' | 'manual_task'
  | 'gateway_exclusive' | 'gateway_parallel'

export interface BpmnNode {
  id: string
  type: BpmnNodeType
  position: { x: number; y: number }
  data: {
    label: string
    assignee_position_id?: string  // FK opcional sipoc_positions
    linked_sipoc_component_id?: string  // FK opcional
    [key: string]: unknown
  }
}

export interface BpmnEdge {
  id: string
  source: string
  target: string
  type: 'sequence_flow'
  label?: string  // ex: "Sim" / "Não" em gateways
}

export interface BpmnDiagramJson {
  nodes: BpmnNode[]
  edges: BpmnEdge[]
}

export interface BpmnDiagramValidation {
  is_valid: boolean
  warnings: string[]
  errors: string[]
}
```

### 3.4 Validação BPMN (regras hardcoded mínimas)

```ts
// utils/bpmnValidation.ts
export function validateBpmn(diagram: BpmnDiagramJson): BpmnDiagramValidation {
  const errors: string[] = []
  const warnings: string[] = []

  // Regra 1: cada gateway tem ≥2 saídas
  for (const node of diagram.nodes) {
    if (node.type.startsWith('gateway_')) {
      const outgoing = diagram.edges.filter(e => e.source === node.id)
      if (outgoing.length < 2) {
        errors.push(`Gateway "${node.data.label}" precisa de ≥2 saídas`)
      }
    }
  }

  // Regra 2: cada start_event tem 0 entradas e ≥1 saída
  for (const node of diagram.nodes.filter(n => n.type === 'start_event')) {
    const incoming = diagram.edges.filter(e => e.target === node.id)
    const outgoing = diagram.edges.filter(e => e.source === node.id)
    if (incoming.length > 0) errors.push(`Start "${node.data.label}" não pode ter entradas`)
    if (outgoing.length === 0) errors.push(`Start "${node.data.label}" precisa ≥1 saída`)
  }

  // Regra 3: cada end_event tem ≥1 entrada e 0 saídas
  for (const node of diagram.nodes.filter(n => n.type === 'end_event')) {
    const incoming = diagram.edges.filter(e => e.target === node.id)
    const outgoing = diagram.edges.filter(e => e.source === node.id)
    if (outgoing.length > 0) errors.push(`End "${node.data.label}" não pode ter saídas`)
    if (incoming.length === 0) errors.push(`End "${node.data.label}" precisa ≥1 entrada`)
  }

  // Regra 4: sem nós órfãos (sem qualquer aresta)
  const connectedIds = new Set([
    ...diagram.edges.map(e => e.source),
    ...diagram.edges.map(e => e.target),
  ])
  for (const node of diagram.nodes) {
    if (!connectedIds.has(node.id) && diagram.nodes.length > 1) {
      warnings.push(`Nó "${node.data.label}" está desconectado`)
    }
  }

  return { is_valid: errors.length === 0, errors, warnings }
}
```

### 3.5 Auto-layout (dagre)

```ts
// utils/autoLayout.ts
import dagre from '@dagrejs/dagre'

export function autoLayoutDagre(diagram: BpmnDiagramJson, direction: 'LR' | 'TB' = 'LR'): BpmnDiagramJson {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: direction, nodesep: 60, ranksep: 90 })
  g.setDefaultEdgeLabel(() => ({}))

  for (const node of diagram.nodes) {
    g.setNode(node.id, { width: 160, height: 80 })
  }
  for (const edge of diagram.edges) {
    g.setEdge(edge.source, edge.target)
  }

  dagre.layout(g)

  return {
    ...diagram,
    nodes: diagram.nodes.map(node => {
      const { x, y } = g.node(node.id)
      return { ...node, position: { x: x - 80, y: y - 40 } }  // center anchor
    }),
  }
}
```

### 3.6 Anatomia do `BpmnEditor`

```
┌──────────────────────────────────────────────────────────────────┐
│ Toolbar: [Salvar] [Auto-Layout] [Validar] [Daedalus✨ disabled] │
├──────┬───────────────────────────────────────────┬───────────────┤
│      │                                            │               │
│  P   │                                            │  Properties   │
│  A   │           BpmnCanvas (xyflow)              │  Panel        │
│  L   │                                            │               │
│  E   │   • Start (●)     • Task (▭)               │  Nó selec:    │
│  T   │   • End (●)       • User Task (▭)          │  - id          │
│  A   │   • Gateway X (◇) • Service Task (▭⚙)      │  - label       │
│      │   • Gateway + (◇) • Manual Task (▭✋)      │  - type        │
│      │   • Event Inter.(◎)                        │  - assignee    │
│      │                                            │  - linked_     │
│      │                                            │    sipoc_      │
│      │                                            │    component_id│
└──────┴───────────────────────────────────────────┴───────────────┘
```

---

## 4. Endpoints TS a criar

```ts
// lib/api/endpoints/bpmnDiagrams.ts
import { z } from 'zod'
import { api } from '@/lib/api/client'  // ou padrão usado no projeto

export const BpmnDiagramSchema = z.object({
  id: z.string().uuid(),
  company_id: z.string().uuid(),
  linked_sipoc_process_id: z.string().uuid().nullable(),
  linked_workflow_id: z.string().uuid().nullable(),
  linked_goal_id: z.string().uuid().nullable(),
  name: z.string().min(1),
  description: z.string().nullable(),
  diagram_json: z.object({ nodes: z.array(z.any()), edges: z.array(z.any()) }),
  version: z.number(),
  generated_by: z.enum(['manual', 'athena', 'daedalus', 'imported']),
  generated_by_task_id: z.string().uuid().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
})

export type BpmnDiagram = z.infer<typeof BpmnDiagramSchema>

export const bpmnDiagrams = {
  list: (companyId: string) =>
    api.get<BpmnDiagram[]>(`/api/companies/${companyId}/bpmn/diagrams`),
  get: (id: string) =>
    api.get<BpmnDiagram>(`/api/bpmn/diagrams/${id}`),
  create: (body: { name: string; description?: string; diagram_json: any; linked_sipoc_process_id?: string; linked_workflow_id?: string; linked_goal_id?: string }) =>
    api.post<BpmnDiagram>('/api/bpmn/diagrams', body),
  update: (id: string, body: Partial<{ name: string; description: string; diagram_json: any }>) =>
    api.patch<BpmnDiagram>(`/api/bpmn/diagrams/${id}`, body),
  delete: (id: string) =>
    api.delete(`/api/bpmn/diagrams/${id}`),
  duplicate: (id: string) =>
    api.post<BpmnDiagram>(`/api/bpmn/diagrams/${id}/duplicate`),
  versions: (id: string) =>
    api.get<Array<{ id: string; version: number; diagram_json: any; created_at: string }>>(`/api/bpmn/diagrams/${id}/versions`),
}
```

---

## 5. Hooks React Query

```ts
// lib/queries/bpmnDiagrams.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { bpmnDiagrams } from '@/lib/api/endpoints/bpmnDiagrams'

export function useBpmnDiagrams(companyId: string) {
  return useQuery({
    queryKey: ['bpmn-diagrams', companyId],
    queryFn: () => bpmnDiagrams.list(companyId),
    enabled: !!companyId,
  })
}

export function useBpmnDiagram(id: string | undefined) {
  return useQuery({
    queryKey: ['bpmn-diagram', id],
    queryFn: () => bpmnDiagrams.get(id!),
    enabled: !!id,
  })
}

export function useCreateBpmnDiagram() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: bpmnDiagrams.create,
    onSuccess: (data) => qc.invalidateQueries({ queryKey: ['bpmn-diagrams', data.company_id] }),
  })
}

export function useUpdateBpmnDiagram() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof bpmnDiagrams.update>[1] }) =>
      bpmnDiagrams.update(id, body),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['bpmn-diagram', data.id] })
      qc.invalidateQueries({ queryKey: ['bpmn-diagrams', data.company_id] })
    },
  })
}

export function useDeleteBpmnDiagram() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: bpmnDiagrams.delete,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['bpmn-diagrams'] }),
  })
}
```

---

## 6. Checklist de aceitação (PR done quando)

- [ ] Stack: zero dependências novas (`@xyflow/react` e `@dagrejs/dagre` já instalados)
- [ ] `/bpmn` lista diagramas do tenant via `useBpmnDiagrams`
- [ ] `/bpmn/new` abre canvas vazio + paleta funcional (drag-to-canvas)
- [ ] `/bpmn/:id` carrega diagram_json do backend e renderiza
- [ ] 6 shape types renderizam corretamente (start, end, intermediate, task, gateway_exclusive, gateway_parallel)
- [ ] Properties panel atualiza node selecionado (label, type, assignee, linked_sipoc_component_id)
- [ ] Botão "Auto-Layout" aplica dagre LR
- [ ] Botão "Validar" executa `validateBpmn()` e exibe erros/warnings em toast
- [ ] Botão "Salvar" faz PATCH no backend (trigger DB versiona automaticamente)
- [ ] Botão "Daedalus ✨" fica **disabled** com tooltip "Geração via Daedalus em fase 2"
- [ ] Diagrama com `linked_sipoc_process_id` aparece também em `/sipoc/processes/:id/bpmn`
- [ ] Sheet `BpmnVersionHistory` lista versões + permite restore

---

## 7. NÃO entra neste PR (fase 2 explícita)

- ❌ **POST `/api/bpmn/generate`** — endpoint backend pra Daedalus criar diagrama via LLM (backend ainda não tem, vira PR backend separado depois)
- ❌ **Export PNG** — requer `html-to-image`, pode esperar
- ❌ **Real-time collaboration** — sem yjs/socket.io
- ❌ **BPMN 2.0 XML import/export** — engine própria, JSON nativo é a fonte

---

## 8. Prompt copy-paste pro agente Claude do frontend

```
Tarefa: Implementar BPMN Modeler completo no VectraClip (vectra-dashboard) seguindo
spec em docs/HANDOFF-FRONTEND-BPMN-MODELER.md (no repo backend vectraclaw-backend).

Contexto:
- Backend está 100% pronto: 7 endpoints CRUD em src/api.py:2157-2430
  (POST/GET/PATCH/DELETE /api/bpmn/diagrams + duplicate + versions)
- Schema vectraclip.bpmn_diagrams + bpmn_diagram_versions com trigger
  automático de versionamento
- Stack do frontend já tem tudo necessário: @xyflow/react ^12.10.2 +
  @dagrejs/dagre ^3.0.0 (verificado em package.json)
- Padrão a espelhar: VectraClip/src/components/workflow/canvas/
  (WorkflowCanvas + StepNode + TriggerNode já existem)

Regras de ouro do projeto (não-negociáveis):
1. ESPELHAR antes de criar — copie shape de StepNode/TriggerNode antes de
   inventar shapes BPMN próprios
2. METADATA-DRIVEN NO HARDCODE — types BPMN não podem ser Literal hardcoded
   no Zod; aceite z.string() e valide contra catálogo se ele existir
3. UI é fonte de dados (MVP) — sem CLI; toda criação/edição via UI

Entregar (escopo MVP — fase 1):
1. Rotas /bpmn, /bpmn/new, /bpmn/:id, /sipoc/processes/:id/bpmn
2. Componente BpmnCanvas reusando padrão WorkflowCanvas
3. 6 custom nodes (start, end, intermediate, task, gateway_exclusive, gateway_parallel)
4. Paleta drag-to-canvas + Properties panel + Toolbar
5. Auto-layout dagre LR + validação BPMN (regras §3.4 do handoff)
6. Endpoints TS (lib/api/endpoints/bpmnDiagrams.ts)
7. Hooks React Query (lib/queries/bpmnDiagrams.ts)
8. Sheet BpmnVersionHistory

NÃO fazer:
- Não criar endpoint /api/bpmn/generate (backend não tem ainda — fase 2)
- Não usar bpmn-js ou Camunda Modeler (engine própria — decisão arquitetural)
- Não inventar shape de node sem espelhar StepNode/TriggerNode
- Não hardcodar lista de modalidades/tipos — usa Zod string + valida no save

Checklist de aceitação no §6 do handoff.
```

---

## 9. Referências

- Plano original do design: [`EXECUCAO-G1-RISK-REGISTER-E-DAEDALUS.md`](./EXECUCAO-G1-RISK-REGISTER-E-DAEDALUS.md) §2
- Decisão de engine própria: memory `feedback_no_camunda_keep_custom_engine`
- ADR pai (Modo 3 Project on-demand usa BPMN como prova visual): [`ADR-VEC-MAPEAR-ANALISAR-AUTOMATIZAR.md`](./ADR-VEC-MAPEAR-ANALISAR-AUTOMATIZAR.md) §3.1
- P3 do ADR pai (`agent_skills × agent_specialties` + bug skills tab): bloqueia retrofit completo do Daedalus, mas NÃO bloqueia a UI BPMN — UI é CRUD de diagrama, agnóstica de quem criou
- Daedalus daemon (existente, ponta solta): `start_all_daemons.py:47` (AGENT_ID `d4ed4145-0000-4000-8000-000000000005`)
