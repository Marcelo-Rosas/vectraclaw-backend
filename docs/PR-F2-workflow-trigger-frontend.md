# PR-F2 — Aba Trigger no /workflow (frontend VectraClip)

> **STATUS REAL — atualizado 2026-05-17 (auditoria pós-implementação):**
>
> ✅ **ENTREGUE — mas de forma diferente do plano original.**
>
> A spec previa **aba "Trigger"** dentro de um form Tabs. A implementação real fez um **pivot arquitetural n8n-style** (decidido na sessão 2026-05-14, ver memory `vectraclaw-2026-05-14-canvas-n8n`) e virou:
>
> - **`TriggerNode.tsx`** — node visual no canvas `@xyflow/react` (`VectraClip/src/components/workflow/canvas/nodes/TriggerNode.tsx`) com ícones lucide pra cada `WorkflowTriggerTypeSlug` (`Hand`, `Clock`, `Zap`, `Bell`)
> - **`CronSelector.tsx`** — componente compartilhado em `VectraClip/src/components/shared/`
> - **`Workflow.tsx`** consome `triggerType`/`cronExpression`/`isScheduled` (linhas 101-102, 296, 304, 340) com `TRIGGER_ICONS` e `TRIGGER_LABEL` maps
>
> **Backend PR #108 mergeado** (3 colunas em `workflow_definitions` + tabela `workflow_trigger_types` + endpoints + sync_routine).
>
> Doc fica como **referência arquitetural histórica** — o plano original (aba em form) ajuda a entender a evolução de pensamento. Quem for ler, deve saber que UI atual é **node no canvas**, não aba de form.

> **Repo destino:** VectraClip (vectra-dashboard) — repositório **separado** deste.
> **Repo backend:** VectraClaw (este) — endpoints já prontos no PR #108 (`feat/workflow-trigger-canon`).

---

## Pra que serve este documento

Especificar a **aba "Trigger" no form de edição de workflow** (`/workflow/{slug}` no VectraClip) que permite ao usuário decidir, **dentro do próprio workflow**, se a execução é manual ou agendada (cron). Pivot arquitetural n8n-style: `/workflow` vira fonte única de criação; `/routines` fica como projeção sincronizada (read-only no futuro).

---

## O que mudou no backend (PR #108)

### 1. Nova tabela canônica
`vectraclip.workflow_trigger_types` — 4 slugs: `manual`, `cron`, `webhook`, `event`.

### 2. Colunas novas em `workflow_definitions`

| Coluna | Tipo | Default | Função |
|---|---|---|---|
| `trigger_type` | `text` FK | `'manual'` | Como o workflow dispara |
| `cron_expression` | `text` nullable | `null` | Cron string quando `trigger_type='cron'` |
| `is_scheduled` | `boolean` | `false` | Toggle on/off sem perder cron |

### 3. Endpoints prontos

#### `GET /api/workflow-trigger-types`
Catálogo read-only (chips no dropdown). Resposta:
```json
[
  { "slug": "manual",  "name": "Manual",   "description": "...", "icon": "hand",      "displayOrder": 100, "isActive": true },
  { "slug": "cron",    "name": "Agendado", "description": "...", "icon": "clock",     "displayOrder": 200, "isActive": true },
  { "slug": "webhook", "name": "Webhook",  "description": "...", "icon": "lightning", "displayOrder": 300, "isActive": true },
  { "slug": "event",   "name": "Evento",   "description": "...", "icon": "bell",      "displayOrder": 400, "isActive": true }
]
```
> `webhook` e `event` aparecem na lista mas estão **disabled** no UI (status "Não implementado ainda" no campo description).

#### `PUT /api/companies/{companyId}/workflows/{slug}`
Salva trigger fields no workflow. Body novo:
```ts
{
  workflow: {
    name: string;
    description?: string | null;
    slug?: string;
    triggerType?: "manual" | "cron" | "webhook" | "event";  // NOVO
    cronExpression?: string | null;                          // NOVO
    isScheduled?: boolean;                                   // NOVO
  },
  steps: WorkflowStepRich[];  // sem mudança
}
```
**Comportamento server-side:**
- Salva 3 campos novos em `workflow_definitions`
- **Sincroniza automaticamente** `vectraclip.routines`:
  - `triggerType='cron'` + `isScheduled=true` + `cronExpression` válido → UPSERT routine vinculada (`status='active'`)
  - Qualquer outro caso → PAUSE routine existente (preserva histórico, não deleta)

#### `POST /api/companies/{companyId}/tasks/from-workflow`
Disparo manual (botão **Run Now**). Body:
```ts
{
  workflowSlug: string;
  parent: { title: string; description?: string; budgetLimit?: number; goalId?: string };
  stepInputs?: Record<string, Record<string, any>>;  // payload por step.slug
}
```
Resposta: `{ parent: Task, subtasks: Task[] }` — parent `in_progress`, subtasks (queued + backlog conforme topologia).

