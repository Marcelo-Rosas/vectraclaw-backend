# W14 — Auditoria de contrato, consumidores e fluxo atual de `workflow_steps.ferramentas`

> **Pedido**: Marcelo cravou 2026-05-19. Antes de implementar W14, auditar o que existe.
> **Caso de exemplo**: conciliação bancária (Kronos).
> **Veredito antecipado**: campo está em **estado fantasma** — escrito por gambiarra em vários lugares e lido por apenas 1 leitor que **não roda em produção**.

---

## 1. Contrato

### 1.1 DB (`vectraclip.workflow_steps`)

```sql
ferramentas jsonb NOT NULL DEFAULT '[]'::jsonb
```

- **Sem CHECK**: aceita qualquer JSON
- **Sem FK**: não aponta pra catalog
- **Sem comment** na coluna
- **0 rows em prod** com `jsonb_array_length(ferramentas) > 0`

### 1.2 Backend Pydantic (`src/models.py:219`)

```python
class WorkflowStepRich(CamelModel):
    ferramentas: List[Any] = Field(default_factory=list)
```

⚠️ **Tipo `List[Any]`**, não `List[str]`. Aceita dict, list-of-dict, string, etc. Frontend espera `string[]` (incongruência).

### 1.3 Backend doc-fonte (`src/services/brain/workflow_aduaneiro.py:81`)

```python
ferramentas: list[str]     # tools do TOOLS_REGISTRY usadas nesta etapa
```

**Único lugar do codebase com semântica documentada**: é "nome de tool em `m3_tools.TOOLS_REGISTRY`". Mas é um dataclass de exemplo offline, não passa pelo DB.

### 1.4 Frontend (`src/types/api.ts:339`)

```ts
ferramentas: string[]
```

Mais restrito que o backend Pydantic. Esperaria backend a alinhar.

### 1.5 Resumo do contrato

| Camada | Tipo declarado | Semântica documentada | Coerência |
|---|---|---|---|
| DB | `jsonb` livre | nenhuma | Sem CHECK = sem validação |
| Pydantic `WorkflowStepRich` | `List[Any]` | nenhuma | Aceita lixo |
| `workflow_aduaneiro.py` dataclass | `list[str]` | tools do `TOOLS_REGISTRY` | É o único contrato real |
| Frontend TS | `string[]` | implícita: lista de "tools" | Não bate com DB |

**Conclusão contrato**: não existe SSOT. Cada camada define um shape diferente. Apenas `workflow_aduaneiro.py:81` documenta o que isso deveria significar.

---

## 2. Consumidores

### 2.1 Leitores (quem usa o valor)

| Local | Como usa | Em produção? |
|---|---|---|
| `src/services/brain/system_prompt.py:124-125` | Injeta `**Ferramentas:** {lista}` no prompt do "Brain" | **NÃO** — `Brain` é coordenador legado (`src/services/brain/`), não está no dispatch atual |
| `src/api.py:5849,5891` | `specialty_slug = ferramentas[0]` — derivação REVERSA (gambiarra) | SIM (endpoint legacy de step) |
| `frontend SipocCard.tsx:265` | `score += step.ferramentas.length * 5` — pontua automação | SIM (UI) |
| `frontend SipocCard.tsx:419-422` + `AgentBuilder.tsx:470-473` | Badges visuais | SIM (UI) |
| `frontend SipocForm.tsx:140` | Form pré-popula | SIM (UI) |

### 2.2 Escritores (quem popula o valor)

| Local | O que escreve | Coerente com contrato? |
|---|---|---|
| `src/api.py:5491,5744,5784` | `[step.specialty_slug]` se existir, senão `[]` | **❌ Gambiarra** — guarda specialty slug, não tool name |
| `src/api_routes/workflows.py:163,204` | passa `act.get("ferramentas") or []` adiante | Reflete o que vem no payload |
| `src/services/bpmn_materialize.py:322` (meu PR Phase 3) | Sempre `[]` | Consciente — BPMN node não tem ferramentas |
| `workflow_aduaneiro.py:98-220` | hardcoded literal: `["extract_bl_pl"]`, `["calculate_cbm"]`, etc. | ✅ — é o exemplo correto |
| `frontend SipocForm.tsx:140` | `defaultValues?.ferramentas || []` | Reflete o backend |

### 2.3 Agentes que IGNORAM `step.ferramentas`

| Agente | Recebe step info? | Lê ferramentas? |
|---|---|---|
| **Kronos** (conciliação) | Não — lê `task.description` KEY=VALUE + `task.input_json` (`kronos.py:1424`) | **❌ Não** |
| Oracle | Lê via `_OracleSession` (in-memory) + task input | **❌ Não** |
| Mercator | Recebe `input_json` da task | **❌ Não** |
| Plutus | idem | **❌ Não** |
| Hodos | idem | **❌ Não** |
| Hermes | IMAP polling, sem workflow | **❌ Não** |
| Athena | Lê goal + RAG + input_json | **❌ Não** |
| Daedalus | Lê goal + SIPOC + input_json | **❌ Não** |
| Morpheus (triage) | Lê task.input_json apenas | **❌ Não** |

