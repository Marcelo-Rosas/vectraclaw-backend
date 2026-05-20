# Athena Recommendations — Catalog Canônico

> **Contrato E2E (bundle + apply + catálogos):** [`CONTRACTS-AGENT-CAPABILITIES.md`](./CONTRACTS-AGENT-CAPABILITIES.md) — fonte para “Alma do Agente” e apply 100%.  
> **Última atualização:** 2026-05-19 (drift auto-apply corrigido; ver contrato pai)
> **Migration:** `supabase/migrations/20260516150000_athena_kind_catalog_canonical.sql`
> **Backend:** `src/api_routes/athena.py` (`_REC_VALID_KINDS`)
> **Frontend Zod:** `src/types/api.ts` (atualizar quando consumir esse doc)

---

## Resumo

`vectraclip.athena_recommendations.kind` aceita **8 valores canônicos**, divididos em 2 categorias funcionais:

- **5 EXECUTÁVEIS** — mutação no DB **após** `POST .../apply` (TO-BE) ou manual hoje; ver [`CONTRACTS-AGENT-CAPABILITIES.md`](./CONTRACTS-AGENT-CAPABILITIES.md) §7
- **3 INFORMATIVOS** — Athena apenas reporta; humano lê e decide o que fazer (sem apply)

---

## 1. Tabela completa