#### `GET /api/companies/{companyId}/workflows/{slug}`
Já existe — agora retorna 3 campos novos no objeto `workflow`:
```ts
{
  workflow: {
    ...
    trigger_type: "manual" | "cron" | "webhook" | "event";
    cron_expression: string | null;
    is_scheduled: boolean;
  },
  steps: WorkflowStep[]
}
```
> ⚠ Backend retorna `snake_case` no GET (consistência com schema), mas aceita `camelCase` no PUT (Pydantic alias). Frontend deve normalizar na read.

---

## O que adicionar no frontend

### Tela alvo
`/workflow/{slug}` ou `/workflow/edit/{slug}` — form de edição do workflow definition.

### Componente novo: aba "Trigger"

Adicionar nova tab no `Tabs` do form (provavelmente já existe um Tabs com "Steps", "Settings", etc.). Conteúdo:

```
┌─────────────────────────────────────────────────────────┐
│ Como esse workflow é disparado?                         │
│                                                          │
│ ┌─[●]─ Manual ──────────────────────────────────────┐  │
│ │  Disparado por ação humana via botão "Run Now"    │  │
│ └────────────────────────────────────────────────────┘  │
│ ┌─[ ]─ Agendado (cron) ─────────────────────────────┐  │
│ │  Disparado por cron expression em janelas fixas    │  │
│ │                                                     │  │
│ │  ┌─ Cron Expression ─────────────────────────────┐ │  │
│ │  │ 0 9 * * 1-5                                    │ │  │
│ │  └────────────────────────────────────────────────┘ │  │
│ │  ↳ "Dias úteis às 09:00 (America/Sao_Paulo)"       │  │
│ │                                                     │  │
│ │  Presets: [Diário 9h] [Seg-Sex 9h] [A cada hora]  │  │
│ │                                                     │  │
│ │  [✓] Ativo  (toggle is_scheduled — pausa sem      │  │
│ │             apagar a expressão)                    │  │
│ └────────────────────────────────────────────────────┘  │
│ ┌─[ ]─ Webhook    ─ Não implementado ──────────────┐  │ disabled
│ └────────────────────────────────────────────────────┘  │
│ ┌─[ ]─ Evento     ─ Não implementado ──────────────┐  │ disabled
│ └────────────────────────────────────────────────────┘  │
│                                                          │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  Próxima execução: 15/05/2026 09:00 (em 18h)            │ ← derivado client-side via cron-parser
│                                                          │
│  [Salvar] [Run Now ⚡]                                  │ ← Run Now sempre visível
└─────────────────────────────────────────────────────────┘
```

### Comportamento

**Form state local:**
```ts
const [triggerType, setTriggerType] = useState<TriggerType>(workflow.trigger_type ?? "manual");
const [cronExpression, setCronExpression] = useState<string>(workflow.cron_expression ?? "");
const [isScheduled, setIsScheduled] = useState<boolean>(workflow.is_scheduled ?? false);
```

**Validações (Zod):**
```ts
const TriggerTabSchema = z.object({
  triggerType: z.enum(["manual", "cron", "webhook", "event"]),
  cronExpression: z.string().nullable(),
  isScheduled: z.boolean(),
}).refine(
  (data) => {
    if (data.triggerType === "cron" && data.isScheduled) {
      return data.cronExpression && data.cronExpression.trim().length > 0;
    }
    return true;
  },
  { message: "Cron expression é obrigatória quando o trigger é 'cron' e está ativo", path: ["cronExpression"] }
);
```

**Submit:**
Inclui os 3 campos no body do PUT:
```ts
await api.put(`/api/companies/${companyId}/workflows/${slug}`, {
  workflow: {
    name: workflow.name,
    description: workflow.description,
    slug: workflow.slug,
    triggerType,
    cronExpression: triggerType === "cron" ? cronExpression : null,
    isScheduled: triggerType === "cron" ? isScheduled : false,
  },
  steps: stepsState,  // já existente
});
```

**Botão "Run Now":**
```ts
async function handleRunNow() {
  const body = {
    workflowSlug: workflow.slug,
    parent: {
      title: `[${workflow.name}] Run manual ${new Date().toLocaleString()}`,
      description: "Disparo manual via /workflow",
      budgetLimit: 0,
    },
    stepInputs: {},  // pode abrir modal pra coletar inputs por step.slug (opcional MVP)
  };
  const res = await api.post(`/api/companies/${companyId}/tasks/from-workflow`, body);
  toast.success(`Workflow disparado: ${res.subtasks.length} subtasks criadas`);
  navigate(`/admin/tasks/${res.parent.id}`);
}
```