**Brain** (`src/services/brain/system_prompt.py`) é o único leitor mas é orquestrador legado **fora do dispatch atual** (`agent_daemon.py`).

### 2.4 `TOOLS_REGISTRY` (`src/m3_tools.py:149`)

3 tools registradas:
- `calculate_cbm`
- `extract_bl_pl`
- `infer_vehicle_capacity`

Exposto via `GET /api/tools` (`api.py:8428-8431`) retornando `list(TOOLS_REGISTRY.keys())`.

**Não existe tabela `tools_catalog`.** Tools vivem em código Python apenas.

### 2.5 Pipeline esperado vs real

| Etapa | Esperado | Real |
|---|---|---|
| User edita step no canvas | preenche `ferramentas: ["extract_bl_pl"]` | UI tem form, mas backend não dispatcha |
| TaskFactory cria task | copia ferramentas pro task.input_json | **NÃO copia** — TaskFactory não menciona ferramentas |
| Daemon recebe task | injeta tools no prompt do agente | **NÃO injeta** — handlers ignoram |
| Agente chama tool | usa name pra resolver em TOOLS_REGISTRY | **Funciona** mas só se agente fizer chamada própria (CMA) |

---

## 3. Fluxo de exemplo: conciliação bancária

### 3.1 Trigger
Task com `operation_type='conciliacao-backlog'` chega.

```
task.description = "OFX_PATH=C:\...\abril.ofx\nPLANNER_PATH=C:\...\planner-abril.csv\nPERIODO_INICIO=2026-04-01"
task.input_json = null (ou KEY=VALUE como fallback)
task.assigned_to_agent_id = 9c8d7e6f-... (Kronos)
```

### 3.2 Dispatch
`agent_daemon.py` claim task → roteia por `operation_type` → chama handler `_run_conciliacao_backlog` em `src/agents/kronos.py`.

### 3.3 Handler Kronos
- Lê `task.description` (KEY=VALUE) — formato nativo Kronos (`kronos.py:1424`)
- Faz parse OFX + CSV via **imports diretos** (`from src.services.kronos_ofx import ...`)
- Aplica regras de `vectraclip.kronos_rules` (113 rows hoje)
- Gera relatório markdown em `audit-results/`
- Cria task derivada `oracle-report` pro HermesReporter

### 3.4 Onde `step.ferramentas` deveria entrar (mas não entra)

**Cenário hipotético**: workflow_definition com 5 steps de conciliação:
```
1. step "scrape-extrato" → ferramentas: ["kronos_browser"]
2. step "parse-ofx" → ferramentas: ["ofx_parser"]
3. step "match-rules" → ferramentas: ["kronos_rules_engine"]
4. step "generate-report" → ferramentas: ["markdown_renderer"]
5. step "send-email" → ferramentas: ["smtp_client"]
```

**Realidade**:
- Não há workflow_definition nenhum pra conciliação (0 rows em `workflow_steps` com slug kronos-*).
- Kronos roda **fora** do framework de workflow. Tasks são enfileiradas direto (manualmente ou pelo scheduler) com `operation_type` específico.
- Handler kronos.py **não consulta** `workflow_steps` nem `ferramentas`.

### 3.5 Onde o brain tentou usar (não funciona em prod)

`src/services/brain/workflow_aduaneiro.py` define WorkflowSteps com `ferramentas` pra um cenário aduaneiro (importação marítima). Estrutura existe, mas:
- É **dataclass Python**, não rows no DB
- `Brain` agent não está conectado ao agent_daemon
- `system_prompt.py:124` renderiza `**Ferramentas:**` mas só quando alguém chama o Brain — nada faz isso hoje

---

## 4. Gaps fundamentais

### 4.1 Falta de catalog

Não existe `tools_catalog` no DB. Strings em `step.ferramentas` são **livres** — não há validação que `"extract_bl_pl"` existe vs typo `"extract_bl_p"`. Frontend pode mostrar tool "fantasma" que não roda.

**Regra de Ouro #1 violada**: `m3_tools.TOOLS_REGISTRY` é catalog **em código**, deveria ter espelho DB (`tools_catalog`).

### 4.2 Gambiarra `api.py:5491,5744,5784`

```python
"ferramentas": [r.get("specialty_slug")] if r.get("specialty_slug") else []
```

Este código grava o **slug da specialty** dentro de `ferramentas`. Em seguida `api.py:5849` faz **derivação reversa**:

