# Code Patterns — VectraClaw / VectraClip

> **Leia este arquivo ANTES de escrever código novo.** Cada padrão aqui foi decidido
> com motivo e já está aplicado em N lugares. Se você está prestes a fazer algo
> parecido com um dos casos abaixo, **use o mesmo padrão** em vez de reinventar.
>
> Mantenha esse doc curto e ativo. Se um padrão muda, atualize aqui na mesma PR.

---

## Regras de Ouro (índice)

| # | Regra | Seção |
|---|--------|--------|
| **1** | Espelhar antes de criar (SELECT / vizinho no catálogo) | P0, P7 |
| **2** | Metadata-driven — **NO HARDCODE** | P1 |
| **3** | Pós-merge: `docker cp` + restart (não assumir deploy automático) | P4 |
| **4** | Invocar `hardcode-auditor` **antes** de melhorar código | P8 (auditor) |
| **5** | Scripts one-off: Docker ephemeral (sem instalar deps no host) | `scripts/autopilot/*` |
| **6** | **NUNCA MCP** para DDL/migrations no Supabase | P9 |

Detalhe operacional de migrations: `supabase/CLAUDE.md`, `supabase/MIGRATIONS.md`.

---

## P0 — Espelhar antes de criar (regra dura) — **REGRA DE OURO #1**

**Antes de adicionar entry em qualquer catálogo (`agent_specialties`, `adapter_catalog`,
`llm_models`, `operation_types_catalog`, `agent_execution_modes`, etc.), você DEVE:**

1. Rodar `SELECT <coluna_relevante> FROM <tabela> LIMIT 1` (ou ler o frontend Zod schema)
2. **Copiar o shape literal** — nomes de campos, tipos, formato de arrays
3. Só então preencher com o seu conteúdo

**Por quê esta regra é dura:** múltiplas violações no mesmo dia (2026-05-16):
- `bpmn-modeling.config_schema[0].options` virou `[{value, label}]` em vez de `["str", "str"]`
  → quebrou Zod do frontend → hotfix #161
- `bpmn-modeling.config_schema[0].default` em vez de `defaultValue` → mesmo hotfix
- Padrão genérico: agentes Claude tendem a "enriquecer" schemas porque o shape "mais rico"
  parece melhor abstratamente. Mas o frontend tem Zod schema rígido que segue o vizinho.
  Schema rico ≠ schema certo.

**Anti-pattern (✋):**

```python
# ❌ ERRADO — assumi shape sem checar
config_schema = [{
    "key": "model",
    "options": [{"value": "x", "label": "X"}],  # parece mais rico…
    "default": "x",                              # parece mais natural…
}]
```

```python
# ✅ CORRETO — espelhei Hodos antes
# (SELECT config_schema FROM agent_specialties WHERE slug='route-cost-calculation')
config_schema = [{
    "key": "model",
    "options": ["x", "y", "z"],     # convenção da casa
    "defaultValue": "x",            # convenção da casa
}]
```

**Aplica a:** specialty config_schema, adapter field definitions, llm_models tier
descriptors, qualquer payload JSONB consumido pelo frontend com Zod schema rígido.

---

## P1 — Catalog-driven enums (no Literal hardcoded) — **REGRA DE OURO #2**

> **Citação Marcelo 2026-05-17 (caps lock):** _"O projeto foi contruido com base em metadados e tabelas independentes configuraveis - NÃO PODE EXISTIR NADA HARDCODADO"_

**Regra:** se existe tabela `vectraclip.X_catalog` (ou `X_types`, `X_modes`, `X_status`,
`llm_models`, `adapter_catalog`, `agent_specialties`), TODO valor que seria `Literal[...]`
ou `z.enum([...])` ou `CONSTANT = [...]` em código ou env-var deve ser **`str` /
`z.string().min(1)` + lookup no catálogo**. Validação contra o catálogo acontece
no validator do PUT (backend) e na render (frontend lista via GET endpoint).

