# Contratos MCP Bindings — Backend × Frontend

> Espelho de tipos pra Backend (Pydantic) e Frontend (TypeScript) trabalharem em paralelo.
> Plan ref: `~/.claude/plans/twinkly-cuddling-hartmanis.md` §13.4.
> Path arquitetural escolhido: **tri-tabela** (`adapter_catalog` + `mcp_server_catalog` + `connector_channels`).

---

## 1. Tabelas DB (vectraclip schema)

### 1.1 `mcp_server_catalog` (cross-tenant)

| Coluna | Tipo PG | Nullable | Default | Notas |
|---|---|---|---|---|
| `id` | text | NO | — | PK. slug (`camunda-mcp`, `mcp-imap`) |
| `name` | text | NO | — | "Camunda Orchestration Cluster" |
| `description` | text | YES | NULL | resumo capability |
| `transport` | text | NO | — | `stdio` \| `http` \| `sse` |
| `endpoint_url_template` | text | YES | NULL | template `https://{cluster}.camunda.io/mcp/cluster` |
| `auth_type` | text | NO | `'none'` | `oauth2_client_credentials` \| `api_key` \| `bearer` \| `none` \| `env_vars` |
| `field_definitions` | jsonb | NO | `'[]'::jsonb` | schema dos campos (array de AdapterFieldDef shape) |
| `category` | text | NO | `'other'` | `bpm` \| `messaging` \| `code` \| `crm` \| `storage` \| `finance` \| `other` |
| `icon` | text | YES | NULL | Lucide name |
| `color` | text | YES | NULL | tailwind class |
| `display_order` | int | NO | 100 | UI sort |
| `is_active` | bool | NO | true | |
| `documentation_url` | text | YES | NULL | link doc oficial |
| `created_at` | timestamptz | NO | now() | |
| `updated_at` | timestamptz | NO | now() | |

**RLS**: SELECT pra `authenticated`; writes só service_role (catalog cross-tenant).

### 1.2 `agent_mcp_bindings` (per-tenant)

| Coluna | Tipo PG | Nullable | Default | Notas |
|---|---|---|---|---|
| `id` | uuid | NO | `gen_random_uuid()` | PK |
| `company_id` | uuid | NO | — | FK `companies(company_id)` ON DELETE CASCADE |
| `agent_id` | uuid | NO | — | FK `agents(id)` ON DELETE CASCADE |
| `mcp_server_id` | text | NO | — | FK `mcp_server_catalog(id)` ON DELETE RESTRICT |
| `field_values_json` | jsonb | NO | `'{}'::jsonb` | credenciais via `vault://uuid` refs |
| `allowed_tools` | text[] | YES | NULL | whitelist; NULL = todos |
| `tools_cache` | jsonb | YES | NULL | array McpTool[] populado em handshake |
| `last_health_at` | timestamptz | YES | NULL | última conexão OK |
| `last_error` | text | YES | NULL | último erro health check |
| `is_active` | bool | NO | true | |
| `created_at` | timestamptz | NO | now() | |
| `updated_at` | timestamptz | NO | now() | |

**Unique**: `(agent_id, mcp_server_id)` — 1 binding por (agente, MCP).
**RLS**: tenant isolation via `company_id = vectraclip.company_id()`.

---

## 2. TypeScript types (Frontend `src/types/api.ts`)

