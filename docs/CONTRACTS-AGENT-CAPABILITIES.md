# Contrato total — Capabilities do Agente (Alma × Catálogos × Athena × Apply)

> **Status:** especificação canônica (TO-BE) + matriz AS-IS (2026-05-19).  
> **Objetivo:** um único contrato para Agent Builder, Athena, MCP, Skills, Adapter/Model e apply E2E — **100% executável** quando a matriz §12 estiver verde.  
> **Documentos irmãos (não duplicar narrativa):**
> - **Plano execução canal (NAVI × Meta × Hermes):** [`PLAN-CANAL-MENSAGERIA-NAVI-HERMES.md`](./PLAN-CANAL-MENSAGERIA-NAVI-HERMES.md) ← **sequência de PRs e bloqueadores**
> - MCP bindings: [`CONTRACTS-MCP-BINDINGS.md`](./CONTRACTS-MCP-BINDINGS.md)
> - Nous Hermes runtime/adapter: [`CONTRACTS-NOUS-HERMES.md`](./CONTRACTS-NOUS-HERMES.md) — **não é canal WABA** (ver plano canal)
> - WhatsApp webhook/templates: [`META-WHATSAPP-WEBHOOK.md`](./META-WHATSAPP-WEBHOOK.md)
> - Inbound intent: [`ADR-VEC-INBOUND-INTENT-CLASSIFIER.md`](./ADR-VEC-INBOUND-INTENT-CLASSIFIER.md) (Accepted W9)
> - Kinds Athena: [`ATHENA-RECOMMENDATIONS.md`](./ATHENA-RECOMMENDATIONS.md)
> - Curadoria MCP: [`HANDOFF-MCP-PHASE-A-COMMUNITY.md`](./HANDOFF-MCP-PHASE-A-COMMUNITY.md)
> - Skills library: [`ADR-VEC-SKILLS-LIBRARY-AUDIT.md`](./ADR-VEC-SKILLS-LIBRARY-AUDIT.md)

---