```python
specialty_slug = (normalized.get("ferramentas") or [None])[0]
```

Isso significa que `step.ferramentas[0]` em **muitas rows existentes** seria `"oracle-research"` ou `"freight-quotation"` — **NOMES DE SPECIALTY, NÃO DE TOOL**. Confusão semântica grave. Score em SipocCard.tsx soma `+5 por ferramenta` interpretando como tools — distorcendo métrica.

### 4.3 Dispatch ignora completamente

Nenhum handler em `src/agents/*.py` lê `step.ferramentas`. Mesmo se o usuário editar via UI e salvar, o valor não muda o comportamento de execução. Apenas score visual de automação no Card é afetado.

### 4.4 Brain como leitor legado

`brain/system_prompt.py:124` é o único leitor com semântica certa, mas:
- Brain não está no dispatch
- Brain é arquitetura paralela (`src/services/brain/`)
- Nenhum endpoint dispara Brain hoje em produção

### 4.5 Frontend descoordenado

UI mostra ferramentas como string[] livre. Não consulta `GET /api/tools` pra autocomplete. User pode digitar `"xyz"` e o sistema aceita.

---

## 5. Resumo executivo

| Aspecto | Estado | Comentário |
|---|---|---|
| Contrato declarado | ❌ Divergente em 4 camadas | DB `jsonb`, Pydantic `List[Any]`, dataclass `list[str]`, TS `string[]` |
| Catálogo SSOT | ❌ Inexistente | `m3_tools.TOOLS_REGISTRY` em código + `mcp_client` runtime |
| Escritores | ⚠️ Inconsistentes | `api.py` grava specialty_slug; `workflow_aduaneiro` grava tool name |
| Leitores em prod | ❌ Nenhum | Apenas UI score (gambiarra) |
| Validação | ❌ Zero | Aceita qualquer string |
| Fluxo conciliação bancária | ❌ Não usa | Kronos lê `task.description` direto, ignora steps |

**`workflow_steps.ferramentas` é, hoje, lixo persistido sem efeito operacional.**

---

## 6. 3 caminhos pra W14 (você decide)

### Caminho 1 — Desativar (curto e correto)

- Marcar coluna como deprecated
- Backfill: limpar valores `[specialty_slug]` (api.py gambiarra)
- Frontend: esconder badges + remover score automation
- Reescrever quando houver dispatch real

**Risco**: zero. Hoje é noop.

### Caminho 2 — Ativar mínimo (entrega valor parcial)

- Criar `vectraclip.tools_catalog` (id, name, category, is_active, runtime_module)
- Seed com `m3_tools.TOOLS_REGISTRY` + tools de `workflow_aduaneiro.py`
- FK `workflow_steps.ferramentas[]` via trigger validation OU CHECK json
- Endpoint `GET /api/tools` lê catalog em vez de TOOLS_REGISTRY
- Frontend dropdown multi-select usando catalog
- Backend dispatch: agent_daemon injeta `task.allowed_tools = step.ferramentas` no input_json antes de chamar handler
- Handlers passam pra CMA via `available_tools` no contexto LLM

**Risco**: médio. Toca dispatch (mas adição backwards-compat — se ferramentas=[] = comportamento atual).

### Caminho 3 — Ativar full (visão Brain ressuscitada)

- Tudo do Caminho 2 +
- Integrar Brain como orquestrador real
- Workflow execution lê `step.ferramentas` + dispatcha via Brain → tools
- Conciliação bancária vira workflow_definition de verdade (5 steps com ferramentas)

**Risco**: alto. Refator de arquitetura.

---

## 7. Recomendação

**Caminho 2** — destrava MVP CFN, é incremental, e não requer mexer no Brain. Permite que o canvas BPMN (sprint paralelo) tenha picker de ferramentas válido que **realmente** influencia execução.

Ordem sugerida de sub-PRs:

1. **W14.1**: migration `tools_catalog` + seed m3_tools + endpoint `GET /api/tools` consume catalog
2. **W14.2**: backfill em `workflow_steps` — limpar valores `[specialty_slug]` (manter `[]` ou converter pra tool real se houver match)
3. **W14.3**: pydantic alignment `WorkflowStepRich.ferramentas: List[str]` + validação FK soft no commit
4. **W14.4**: agent_daemon injeta `task.allowed_tools` no input_json + handlers leem (Kronos primeiro como dogfood)
5. **W14.5**: frontend ToolsMultiSelect (consome `/api/tools` catalog) + plug em NodeConfigPanel (depois sprint BPMN encerrar)

Cada sub-PR é independente e <200 linhas.

---

## 8. Próximos passos

- [ ] Você lê esta auditoria
- [ ] Decide caminho (1, 2 ou 3)
- [ ] Eu executo ordem de sub-PRs no caminho escolhido (se for W14.1 backend isolado, posso fazer agora)
