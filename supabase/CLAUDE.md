# `supabase/` — Schema, migrations e disciplina

> Banco de dados de produção: **`epgedaiukjippepujuzc`** (Supabase hosted). Schema canônico: **`vectraclip`** (NUNCA `public`).
>
> Para drift handling avançado, repair, fluxo de reconciliação remoto/local: ver `MIGRATIONS.md` nesta pasta.

---

## Estrutura da pasta

```
supabase/
├── CLAUDE.md             ← este arquivo
├── MIGRATIONS.md         ← drift handling, repair, fluxo db pull/push
├── config.toml           ← config CLI Supabase (project ref, schemas, etc.)
├── seed.sql              ← seed para dev local (db reset)
└── migrations/
    └── YYYYMMDDHHMMSS_<slug>.sql       ← formato obrigatório
```

**Não colocar** dentro de `migrations/`:
- `CLAUDE.md`, `README.md`, ou qualquer não-`.sql`
- Backups (`migrations_backup_*/` é local, gitignored)
- SQL ad-hoc com nome diferente do padrão CLI

---

## Convenções de nomenclatura de migration

Formato:
```
YYYYMMDDHHMMSS_<slug_curto_descritivo>.sql
```

Exemplos válidos no main atual:
```
20260506025418_remote_schema.sql
20260506120001_fix_ollama_base_url_field_type.sql
20260506150000_add_huggingface_adapter.sql
20260506160000_add_task_evaluation_fields.sql
20260506170000_add_extra_llm_models.sql
```

**Regras:**
- Timestamp **estritamente crescente**. Ao criar migration nova, usar `date +%Y%m%d%H%M%S` (UTC) ou um valor posterior ao último arquivo existente.
- Para o mesmo dia, incrementar minutos/segundos para evitar colisão em merge concorrente.
- Slug em snake_case, descritivo. Adicionar prefixo VEC-NNN no comentário do topo do `.sql`, **não no nome do arquivo** (o nome fica curto e legível).

---

## Schema canônico — sempre `vectraclip.`

```sql
-- ✅ CORRETO
CREATE TABLE IF NOT EXISTS "vectraclip"."minha_tabela" (...);
INSERT INTO vectraclip.llm_models (...) VALUES (...);
ALTER TABLE vectraclip.tasks ADD COLUMN ...;

-- ❌ ERRADO (vai pro schema public, fora do escopo)
CREATE TABLE IF NOT EXISTS "minha_tabela" (...);
INSERT INTO llm_models (...) VALUES (...);
```

**Padrão:** sempre fully-qualified. Qualquer DDL/DML em migration deve prefixar `vectraclip.`.

---

## ⛔ NUNCA usar `mcp apply_migration`

DDL **sempre** vai como arquivo em `supabase/migrations/` + `supabase db push` (local) ou CI.

**Por quê:**
- Apply via MCP cria registro no histórico remoto sem arquivo correspondente local → drift permanente.
- Não tem versionamento Git → impossível auditar.
- Não roda em outros ambientes (staging) automaticamente.

**Fluxo correto:**
```powershell
# 1. Criar arquivo
$ts = Get-Date -Format "yyyyMMddHHmmss"
New-Item "supabase/migrations/${ts}_minha_mudanca.sql"
# (editar)

# 2. Verificar drift
supabase migration list

# 3. Dry-run
supabase db push --dry-run

# 4. Aplicar
supabase db push
```

---

## Tabelas-chave do VectraClaw

