# ADR-VEC-MCP-SEPARATION — Separação tri-tabela Adapter / MCP / Channel

- **Data**: 2026-05-19
- **Status**: Aceito + Implementado (backend N4-N7.5 em prod; Frontend pendente)
- **Autor**: Claude (autopilot) sob direção de Marcelo
- **Plano origem**: `~/.claude/plans/twinkly-cuddling-hartmanis.md`
- **Contrato**: `docs/CONTRACTS-MCP-BINDINGS.md` (PR #247)
- **Relacionado**: `ADR-VEC-SKILLS-LIBRARY-AUDIT.md`, `feedback_no_camunda_keep_custom_engine`

---

## 1. Contexto

`adapter_catalog` misturava 3 conceitos: LLM providers (claude_code, gemini, ollama…), MCP servers (mcp-imap, mcp-gmail…) e channel (meta-whatsapp). 13 rows, 75% dos MCP órfãos, 1 Gemini broken, 1 Codex zumbi. A config do agente não distinguia "qual é LLM" de "qual é tool MCP" — tudo caía em `agent_adapter_configs` opaco.

Marcelo cravou (2026-05-19): UI de config do agente deve separar **Adapter** (LLM) de **MCP** (tools) em seções distintas; usar MCP como o Claude CLI usa `/mcp` (registro + discovery + namespacing + auth), escalado multi-tenant.

## 2. Decisão

Separação **tri-tabela**:

| Conceito | Catálogo (cross-tenant) | Binding (per-tenant) |
|---|---|---|
| **LLM provider** | `adapter_catalog` (purgado: só LLM) | `agent_adapter_configs` |
| **MCP server** | `mcp_server_catalog` (novo) | `agent_mcp_bindings` (novo) |
| **Channel** | `connector_channels` (já existia) | per-company |

Skill (specialty) é uma **quarta** dimensão ortogonal (`agent_specialties` / `agent_specialty_configs`) — ver `ADR-VEC-SKILLS-LIBRARY-AUDIT.md`. Não confundir com MCP.

## 3. Implementação entregue (10 PRs, 2026-05-19)

| PR | Camada | O quê |
|---|---|---|
| #247 | contrato | TS+Pydantic+endpoints+seed em `docs/CONTRACTS-MCP-BINDINGS.md` |
| #248 | DB | N1 Oracle Gemini `model_id=null → gemini-2.5-pro` |
| #249 | DB | N2 cleanup 4 órfãos (codex/mcp-gmail/mcp-slack/mcp-github) + template_language deprecated. **13→9 adapters** |
| #250 | DB | N3 Hermes IMAP `secret:GODDADY_SECRET → vault://uuid` |
| #251 | DDL | N4 `mcp_server_catalog` + `agent_mcp_bindings` + RLS + 7 idx |
| #254 | DML | N5 seed 3 servers (mcp-imap + camunda-mcp + supabase-mcp) |
| #255 | API | N6 router `agent_mcp_bindings.py` — 8 endpoints CRUD + handshake + tools/refresh |
| #256 | service | N7 `mcp_client.py` auth resolver (oauth2/bearer/api_key) + health_check + JSON-RPC |
| #257 | agent | N7.5 Daedalus `compile-prompt` injeta tools `mcp__<server>__<tool>` |
| #253 | fix | P0-A create_agent cascade (bug ativo descoberto na auditoria) |

## 4. Esquema das tabelas

### `mcp_server_catalog` (cross-tenant)
`id` (text PK) · `name` · `description` · `transport` (stdio\|http\|sse) · `endpoint_url_template` · `auth_type` (oauth2_client_credentials\|api_key\|bearer\|none\|env_vars) · `field_definitions` (jsonb, shape adapter_field_definitions) · `category` (bpm\|messaging\|code\|crm\|storage\|finance\|other) · `icon`/`color`/`display_order` · `is_active` · `documentation_url`. CHECK em transport/auth_type/category.

### `agent_mcp_bindings` (per-tenant)
`id` (uuid PK) · `company_id` (FK CASCADE) · `agent_id` (FK CASCADE) · `mcp_server_id` (FK RESTRICT) · `field_values_json` (vault:// refs) · `allowed_tools` (text[] whitelist, NULL=todos) · `tools_cache` (jsonb, populado handshake) · `last_health_at` · `last_error` · `is_active`. UNIQUE (agent_id, mcp_server_id). RLS tenant isolation (auth.jwt → app_metadata → vectraclip → company_id).

## 5. Runtime — como o agente consome MCP

1. Admin pluga MCP no agente via binding (UI pendente; endpoint N6 live).
2. `POST /api/mcp-bindings/{id}/handshake` → `McpClient.from_binding()` resolve auth (oauth2 token exchange / bearer / api_key) + lista tools → popula `tools_cache`.
3. Daedalus `compile-prompt` (N7.5) lê bindings ativos do agente delegado + injeta tools prefixed `mcp__<server>__<tool>` no system_prompt (respeita `allowed_tools`).
4. Camunda MCP = referência BPMN **design-time** pro Daedalus (NÃO execução; engine própria mantida — `feedback_no_camunda_keep_custom_engine`).

Naming: hífens no `server_id` viram underscore no prefixo (`camunda-mcp` → `mcp__camunda_mcp__<tool>`).

## 6. Deferido (raio/risco — sem consumidor hoje)

- **stdio transport** — subprocess JSON-RPC. Todos servers seedados são http. `resolve_mcp_auth` levanta `McpAuthError("stdio_transport_not_implemented")`.
- **Background health loop** — só `health_check()` on-demand. Loop periódico tocando todos bindings = scope futuro.
- **Cutover Hermes** — `mcp-imap` existe nas DUAS tabelas (adapter_catalog legacy + mcp_server_catalog novo). Hermes ainda lê IMAP de `agent_adapter_configs`. N5 foi aditivo; migrar Hermes pro binding precisa de wiring no daemon (futuro).
- **Frontend F1-F7** — TS types, tab MCP no AgentDetail (espelhar SpecialtyConfigCard), hooks, wizard auth. Não iniciado.
- **N8 smoke E2E** — precisa JWT/UI; validação manual pendente.

## 7. Auditorias (read-only, 2 subagentes)

- N4 vs contrato: ✅ bate 1:1; único P2 = policy SELECT filtra `is_active=true` (contrato não declarava; aceito como UX-only).
- Skills Library factual: 15/17 premissas Cursor confirmadas; refutou #12 (atomic create inexistente → virou P0-A).

## 8. Consequências

**Positivas**: separação conceitual limpa; MCP plugável por agente sem hardcode; auth governado por vault://; tools whitelist per-binding; multi-tenant via RLS; Camunda como referência sem virar engine.

**Custo**: 4 catálogos pra UI gerenciar (adapter/mcp/skill/channel). Mitigação: convergir no compilador de prompt (`compile_agent_capabilities`), não no schema.

**Pendência crítica**: sem Frontend (tab MCP), bindings só criáveis via curl/endpoint. Cutover Hermes não feito — duplicação mcp-imap temporária.