## 0. Mapa mental (uma página)

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ CATÁLOGOS GLOBAIS (SSOT — sem company_id)                                │
│  agent_specialties │ mcp_server_catalog │ adapter_catalog │ llm_models │
│  + curadoria comunidade (CSV/JSON — não runtime direto)                 │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ Athena lê snapshot (TO-BE)
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ PROPOSTA (Athena only)                                                    │
│  athena_recommendations.proposed_changes_json                           │
│    └─ hire/retrofit: inclui agent_capability_bundle v1 (TO-BE)        │
│  skill_proposals.bundle_json (TO-BE — opcional espelho UI Builder)      │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ humano approve total | parcial
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ APPLY (transação — TO-BE)                                               │
│  POST .../recommendations/{id}/apply                                    │
│    → agents + agent_specialty_configs + agent_mcp_bindings              │
│      + agent_adapter_configs (+ handshake MCP best-effort)              │
└───────────────────────────────┬─────────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ RUNTIME                                                                 │
│  specialty_resolver + agent_client_factory + MCP invoke (daemon)        │
└─────────────────────────────────────────────────────────────────────────┘
```

**Regra de ouro #2:** nenhum slug de catálogo, model_id, MCP id ou operation_type hardcoded em Python/TS — só IDs vindos do DB ou do bundle aprovado.

---

## 1. Princípios normativos

| # | Regra |
|---|--------|
| P1 | **Skill ≠ MCP.** Skill = `agent_specialties` + `agent_specialty_configs` (prompt, op_types, config). MCP = tools remotas + handshake. |
| P2 | **Catálogo global, binding per-tenant.** Publicação PMO em `/admin/*`; tenant ativa em agente. |
| P3 | **Proposta automática só Athena.** Agent Builder **não** gera bundle sozinho; humano monta manual após rejeitar/ajustar. |
| P4 | **Aprovação parcial obrigatória no contrato.** Todo item do bundle tem `decision: approve \| reject \| override`. |
| P5 | **Apply é transação.** Falha em MCP handshake **não** reverte agent row já criada — retorna `422 partial_apply` (mesma semântica do `POST .../agents` P0-A). |
| P6 | **Hermes (daemon IMAP) ≠ Nous Hermes (adapter) ≠ NAVI (WhatsApp conversa).** WABA = `meta-whatsapp` + NAVI; ver [`PLAN-CANAL-MENSAGERIA-NAVI-HERMES.md`](./PLAN-CANAL-MENSAGERIA-NAVI-HERMES.md). |

---

## 2. Quad-tabela (SSOT)

### 2.1 Skills — `vectraclip.agent_specialties`

| Coluna | Tipo | Notas |
|--------|------|--------|
| `id` | text PK | slug estável (`freight-quotation`) |
| `slug` | text UNIQUE | |
| `name`, `domain`, `description` | text | `domain` alinha `agent_domains` |
| `compatible_roles` | text[] | |
| `system_prompt_template` | text | SSOT do template |
| `config_schema` | jsonb | fields + `operation_types[]` |
| `is_active` | bool | |
| **TO-BE** `source` | text | `seed` \| `athena` \| `import_csv` \| `markdown_upload` |
| **TO-BE** `status` | text | `active` \| `draft` \| `deprecated` |
| **TO-BE** `instruction_*` | text | upload/paste MD — ver plan Skills |

**Binding:** `agent_specialty_configs` (`company_id`, `agent_id`, `specialty_id`, `values` jsonb).

**API existente:** CRUD `/api/agent-specialties`, bind em agent detail.

### 2.2 MCP — `vectraclip.mcp_server_catalog` + `agent_mcp_bindings`

Contrato completo: [`CONTRACTS-MCP-BINDINGS.md`](./CONTRACTS-MCP-BINDINGS.md).

### 2.3 Adapter — `vectraclip.adapter_catalog` + `agent_adapter_configs`

| Slug exemplo | provider | Uso |
|--------------|----------|-----|
| `claude-code-cli` | `claude_code` | default daemons |
| `nous-hermes` | `nous_hermes` | runtime Hermes-Nous — [`CONTRACTS-NOUS-HERMES.md`](./CONTRACTS-NOUS-HERMES.md) |
| `huggingface`, `ollama`, … | … | |

**Binding:** `agent_adapter_configs` (`adapter_id`, `field_values_json`, `is_active`).

### 2.4 Models — `vectraclip.llm_models`

Versionado por `(id, effective_from)`. Referenciado em `field_values_json.model_id` do adapter.

---

## 3. Catálogos de comunidade (curadoria → seeds)

Dois pipelines paralelos; **Athena só lê catálogo produto + snapshot opcional da fila**.

### 3.1 MCP comunidade (Fase A — implementado UI)

| Artefato | Path | Runtime? |
|----------|------|----------|
| SSOT CSV | `docs/THE_RESOURCES_TABLE.csv` | Não |
| JSON build | `VectraClip/public/data/the-resources.json` | Só UI `/admin/mcp` aba Comunidade |
| Fila PMO | `localStorage` key `mcp_curation_queue_v1` | Não |
| **TO-BE** `mcp_proposals` | migration Fase B | Staging antes de `mcp_server_catalog` |

**Campos mínimos no snapshot para Athena (TO-BE):**

```json
{
  "community_mcp_candidates": [
    {
      "resourceId": "tool-…",
      "name": "…",
      "githubUrl": "https://github.com/…",
      "relevance": "high|medium|low",
      "suggestedCatalogId": "mcp-custom-foo",
      "inProductCatalog": false,
      "queueStatus": "queued|exported|dismissed"
    }
  ]
}
```

### 3.2 Skills comunidade (Fase A — **não** implementado UI)

| Artefato | Path | Filtro import |
|----------|------|----------------|
| Mesmo CSV | `THE_RESOURCES_TABLE.csv` | `category` ∈ skills (ver `Bloco de Notas/categories.yaml`) |
| **TO-BE** JSON | `public/data/the-skills.json` | espelho MCP build script |
| **TO-BE** `skill_import_proposals` | DB | PMO → `agent_specialties` `status=draft` |

**Regra:** `categories.yaml` é vocabulário de **import**, não substitui `agent_domains`.

---

## 4. `AgentCapabilityBundle` v1 (coração da “Alma do Agente”)

Tipo canônico embutido em `proposed_changes_json` (hire/retrofit) e em `skill_proposals.bundle_json` (TO-BE).

### 4.1 Envelope

```json
{
  "schema_version": 1,
  "mode": "hire_new_agent",
  "agent": { },
  "adapter": { },
  "model": { },
  "skills": [ ],
  "mcp_bindings": [ ],
  "community_refs": { },
  "compiled_system_prompt_preview": "…",
  "estimated_cost_per_month_usd": 50,
  "rationale_extras": ["…"]
}
```

`mode` ∈ `hire_new_agent` | `retrofit_existing_agent`.

### 4.2 `agent` (hire)

```json
{
  "name": "Mercator Jr",
  "role": "Analista comercial de cotações",
  "domain": "logistics",
  "system_prompt": "Você é…",
  "token_budget": 50000,
  "execution_mode": "REALTIME",
  "requires_approval": false,
  "reports_to_agent_id": null
}
```

### 4.3 `adapter` + `model`

```json
{
  "adapter": {
    "catalog_slug": "claude-code-cli",
    "field_values_json": { "model_id": "claude-haiku-4-5" }
  },
  "model": {
    "llm_model_id": "claude-haiku-4-5",
    "effective_from": "2026-01-01T00:00:00Z"
  }
}
```

Alternativa Nous:

```json
{
  "adapter": {
    "catalog_slug": "nous-hermes",
    "field_values_json": {
      "inference_provider": "openrouter",
      "model_id": "nousresearch/hermes-4",
      "approval_mode": "smart",
      "max_turns": "20"
    }
  }
}
```

### 4.4 `skills[]` (itens checklist)

```json
{
  "item_id": "sk-1",
  "action": "bind_existing",
  "specialty_id": "freight-quotation",
  "values": { "operation_types": ["email_lead"] },
  "rationale": "Cobre gap SIPOC cotação",
  "decision": "approve",
  "override": null
}
```

`action` ∈ `bind_existing` | `create_draft_specialty` (TO-BE: cria `agent_specialties` draft + bind).

### 4.5 `mcp_bindings[]`

```json
{
  "item_id": "mcp-1",
  "action": "bind_existing",
  "mcp_server_id": "mcp-imap",
  "field_values_json": {},
  "allowed_tools": null,
  "rationale": "Hermes email_lead",
  "decision": "approve",
  "override": null,
  "run_handshake": true
}
```

`action` ∈ `bind_existing` | `propose_community_seed` (só referência — não bind até existir em `mcp_server_catalog`).

### 4.6 `community_refs` (somente leitura na proposta)

```json
{
  "mcp_resource_ids": ["tool-abc"],
  "skill_resource_ids": ["skill-xyz"],
  "catalog_snapshot_at": "2026-05-19T12:00:00Z"
}
```

### 4.7 Aprovação parcial — payload

```json
{
  "decisions": [
    { "item_id": "sk-1", "decision": "approve" },
    { "item_id": "mcp-1", "decision": "reject" },
    {
      "item_id": "adapter",
      "decision": "override",
      "override": { "catalog_slug": "nous-hermes", "field_values_json": { "model_id": "…" } }
    }
  ],
  "review_notes": "Sem IMAP até credenciais"
}
```

---

## 5. Integração `athena_recommendations`

### 5.1 Kinds (8) — sem mudança de CHECK

Executáveis: `hire_new_agent`, `add_specialty`, `rewrite_system_prompt`, `create_specialty`, `consolidate_agents`.  
Informativos: `diagnose_gap`, `suggest_automation`, `suggest_hire_agent`.

### 5.2 `proposed_changes_json` por kind (evolução)

#### `hire_new_agent` — **v2 (TO-BE)**

```json
{
  "schema_version": 2,
  "agent_capability_bundle": { }
}
```

**v1 (AS-IS no validador Python):** `name`, `role`, `system_prompt` obrigatórios — sem bundle.

#### `retrofit_existing_agent` — **kind novo (TO-BE migration)**

Mesmo `agent_capability_bundle` com `mode: "retrofit_existing_agent"` e `target_agent_id` na row.

Substitui combinar várias rows (`add_specialty` + bindings MCP) quando o pacote é coerente.

#### Kinds existentes (retrofit granular) — mantidos

| kind | Campos obrigatórios (validador atual) |
|------|--------------------------------------|
| `add_specialty` | `agent_id`, `specialty_id`, `prompt_addendum` |
| `rewrite_system_prompt` | `agent_id`, `proposed_prompt` (≥100 chars) |
| `create_specialty` | `name`, `slug`, `description` |
| `consolidate_agents` | `source_agent_ids` (≥2), `merged_prompt` |

**TO-BE:** `add_specialty` / `create_specialty` devem referenciar `specialty_id` **existente no catálogo** (Athena prompt inclui lista).

### 5.3 Athena context builder (TO-BE — obrigatório para 100%)

Antes do Gemini em `athena-recommend` / `athena-audit`:

```python
CatalogSnapshot = {
  "skills_active": [{ "id", "slug", "name", "domain", "operation_types": [...] }],
  "mcp_active": [{ "id", "name", "category", "transport" }],
  "adapters_active": [{ "slug", "provider", "display_name" }],
  "models_active": [{ "id", "provider", "display_name" }],
  "community_mcp_queued": [...],  # opcional: top N da fila exportada
  "existing_agents_summary": [{ "id", "name", "specialty_count", "mcp_count" }]
}
```

Fontes SQL + (opcional) arquivo JSON comunidade commitado no repo.

---

## 6. `skill_proposals` (TO-BE — UI Agent Builder)

Tabela espelho opcional quando a UX precisar rascunho antes de virar `athena_recommendations`.

```sql
CREATE TABLE vectraclip.skill_proposals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES vectraclip.companies(company_id),
  source text NOT NULL CHECK (source = 'athena'),
  status text NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','approved','rejected','superseded','partially_applied')),
  bundle_json jsonb NOT NULL,
  partial_approval jsonb,
  target_agent_id uuid REFERENCES vectraclip.agents(id),
  athena_recommendation_id uuid REFERENCES vectraclip.athena_recommendations(id),
  reviewed_by_user_id uuid REFERENCES auth.users(id),
  reviewed_at timestamptz,
  review_notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

**Regra:** 1:1 opcional com recommendation; apply sempre via executor §7.

---

## 7. Apply executor (TO-BE — lacuna crítica para “100%”)

### 7.1 Endpoints

| Método | Path | Body | Response |
|--------|------|------|----------|
| `POST` | `/api/athena/recommendations/{id}/apply` | `ApplyRecommendationBody` | `ApplyRecommendationResult` |
| `POST` | `/api/companies/{company_id}/agents/from-bundle` | `AgentCapabilityBundle` + `decisions?` | idem (atalho Agent Builder) |

### 7.2 `ApplyRecommendationBody`

```typescript
type ApplyRecommendationBody = {
  decisions?: BundleDecision[]  // parcial; default = approve all executable items
  dry_run?: boolean             // valida catálogo + FKs, não persiste
  run_mcp_handshake?: boolean     // default true
}
```

### 7.3 `ApplyRecommendationResult`

```typescript
type ApplyRecommendationResult = {
  status: 'applied' | 'partial_apply' | 'failed'
  recommendation_id: string
  agent_id?: string
  created: {
    agent: boolean
    adapter_binding: boolean
    specialty_bindings: string[]   // specialty_ids
    mcp_bindings: string[]         // binding uuids
  }
  errors: Record<string, string>   // item_id → mensagem
  handshake_results?: Record<string, { ok: boolean; tools_count?: number; error?: string }>
}
```

### 7.4 Algoritmo (ordem fixa)

1. `SELECT` recommendation `status='approved'` (ou `pending` se `auto_approve=true` admin-only — **fora do escopo v1**).
2. Parse `proposed_changes_json` → bundle v1/v2.
3. Merge `decisions` (parcial).
4. **TX:**
   - `INSERT agents` (hire) OU lock `agents` (retrofit)
   - `UPSERT agent_adapter_configs`
   - `UPSERT agent_specialty_configs` por skill aprovada
   - `INSERT agent_mcp_bindings` por MCP aprovado
5. Pós-TX: handshake MCP async/best-effort.
6. `UPDATE athena_recommendations SET status='applied', review_notes=…`.
7. Se `errors` não vazio mas agent existe → HTTP **422** + body (igual create_agent P0-A).

### 7.5 AS-IS (hoje)

| Endpoint | Comportamento real |
|----------|-------------------|
| `PATCH .../recommendations/{id}` | Só muda status; **não aplica** |
| `POST .../mark-applied` | Humano já aplicou na mão; **não executa** bundle |
| `POST .../agents` | Cascade adapter+specialty; **sem MCP** |
| Council `hire_agent` | Cria só row `agents` — **sem bundle** |

**Correção documental:** `ATHENA-RECOMMENDATIONS.md` §1 tabela “Athena auto-aplica” está **errada** até §7 existir.

---

## 8. Agent Builder (VectraClip) — contrato UI

Rota: `/admin/agent-builder`.

### 8.1 Modos

| Modo | Entrada | Saída |
|------|---------|--------|
| **Manual** | 4 pickers (adapter, model, skills, MCP) | `POST .../agents` ou mutations incrementais |
| **Pacote Athena** | `?recommendationId=` ou `?proposalId=` | Checklist bundle §4 + approve parcial → `POST .../apply` |

### 8.2 Componentes TO-BE

| Componente | Responsabilidade |
|------------|------------------|
| `AgentCapabilityBundlePanel` | Render checklist + decisions |
| `AgentMcpSection` | Reusar de AgentDetail (contrato MCP §6) |
| `AgentMetaSuggestions` | Mantém heurística local — **não** substitui Athena |

### 8.3 Create atômico (P0)

Request alinhado ao backend `NewAgentInput`:

```typescript
type CreateAgentAtomicInput = {
  name: string
  role: string
  tokenBudget: number
  systemPrompt?: string
  adapterId?: string
  modelId?: string
  adapterFieldValues?: Record<string, unknown>
  specialtyId?: string
  specialtyConfigValues?: Record<string, unknown>
  // TO-BE:
  mcpBindings?: Array<{ mcpServerId: string; fieldValuesJson?: object; allowedTools?: string[] }>
}
```

---

## 9. Fluxos E2E (aceite 100%)

### F1 — Hire com catálogo

1. PMO mantém `/admin/specialties` + `/admin/mcp` produto.
2. Task `athena-recommend` `kind=hire_new_agent` com `CatalogSnapshot` no prompt.
3. Row `pending` com `agent_capability_bundle` v2.
4. Admin abre Builder com bundle → aprova parcial → `POST .../apply`.
5. Agente aparece em `/agents` com adapter + ≥1 skill + ≥0 MCP conforme decisões.
6. Smoke: task de teste com `operation_type` da skill.

### F2 — Retrofit agente existente

1. `athena-audit` + `athena-recommend` `retrofit_existing_agent` (ou kinds granulares).
2. Bundle só com delta (`skills[]`, `mcp_bindings[]`, opcional `rewrite_system_prompt` item).
3. Apply não duplica bindings existentes (UPSERT / skip se igual).

### F3 — Comunidade → produto → Athena

1. PMO marca item na fila MCP comunidade → export JSON Fase B → seed `mcp_server_catalog`.
2. Próximo `hire_new_agent` pode referenciar `mcp_server_id` real (não só `propose_community_seed`).

### F4 — Nous Hermes como adapter do bundle

1. `adapter.catalog_slug = nous-hermes` no bundle aprovado.
2. Apply cria `agent_adapter_configs` com field map do catálogo.
3. Execução: `NousHermesAgentClient` — ver [`CONTRACTS-NOUS-HERMES.md`](./CONTRACTS-NOUS-HERMES.md).

---

## 10. Pydantic / TypeScript (espelho)

Backend (`src/models.py` — TO-BE):

```python
class BundleItemDecision(CamelModel):
    item_id: str
    decision: Literal["approve", "reject", "override"]
    override: Optional[Dict[str, Any]] = None

class AgentCapabilityBundleV1(CamelModel):
    schema_version: Literal[1] = 1
    mode: Literal["hire_new_agent", "retrofit_existing_agent"]
    agent: Dict[str, Any]
    adapter: Dict[str, Any]
    model: Optional[Dict[str, Any]] = None
    skills: List[Dict[str, Any]] = []
    mcp_bindings: List[Dict[str, Any]] = []
    community_refs: Optional[Dict[str, Any]] = None
```

Frontend: `src/types/agentCapabilityBundle.ts` (TO-BE) — reexport Zod strict `schema_version`.

---

## 11. Matriz implementação (AS-IS 2026-05-19)

| Capacidade | AS-IS | TO-BE owner |
|------------|-------|-------------|
| Catálogo MCP produto + API | ✅ | — |
| Curadoria MCP comunidade UI | ✅ | Fase B → `mcp_proposals` |
| Catálogo Skills (`agent_specialties`) | ✅ | + colunas governança |
| Curadoria Skills comunidade | ❌ | script + aba UI |
| `CatalogSnapshot` no Athena | ❌ | `athena.py` |
| `agent_capability_bundle` v2 | ❌ | `athena.py` + validador |
| `skill_proposals` table | ❌ | migration |
| `POST .../apply` | ❌ | `api_routes/athena.py` + service |
| Agent Builder pacote Athena | ❌ | VectraClip |
| MCP no create agent | ❌ | `api.py` cascade |
| MCP tab AgentDetail | ❌ | VectraClip |
| Aprovação parcial | ❌ | apply body |
| Nous Hermes F1 (health/exec) | ✅ | [`CONTRACTS-NOUS-HERMES.md`](./CONTRACTS-NOUS-HERMES.md) |
| Nous Hermes F3 (daemon task) | ⚠️ parcial | `nous_hermes_agent_client.py` |
| Docs “auto-apply” Athena | ❌ drift | corrigir `ATHENA-RECOMMENDATIONS.md` §1 |

---

## 12. Sequência de PRs até verde (100%)

| PR | Escopo | Depende |
|----|--------|---------|
| **AC-1** | `CatalogSnapshot` + prompt Athena; validador bundle v2 em `hire_new_agent` | — |
| **AC-2** | `POST .../recommendations/{id}/apply` + `AgentApplyService` | AC-1 |
| **AC-3** | Cascade MCP em `create_agent` + `from-bundle` | CONTRACTS-MCP |
| **AC-4** | Agent Builder `AgentCapabilityBundlePanel` + wire apply | AC-2, AC-3 |
| **AC-5** | `skill_proposals` (opcional se AC-2 usar só recommendations) | AC-2 |
| **AC-6** | `retrofit_existing_agent` kind + audit usa snapshot | AC-1 |
| **AC-7** | Skills comunidade build JSON + UI (paridade MCP) | — |
| **AC-8** | Fix doc drift `ATHENA-RECOMMENDATIONS.md` | AC-2 |

**Definition of Done (100%):** F1–F4 da §9 passam em smoke automatizado (`tests/test_agent_capability_apply.py` TO-BE).

---

## 13. Onde estava o contrato Nous Hermes?

| Documento | O que é |
|-----------|---------|
| [`docs/PRD-NOUS-HERMES-INTEGRATION.md`](./PRD-NOUS-HERMES-INTEGRATION.md) | PRD narrativo completo (Fases 1–5) |
| [`docs/CONTRACTS-NOUS-HERMES.md`](./CONTRACTS-NOUS-HERMES.md) | **Contrato técnico** extraído (este repo) — endpoints, adapter, migration |
| `supabase/migrations/20260518150000_nous_hermes_adapter.sql` | Seed catálogo |
| `src/api_routes/nous_hermes.py` | `GET/POST /api/nous-hermes/*` |
| `src/services/nous_hermes.py` | Resolução config + HTTP runtime |
| `nous-hermes-runtime/wrapper.py` | Container :9120 |

Não existia arquivo `CONTRACTS-NOUS-HERMES.md` — só o PRD. O contrato de capabilities **referencia** Nous como mais um `adapter.catalog_slug`, não como daemon Hermes IMAP.

---

## 14. Changelog

| Data | Versão | Notas |
|------|--------|-------|
| 2026-05-19 | 1.0.0 | Contrato total inicial; bundle v1; apply executor spec; mapa Nous Hermes |