**Escopo amplo (não só enums):**
- Constantes de modelos / cost-per-token → `llm_models` (versionado)
- Lista de providers / adapters → `adapter_catalog`
- Specialties / prompts editáveis → `agent_specialties` + `agent_specialty_configs`
- Fallback chains / hyperparams (max_turns, temperature, approval_mode) → `agent_adapter_configs.field_values_json`
- Routing scores → `operation_types_catalog.routing_score` (após P13)
- Feature flags por tenant → `adapter_catalog.is_active` ou catálogo dedicado
- Tipos de operação / status → catálogos respectivos
- Keys de API → `agent_adapter_configs` ou referência a vault (não env compartilhado)

**Sinais de violação (red flags):**
- Adicionando `HERMES_FOO=...` ou `GEMINI_FOO=...` em `.env.example` → tem tabela espelho?
- Adicionando `CONSTANT_DICT = {...}` em `.py` → tem tabela espelho?
- `XXX_BASE_URL = "https://..."` em `src/managed_agents/*.py` → `adapter_field_definitions.base_url` é o pattern
- `XXX_TOOL_CAPABLE_MODELS = {...}` set em `.py` → coluna `llm_models.supports_tool_calling` é o pattern
- Hardcoding slug de model em config (ex: `"hermes-4-405b"`) → `llm_models.id` é a fonte
- "Vou hardcodar pra MVP e migrar depois" → migrar nunca acontece. Fazer certo desde o início.

### Caso real (2026-05-17) — Groq adapter (regravado pós-2-violações-no-mesmo-dia)

Tentei adicionar Groq adapter com 2 hardcodes:
```python
# ❌ ERRADO — duas violações no mesmo arquivo
GROQ_BASE_URL = "https://api.groq.com/openai/v1"           # url hardcoded
GROQ_TOOL_CAPABLE_MODELS = {"llama-3.3-70b-versatile", ...}  # set hardcoded
```

Pulei a regra "espelhar antes" — `adapter_field_definitions` do Ollama já mostra o pattern:
```
ollama.base_url → field_type=text, required=true, sort_order=10
```

E `llm_models` é versionado, deveria carregar capacidades. Correção:
```python
# ✅ CORRETO — sem constantes Python
base_url = config["base_url"]  # vem de adapter_field_definitions seed
if not base_url:
    raise ValueError("base_url ausente: configure no adapter UI")
# tool_capable lê de llm_models.supports_tool_calling (coluna nova)
```

Lição: `src/managed_agents/*_agent_client.py` **não deve ter NENHUMA constante de URL ou de set de modelos**. Guardrail em runtime: `__init__` levanta `ValueError("base_url ausente")` se config não tem — sistema falha alto na primeira chamada em vez de silenciosamente usar default Python.

**Vault do projeto = Supabase com RLS.** `agent_adapter_configs.field_values_json` (por agente, RLS por company_id) guarda secrets; `adapter_field_definitions` guarda shape. Nenhum secret/config vai em `.env`, `.py` ou hook git — fonte única é o catálogo.

### Já aplicado a

| Conceito | Tabela catalog | Backend | Frontend |
|---|---|---|---|
| `adapter_type` | `adapter_catalog` | `models.Agent.adapter_type: str` | `schemas.ts:101 agentAdapterTypeSchema = z.string().min(1)` |
| `operation_type` | `operation_types_catalog` | `models.Task.operation_type` (mas Pydantic ainda Literal — ver gap V6 backend) | `taskOperationTypeSchema = z.string()` |
| `execution_mode` | `agent_execution_modes` | `models.AgentExecutionConfig.execution_mode: str` + validator | `agentExecutionModeSchema = z.string().min(1)` |

### Como aplicar a um novo conceito

**Backend (`src/models.py`):**

```python
# ANTES (errado)
some_field: Literal["A", "B", "C"]

# DEPOIS (correto)
# str + FK em vectraclip.some_table.some_field garante validação contra
# `some_catalog`. Catalog-driven, não hardcoded.
some_field: str
```

**Backend (`src/api.py` — input model do PUT):**

```python
@validator("someField", pre=True)
def normalize_and_validate(cls, v):
    if v is None or (isinstance(v, str) and not v.strip()):
        raise ValueError("someField_required")
    v = str(v).strip().upper()  # ou .lower() — convenção do catálogo
    valid = _load_some_catalog_ids()  # cacheado 60s
    if valid and v not in valid:
        raise ValueError(f"unknown_value: '{v}' (válidos: {sorted(valid)})")
    return v
```

