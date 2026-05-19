# ADR-VEC-SKILLS-LIBRARY-AUDIT — Auditoria independente da Skills Library + mapeamento UI do agente

- **Data**: 2026-05-19
- **Status**: Proposto (auditoria; não-implementação)
- **Autor**: Claude (autopilot) sob direção de Marcelo
- **Contexto de origem**: dois planos Cursor — `.cursor/plans/skills_library_architecture_31fdd4b2.plan.md` e `.cursor/plans/bloco_notas_bpmn_audit_f1c1d797.plan.md`
- **Relacionado**: `docs/CONTRACTS-MCP-BINDINGS.md` (tri-tabela MCP, PR #247), migration `20260519233000_n4_mcp_server_catalog_and_bindings.sql`, `~/.claude/plans/twinkly-cuddling-hartmanis.md`

---

## 1. Resumo

O plano Cursor "Skills Library" propõe evoluir o par `agent_specialties` / `agent_specialty_configs` para uma "biblioteca de skills" (quad-tabela com MCP/adapter/channel) + nova camada de governança `skill_proposals`. Esta auditoria **valida as premissas factuais do plano contra o estado real do código/DB** e forma um veredito arquitetural independente, com priorização própria que diverge da do Cursor.

**Veredito**: direção arquitetural correta (não duplicar, skill≠mcp, catálogo global + binding per-tenant). **Mas** a priorização do Cursor subestima um bug ativo de produção (atomic create é fachada) e propõe `skill_proposals` prematuramente.

---

## 2. Verificação factual (subagente, somente leitura)

15 de 17 premissas confirmadas contra DB/código. As 2 que mudam a análise:

| # | Premissa Cursor | Veredito | Evidência |
|---|---|---|---|
| 12 | "Existe atomic create de agente com specialty+adapter+model" | **REFUTADO** | Frontend manda payload rico p/ `POST /companies/{id}/agents`; backend `create_agent` (`src/api.py:3583`) **só insere row em `agents`**, descarta o resto. `_persist_agent_atomic` é comentário fantasma (`api.py:6765`) — função não existe. |
| 5 | "`athena_recommendations` tem `source`+`payload`" | **PARCIAL** | Tabela existe com `kind`/`status`/`proposed_changes_json` — sem `source` nem `payload`. |
| 6 | "`approvals.request_type` com valores em uso" | **PARCIAL** | Coluna existe; tabela **vazia (0 rows)** — fluxo Council/hire nunca exercido em prod. |

Confirmadas (resumo): `agent_specialties` é global sem `company_id` (#1); `agent_specialty_configs` per-tenant com `specialty_id`/`values`/`agent_id` (#2); FK `workflow_steps.agent_specialty_config_id` existe (#3); não existem `agent_skills`/`skill_catalog`/`skill_proposals` (#4); `operation_types_catalog` existe + `values.operation_types[]` (#7); `agent_skills.py` GET /agent-skills com join (#8); `_auto_create_agent_from_approval` cria só `agents` sem cascade (#9); `specialty_resolver.py` é ponto único de render prompt (#10); `daedalus.py:659` lê `agent_specialty_config_id` (#11); rotas frontend confirmadas (#13-15); `categories.yaml` = awesome-claude-code (#16); `agent_domains` existe (#17).

---

## 3. Mapeamento da UI do agente (`/agents/:id` + `/admin/agent-builder`)

Achado que **nenhum dos dois planos mapeou completamente**: há **duas superfícies** distintas, com comportamentos de persistência diferentes.

### 3.1 `/agents/:id` — `src/pages/AgentDetail.tsx` (EDIT — funciona)

6 tabs funcionais + 1 placeholder:

| Tab | Label | Componente | Persiste via | Estado |
|---|---|---|---|---|
| `overview` | Visão geral | inline | — (read) | OK |
| `instructions` | Instruções | `SystemPromptTab` | `PATCH /agents/{id}` systemPrompt | OK |
| `configuration` | Configuração | `AdapterConfigCard` + `AgentEditCard` + `AgentExecutionCard` | `useSaveAgentAdapterConfig` → `agent_adapter_configs` (adapterId + fieldValuesJson, secrets vault://) | OK |
| `skills` | Especialidade | `SpecialtyConfigCard` | `useSaveAgentSpecialtyConfig` → `agent_specialty_configs` (specialtyId + values) | OK |
| `heartbeats` | Heartbeats | `HeartbeatTimeline` | WS read | OK |
| `runs` | Runs | `AgentRunsTab` | read | OK |
| `prospects` | Prospecção | inline stub | nenhum | **PLACEHOLDER** (só specialty gymsite-prospect) |

**Chave**: o edit path persiste specialty + adapter **incrementalmente via mutations separadas** — isso funciona corretamente hoje.

### 3.2 `/admin/agent-builder` — `src/components/workflow/AgentBuilder.tsx` (CREATE — quebrado no backend)

- Wizard create-only (sem tabs). `useCreateAgentAtomic` → `POST /companies/{id}/agents`.
- Backend descarta specialty/adapter/model (ver §2 #12). **AgentBuilder cria agentes "pelados"** — sem skill, sem adapter, sem modelo.
- Comentário no código: `TODO(edit-path): when editingAgentId prop is added...` — edit path não existe no builder.

### 3.3 Zero seção MCP em qualquer superfície

Grep confirma: nenhuma tab/seção MCP no AgentDetail nem AgentBuilder. A MCP section do contrato `CONTRACTS-MCP-BINDINGS.md` precisa nascer.

---

## 4. Mudanças de UI necessárias (mapeadas agora)

| Mudança | Onde | Padrão a espelhar | Esforço |
|---|---|---|---|
| Nova tab **"MCP"** no AgentDetail | `AgentDetail.tsx` AGENT_TABS | `SpecialtyConfigCard` (picker catalog + config + delete) → grava `agent_mcp_bindings` | M |
| Seção MCP no AgentBuilder | `AgentBuilder.tsx` | `AgentMcpSection` do contrato §6.1 | M |
| Health badge no binding MCP | nova | — (MCP-specific, skills não têm) | S |
| Allowed-tools whitelist | nova | multiselect do `tools_cache` | S |
| Corrigir AgentBuilder create | reusar mutations incrementais do AgentDetail OU consertar atomic backend | `useSaveAgentAdapterConfig` + `useSaveAgentSpecialtyConfig` | — (ver P0-A) |

**Insight de baixo custo**: o edit path já tem o padrão certo (mutations incrementais separadas por capability). A correção mais barata do create é o AgentBuilder **reusar essas mesmas mutations** após criar a row base, em vez de depender de um atomic endpoint inexistente.

---

## 5. Veredito arquitetural independente

### Concordo com o Cursor
- NÃO criar `agent_skills` greenfield — evoluir `agent_specialties` (FK em workflow_steps torna rename caro; 70% já existe). Alinha Regra de ouro #1.
- Skill ≠ MCP. Skill = prompt + config + op_types estático; MCP = tools remotas (handshake/health). Tabelas separadas.
- Catálogo global + binding per-tenant (já é assim).
- `skill_proposals` como conceito de governança faz sentido.

### Divirjo do Cursor
1. **O P0 real é o atomic create quebrado, não o naming.** É bug ativo (AgentBuilder cria agentes pelados), não feature futura. Bloqueia MCP section E skill proposals.
2. **`skill_proposals` é prematuro.** `approvals` vazia, fluxo hire nunca rodou E2E. Construir governança sobre fluxo não-validado = over-engineering. Primeiro UM hire atômico, depois staging.
3. **`specialty_resolver.py` é SPOF runtime.** Mexer em `values` shape (ex: extrair `operation_types` p/ coluna própria) tem blast radius em Athena+Daedalus+Kronos+Morpheus. Contract tests no resolver ANTES de tocar shape = segundo P0.
4. **Convergência = compilador de prompt, não schema.** Manter 4 catálogos separados no DB; unificar numa função `compile_agent_capabilities` que lê os 4. Não criar tabela "Capabilities".
5. **Fatiar as ~11 colunas novas** propostas em `agent_specialties`. Governança (status/source) primeiro; `instruction_*` (upload MD) só quando UI de upload existir.

---

## 6. Ordem recomendada (diverge da do Cursor)

1. **P0-A** — Consertar create de agente (cascade adapter+specialty+model real, ou AgentBuilder reusa mutations incrementais). Bug ativo.
2. **P0-B** — Contract tests `specialty_resolver` antes de mexer em `values`.
3. **P0-C** — Completar W15 wire-up (`agent_specialty_config_id` persistido; FK estável). [concordo c/ Cursor]
4. **P1** — Colunas governança (`status`/`source`) em `agent_specialties` + view `skill_catalog` + tab MCP no AgentDetail (contrato MCP já existe).
5. **P2** — `skill_proposals` **só após** hire atômico + approvals validados E2E.
6. **P3** — `instruction_*` (upload/paste MD) + import CSV comunidade (`source=import_csv`).

---

## 7. Cruzamento bloco_notas × skills_library
Ortogonais (MCP library vs Skills library). **Convergência crítica**: ambas passam pelo AgentBuilder → mesmo `create_agent` quebrado. Consertar P0-A destrava as duas. `categories.yaml` = vocabulário de import (não runtime) → `docs/references/` + seeds `source=import_csv`.

---

## 8. Decisões cravadas por Marcelo (2026-05-18, mantidas)
1. Catálogo global (sem `company_id`); binding per-tenant.
2. Propostas automáticas só de Athena (`skill_proposals.source='athena'`).
3. Aprovação parcial permitida (`bundle_json` com checklist por item + overrides).
4. NÃO renomear `agent_specialties`; API/UI pode dizer "Skill".

---

## 9. Próximas ações desta sessão
- [x] Registrar esta auditoria (este ADR)
- [ ] Abrir **P0-A** (fix create de agente) como próximo PR — bug ativo
- [ ] Voltar ao roadmap MCP (N5 seed) com skills como backlog separado
