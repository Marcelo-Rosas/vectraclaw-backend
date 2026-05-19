# Auditoria Brain × Daedalus — comparação pré-migração

> **Decisão upstream**: Marcelo escolheu Caminho 3 do W14 (ativar full orchestration) MAS substituindo Brain por Daedalus como orquestrador.
> **Pedido**: auditar o que Brain faz hoje pra comparar com Daedalus e mapear o que Daedalus precisa absorver.
> **Data**: 2026-05-19

---

## 1. Brain (`src/services/brain/`)

868 linhas em 3 módulos. **NÃO é um agente** — é uma biblioteca importada por `api.py` em 6 pontos. Sem AGENT_ID, sem dispatch, sem handler.

### 1.1 `system_prompt.py` (241 linhas)
- Função: `build_system_prompt()` retorna string master compilada
- 6 seções estáticas: Identidade Vectra Cargo + Tools (3 hardcoded: extract_bl_pl, calculate_cbm, send_whatsapp_webhook) + Workflow aduaneiro + Business rules + Escalation + Formatação
- Persona única "Orquestrador VectraClaw" — não parametrizável por company/agente
- Hash + versionamento (`system_prompt_meta()`)
- **Consumido em**: `api.py:8438,8542` (provavelmente endpoints `/api/agent/system-prompt` e `/api/agent/health`)

### 1.2 `workflow_aduaneiro.py` (263 linhas)
- 8 steps hardcoded (W1 a W7 + W4_ALERTA) específicos da importação marítima Vectra Cargo
- `WorkflowStep` dataclass: `id, nome, descricao, responsavel, ferramentas, entrada, saida, decisoes, proximo, alertas`
- Catalogs hardcoded: INCOTERMS (5), CONTAINER_SPECS (5), PORTOS_VECTRA (3), TOLERANCIAS (4), CANAIS_SISCOMEX (4), DOCUMENTOS_IMPORTACAO (7)
- `workflow_to_dict()` serializa pra JSON (consumido por API)
- **Consumido em**: `api.py:8445,8561` (`/api/agent/workflow`, `/api/agent/health`)

### 1.3 `db_failover.py` (364 linhas)
- Catálogo de **10 categorias** de erros DB (FK_VIOLATION, UNIQUE_VIOLATION, NOT_NULL_VIOLATION, CHECK_VIOLATION, AUTH_FAILED, RLS_BLOCKED, etc.)
- `FailoverResult` dataclass com `ai_instruction`, `suggested_fix`, `retry_hint`
- Decorator `@with_db_failover(operation, table, retry_hint)` pra wrapping de corrotinas async
- **Consumido em**: `api.py:3803,7861,8456,8601` (health endpoint + 2 mutations sensíveis)

### 1.4 Endpoints expostos via Brain
| Endpoint | Função | Module |
|---|---|---|
| `GET /api/agent/system-prompt` | Retorna prompt master + meta | `system_prompt.py` |
| `GET /api/agent/workflow` | Retorna workflow aduaneiro serializado | `workflow_aduaneiro.py` |
| `GET /api/agent/health` | Health check do brain (tools, prompt, workflow, db_failover) | todos os 3 |

---

## 2. Daedalus (`src/agents/daedalus.py`)

320 linhas, **agente real** com AGENT_ID `d4ed4145-0000-4000-8000-000000000005`.