```typescript
/**
 * MCP server registrado no catalog cross-tenant.
 * Espelha vectraclip.mcp_server_catalog.
 */
export type McpServerCatalogItem = {
  id: string  // 'camunda-mcp', 'mcp-imap', etc.
  name: string
  description: string | null
  transport: McpTransport
  endpointUrlTemplate: string | null
  authType: McpAuthType
  fieldDefinitions: AdapterFieldDef[]
  category: McpCategory
  icon: string | null
  color: string | null
  displayOrder: number
  isActive: boolean
  documentationUrl: string | null
  createdAt: string
  updatedAt: string
}

export type McpTransport = 'stdio' | 'http' | 'sse'

export type McpAuthType =
  | 'oauth2_client_credentials'
  | 'api_key'
  | 'bearer'
  | 'none'
  | 'env_vars'

export type McpCategory =
  | 'bpm'
  | 'messaging'
  | 'code'
  | 'crm'
  | 'storage'
  | 'finance'
  | 'other'

/**
 * Binding (agent × mcp_server) per-tenant.
 * Espelha vectraclip.agent_mcp_bindings.
 */
export type AgentMcpBinding = {
  id: string  // uuid
  companyId: string
  agentId: string
  mcpServerId: string  // FK
  fieldValuesJson: Record<string, unknown>  // vault://uuid refs pra secrets
  allowedTools: string[] | null  // null = todos
  toolsCache: McpTool[] | null  // populated em handshake
  lastHealthAt: string | null
  lastError: string | null
  isActive: boolean
  createdAt: string
  updatedAt: string
}

/**
 * Tool exposed por MCP server.
 * Cached em agent_mcp_bindings.tools_cache após handshake.
 */
export type McpTool = {
  name: string
  description: string | null
  inputSchema: Record<string, unknown>  // JSON Schema
}

/**
 * AdapterFieldDef — shape reusado de adapter_field_definitions.
 * Frontend já tem este tipo declarado; mcp_server_catalog.field_definitions
 * usa o mesmo formato.
 */
// export type AdapterFieldDef = { ... }  // já existe em src/types/api.ts
```

---

## 3. Endpoints REST

| Método | Path | Body | Response |
|---|---|---|---|
| GET | `/api/mcp/servers` | — | `McpServerCatalogItem[]` |
| GET | `/api/mcp/servers/{id}` | — | `McpServerCatalogItem` |
| GET | `/api/agents/{agentId}/mcp-bindings` | — | `AgentMcpBinding[]` |
| POST | `/api/agents/{agentId}/mcp-bindings` | `{ mcpServerId, fieldValuesJson, allowedTools? }` | `AgentMcpBinding` |
| PATCH | `/api/mcp-bindings/{id}` | partial `{ fieldValuesJson?, allowedTools?, isActive? }` | `AgentMcpBinding` |
| DELETE | `/api/mcp-bindings/{id}` | — | 204 |
| POST | `/api/mcp-bindings/{id}/handshake` | — | `{ tools: McpTool[], healthAt: string }` |
| POST | `/api/mcp-bindings/{id}/tools/refresh` | — | `{ tools: McpTool[] }` |

**Auth**: middleware existente (request.state.company_id via JWT). Multi-tenant garantido via FK `company_id` + RLS.

**Error codes**:
- 404: server_id ou binding_id não existe (não vaza cross-tenant)
- 409: binding já existe pra (agent, server) — UNIQUE constraint
- 422: field_values_json não satisfaz field_definitions (vault refs inválidas, campos required vazios)
- 502: handshake falhou (MCP server inacessível) — retorna last_error no body

---

## 4. Pydantic backend (`src/models.py` adicionar)

```python
from typing import Any, Dict, List, Literal, Optional
from src.models import CamelModel


class McpServerCatalogItem(CamelModel):
    id: str
    name: str
    description: Optional[str] = None
    transport: Literal['stdio', 'http', 'sse']
    endpoint_url_template: Optional[str] = None
    auth_type: Literal['oauth2_client_credentials', 'api_key', 'bearer', 'none', 'env_vars']
    field_definitions: List[Dict[str, Any]] = []
    category: Literal['bpm', 'messaging', 'code', 'crm', 'storage', 'finance', 'other']
    icon: Optional[str] = None
    color: Optional[str] = None
    display_order: int = 100
    is_active: bool = True
    documentation_url: Optional[str] = None
    created_at: str
    updated_at: str


class McpTool(CamelModel):
    name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any] = {}


class AgentMcpBinding(CamelModel):
    id: str
    company_id: str
    agent_id: str
    mcp_server_id: str
    field_values_json: Dict[str, Any] = {}
    allowed_tools: Optional[List[str]] = None
    tools_cache: Optional[List[McpTool]] = None
    last_health_at: Optional[str] = None
    last_error: Optional[str] = None
    is_active: bool = True
    created_at: str
    updated_at: str


class AgentMcpBindingCreate(CamelModel):
    """POST body."""
    mcp_server_id: str
    field_values_json: Dict[str, Any] = {}
    allowed_tools: Optional[List[str]] = None


class AgentMcpBindingPatch(CamelModel):
    """PATCH body — todos opcionais."""
    field_values_json: Optional[Dict[str, Any]] = None
    allowed_tools: Optional[List[str]] = None
    is_active: Optional[bool] = None


class HandshakeResponse(CamelModel):
    tools: List[McpTool]
    health_at: str
```

