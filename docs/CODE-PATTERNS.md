# Code Patterns — VectraClaw / VectraClip

> **Leia este arquivo ANTES de escrever código novo.** Cada padrão aqui foi decidido
> com motivo e já está aplicado em N lugares. Se você está prestes a fazer algo
> parecido com um dos casos abaixo, **use o mesmo padrão** em vez de reinventar.
>
> Mantenha esse doc curto e ativo. Se um padrão muda, atualize aqui na mesma PR.

---

## P0 — Espelhar antes de criar (regra dura)

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

## P1 — Catalog-driven enums (no Literal hardcoded)

**Regra:** se existe tabela `vectraclip.X_catalog` (ou `X_types`, `X_modes`, `X_status`),
TODO valor que seria `Literal[...]` ou `z.enum([...])` deve ser **`str` / `z.string().min(1)`**
+ comentário curto apontando o catálogo. Validação contra o catálogo acontece
no validator do PUT (backend) e na render (frontend lista via GET endpoint).

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

## P4 — Live-update container (sem rebuild)

```powershell
docker cp src/api.py vectraclaw-backend:/app/src/api.py
docker compose restart backend
```

Espere `Health.Status = healthy` antes de smoke. **Não** use `--build` pra
mudança rápida durante dev — `cp` + restart leva ~10s, build leva ~3min.

`compose up --build -d` só quando muda `requirements.txt`, `Dockerfile`, ou
imagem precisa de novos pacotes do sistema.

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

## P6 — Onde NÃO há catálogo, declare como decisão (não como omissão)

Alguns enums são realmente locais (máquina de estados interna), não merecem catálogo:

| Campo | Onde fica Literal | Por quê |
|---|---|---|
| `Agent.status` | `models.py:23` `idle/working/offline/error/paused` | Máquina de estados do daemon, não config de negócio |
| `Task.status` | `models.py:101` | Idem (workflow interno) |
| `User.role` | `models.py:591` `admin/member` | Auth/security — mudar tem implicação maior que catálogo |
| `SipocComponent.type` | `models.py:1025` `supplier/input/activity/output/customer` | Framework SIPOC tem 5 canônicos por definição |
| `Incident.severity` | `models.py:623` `low/medium/high` | Escala universal |

Se você AINDA acha que merece catálogo, abra issue antes de mexer — não é mero
hardcode, é decisão arquitetural com trade-off.

---

## Onde gravar nova decisão

- Padrão **novo** que vai se repetir → adicione P-N aqui
- Decisão **única** sobre uma feature → ADR em `docs/ADR-VEC-XXX-*.md`
- Resultado de **dogfood/smoke** → `docs/DOGFOOD-*.md`
- Auditoria **pontual** → `docs/AUDIT-*.md`

Não invente novos diretórios de docs — esses 4 padrões já cobrem.