**Backend — helper de cache (template):**

```python
_SOME_CACHE = {"ids": None, "default": None, "fetched_at": 0.0}
_SOME_CACHE_TTL_S = 60.0

def _load_some_catalog_ids() -> set:
    import time
    now = time.time()
    cached = _SOME_CACHE.get("ids")
    if cached is not None and (now - _SOME_CACHE.get("fetched_at", 0.0)) < _SOME_CACHE_TTL_S:
        return cached
    if not supabase:
        return set()
    try:
        res = supabase.table("some_catalog").select("id,is_active").eq("is_active", True).execute()
        rows = res.data or []
        _SOME_CACHE["ids"] = {str(r["id"]) for r in rows if r.get("id")}
        _SOME_CACHE["default"] = str(rows[0]["id"]) if rows else None
        _SOME_CACHE["fetched_at"] = now
        return _SOME_CACHE["ids"]
    except Exception as e:
        logger.warning(f"_load_some_catalog_ids fallback: {e}")
        return set()
```

**Frontend (`VectraClip/src/types/api.ts`):**

```ts
// some_field é catalog-driven (vectraclip.some_catalog).
// Backend dropou o Literal — aceitar string livre evita drift.
// O componente lista as opções via GET /api/some-catalog.
export type SomeFieldType = string
```

**Frontend (`VectraClip/src/lib/api/schemas.ts`):**

```ts
export const someFieldSchema: z.ZodType<SomeFieldType> = z.string().min(1)
```

**Frontend — componente que usa:**

Se o catálogo tem **`config_schema` JSONB**, renderize via
`<DynamicSchemaForm schema={selectedItem.configSchema} value={...} onChange={...} />`
(já existe em `VectraClip/src/components/forms/DynamicSchemaForm.tsx`).
Aceita `text | textarea | number | boolean | secret | select`.

### Anti-patterns

❌ `Literal["A", "B", "C"]` em `models.py` quando existe `X_catalog` no DB
❌ `<SelectItem value="A">` hardcoded em JSX quando o backend já tem GET
❌ `if mode === "A" { ... } else if mode === "B" { ... }` em JSX (renderiza via config_schema)
❌ `const VALID_X = ("a", "b", "c")` em `api.py` (use `_load_X_ids()`)
❌ Fallback `or "DEFAULT_VALUE"` hardcoded em fluxo (busca primeiro do catalog por `display_order`)

---

## P2 — Normalização de payload camelCase → snake_case (SIPOC)

Frontends do VectraClip mandam camelCase. DB exige snake_case. Helper único em
`src/api.py`:

```python
def _normalize_sipoc_payload_to_snake(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Aceita camelCase OU snake_case, devolve snake_case."""
    camel_to_snake = {
        "companyId": "company_id",
        "sectorId": "sector_id",
        # ... full list em api.py
    }
    # ...
```

**Regra:** TODO handler POST/PATCH SIPOC chama
`payload = _normalize_sipoc_payload_to_snake(payload)` **na primeira linha**
após auth. Antes de adicionar handler novo, **expanda o dict** se faltar key
— não crie helper paralelo.

### Já aplicado a

