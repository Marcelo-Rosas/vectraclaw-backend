# VEC-199b — VectraClaw Prompt V1.1 (Heartbeat Doctor: persistência real + bug fixes)

**Issue Linear:** [VEC-200](https://linear.app/vectra-cargo/issue/VEC-200) — Heartbeat Doctor em Postgres (sair do in-memory) *(arquivo versionado como `VEC-199b` porque é patch da V1; Linear atribui ID próprio)*
**Repositório alvo:** `VectraClaw` — `src/api.py`, `src/services/heartbeat_doctor/*`, `src/models.py`
**Espelho local (operacional):** [`docs/SUPABASE_DUAL_CLIENT.md`](./SUPABASE_DUAL_CLIENT.md) — dois clients Supabase (service_role vs auth).
**Documento anterior:** [`docs/VEC-199-VectraClaw-Prompt-V1.md`](./VEC-199-VectraClaw-Prompt-V1.md)
**Relaciona-se com:** `VEC-199` (bloqueada por esta), `VEC-197b` (grants que esta VEC reutiliza)

---

## 🗺️ Território

| Responsabilidade                                        | Dono        | Onde (para esta VEC)                                                               |
|---------------------------------------------------------|-------------|------------------------------------------------------------------------------------|
| Schema `vectraclip.incidents` + `vectraclip.incident_audit` | **já aplicado pelo VectraClip** | migration `vec_199_incidents_schema` — ver §3 |
| Coluna `companies.tier` + seed Vectra Cargo=`enterprise` | **já aplicado pelo VectraClip** | migration `vec_199_seed_company_tier` — ver §3 |
| Policies RLS em `incidents` e `incident_audit`          | **já aplicado pelo VectraClip** | mesma migration — `select to authenticated where company_id = jwt.company_id` |
| Grants `SELECT` para `authenticated`                    | **já aplicado pelo VectraClip** | mesma migration — writes só via `service_role` |
| Trocar storage in-memory → Postgres real                | VectraClaw  | `VectraClaw/src/services/heartbeat_doctor/store.py` (novo) + chamadas em `loop.py` / endpoints |
| Corrigir endpoints 500 (GET by id, Undo sem janela)     | VectraClaw  | `VectraClaw/src/api.py`                                                            |
| Gravar `incident_audit` em cada evento                  | VectraClaw  | `VectraClaw/src/services/heartbeat_doctor/audit.py` (novo)                         |
| Refinar detector S5 `burn_rate_anomaly`                 | VectraClaw  | `VectraClaw/src/services/heartbeat_doctor/symptoms.py`                             |
| Reset/limpeza de incidents pós-smoke                    | VectraClip  | MCP Supabase — **Claw não executa DELETE direto**                                  |
| Contrato Zod `Incident` / hooks React Query / UI        | VectraClip  | `src/types/api.ts`, `src/lib/queries/incidents.ts`, `src/components/council/*`     |

---

## Contexto — auditoria da V1

Auditoria end-to-end detectou que a V1 rodou com storage **in-memory**. Endpoints respondem e o loop funciona, mas existem gaps de persistência e bugs de design.

| Gap | Evidência |
|---|---|
| Nenhuma migration `vec_199_*` aplicada | `supabase_migrations.schema_migrations` — última `vec_*` era `vec_197_vectraclip_write_grants_authenticated`. |
| Tabelas `incidents` / `incident_audit` não existiam | `select table_name from information_schema.tables where table_schema='vectraclip'` → `[agents, app_users, companies, heartbeats, tasks]`. |
| Coluna `companies.tier` inexistente | `columns` de `companies` tinha só `id, name, created_at, updated_at`. |
| D5 (company_tier) não computa | Sem coluna → loop usa default. Perde o diferencial multi-tier do MVP. |
| `GET /api/incidents/{id}` → 500 | Endpoint singular nunca implementado ou quebrado. |
| `POST /api/incidents/{id}/undo` → 500 | Quando `undo_expires_at IS NULL`, crashes em vez de 400. |
| S5 `burn_rate_anomaly` não disparou | Atlas em `status='offline'` → loop pula (§4.5 da V1). Gap de design, não bug de implementação. |
| `incident_audit` ausente | Nenhum log pós-mortem, impossibilita análise futura. |

Score: **6/13 passaram**. Reaberta como V1.1 com escopo cirúrgico (persistência + bugs).

---

## ⚠️ Baseline do banco — já pronto pelo VectraClip

**Não rodar SQL nenhum.** Migrations abaixo já foram aplicadas via MCP Supabase:

1. `20260420_vec_199_incidents_schema` — cria `vectraclip.incidents` + `vectraclip.incident_audit`, adiciona `companies.tier`, RLS `select to authenticated` filtrada por `company_id` do JWT, grants `SELECT` pra `authenticated`.
2. `20260420_vec_199_seed_company_tier` — Vectra Cargo = `enterprise`.

Validação esperada:

```sql
select (select count(*) from vectraclip.incidents)           as incidents_rows,  -- 0
       (select count(*) from vectraclip.incident_audit)      as audit_rows,      -- 0
       (select tier from vectraclip.companies
         order by created_at asc limit 1)                    as vectra_tier,     -- 'enterprise'
       (select count(*) from pg_policies
         where schemaname='vectraclip'
           and tablename in ('incidents','incident_audit'))  as policy_count;    -- 2
```

Se esse `select` devolver algo diferente, **pare** e sinalize.

---

## Fix 0 — Dois clients Supabase (service_role ≠ auth) — **obrigatório**

Sintoma: após login, `permission denied` em `incidents` / `incident_audit` nas escritas do Doctor. **Causa típica:** não é RLS — é o `supabase-py` reconstruindo o PostgREST do **mesmo** client de service role quando `.auth` dispara `SIGNED_IN`.

**Regra:** `supabase` = `SUPABASE_SERVICE_ROLE_KEY` (só dados server-side + Doctor; sem `.auth`). `supabase_auth` = `SUPABASE_ANON_KEY` (só login / refresh / logout). `persist_session=False` em ambos no worker HTTP.

Detalhes, critério de aceite, comando `serve` e porta no Windows: [**`docs/SUPABASE_DUAL_CLIENT.md`**](./SUPABASE_DUAL_CLIENT.md). Implementação: `src/api.py`.

---

## Fix 1 — 🔴 Persistência real (Postgres, não memória)

Todo acesso a incident/audit passa por um único módulo `store.py` que usa `service_role`.

**Criar `src/services/heartbeat_doctor/store.py`** (ver spec completa no prompt original).

---

## Fix 2 — 🔴 Gravar `incident_audit` em cada evento

**Criar `src/services/heartbeat_doctor/audit.py`** (ver spec completa no prompt original).

---

## Fix 3 — 🔴 `GET /api/incidents/{id}` (hoje 500)

Endpoint singular não existe ou crasha. Implementar 404 correto e camelCase.

---

## Fix 4 — 🔴 `POST /api/incidents/{id}/undo` 500 quando `undo_expires_at IS NULL`

Validar janela de undo e retornar 400 adequado.

---

## Fix 5 — 🟡 S5 `burn_rate_anomaly` em agente offline

`burn_rate_anomaly` **deve** monitorar offline também.

---

## Smoke test / Critério de aceite

- Subir com `python -m src.main serve --port 3100` (ver **Fix 0** se houver `EADDRINUSE` no Windows).
- [ ] **Fix 0:** após login, sem `permission denied` do Doctor; clients separados.
- (Demais passos / scripts: spec completa no repositório **VectraClip** `docs/VEC-199b-VectraClaw-Prompt-V1.1.md`, § smoke.)

---

## Fora de escopo

- Não rodar SQL de migration.
- Não rodar `UPDATE`/`DELETE` ad-hoc.
- Não refatorar o severity score.
- Não editar `VectraClip/*`.
- Não implementar rollback semântico de Undo (só marca decision).

---

*Última atualização: 20/Abr/2026 — patch pós-auditoria V1.1.*