| Tabela | Papel | PK |
|---|---|---|
| `vectraclip.companies` | Tenants | `id` |
| `vectraclip.agents` | Catálogo de agentes (8 daemons + outros) | `id` |
| `vectraclip.tasks` | Filas de tarefas | `id` |
| `vectraclip.heartbeats` | Eventos de runtime dos agentes | `id` |
| `vectraclip.incidents` | Registro de problemas detectados pelo Heartbeat Doctor | `id` |
| `vectraclip.llm_models` | Catálogo de modelos LLM (HF, Anthropic, Ollama, OpenAI) | **`(id, effective_from)`** ⚠️ |
| `vectraclip.adapter_catalog` | Adapters disponíveis por company (HF, Ollama, etc.) | `id` |
| `vectraclip.adapter_field_definitions` | Schema dos campos de cada adapter | `id` |
| `vectraclip.agent_adapter_configs` | Config de adapter por agente (com `field_values_json`) | `id` |
| `vectraclip.workflow_steps` | Passos de workflow customizado | `id` |
| `vectraclip.sipoc_*` | Tabelas do SIPOC builder | variado |

### `llm_models` — PK composta

```sql
PRIMARY KEY (id, effective_from)
```

**Razão:** modelos têm preço variável no tempo. Adicionar nova versão = INSERT com `effective_from` mais recente.

**Migration de modelo:** sempre idempotente:
```sql
INSERT INTO vectraclip.llm_models (...)
VALUES (...)
ON CONFLICT (id, effective_from) DO NOTHING;
```

### `adapter_catalog` — seed por company

Migrations que adicionam adapter precisam fazer loop por company:
```sql
DO $$
DECLARE rec RECORD;
BEGIN
  FOR rec IN SELECT company_id FROM vectraclip.companies LOOP
    INSERT INTO vectraclip.adapter_catalog (company_id, slug, ...)
    VALUES (rec.company_id, 'meu_adapter', ...)
    ON CONFLICT (company_id, slug) DO NOTHING;
  END LOOP;
END $$;
```

**Não esquecer:** o `adapter_field_definitions` correspondente também por company.

---

## Drift handling — checklist

Antes de qualquer push em produção:

```powershell
supabase migration list
```

**Casos:**

| Situação | Ação |
|---|---|
| Local 5/5, remoto 5/5, todos alinhados | OK, push se houver novo |
| Local tem 1 a mais que remoto (na ponta) | `supabase db push --dry-run` → aplicar |
| Remoto tem 1 a mais que local | `supabase db pull` para gerar arquivo + commit |
| Drift no meio (out-of-order) | **Investigar com calma.** Provavelmente alguém aplicou via MCP ou outro repo. Ler `MIGRATIONS.md`. Decidir entre repair, copiar arquivo, ou rebaseline. |
| Erro "Remote migration versions not found in local" | Ver `MIGRATIONS.md` (seção drift). **Não repair às cegas.** |

**Quando duvidar, abrir um PR de baseline em vez de tocar o histórico.**

---

## Backups e arquivos auxiliares

- `supabase/migrations_backup_<timestamp>/` é **local** (gitignored). Tira snapshot antes de drástica mudança no histórico.
- `supabase/.branches/`, `supabase/.temp/` são gerados pelo CLI (gitignored).
- `supabase/seed.sql` é para `supabase db reset` em dev local (não roda em produção).

---

## RLS / segurança

- Toda tabela com dados de cliente deve ter RLS habilitado: `ALTER TABLE ... ENABLE ROW LEVEL SECURITY;`
- Policy padrão de leitura para `authenticated`, write para `service_role`.
- Migrations de RLS reescritas em `20260426000000_vec_rls_initplan_fix.sql` (ramo antigo) — verificar política antes de assumir que está OK.

---

## CI / aplicação automática

> Status atual: **CI ainda não configurada para aplicar migrations**. PRs validam só que o `.sql` parsea (via Supabase CLI local antes de merge).

Quando CI for habilitada:
- `db push --dry-run` em PR (preview)
- `db push` automático em merge para `main` (após approve manual no GitHub Actions)

---

## Comando de emergência — listar versões locais para comparar

```powershell
python scripts/list_migration_versions.py
python scripts/list_migration_versions.py --compare caminho\remote_versions.txt
```

Mais detalhe em `MIGRATIONS.md`.