- POST `/api/sipoc/positions`, `/sectors`, `/processes`, `/components`
- PATCH `/sectors`, `/processes`, `/components/{id}` (Lote 1 BE-A/B/C — PR #145)

### Sintoma de violação

PATCH retorna `400 "no_valid_fields"` apesar do payload ter campos válidos
→ falta entry no `camel_to_snake` dict.

---

## P3 — RBAC com `require_role_not(scope, BLOCKED_SET, action_label)`

Endpoints de mutation SIPOC reusam constants:

```python
_SIPOC_EDIT_BLOCKED_ROLES = _SIPOC_DELETE_BLOCKED_ROLES
```

**Regra:** NÃO crie novo set de roles por handler — reuse o existente da
mesma categoria (read / edit / delete / admin).

---

## P4 — Live-update container (sem rebuild) — **REGRA DE OURO #3 PÓS-MERGE**

> **Citação Marcelo 2026-05-17 (após PR #184):** _"Sim sempre rode — Regra de Ouro após Merge manual do Marcelo rodar `docker cp` + restart para aplicação do smoke"_

CI atual **não faz deploy automático**. Merge no `main` ≠ código rodando em prod.
Após Marcelo mergear PR que toca `src/*.py`, Claude DEVE executar:

```powershell
# 1. Sync local
git checkout main && git pull --ff-only

# 2. Cp dos arquivos alterados (espelhar lista do diff do PR)
docker cp src/api.py vectraclaw-backend:/app/src/api.py
docker cp src/models.py vectraclaw-backend:/app/src/models.py
# (mais arquivos conforme PR)

# 3. Restart
docker compose restart backend

# 4. Aguardar healthy (~15-25s)
Start-Sleep -Seconds 15
docker compose ps backend
# Esperado: "Up X seconds (healthy)"

# 5. Validar mudança (pra schema changes — confirma deploy pegou)
curl -sS https://api-vectraclip.vectracargo.com.br/openapi.json `
  | python -c "import sys,json; print(json.dumps(json.load(sys.stdin)['components']['schemas']['<ModelChanged>'], indent=2))"

# 6. Só ENTÃO smoke
```

**Sintoma de violação:** smoke mostra schema antigo (Literal[...]) quando código
local mostra `str + validator`. Diagnóstico: deploy não foi feito. NÃO é PR
parcial.

`compose up --build -d` (3min) só quando:
- `requirements.txt` mudou (deps novas)
- `Dockerfile` mudou
- Adicionou/removeu arquivo (não só editou)
- Cache suspeito

Pra edição de Python existente, `cp` + restart é 18x mais rápido e suficiente.

**Não aplicar a:** migrations SQL (`supabase db push` separado), só `docs/`,
tests, outro repo (cargo-flow-navigator/VectraClip).

Detalhe completo: memory `feedback_post_merge_live_update.md` (regra de ouro #3).

---

## P5 — PR cirúrgico, escopo único

Cada PR resolve **um conceito**. Não bundlar:
- "execution_mode catalog-driven" ≠ "operation_type catalog-driven" (PRs separados)
- "RACI matrix backend" ≠ "Diagnose UI" (PRs separados)

Body do PR cita:
1. Que conceito fecha (1 linha)
2. Lista de arquivos tocados + diff stat
3. Smoke executado (lista T1..Tn com HTTP code)
4. Padrão aplicado (linka este `CODE-PATTERNS.md` por número, ex.: "Segue P1")

---

## P8 — Broken windows intencionais (UI quebrada como sinal honesto)

**Regra:** se uma feature tem dependência crítica **não-implementada** (ex.: executor real,
integração externa, fluxo de aprovação incompleto), **deixar a UI quebrar pode ser melhor
que UX bonita que mascara o gap.** Documentar SEMPRE em `AUDIT-CONSOLIDADO.md` com
tag `⏸️ INTENTIONAL` + critério de saída.

### Por que isso é regra, não improviso

UI bonita cria **dívida invisível**: humano (e cliente) usa a feature achando que está
fazendo X, quando na real o sistema só registra status. Erro vermelho na tela é uma
**flag estrutural** — todo mundo que abre vê o gap. Conserto cosmético = sumir o sinal.

### Quando aplicar

- Feature display-only que parece interativa (botões "Aprovar" sem executor real)
- Integração externa mockada que vai ser substituída
- Workflow incompleto onde N de M passos existem (UI mostraria o N como se fosse M)
- Endpoint backend mais novo que frontend (sem retrocompat planejada)

### Quando NÃO aplicar

- Bug genuíno em feature completa → conserte normal
- Erro de validação esperado (form de input) → mostre msg amigável
- Loading state → use skeleton, não erro

### Caso real (2026-05-16) — B7-bis

`/agents/recommendations` retorna `Falha ao carregar` porque `recommendationKindSchema` é
`z.enum([5 valores])` mas backend agora envia 8 (PR #141 canonicalizou + adicionou
`diagnose_gap`). **Fix de 1 linha** (`z.string().min(1)`) está mapeado mas **não foi
aplicado de propósito** — porque mesmo com o Zod consertado, aprovar uma recommendation
não dispara executor. O sistema só muda `status='applied'`; o trabalho real (editar
prompt, hire agent) fica todo manual. UI bonita induziria humano a aprovar achando que
"vai aplicar". Erro vermelho = honestidade.

**Condição de reverter:** quando existir `POST /api/athena/recommendations/{id}/execute`
fazendo o trabalho real — ver `AUDIT-CONSOLIDADO.md` §"Decisão registrada: B7-bis".

### Anti-pattern

```ts
// ❌ — UI bonita esconde gap
export const recommendationKindSchema = z.string().min(1)  // ok zod
// + botão "Aprovar" ativo
// + toast "Recommendation aprovada com sucesso!"
// + nada acontece de verdade no backend
```

```ts
// ✅ — broken window intencional + documentação
export const recommendationKindSchema = z.enum([...])  // proposital — não consertar
// (ver docs/AUDIT-CONSOLIDADO.md §"Decisão registrada: B7-bis")
```

### Comentário obrigatório no código quando aplicar

```ts
// ⏸️ INTENTIONAL BROKEN — ver docs/AUDIT-CONSOLIDADO.md §"<seção>"
// Não consertar sem ler primeiro. Condição de reverter: <X>.
```

---

## P8 — Invocar hardcode-auditor ANTES de toda melhoria — **REGRA DE OURO #4**

> **Origem 2026-05-17:** 3 violações da Regra de Ouro #2 (NO HARDCODE) no mesmo
> dia (GROQ_BASE_URL, GROQ_TOOL_CAPABLE_MODELS, INSERT ignorando company_id NOT
> NULL). Memórias `mirror-before-create` e `metadata-driven-no-hardcode` não
> estavam sendo aplicadas pró-ativamente — só reativamente quando o usuário
> cortava. Agente dedicado força auditoria **PRÉ-implementação**.

**Regra:** TODA nova melhoria (PR, refactor, feature, bugfix que toca módulo)
→ invocar `Agent(subagent_type='hardcode-auditor')` ANTES de propor
implementação. O agente vive em `.claude/agents/hardcode-auditor.md`
(project-local, versionado).

**Como invocar:**

```python
Agent(
  description="Audit <escopo> pre-merge",
  subagent_type="hardcode-auditor",
  prompt="""
  Escopo: <arquivos/módulos afetados>
  Mudança proposta: <1 parágrafo>
  Hardcodes pré-identificados (se já varreu): <lista>
  Veredito esperado: confirmar/refutar achados + adicionar próprios.
  """
)
```

**Output:** relatório padronizado P0/P1/P2 + impacto na mudança + recomendação
("Prossiga" / "Prossiga + amplie pra X,Y" / "Pause e fatie" / "Bloqueie").

**Exceções aceitáveis** (pode pular auditor):
- Edição puramente cosmética (docstring, formatação, whitespace)
- Update de doc `.md` sem mudar código
- Hotfix de typo em string de log/erro
- Em dúvida → invocar.

**Caso real (2026-05-17) — PR Groq:** auditor pego depois de 3 violações
identificou +4 itens que estavam fora do meu radar (HF_INFERENCE_PROVIDERS
letra morta, case `Google`/`google` no adapter gemini, dados de Oracle/Athena
com `model` em vez de `model_id`, field_def GEMINI_API_KEY letra morta).
PR original (Groq cirúrgico) virou PR ampliado catalog-hygiene — escolha do
operador, sustentada por dados objetivos do relatório.

**Padrão de saída do auditor** é determinístico — code review consegue cruzar
PR com o relatório linha a linha.

---

## P9 — NUNCA MCP para DDL/migrations — **REGRA DE OURO #6**

> **Origem 2026-05-20:** `db push` bloqueado por 3 versões só no remoto
> (`20260520030345`, `20260520030518`, `20260520030549`) sem `.sql` no git —
> típico de `apply_migration` via MCP Supabase ou SQL Editor fora do fluxo.

**Regra:** qualquer DDL/DML de schema (CREATE/ALTER TABLE, seeds de catálogo,
CHECK, RLS, RPC) **só** via arquivo em `supabase/migrations/` + `supabase db push`.
**Proibido** usar ferramentas MCP (`apply_migration`, `execute_sql` para DDL)
ou SQL Editor no dashboard para mudanças que devem persistir em produção.

**Por quê:**
- MCP cria registro em `supabase_migrations.schema_migrations` **sem** arquivo
  local → `Remote migration versions not found in local migrations directory`
- Sem Git → sem review, sem reprodução em outro ambiente
- `migration repair` só conserta o livro-razão; não substitui o `.sql` perdido

**Fluxo correto:**

```powershell
$ts = Get-Date -Format "yyyyMMddHHmmss"
New-Item "supabase/migrations/${ts}_minha_mudanca.sql"
# editar SQL (prefixo vectraclip., cabeçalho P7)
supabase migration list
supabase db push --dry-run
supabase db push
```

**Se o agente sugerir MCP para migration:** recusar, criar o `.sql` e usar CLI.
MCP Supabase é aceitável para **leitura** (`list_tables`, `execute_sql` SELECT,
logs, advisors) — nunca para aplicar schema.

**Drift já existente:** `supabase/MIGRATIONS.md` (repair versão a versão + recuperar
SQL antes de `reverted` às cegas).

---

## P7 — Cabeçalho de auditoria em migrations novas

> **Origem 2026-05-17:** 3 violações de Regra de Ouro #1 (espelhar antes) no
> mesmo dia. Cabeçalho força o autor a *parar e checar* antes do INSERT/ALTER.

**Toda migration nova** em `supabase/migrations/` começa com 2 linhas
(qualquer lugar nas primeiras 30 linhas, como comentário SQL):

```sql
-- ESPELHEI ANTES: SELECT column_name, is_nullable FROM information_schema.columns
--                 WHERE table_schema='vectraclip' AND table_name='adapter_catalog'
--                 (descobri: company_id NOT NULL, UNIQUE (company_id, slug),
--                  display_name NOT NULL, id PK global)
-- PADRÃO ADOTADO: loop por companies + gen_random_uuid() (mesmo shape de
--                 20260506150000_add_huggingface_adapter.sql)

DO $$ ...
```

**Por quê:**
- Força documentar **qual tabela espelhou** (auditável no `git blame`)
- Força declarar **qual padrão da casa** adotou (não inventou shape novo)
- PR reviewer verifica em 5s sem precisar entrar no DB
- Esquecer = pego no code review (não há hook git — DB é a fonte da
  verdade; runtime falha em quem hardcoda; review humano valida quem
  ignorou espelhar)

**Aplica a:** toda migration `supabase/migrations/*.sql` nova.

---

## P6 — Onde NÃO há catálogo, declare como decisão (não como omissão)

Alguns enums são realmente locais (máquina de estados interna), não merecem catálogo:

| Campo | Onde fica Literal | Por quê |
|---|---|---|
| `Agent.status` | `models.py:23` `idle/working/offline/error/paused` | Máquina de estados do daemon, não config de negócio |
| `Task.status` | `models.py:101` | Idem (workflow interno) |
| `User.role` | `models.py:591` `admin/member` | Auth/security — mudar tem implicação maior que catálogo |
| `SipocComponent.type` | `models.py:1025` `supplier/input/activity/output/customer` | Framework SIPOC tem 5 canônicos por definição |
| `Incident.severity` | `models.py:623` `low/medium/high` | Escala universal |
| `AdapterFieldDefinition.field_type` | `models.py:422` `text/textarea/number/boolean/select/multiselect/file_upload/secret/url` | Cada tipo vira componente React diferente (switch UI). Adicionar tipo = adicionar componente = code change inevitável |

Se você AINDA acha que merece catálogo, abra issue antes de mexer — não é mero
hardcode, é decisão arquitetural com trade-off.

---

## Onde gravar nova decisão

- Padrão **novo** que vai se repetir → adicione P-N aqui
- Decisão **única** sobre uma feature → ADR em `docs/ADR-VEC-XXX-*.md`
- Resultado de **dogfood/smoke** → `docs/DOGFOOD-*.md`
- Auditoria **pontual** → `docs/AUDIT-*.md`

Não invente novos diretórios de docs — esses 4 padrões já cobrem.