### 2.1 Identidade
- AGENT_ID imutável (SSOT em `src/agent_ids.py`)
- Specialty `bpmn-modeling` (agent_specialties + agent_specialty_configs)
- Op types em catalog (backfill PR0b #228): `bpmn-generate`, `sipoc-to-bpmn`, `bpmn-approved-to-workflow`

### 2.2 Pipeline atual
- `entrypoint(task, supabase)`: handler dispatchado por agent_daemon
- 2 source types em `input_json.source_type`:
  - `sipoc_process`: lê `sipoc_components` do processo + gera diagrama linear (1 user_task por activity)
  - `freeform`: texto livre vira 1 task
- Persiste em `bpmn_diagrams` (generated_by='daedalus')
- Retorna envelope I/T/O com `diagram_id`, `diagram_json`, `nodes_count`, `engine_mode='statistical_fallback'`

### 2.3 Estado de evolução
- LLM (Gemini) **bloqueado** — R1 do projeto (memory `gemini_403_permission_denied_2026-05-16`)
- Hoje roda apenas fallback estatístico (layout linear)
- `engine_mode` virará `"llm"` quando R1 resolver

### 2.4 Gap conhecido
Memory `feedback_agent_hiring_ritual` cravado 2026-05-17: **Daedalus é ponta solta a retrofitar**. Foi criado sem ritual completo McKinsey (perfil + skills + responsabilidades + relacionamentos + métricas). É o único agente sem rito de contratação completo.

---

## 3. Comparação direta

| Função | Brain | Daedalus | Daedalus pós-migração |
|---|---|---|---|
| **AGENT_ID** | ❌ não é agente | ✅ d4ed4145-... | ✅ mantém |
| **Dispatcheado por agent_daemon** | ❌ | ✅ | ✅ |
| **System prompt** | ✅ master estático | ❌ | 🆕 **precisa criar** — dinâmico por workflow |
| **Documenta workflow aduaneiro** | ✅ 8 steps hardcoded | ❌ | ⚠️ **NÃO migrar** — workflow vai pra DB (Caminho 2/3 W14) |
| **Documenta tools** | ✅ 3 tools no prompt | ❌ | 🆕 **precisa criar** — lê `tools_catalog` (W14) |
| **Catalogs domínio (incoterms, portos…)** | ✅ hardcoded inline | ❌ | ⚠️ **NÃO migrar** — vira tabelas (`incoterms`, `ports`, `container_specs`) |
| **Self-healing DB** | ✅ decorator | ❌ | ❌ — fica como módulo infra independente |
| **Gera BPMN visual** | ❌ | ✅ | ✅ mantém |
| **Lê SIPOC** | ❌ | ✅ | ✅ mantém + amplia |
| **Lê workflow_definitions/steps** | ❌ | ❌ | 🆕 **precisa criar** |
| **Roteia tasks ativamente** | ❌ | ❌ | 🆕 **precisa criar** (orchestration loop) |
| **Integração LLM** | ❌ texto estático | ⏸ aguarda R1 | ✅ ativo |
| **Endpoints REST** | ✅ 3 endpoints `/api/agent/*` | ❌ | 🆕 **precisa criar** — `/api/orchestrator/*` |

---

## 4. O que Daedalus precisa absorver

### 4.1 ABSORVER (vira parte de Daedalus)

| Função do Brain | Como Daedalus implementa |
|---|---|
| Compilar system prompt master | Função `compile_orchestrator_prompt(workflow_id, step_id, company_id)` — **dinâmico** lendo `workflow_definitions + workflow_steps + tools_catalog`. Persona base + injeção contextual. |
| Documentar tools | Lê `tools_catalog` (a criar via W14.1) + filtra por `step.ferramentas[]` |
| Documentar workflow do step atual | Lê `workflow_steps WHERE workflow_id=X` + serializa contexto pro prompt |

### 4.2 NÃO ABSORVER (vira infra ou DB)

| Função do Brain | Destino |
|---|---|
| `db_failover.py` | **Mover** pra `src/services/db_failover.py` (out of `brain/` namespace). É infra cross-cutting. Decorator `@with_db_failover` continua funcionando — só muda import path. |
| `workflow_aduaneiro.py` (8 steps hardcoded) | **Migrar pra DB**: criar `workflow_definition` "Importação Marítima Vectra" + 8 `workflow_steps` rows + popular `ferramentas`. Migration única. Deletar o dataclass depois. |
| Catalogs INCOTERMS/PORTOS/CONTAINER_SPECS/TOLERANCIAS/CANAIS_SISCOMEX | **Migrar pra DB**: 5 novas tabelas catalog (cross-tenant ou per-company conforme caso). Regra ouro #2. |
| Persona "Orquestrador VectraClaw" estática | **Substituir** por persona Daedalus dinâmica (ler `agents.system_prompt` + `agent_specialty_configs.values`) |

### 4.3 NOVO em Daedalus (não existe nem em Brain nem em Daedalus hoje)

| Função | Por quê |
|---|---|
| **Orchestration loop ativo** | Brain era passivo (dados pra prompt), Daedalus hoje é passivo (handler reativo). Como orquestrador real, precisa loop que: 1) pega workflow_definition ativo, 2) calcula próximo step, 3) cria task com agente correto, 4) monitora done/blocked, 5) avança step seguinte |
| **Op types orchestration** | Hoje só `bpmn-generate`. Precisa adicionar: `workflow-orchestrate-step`, `workflow-route-task`, `workflow-monitor`, `workflow-replan` |
| **Endpoint `/api/orchestrator/run/{workflow_id}`** | Trigger humano que substitui as 3 rotas `/api/agent/*` do Brain |
| **Estado de execução** | `vectraclip.workflow_runs` (não existe) — instâncias rodando de workflow_definitions, com cursor de step atual |

---

## 5. Retrofit pré-requisito do Daedalus (memory `agent_hiring_ritual`)

Antes de Daedalus assumir esse papel, hiring ritual deve ser concluído:

| Item McKinsey | Estado hoje | Precisa |
|---|---|---|
| Perfil (mission, scope) | Implícito no docstring | Doc formal em `docs/AGENTS/daedalus.md` |
| Skills declaradas | `bpmn-modeling` apenas | Adicionar: `workflow-orchestration`, `tool-binding`, `system-prompt-compilation` |
| Responsabilidades (RACI) | Não definido | R: gerar BPMN + orquestrar workflows. A: Athena (HR). C: outros agentes. I: humano |
| Relacionamentos | Não mapeado | Daedalus → Athena (recebe feedback), Daedalus → todos agents (dispatcha), Daedalus → SIPOC (lê AS-IS) |
| Métricas | Não definido | tasks orquestradas/dia, taxa de sucesso de step, latência média entre steps |
| Rollback | Não definido | Se Daedalus falha N tasks, system pausa workflow e alerta humano |
| Aprovação | Não pediu | Marcelo aprova retrofit antes de migração começar |

---

## 6. Plano de migração proposto (5 sub-PRs sequenciais)

### M1 — Retrofit Daedalus (sem código novo de orchestration)
- Criar `docs/AGENTS/daedalus.md` (hiring ritual completo)
- Atualizar `agents.system_prompt` Daedalus + `agent_specialty_configs.values` com novas skills
- Aprovação Marcelo

### M2 — Migrar db_failover pra fora do brain
- Mover `src/services/brain/db_failover.py` → `src/services/db_failover.py`
- Atualizar 4 imports em api.py
- Compat alias `src/services/brain/db_failover.py` que re-exporta (avoid break-changes em PRs paralelos)
- **Risco**: BAIXO. Refactor mecânico.

### M3 — Migrar workflow_aduaneiro pra DB
- Migration `tools_catalog` (W14.1)
- Migration `incoterms` + `container_specs` + `ports` + `tolerances` + `siscomex_channels` (5 catalogs)
- Migration: INSERT `workflow_definitions` "Importação Marítima Vectra" + 8 `workflow_steps` + populate `ferramentas`
- Endpoint `/api/agent/workflow` lê DB em vez de dataclass
- Deletar `src/services/brain/workflow_aduaneiro.py`
- **Risco**: MÉDIO. Toca catalogs + endpoint existente.

### M4 — Daedalus orchestration capabilities
- Função `daedalus.compile_orchestrator_prompt(workflow_step_id, company_id)`
- Handler `workflow-orchestrate-step` — recebe workflow_step_id, calcula próximo task a criar
- Tabela `workflow_runs` (instância de execução)
- Endpoint `/api/orchestrator/run/{workflow_id}`
- **Risco**: ALTO. Lógica nova de orchestration.

### M5 — Aposentar Brain
- Endpoint `/api/agent/system-prompt` → 301 pra `/api/orchestrator/system-prompt/{workflow_id}` (ou deprecated 410)
- Deletar `src/services/brain/system_prompt.py`
- Deletar `src/services/brain/__init__.py` + diretório
- **Risco**: BAIXO se M2+M3+M4 sólidos.

---

## 7. Métricas pra autorizar a migração

Antes de M4 (orquestração nova), deve estar verde:
- ✅ M1 aprovado por Marcelo (Daedalus retrofit completo)
- ✅ M2 OK em prod (db_failover funcionando no novo path)
- ✅ M3 OK em prod (workflow_aduaneiro endpoint igual via DB)
- ✅ W14.1 OK em prod (`tools_catalog` populado com tools de m3 + workflow_aduaneiro)

---

## 8. Decisões pra você

1. **Aprova retrofit Daedalus (M1)?** Sem hiring ritual concluído não migra.
2. **Catalogs domínio** (incoterms, portos, container_specs, tolerances, canais_siscomex) — **cross-tenant** (todo mundo vê) ou **per-company** (Vectra Cargo isolated)?
3. **Ordem**: M1→M2→M3→M4→M5 sequencial, ou M2 (refactor barato) pode ir antes de M1?
4. **`workflow_runs` table** — existe gap. Quer expandir scope da M4 pra incluir runs table + UI de monitoring?
5. **Brain `db_failover` decorator** — mantém nome `@with_db_failover` ou renomeia pra `@with_db_recovery` ao mover (separar do namespace "brain")?

---

## 9. Resumo executivo

| Conclusão | Detalhe |
|---|---|
| Brain é **biblioteca**, Daedalus é **agente** | Migração não é "renomear" — Daedalus absorve 1 das 3 responsabilidades (system_prompt), outras 2 viram DB ou infra |
| Daedalus precisa retrofit hiring antes | Memory `agent_hiring_ritual` cravada — ponta solta hoje |
| `workflow_aduaneiro` deve migrar pra DB | Não absorver no Daedalus. Regra ouro #2 (NO HARDCODE). Vira `workflow_definitions` + steps reais. |
| `db_failover` é infra cross-cutting | Move pra `src/services/db_failover.py` (fora do namespace brain) |
| 5 sub-PRs (M1-M5) | M1 retrofit, M2 refactor, M3 migrate to DB, M4 nova orchestration, M5 cleanup |
| Pré-requisito Daedalus orchestrator | M1 + M2 + M3 + W14.1 verdes antes de tocar M4 |