---

## 5. Seed inicial (N5)

3 rows em `mcp_server_catalog`:

```sql
INSERT INTO vectraclip.mcp_server_catalog (id, name, description, transport, endpoint_url_template, auth_type, field_definitions, category, icon, documentation_url) VALUES
  (
    'mcp-imap',
    'IMAP Inbox',
    'Polling de inbox IMAP pra agente Hermes (leitura email_lead).',
    'http',
    'imap://{host}:{port}',
    'api_key',
    '[
      {"key":"host","label":"IMAP Host","type":"text","required":true},
      {"key":"port","label":"Port","type":"number","default":993},
      {"key":"username","label":"Username","type":"text","required":true},
      {"key":"password","label":"Password","type":"secret","required":true}
    ]'::jsonb,
    'messaging',
    'mail',
    'https://www.rfc-editor.org/rfc/rfc3501'
  ),
  (
    'camunda-mcp',
    'Camunda Orchestration Cluster',
    'Referência BPMN canônica pra Daedalus modelagem (não execução). HTTP streamable Camunda 8.9+.',
    'http',
    'https://{cluster}.camunda.io/mcp/cluster',
    'oauth2_client_credentials',
    '[
      {"key":"cluster_url","label":"Cluster URL","type":"text","required":true,"placeholder":"https://abc123.cl.camunda.io"},
      {"key":"client_id","label":"Client ID","type":"text","required":true},
      {"key":"client_secret","label":"Client Secret","type":"secret","required":true},
      {"key":"oauth_token_url","label":"OAuth Token URL","type":"text","required":true,"placeholder":"https://login.cloud.camunda.io/oauth/token"}
    ]'::jsonb,
    'bpm',
    'git-branch',
    'https://docs.camunda.io/docs/apis-tools/orchestration-cluster-api-mcp/orchestration-cluster-api-mcp-overview/'
  ),
  (
    'supabase-mcp',
    'Supabase Vectraclip Schema',
    'Read schema interno workflow_definitions/sipoc_components pra agente consultar metadados próprios.',
    'http',
    'https://{project_ref}.supabase.co/mcp',
    'bearer',
    '[
      {"key":"project_ref","label":"Project Ref","type":"text","default":"epgedaiukjippepujuzc","readonly":true},
      {"key":"access_token","label":"Access Token","type":"secret","required":true}
    ]'::jsonb,
    'storage',
    'database',
    'https://supabase.com/docs'
  )
ON CONFLICT (id) DO NOTHING;
```

---

## 6. Convenções pra Frontend Agent

### 6.1 Onde criar componentes

| Tipo | Path |
|---|---|
| Hook React Query | `src/lib/queries/mcpBindings.ts` |
| API client | `src/lib/api/endpoints/mcpBindings.ts` |
| Section UI no AgentBuilder | `src/components/admin/agents/AgentMcpSection.tsx` (novo) |
| Wizard auth flow | `src/components/admin/agents/McpAuthWizard.tsx` (novo) |
| Tools whitelist multiselect | `src/components/admin/agents/McpToolsPicker.tsx` (novo) |
| MSW handlers (mock) | `src/mocks/handlers.ts` (append) |

### 6.2 Pattern handler MSW exemplo