### Presets de cron (UX)

| Label | Expression | Human (timezone São Paulo) |
|---|---|---|
| Diário 9h | `0 9 * * *` | Todos os dias às 09:00 |
| Seg-Sex 9h | `0 9 * * 1-5` | Dias úteis às 09:00 |
| Seg-Sex 12h | `0 12 * * 1-5` | Dias úteis ao meio-dia |
| A cada hora | `0 * * * *` | No início de cada hora |
| A cada 30min | `*/30 * * * *` | A cada 30 minutos |
| Semanal (Seg 9h) | `0 9 * * 1` | Toda segunda às 09:00 |

### Render do "Próxima execução"

Usar `cron-parser` (já está no bundle se /routines usa cron) ou `cronstrue` (human-readable). Exibir só quando `triggerType='cron'` e `cronExpression` é válido.

```ts
import cronstrue from "cronstrue/i18n";
const human = cronstrue.toString(cronExpression, { locale: "pt_BR" });
// "às 09:00 de segunda-feira a sexta-feira"
```

---

## Hook React Query

```ts
// hooks/useWorkflowTriggerTypes.ts
export function useWorkflowTriggerTypes() {
  return useQuery({
    queryKey: ["workflow-trigger-types"],
    queryFn: () => api.get<WorkflowTriggerType[]>("/api/workflow-trigger-types"),
    staleTime: 1000 * 60 * 10, // 10min (catálogo canon muda raro)
  });
}
```

---

## Tela `/routines` — ajuste pequeno

Adicionar coluna "Workflow" (link) e remover o botão "Nova Rotina":

| Antes | Depois |
|---|---|
| Header com botão `[+ Nova Rotina]` | Header read-only com texto "Projeções de workflows agendados — para criar, vá em /workflow" |
| Tabela: Nome, Cron, Status, Ações | Tabela: Nome, **Workflow** (link → `/workflow/{slug}`), Cron, Status, Ações (Pause/Resume/Run Now/Delete) |

> ⚠ **Não deletar** o endpoint POST /api/routines ainda — frontend só esconde o botão. Backend deprecation vem no PR-T3.

---

## Checklist de aceitação (PR-F2 done quando)

- [ ] `GET /api/workflow-trigger-types` consumido via hook com cache
- [ ] Aba "Trigger" renderiza no form `/workflow/{slug}`
- [ ] Radio com 4 opções (webhook/event disabled, mostrando "Não implementado ainda")
- [ ] Campo cron_expression aparece só quando `triggerType='cron'`
- [ ] 6 presets clicáveis preenchem o campo
- [ ] Toggle `isScheduled` controla `status='active' | 'paused'` na routine sincronizada
- [ ] Salvar workflow propaga 3 campos pro PUT
- [ ] `Run Now` chama `/tasks/from-workflow` e navega pro detail
- [ ] Próxima execução renderizada via cronstrue/cron-parser
- [ ] `/routines` esconde botão "Nova Rotina" + mostra coluna Workflow

---

## Prompt copy-paste para o agente do frontend

```
Tarefa: Adicionar aba "Trigger" no form de edição de workflow do VectraClip.

Contexto:
- Backend PR #108 mergeado em vectraclaw-backend já expôs 3 colunas novas em
  workflow_definitions (trigger_type, cron_expression, is_scheduled) +
  endpoint GET /api/workflow-trigger-types + sync_routine_for_workflow no
  upsert handler.
- Spec completo: docs/PR-F2-workflow-trigger-frontend.md no repo backend
  (cole o conteúdo aí em uma issue se precisar).

Repos:
- Backend: VectraClaw (vectraclaw-backend) — endpoints já em :3100
- Frontend: VectraClip (vectra-dashboard) — esse aqui

Entregar:
1. Hook useWorkflowTriggerTypes consumindo GET /api/workflow-trigger-types
2. Nova aba "Trigger" no form do /workflow/{slug} com:
   - Radio manual/cron/webhook/event (últimos 2 disabled)
   - Campo cron_expression condicional
   - Toggle is_scheduled
   - 6 presets cron
   - Renderização humano via cronstrue (pt_BR)
3. Botão "Run Now" no rodapé do form (sempre visível) → POST /api/companies/{id}/tasks/from-workflow
4. /routines: remover botão "Nova Rotina" + adicionar coluna Workflow

Validação:
- Zod refine: cron_expression obrigatório quando triggerType='cron' AND isScheduled=true
- Backend retorna snake_case no GET, aceita camelCase no PUT — normalizar via mapper

NÃO mexer:
- Endpoints existentes do backend
- Modal de criação de routine (só esconde o botão, não remove a rota)
- Tabela workflow_steps no DB
```
