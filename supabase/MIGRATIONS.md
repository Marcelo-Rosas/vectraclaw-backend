# Migrations — guia operacional (drift, repair, pull/push)

> **Projeto:** `epgedaiukjippepujuzc` · **Schema:** `vectraclip` (nunca `public` por engano).  
> **Normas de nome e DDL:** `supabase/CLAUDE.md`.

---

## Índice

1. [Organizar drift em 5 passos](#1-organizar-drift-em-5-passos)  
2. [Referência rápida de comandos](#2-referência-rápida-de-comandos)  
3. [O que o CLI compara](#3-o-que-o-cli-compara)  
4. [O que é `migration repair`](#4-o-que-é-migration-repair)  
5. [Decisão por sintoma](#5-decisão-por-sintoma) · [5.1 Exemplo real](#51-exemplo-real--migration-list-2026-05-13)  
6. [Causas que geram bagunça](#6-causas-que-geram-bagunça)  
7. [Backup e checklist](#7-backup-e-checklist)  
8. [Repair no remoto — uma versão por vez](#8-repair-no-remoto-uma-versão-por-vez)  
9. [Troubleshooting — `db push` vs `db pull` vs `repair`](#9-troubleshooting--db-push-vs-db-pull-vs-repair)  
10. [Referências externas](#10-referências-externas)

---

## 1. Organizar drift em 5 passos

Use esta sequência sempre que `migration list` ou `db pull` mostrarem desalinhamento.

| Passo | Ação | Objetivo |
|-------|------|-----------|
| **1** | `git pull` no branch acordado (`main` / release) | Garantir que `supabase/migrations/` é a mesma base do time |
| **2** | `supabase migration list` | Ver exatamente: só local, só remoto, ou os dois |
| **3** | Decidir fonte da verdade (ver [§5](#5-decisão-por-sintoma)) | Git vs remoto — sem isso, repair vira chute |
| **4** | Executar: recuperar `.sql` faltantes **ou** `repair` **versão a versão** | Alinhar histórico ao schema real |
| **5** | `migration list` de novo → só então `db pull` ou `db push` | Confirmar que o CLI concorda com o git |

Depois de um `repair` em produção, **registre** em PR ou issue: data, versões, quem validou, e se o DDL já estava aplicado ou não.

---

## 2. Referência rápida de comandos

```powershell
cd C:\Users\marce\VectraClaw

supabase migration list              # colunas: local / remoto — comece sempre aqui
supabase db push --dry-run          # simula aplicação de migrations pendentes (local → remoto)
supabase db push                    # aplica (só com PR/review conforme política do time)
supabase db pull                    # introspect — só quando histórico local = remoto
supabase db pull --debug            # mais log; se sugerir repair, ver [§8](#8-apêndice--exemplo-de-saída-do-db-pull)

# Repair (um comando por vez, após validação explícita)
# supabase migration repair --status reverted  <YYYYMMDDHHMMSS>
# supabase migration repair --status applied   <YYYYMMDDHHMMSS>
```

---

## 3. O que o CLI compara

| Lado | Onde está |
|------|-----------|
| **Remoto** | Tabela `supabase_migrations.schema_migrations` |
| **Local** | Arquivos `supabase/migrations/*.sql` (prefixo numérico = versão) |

**Regra:** cada versão aplicada no remoto deveria ter **um** arquivo com o mesmo timestamp no git. Divergência = “bagunça” que bloqueia `db pull` ou confunde `db push`.

---

## 4. O que é `migration repair`

- Ajusta **somente** o livro-razão em `schema_migrations`.  
- **Não** reverte `ALTER TABLE`, `CREATE`, dados.  
- `reverted` — remove o registro “esta versão foi aplicada”.  
- `applied` — marca como aplicada **sem rodar** o `.sql` (use se o DDL já está no banco e falta só o registro).

**Armadilha:** após `reverted`, um `db push` pode tentar **reaplicar** uma migration cujo efeito já existe no banco → conflito de DDL. Por isso o passo 3 (fonte da verdade) é obrigatório.

---

## 5. Decisão por sintoma

### Sintoma: `migration list` mostra linhas **só no remoto** (sem arquivo local)

1. Buscar os `.sql` em outro branch, fork ou backup (`migrations_backup_*`).  
2. Achou o arquivo e bate com o que rodou → commit no `main` → `migration list` deve alinhar.  
3. **Não** achou arquivo e o schema já está como o produto precisa → aí sim `repair --status reverted` **por versão**, com registro em PR/issue.

### Sintoma: `migration list` mostra arquivo **só no local** (ponta do git)

Fluxo normal de entrega: `db push --dry-run` → `db push` (após review).

### Sintoma: `db pull` — *migration history does not match local files*

1. **Não** trate `pull` como conserto do histórico.  
2. Resolver o desalinhamento (§5 acima ou apêndice como **exemplo** de sugestão do CLI).  
3. Quando `migration list` estiver verde, usar `db pull` só se precisar de baseline/schema dump além das migrations.

### Sintoma: erro ao aplicar migration (DDL duplicado, objeto já existe)

É problema de **schema**, não só de histórico. Corrigir SQL (idempotência `IF NOT EXISTS`, `DROP IF EXISTS` onde fizer sentido) ou ajustar o banco manualmente com plano documentado — não empurrar `repair` às cegas.

### 5.1 Exemplo real — `migration list` (2026-05-13)

Saída do `supabase migration list` (CLI **v2.84.2**). Como ler:

| Colunas | Significado |
|---------|-------------|
| **Local** vazio · **Remote** preenchido | Versão consta no histórico do remoto, mas **não há** `supabase/migrations/<versão>_*.sql` no repo (DDL provavelmente aplicado fora do git ou arquivo perdido no merge). |
| **Local** preenchido · **Remote** vazio | Arquivo existe no disco; migration **ainda não** registrada/aplicada no remoto — típico de pendência de `db push`. |

**Nove versões só no remoto** (sem linha na coluna Local):

`20260511230743`, `20260511230853`, `20260512131455`, `20260512133040`, `20260512152122`, `20260512153004`, `20260512161436`, `20260512202941`, `20260512234145`

**Uma versão só no local** (sem linha na coluna Remote):

`20260513134730` → arquivo `20260513134730_kronos_planner_specialties.sql`; o `db push` só consegue aplicá-la de forma limpa depois que o histórico remoto **deixar de exigir** essas nove entradas “órfãs” (recuperando os `.sql` ou alinhando com `repair`, conforme §5 e §8).

**Ordem sugerida de saneamento**

1. Tentar **recuperar** os nove arquivos `.sql` de outro branch, backup ou quem aplicou.  
2. Se **não** existirem arquivos: validar em equipe se o DDL dessas versões já está coberto pelo schema atual **sem** risco de duplicar objetos; só então `migration repair --status reverted` **versão a versão** nas nove.  
3. Rodar `supabase migration list` de novo até Local/Remote baterem nas linhas restantes.  
4. `supabase db push --dry-run` → `db push` para aplicar `20260513134730` no remoto.

**Comandos prontos (uma versão por vez):** ver [§8](#8-repair-no-remoto-uma-versão-por-vez).

**Cuidado:** se alguma das nove migrações fez DDL que **não** está repetido nas migrations seguintes do git, marcar `reverted` só limpa o registro — o banco continua com o objeto, mas o git nunca documentou a mudança. Isso é dívida técnica; prefira recuperar o SQL.

**Opcional:** atualizar o CLI (`v2.84.2` → sugerido `v2.98.x`) para mensagens e repair mais recentes — não substitui validação manual do histórico.

---

## 6. Causas que geram bagunça

| Causa | O que fazer daqui pra frente |
|--------|------------------------------|
| DDL no SQL Editor / outro repositório | Só DDL versionado em `migrations/` + `db push` |
| `apply_migration` via MCP (proibido no repo) | Ver `supabase/CLAUDE.md` |
| Arquivo `.sql` apagado ou renomeado após aplicar no remoto | Nunca apagar versão já aplicada em prod sem `repair` + plano |
| PRs paralelos com timestamps colidentes | Timestamp sempre crescente; conflito = resolver antes do merge |

**Nota interna:** a migration `20260511010811_vec388_*` documenta aplicação prévia via MCP — exemplo do tipo de evento que gera drift.

---

## 7. Backup e checklist

### Backup local (antes de repair em massa ou rebase de pasta)

```powershell
Copy-Item -Recurse supabase\migrations `
  supabase\migrations_backup_$(Get-Date -Format yyyyMMddHHmmss)
```

Manter `migrations_backup_*` **fora do git** (gitignore), como no `CLAUDE.md`.

### Checklist ao adicionar migration nova

- [ ] Timestamp **maior** que o último arquivo em `main`  
- [ ] Objetos em **`vectraclip.`**  
- [ ] RLS em tabelas com dado de cliente  
- [ ] `NOTIFY pgrst, 'reload schema'` se mudar coisas expostas à API REST  
- [ ] Nenhuma DDL “só no painel” em paralelo

---

## 8. Repair no remoto — uma versão por vez

Use esta seção **só** depois de [§5.1](#51-exemplo-real--migration-list-2026-05-13) e do time decidirem que os nove registros órfãos devem sair do histórico remoto **sem** recuperar os `.sql`.

**Regra:** em cada passo rode **apenas um** `repair`, depois **`supabase migration list`** e confira se a linha daquela versão sumiu do lado Remote. Só então passe ao próximo.

```powershell
cd C:\Users\marce\VectraClaw
```

### 8.1 Remover do histórico remoto (ordem cronológica)

**Passo 1 de 9**

```powershell
supabase migration repair --status reverted 20260511230743
supabase migration list
```

**Passo 2 de 9**

```powershell
supabase migration repair --status reverted 20260511230853
supabase migration list
```

**Passo 3 de 9**

```powershell
supabase migration repair --status reverted 20260512131455
supabase migration list
```

**Passo 4 de 9**

```powershell
supabase migration repair --status reverted 20260512133040
supabase migration list
```

**Passo 5 de 9**

```powershell
supabase migration repair --status reverted 20260512152122
supabase migration list
```

**Passo 6 de 9**

```powershell
supabase migration repair --status reverted 20260512153004
supabase migration list
```

**Passo 7 de 9**

```powershell
supabase migration repair --status reverted 20260512161436
supabase migration list
```

**Passo 8 de 9**

```powershell
supabase migration repair --status reverted 20260512202941
supabase migration list
```

**Passo 9 de 9**

```powershell
supabase migration repair --status reverted 20260512234145
supabase migration list
```

### 8.2 Só se o DDL de `20260513134730` **já** estiver no remoto

Use **`applied`** apenas quando o conteúdo da migration já foi aplicado manualmente / por outro caminho e falta **só** o registro no histórico. Caso contrário, pule para **8.3** e use `db push`.

**Passo opcional (marcar como aplicada sem rodar o arquivo)**

```powershell
supabase migration repair --status applied 20260513134730
supabase migration list
```

### 8.3 Aplicar a migration que existe no git (fluxo normal)

Se `20260513134730` **não** estiver no remoto como schema e você **não** usou `applied` acima:

```powershell
supabase db push --dry-run
supabase db push
supabase migration list
```

### 8.4 Depois que tudo alinhar

```powershell
supabase db pull
```

(só se precisar de introspect; se `pull` não for necessário, pode omitir.)

---

**Nota:** a sugestão original veio de `db pull --debug` em maio/2026; se o remoto ou o `main` mudarem, rode `migration list` de novo e **não** use esta lista sem conferir.

---

## 9. Troubleshooting — `db push` vs `db pull` vs `repair`

> Seção gravada 2026-05-17 após confusão real durante deploy da migration `20260517120000_a2_drop_operation_type_checks.sql` (Marcelo escreveu o resumo completo; consolidado aqui pra próxima ocorrência).

### 9.1 Dois problemas distintos — não misturar

| # | Sintoma | Causa | Solução |
|---|---|---|---|
| **P1** | `db pull` → `"migration history does not match local files"` | Local tem migrations a mais que o remoto (PR mergeado mas `db push` não rodou ainda) | `db push` das pendentes — **não** `repair` |
| **P2** | `db pull` → falha replay no meio (FK, seeds, "Mnemos não encontrado", etc.) | Migrations antigas assumem **dados da Vectra** (companies seeded, agents). Shadow DB que o CLI recria começa **vazio** | **Não usar `db pull` neste repo**. OU PR shadow-replay safe nas migrations seed (ver chore #187 de 2026-05-17) |

### 9.2 `migration repair --status applied` ≠ `db push` — diferença crítica

| Comando | O que faz | Quando usar |
|---|---|---|
| **`repair --status applied <version>`** | Marca histórico em `supabase_migrations.schema_migrations` **sem rodar SQL** | DDL **já existe no banco** mas falta o registro (ex: aplicação manual via SQL editor, drift acidental) |
| **`db push`** | Aplica SQL das migrations cujo `version` não está em `schema_migrations` | Migration **ainda não rodou** no banco |

**Erro comum:** quando CLI sugere `repair --status applied` no output de erro de `db pull`, NÃO seguir cegamente. Confirmar primeiro se o DDL realmente já está no banco. Se não está, é `db push`. Se sim, é `repair`.

### 9.3 SQL template — validar pós-migration que DDL foi aplicado de fato

Útil quando você quer confirmar que `schema_migrations.version` e o schema real estão coerentes (não confiar só no CLI):

```sql
-- Constraints pelo nome (ex: operation_type CHECKs da migration A.2)
SELECT conname FROM pg_constraint
WHERE conrelid IN ('vectraclip.tasks'::regclass, 'vectraclip.routines'::regclass)
  AND contype = 'c'
  AND conname LIKE '%operation_type%';
-- Esperado pós-A.2: 0 rows

-- Migration registrada no histórico
SELECT version FROM supabase_migrations.schema_migrations
WHERE version = '<YYYYMMDDHHMMSS>';
-- Esperado: 1 row

-- COMMENT aplicado em coluna (se sua migration adicionou COMMENT)
SELECT t.relname, a.attname, d.description
FROM pg_description d
JOIN pg_attribute a ON a.attnum = d.objsubid AND a.attrelid = d.objoid
JOIN pg_class t ON t.oid = a.attrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = 'vectraclip' AND d.description LIKE '%<keyword da sua migration>%';
```

**Triple-confirmação** (CLI histórico + schema real + COMMENT) garante que migration aplicou de fato e não só registrou.

### 9.4 Fluxo recomendado consolidado

```powershell
# ✅ Rotina normal — NÃO precisa de db pull
supabase migration list              # status local vs remote
supabase db push --dry-run           # simula
supabase db push                     # aplica

# Pós-merge de PR que toca .sql:
# (não esquecer: também rodar docker cp + restart no backend — Regra de Ouro #3 de CODE-PATTERNS.md P4)

# ⚠️  Evitar neste repo enquanto seeds não forem replay-safe
supabase db pull
# Se precisar mesmo: garantir que migrations seed têm guards
# (IF companies > 0, IF agent EXISTS — ver chore #187)

# ⛔ Nunca
mcp apply_migration
# → drift permanente (ver supabase/CLAUDE.md)
```

### 9.5 Janela de risco operacional — quando código backend vai à frente do schema

Cenário real do PR #184 (A.2): backend foi deployado com validador catalog-driven (`_validate_operation_type` em `api.py`) ANTES da migration `20260517120000` (DROP CHECK) ser aplicada no remoto. Resultado seria:

- API aceita novo `operation_type` recém-cadastrado no catálogo (Pydantic passou)
- INSERT no Postgres falha **500** porque CHECK constraint antigo ainda existe e o valor não está na lista

**Ação preventiva pós-merge:**

1. Identificar se PR tem migration nova
2. Se sim, rodar `supabase db push` **antes** de habilitar o caminho de código que depende dela
3. Validar via §9.3 SQL template
4. Só depois fazer smoke

No caso A.2 essa janela durou ~horas (Marcelo aplicou rápido), mas o risco é real em deploys mais longos.

### 9.6 5 migrations shadow-replay safe (registro histórico)

Em 2026-05-17, `chore #187` commitou guards defensivos em 5 migrations seed pra que shadow DB do `db pull` pare de falhar:

- `20260507194100_vec_rag_seed_mnemos.sql`
- `20260510202220_vec388_pr1_seed_athena_agent.sql`
- `20260513134730_kronos_planner_specialties.sql`
- `20260513225554_routine_workflow_binding.sql`
- `20260513234412_kronos_handoff_relational.sql`

Padrão dos guards: `IF (SELECT count(*) FROM vectraclip.companies) > 0` ou `IF EXISTS (SELECT 1 FROM vectraclip.agents WHERE id = '<uuid>')` antes de seeds/checks. **NÃO re-rodam em prod** (já registradas em `schema_migrations`), só evitam falha em replay.

**Padrão pra próximas seeds:** novo INSERT que depende de tenant/agent deve ter guard equivalente. Próximo dev que cair em P2 → ler §9.1 + §9.6.

---

## 10. Referências externas

- Supabase — [migration history / ambientes](https://supabase.com/docs/guides/cli/managing-environments#migration-history) (validar com a versão do seu CLI, ex. 2.84.x).  
- Repo: `supabase/CLAUDE.md`.
- Resumo Marcelo 2026-05-17 — origem de §9 desta página.