```typescript
// src/mocks/handlers.ts append
import { rest } from 'msw'
import type { McpServerCatalogItem, AgentMcpBinding } from '@/types/api'

const mockServers: McpServerCatalogItem[] = [
  {
    id: 'camunda-mcp',
    name: 'Camunda Orchestration Cluster',
    description: 'BPMN reference pra Daedalus',
    transport: 'http',
    endpointUrlTemplate: 'https://{cluster}.camunda.io/mcp/cluster',
    authType: 'oauth2_client_credentials',
    fieldDefinitions: [/* ... */],
    category: 'bpm',
    icon: 'git-branch',
    color: null,
    displayOrder: 10,
    isActive: true,
    documentationUrl: 'https://docs.camunda.io/...',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  },
  // ... mcp-imap, supabase-mcp
]

const mockBindings: AgentMcpBinding[] = []

export const mcpHandlers = [
  rest.get('/api/mcp/servers', (_req, res, ctx) =>
    res(ctx.json(mockServers))
  ),
  rest.get('/api/agents/:agentId/mcp-bindings', (req, res, ctx) =>
    res(ctx.json(mockBindings.filter((b) => b.agentId === req.params.agentId)))
  ),
  rest.post('/api/agents/:agentId/mcp-bindings', async (req, res, ctx) => {
    const body = await req.json()
    const newBinding: AgentMcpBinding = {
      id: crypto.randomUUID(),
      companyId: 'mock-company',
      agentId: req.params.agentId as string,
      mcpServerId: body.mcpServerId,
      fieldValuesJson: body.fieldValuesJson || {},
      allowedTools: body.allowedTools || null,
      toolsCache: null,
      lastHealthAt: null,
      lastError: null,
      isActive: true,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }
    mockBindings.push(newBinding)
    return res(ctx.status(201), ctx.json(newBinding))
  }),
  rest.post('/api/mcp-bindings/:id/handshake', (req, res, ctx) => {
    const binding = mockBindings.find((b) => b.id === req.params.id)
    if (!binding) return res(ctx.status(404))
    binding.toolsCache = [
      { name: 'list_process_definitions', description: 'List BPMN defs', inputSchema: {} },
      { name: 'get_process_definition_xml', description: 'Get BPMN XML by id', inputSchema: {} },
    ]
    binding.lastHealthAt = new Date().toISOString()
    return res(ctx.json({ tools: binding.toolsCache, healthAt: binding.lastHealthAt }))
  }),
]
```

---

## 7. Naming convention tool prefixed

Pattern Claude CLI: `mcp__<server_id>__<tool_name>`. Vectra herda:

| MCP server_id | Tool name | Prefixed pro LLM |
|---|---|---|
| `camunda-mcp` | `list_process_definitions` | `mcp__camunda_mcp__list_process_definitions` |
| `mcp-imap` | `read_inbox` | `mcp__mcp_imap__read_inbox` |
| `supabase-mcp` | `query_workflow_steps` | `mcp__supabase_mcp__query_workflow_steps` |

Conversão: hífens em `server_id` viram underscores no prefixo (compatível com LLM tool naming).

---

## 8. Roadmap parallel (resumo §13.3)

- **Phase 0** (Backend solo): N1 hotfix Gemini → N2 cleanup órfãos → N3 vault migration
- **Phase 1** (paralelo):
  - Backend: N4 DDL tabelas
  - Frontend: F1 TS types → F2 UI skeleton MSW → F3 hooks React Query
- **Phase 2** (paralelo):
  - Backend: N5 seed → N6 endpoints → N7 MCPClient refactor
  - Frontend: F4 wizard auth → F5 health badge → F7 tools picker
- **Phase 3** (paralelo):
  - Backend: N7.5 Daedalus prompt enrich
  - Frontend: F6 switch MSW → real
- **Phase 4**: N8 E2E + N9 docs

---

**Status**: este doc é contrato vivo. Atualize quando schema mudar. Pré-condição Phase 1 (Backend N4 + Frontend F1).