| kind | Categoria | Quem gera | Quem executa | Mutação |
|---|---|---|---|---|
| `hire_new_agent` | Executável | Athena (`athena-recommend`) | Humano + **`POST .../apply`** (TO-BE) | INSERT `agents` + bindings via bundle |
| `add_specialty` | Executável | Athena | Humano + apply (TO-BE) ou AgentDetail manual | INSERT `agent_specialty_configs` |
| `rewrite_system_prompt` | Executável | Athena | Humano + apply ou edit manual + `mark-applied` | UPDATE `agents.system_prompt` + history |
| `create_specialty` | Executável | Athena | Humano + apply (TO-BE) | INSERT `agent_specialties` |
| `consolidate_agents` | Executável | Athena | Humano + apply (TO-BE) | Merge + redirect tasks |
| `diagnose_gap` | Informativo | Endpoint `POST /api/sipoc/diagnose/{sector_id}` (PR9 #139) | **Ninguém — só relatório** | Nenhuma; humano lê |
| `suggest_automation` | Informativo | Derivado do diagnose (activities com 5W2H≥70%) | Humano marca `automation_status` no SIPOC | Humano via UI |
| `suggest_hire_agent` | Informativo | Derivado do diagnose (operation_types sem agent) | Humano aprova → vira `hire_new_agent` | Conversão manual |

---

## 2. Estrutura comum (todas kinds)

```ts
{
  id: uuid,
  company_id: uuid,
  kind: <um dos 8 acima>,
  status: 'pending' | 'approved' | 'applied' | 'rejected' | 'superseded',
  target_agent_id?: uuid,         // executáveis sobre agent específico
  target_specialty_id?: text,     // executáveis sobre specialty
  triggered_by_goal_id?: uuid,    // se vem de athena-classify de goal
  triggered_by_task_id?: uuid,    // se vem de uma task específica
  title: text,
  rationale: text,                // explicação humana-legível
  proposed_changes_json: jsonb,   // shape varia por kind (ver §3)
  citations: jsonb[],             // pra recomendações RAG-grounded
  confidence: numeric (0.0-1.0),
  estimated_effort: 'S' | 'M' | 'L' | 'XL',
  reviewed_by_user_id?: uuid,
  reviewed_at?: timestamptz,
  review_notes?: text,
  applied_history_id?: uuid,      // FK pra agent_prompt_history em rewrite_*
  created_at: timestamptz,
  updated_at: timestamptz
}
```

---

## 3. Shape de `proposed_changes_json` por kind

### `hire_new_agent`
```json
{
  "name": "Novo Agente Mercator Jr",
  "domain": "logistics",
  "specialty_slugs": ["freight-quotation"],
  "model_id": "claude-haiku-4-5",
  "estimated_cost_per_month_usd": 50,
  "rationale_extras": ["alta demanda em cotações"]
}
```

### `add_specialty`
```json
{
  "agent_id": "uuid",
  "specialty_id": "uuid",
  "config_overrides": { "field_values_json": {...} }
}
```

### `rewrite_system_prompt`
```json
{
  "agent_id": "uuid",
  "current_prompt_hash": "abc123",
  "proposed_prompt": "Você é o Mercator...",
  "diff_summary": "Adiciona contexto de TMS C.6",
  "expected_impact": "redução de 30% em tokens por task"
}
```

### `create_specialty`
```json
{
  "slug": "freight-document-extract",
  "name": "Extração de Documentos de Frete",
  "domain": "logistics",
  "default_operation_type": "oracle-extract"
}
```

### `consolidate_agents`
```json
{
  "primary_agent_id": "uuid (mantido)",
  "secondary_agent_ids": ["uuid", "uuid (a remover)"],
  "redirect_task_history": true
}
```

### `diagnose_gap` (PR9 #139)
```json
{
  "sector": {"id", "name"},
  "kpis": {
    "totalProcesses", "totalActivities",
    "coverage5w2hPct", "responsibleCoveragePct"
  },
  "automationStatusCounts": {"undefined", "manual", "hybrid", "automated"},
  "operationTypeCounts": {"<slug>": <int>},
  "automationCandidates": [activity_summary],
  "gaps5w2h": [activity_summary],
  "gapsResponsible": [activity_summary],
  "hireSuggestions": [{"operationType", "activitiesCount", "rationale"}]
}
```

### `suggest_automation`
```json
{
  "activity_id": "uuid",
  "current_automation_status": "manual",
  "proposed_automation_status": "hybrid",
  "operation_type": "oracle-extract",
  "rationale": "5W2H≥70% + 200+ ocorrências/mês"
}
```

### `suggest_hire_agent`
```json
{
  "from_activity_ids": ["uuid", "uuid"],
  "suggested_operation_type": "freight-quotation",
  "expected_volume_per_month": 150,
  "rationale": "5 atividades de cotação sem agent dedicado"
}
```

---

## 4. Fluxo de aprovação/rejeição

```
   ┌──────────────┐
   │  pending     │  ← criada por Athena ou endpoint humano
   └──────┬───────┘
          │
   ┌──────┴──────┬──────────────┐
   ▼             ▼              ▼
 approved    rejected      superseded
   │             │              │
   ▼             │              │
 applied       (fim)          (substituída por outra mais nova)
```

### Endpoints relacionados

| Endpoint | Função | RBAC |
|---|---|---|
| `GET /api/athena/recommendations?status=pending` | Lista pendentes (paginated) | authenticated do tenant |
| `GET /api/athena/recommendations/{id}` | Detalhe | authenticated do tenant |
| `PATCH /api/athena/recommendations/{id}` | Aprovar/Rejeitar/Superseder | admin/consultant/company_admin |
| `POST /api/athena/recommendations/{id}/mark-applied` | Marca como aplicada (humano confirma execução pra kinds executáveis) | admin/consultant/company_admin |

**Pra kinds informativos** (`diagnose_gap`, `suggest_*`): aprovar não dispara mutação no DB — é apenas tracking de "leu, considerou". Pode ir direto pra `applied` ou `rejected` sem precisar de ação manual.

**Pra kinds executáveis**: aprovar é precondição; a ação real é `POST /api/athena/recommendations/{id}/apply` (contrato AC-2) ou manual; `mark-applied` só confirma status sem executar mutações.

---

## 5. Validação (defesa em camadas)

| Camada | Onde | O que valida |
|---|---|---|
| Frontend Zod | `src/types/api.ts` (VectraClip) | Aceita response do GET com kind ∈ 8 valores |
| Backend query validator | `_REC_VALID_KINDS` em `src/api_routes/athena.py` | Rejeita filtro `?kind=foo` com 422 |
| DB CHECK constraint | `athena_recommendations_kind_check` | Rejeita INSERT/UPDATE com kind inválido (erro 23514) |

Se uma camada divergir das outras = drift (foi o caso pré-PR140). Manter as 3 sempre alinhadas:
1. Esta doc é fonte de verdade
2. Mudou kind aqui? Migration + backend + frontend no mesmo PR (ou PRs encadeados com ordem clara)

---

## 6. Histórico de migrations

| Migration | Estado |
|---|---|
| `20260511201201_vec408_athena_recommendations` | Cria tabela inicial (sem CHECK em kind — kind era TEXT livre) |
| `20260516130000_pr2_p1_core_schema` | **Drift introduzido**: adiciona CHECK com 4 valores incompletos (`rewrite_system_prompt`, `diagnose_gap`, `suggest_automation`, `suggest_hire_agent`). Faltavam 4 executáveis |
| `20260516150000_athena_kind_catalog_canonical` | **Resolve drift**: CHECK final com os 8 valores canônicos |

---

## 7. Pendências relacionadas (backlog)

| Item | Resolução |
|---|---|
| Frontend Zod ainda em 5 valores (quebra ao receber `diagnose_gap`) | PR frontend separado: atualizar `src/types/api.ts` pra aceitar os 8 |
| `GET /api/sipoc/diagnose/{sector_id}/latest` ainda não existe | Backend novo: ler última `diagnose_gap` sem disparar nova (evita poluir Analytics quando frontend roda batch de N sectors) |
| Auto-action handlers (Athena execute) para `hire_new_agent`, `add_specialty`, etc. | Roadmap P2 — Athena ainda só recomenda esses, humano aplica via UI |

---

## 8. Roadmap de expansão do catálogo (futuro, baseado em Schmidt LogFrame)

O livro *Strategic Project Management Made Simple* (Terry Schmidt) define **4 perguntas estratégicas** + **3 ciclos de aprendizagem** que mapeiam pra handlers Athena. Hoje cobrimos parcialmente — kinds adicionais virão conforme implementamos handlers faltantes:

### Strategic Foundation (4 perguntas LogFrame)

| Pergunta Schmidt | Handler Athena | kind futuro |
|---|---|---|
| "O que está tentando alcançar e por quê?" | `athena-classify` ✅ (PR3) | `classify_goal_kind` (atualmente sem kind dedicado) |
| "Como medirá o sucesso?" | **falta** `athena-define-metrics` | `define_success_metrics` |
| "Que condições devem existir?" | parcial via diagnose_gap | `identify_risks` (formal risk register) |
| "Como chegará lá?" | `athena-charter` ✅ (PR4) | `charter_proposal` (sem kind dedicado) |

### Learning Cycles (Schmidt §"Adaptando-se aos ciclos")

| Ciclo | Handler Athena | kind futuro |
|---|---|---|
| **Monitor** (tático diário) | já feito via heartbeats + cost analytics | n/a (não é recommendation) |
| **Review** (estratégico periódico) | `athena-recommend` ⚠️ schema sem execução | `review_finding` |
| **Evaluate** (pós-projeto, EVM) | `athena-evm` ⚠️ schema sem execução | `evaluation_summary` |

### Stakeholder engagement

| Conceito Schmidt | Tabela | kind futuro |
|---|---|---|
| "Avalie continuamente se apoio cai" | `sipoc_raci` + `app_users` | `stakeholder_alert` |

### Total projetado

- **Hoje:** 8 kinds (5 executáveis + 3 informativos)
- **Futuro (após implementar handlers Schmidt completos):** ~14 kinds (5 + 9 informativos)

Cada novo kind requer: migration ampliando CHECK + atualizar `_REC_VALID_KINDS` + atualizar Frontend Zod + atualizar este doc. Padrão estabelecido em migration `20260516150000_athena_kind_catalog_canonical.sql`.
