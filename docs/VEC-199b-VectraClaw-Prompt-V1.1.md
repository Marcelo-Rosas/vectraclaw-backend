# VEC-199b — VectraClaw Prompt V1.1 (Heartbeat Doctor: persistência real + bug fixes)

**Issue Linear:** [VEC-200](https://linear.app/vectra-cargo/issue/VEC-200) — Heartbeat Doctor em Postgres (sair do in-memory) *(arquivo versionado como `VEC-199b` porque é patch da V1; Linear atribui ID próprio)*
**Repositório alvo:** `VectraClaw` — `src/api.py`, `src/services/heartbeat_doctor/*`, `src/models.py`
**Documento anterior:** [`docs/VEC-199-VectraClaw-Prompt-V1.md`](./VEC-199-VectraClaw-Prompt-V1.md)
**Relaciona-se com:** `VEC-199` (bloqueada por esta), `VEC-197b` (grants que esta VEC reutiliza)

---

## 🗺️ Território

> Convenção oficial — template em [`docs/_VectraClaw-Prompt-TEMPLATE.md`](./_VectraClaw-Prompt-TEMPLATE.md).
>
> **Novo a partir desta VEC:** migrations saem 100% do escopo do Claw. VectraClip aplica via MCP Supabase **antes** da VEC chegar ao Claw e só depois libera a spec. Ver §6 e as cláusulas permanentes no template.

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

Cláusulas permanentes: Claw **não roda migrations**, **não toca `VectraClip/*`**, **não edita MSW**, **não assina commits com IA**.

---

## Contexto — auditoria da V1

Auditoria end-to-end (regra `vec-audit-after-claw.mdc`) contra Claw rodando em `:3100` + MCP Supabase detectou que a V1 rodou com storage **in-memory** (provavelmente `dict`/`list` dentro do processo Python). Endpoints respondem e o loop funciona, mas:

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

Score: **6/13 passaram**. Reaberta como V1.1 com escopo cirúrgico (persistência + bugs), sem repensar arquitetura.

---

## ⚠️ Baseline do banco — já pronto pelo VectraClip

**Não rodar SQL nenhum.** Migrations abaixo já foram aplicadas via MCP Supabase no projeto canônico (`epgedaiukjippepujuzc`) antes desta VEC chegar ao Claw:

1. `20260420_vec_199_incidents_schema` — cria `vectraclip.incidents` + `vectraclip.incident_audit`, adiciona `companies.tier`, RLS `select to authenticated` filtrada por `company_id` do JWT, grants `SELECT` pra `authenticated`. [SQL completo na spec anterior, §4.1](./VEC-199-VectraClaw-Prompt-V1.md#41--migration-vec_199_incidents_schemasql).
2. `20260420_vec_199_seed_company_tier` — Vectra Cargo = `enterprise`.

Validação esperada (Claw pode rodar pra confirmar, mas **não** pode aplicar):

```sql
select (select count(*) from vectraclip.incidents)           as incidents_rows,  -- 0
       (select count(*) from vectraclip.incident_audit)      as audit_rows,      -- 0
       (select tier from vectraclip.companies
         order by created_at asc limit 1)                    as vectra_tier,     -- 'enterprise'
       (select count(*) from pg_policies
         where schemaname='vectraclip'
           and tablename in ('incidents','incident_audit'))  as policy_count;    -- 2
```

Se esse `select` devolver algo diferente, **pare** e sinalize. Não tente "consertar" com migration — é problema de ambiente ou do projeto apontado.

---

## Fix 0 — 🟣 Dois clients Supabase (service_role ≠ auth) — **obrigatório**

**Espelhos operacionais (mesmo contrato que esta seção):** [`docs/VEC-199b-fix0-dual-supabase-clients.md`](VEC-199b-fix0-dual-supabase-clients.md) (VectraClip) · `VectraClaw/docs/SUPABASE_DUAL_CLIENT.md` (backend, quando existir).

Sintoma falso que às vezes aparece após `POST /api/auth/login`: `permission denied for table incidents` no Doctor / inserts com `service_role`. **Não é RLS mal configurada** — é **contaminação do client** no `supabase-py` (ex.: 2.0.x): em `Client.__init__` existe um listener de auth que, em cada `SIGNED_IN`, zera `self._postgrest` e reconstrói o PostgREST com o JWT do usuário no header `Authorization`. Se login e Doctor compartilham o **mesmo** `create_client` feito com a **service key**, a primeira sessão pós-login troca o client global para modo `authenticated` e o backend perde grants de `INSERT` no papel `service_role`.

**Regra de implementação em `VectraClaw/src/api.py` (e qualquer módulo que crie client):**

| Client        | Chave          | Uso |
|---------------|----------------|-----|
| `supabase`    | `SUPABASE_KEY` (service_role) | Doctor, `store.py`, endpoints server-side, **nunca** chama `.auth.*` |
| `supabase_auth` | `SUPABASE_ANON_KEY` | Só `login` / `refresh` / `logout` — o listener pode reconfigurar este client à vontade |

Em ambos: `ClientOptions(..., persist_session=False)` no servidor, para não misturar persistência de sessão com o processo do API worker.

Exemplo mínimo (ajuste imports/paths ao repo real):

```python
from supabase import create_client, ClientOptions

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
    options=ClientOptions(schema=SCHEMA, persist_session=False),
)

supabase_auth = create_client(
    SUPABASE_URL,
    SUPABASE_ANON_KEY,
    options=ClientOptions(schema=SCHEMA, persist_session=False),
) if SUPABASE_ANON_KEY else None
```

**Critério de aceite:** após login com JWT real, logs só com `200`/`400` esperados; **zero** `permission denied` em `incidents` / `incident_audit` em operações do Doctor.

**Processo e porta (Windows):**

- Subir o Claw com o entrypoint canônico do repo, ex.: `python -m src.main serve --port 3100` — **não** atrelar ad hoc a `uvicorn src.api:app` se a spec do projeto definiu outro módulo (middleware, lifespan, etc.).
- Se o restart "falha" com porta ocupada, é em geral **EADDRINUSE** + processo zumbi na `:3100`:

```powershell
netstat -ano | findstr :3100
taskkill /PID <pid> /F
```

---

## Fix 1 — 🔴 Persistência real (Postgres, não memória)

O coração desta VEC. Todo acesso a incident/audit passa por um único módulo `store.py` que usa `service_role` (mesmo padrão de auth dos endpoints de mutação em agents).

**Criar `src/services/heartbeat_doctor/store.py`:**

```python
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from src.supabase import get_service_role_client  # cliente singleton já usado p/ mutações
from src.models import Incident, IncidentAudit

INCIDENTS_TABLE = "incidents"
AUDIT_TABLE     = "incident_audit"


async def insert_incident(row: dict) -> Incident:
    """row: snake_case (company_id, agent_id, symptom, fix_applied, severity, ...)."""
    client = get_service_role_client()
    result = (
        client.schema("vectraclip")
              .table(INCIDENTS_TABLE)
              .insert(row)
              .execute()
    )
    if not result.data:
        raise RuntimeError("incident_insert_failed")
    return Incident.model_validate(result.data[0])


async def get_incident_by_id(incident_id: UUID, company_id: UUID) -> Optional[Incident]:
    client = get_service_role_client()
    result = (
        client.schema("vectraclip")
              .table(INCIDENTS_TABLE)
              .select("*")
              .eq("id", str(incident_id))
              .eq("company_id", str(company_id))  # defense-in-depth: service_role bypassa RLS
              .maybe_single()
              .execute()
    )
    if not result.data:
        return None
    return Incident.model_validate(result.data)


async def list_incidents(
    company_id: UUID,
    decision: Optional[str] = None,
    limit: int = 50,
) -> list[Incident]:
    client = get_service_role_client()
    q = (
        client.schema("vectraclip")
              .table(INCIDENTS_TABLE)
              .select("*")
              .eq("company_id", str(company_id))
              .order("created_at", desc=True)
              .limit(limit)
    )
    if decision and decision != "all":
        q = q.eq("decision", decision)
    return [Incident.model_validate(r) for r in q.execute().data]


async def update_incident_decision(
    incident_id: UUID,
    company_id: UUID,
    *,
    decision: str,
    resolved: bool = False,
) -> Optional[Incident]:
    client = get_service_role_client()
    patch: dict = {"decision": decision}
    if resolved:
        patch["resolved_at"] = datetime.now(timezone.utc).isoformat()
    result = (
        client.schema("vectraclip")
              .table(INCIDENTS_TABLE)
              .update(patch)
              .eq("id", str(incident_id))
              .eq("company_id", str(company_id))
              .execute()
    )
    if not result.data:
        return None
    return Incident.model_validate(result.data[0])
```

**Trocar em `loop.py`:** todas as chamadas `incidents_cache.append(...)`, `incidents_dict[id] = ...`, etc., viram `await insert_incident(row)`. Listagem vira `await list_incidents(...)`.

> ⚠️ `service_role` bypassa RLS — por isso passamos `company_id` explicitamente em todo SELECT/UPDATE. O filtro redundante é *defense-in-depth*: se um bug vazar query sem company_id, o SQL ainda não escapa do tenant esperado.

---

## Fix 2 — 🔴 Gravar `incident_audit` em cada evento

**Criar `src/services/heartbeat_doctor/audit.py`:**

```python
from uuid import UUID
from src.supabase import get_service_role_client

AUDIT_TABLE = "incident_audit"

EVENT_DETECTED          = "detected"
EVENT_FIX_EXECUTED      = "fix_executed"
EVENT_FIX_FAILED        = "fix_failed"
EVENT_UNDO              = "undo"
EVENT_COUNCIL_APPROVED  = "council_approved"
EVENT_COUNCIL_REJECTED  = "council_rejected"


async def append_audit(
    incident_id: UUID,
    *,
    event: str,
    actor: str,            # 'doctor' | user_id string
    payload: dict | None = None,
) -> None:
    client = get_service_role_client()
    client.schema("vectraclip").table(AUDIT_TABLE).insert({
        "incident_id": str(incident_id),
        "event": event,
        "actor": actor,
        "payload": payload or {},
    }).execute()
```

**Plugar:**

| Onde | Evento | Actor |
|---|---|---|
| `handle_symptom` logo após `insert_incident` | `detected` | `'doctor'` |
| Dentro do `try` de `execute_fix`, após sucesso | `fix_executed` | `'doctor'` |
| No `except FixFailed` | `fix_failed` | `'doctor'` |
| Handler do `POST /:id/undo` (sucesso) | `undo` | `request.state.user_id` |
| Handler do `POST /:id/approve` com `approved=true` | `council_approved` | `request.state.user_id` |
| Handler do `POST /:id/approve` com `approved=false` | `council_rejected` | `request.state.user_id` |

Mínimo de 2 linhas de audit por incident completo (`detected` + `fix_executed` OU `detected` + `council_approved`). Smoke em §5 valida.

---

## Fix 3 — 🔴 `GET /api/incidents/{id}` (hoje 500)

Endpoint singular não existe ou crasha. Implementar:

```python
@app.get("/api/incidents/{incident_id}")
@app.get("/incidents/{incident_id}")
async def get_incident(incident_id: UUID, request: Request):
    company_id = extract_company_id(request.state.token)  # já existe nos outros endpoints
    incident = await store.get_incident_by_id(incident_id, company_id)
    if not incident:
        raise HTTPException(status_code=404, detail="incident_not_found")
    return incident.model_dump(by_alias=True)
```

- 404 (não 500) quando o incident não existe ou é de outra company.
- `by_alias=True` garante camelCase no wire (padrão Pydantic + `alias_generator=to_camel`).

---

## Fix 4 — 🔴 `POST /api/incidents/{id}/undo` 500 quando `undo_expires_at IS NULL`

Hoje o handler crasha em vez de validar. Pattern correto:

```python
@app.post("/api/incidents/{incident_id}/undo")
@app.post("/incidents/{incident_id}/undo")
async def undo_incident(incident_id: UUID, request: Request):
    company_id = extract_company_id(request.state.token)
    user_id    = extract_user_id(request.state.token)

    incident = await store.get_incident_by_id(incident_id, company_id)
    if not incident:
        raise HTTPException(status_code=404, detail="incident_not_found")

    # Regra de Undo: só vale para auto_healed com janela ainda aberta.
    if incident.decision != "auto_healed":
        raise HTTPException(status_code=400, detail="undo_not_applicable")
    if incident.undo_expires_at is None or incident.undo_expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="undo_window_expired")

    updated = await store.update_incident_decision(
        incident_id, company_id, decision="undone", resolved=True,
    )
    await audit.append_audit(
        incident_id, event=audit.EVENT_UNDO, actor=user_id,
        payload={"reverted_fix": incident.fix_applied},
    )
    return {"status": "ok", "decision": "undone"}
```

Nunca 500. Sempre um `detail` legível (`undo_not_applicable` vs `undo_window_expired`).

---

## Fix 5 — 🟡 S5 `burn_rate_anomaly` em agente offline

Gap de design da V1 (não bug do Claw). A V1 definiu `fetch_all_active_agents # status != 'offline'`. Mas `burn_rate_anomaly` **deve** monitorar offline também — um agente offline com burn alto é exatamente o sintoma que o Council precisa ver.

**Regra refinada:**

```python
# src/services/heartbeat_doctor/loop.py
async def doctor_tick():
    # S5 é "sempre" — burn acumula mesmo quando o agente está offline.
    always_on_agents = await store.fetch_all_agents()  # inclui offline
    for agent in always_on_agents:
        if sym := await detect_burn_rate_anomaly(agent):
            await handle_symptom(agent, sym)

    # S1..S4, S6: só agentes ativos.
    active_agents = [a for a in always_on_agents if a.status != 'offline']
    for agent in active_agents:
        for detector in (detect_heartbeat_gap, detect_task_claim_stale,
                         detect_jwt_expired, detect_adapter_unresponsive,
                         detect_unknown_sentinel):
            if sym := await detector(agent):
                await handle_symptom(agent, sym)
```

Justificativa no comment: "`burn_rate_anomaly` é o único sintoma válido em offline; demais detectores assumem agente rodando."

---

## Smoke test / Critério de aceite

Rodar contra Claw reiniciado **após aplicar os fixes**. O restart é crítico: storage in-memory atual só some quando o processo reinicia. Use o comando de `serve` documentado no próprio repo Claw (ex. `python -m src.main serve --port 3100`) e confira § Fix 0 se vir `EADDRINUSE` no Windows.

```powershell
$body = @{email="marcelo.rosas@vectracargo.com.br";password="vectra123"} | ConvertTo-Json
$tok  = (Invoke-RestMethod -Uri "http://localhost:3100/api/auth/login" -Method POST -ContentType "application/json" -Body $body).accessToken
$h    = @{"Authorization"="Bearer $tok"; "Origin"="http://localhost:3000"}

$atlas = "a0000000-0000-4000-8000-000000000004"  # offline, burn 60000

# 1) Baseline: GET /api/incidents deve começar vazio após restart
# (se não vazio: sinaliza — indica que storage ainda é in-memory OU que o doctor criou incidents durante startup).
$r1 = Invoke-RestMethod -Uri "http://localhost:3100/api/incidents" -Headers $h
Write-Host "[T1] incidents antes do trigger: $($r1.Count)"

# 2) Forçar S5 em Atlas (offline + burn 500k)
Invoke-RestMethod -Uri "http://localhost:3100/api/_test/agents/$atlas/set-burn" `
  -Method POST -Headers $h -ContentType "application/json" -Body '{"burn":500000}'

Start-Sleep -Seconds 35  # 1 tick + margem

# 3) pending_council deve ter um burn_rate_anomaly em Atlas
$pending = Invoke-RestMethod -Uri "http://localhost:3100/api/incidents?status=pending_council" -Headers $h
$s5 = $pending | Where-Object { $_.symptom -eq "burn_rate_anomaly" -and $_.agentId -eq $atlas }
if (-not $s5) { throw "[T3] S5 não disparou" }

# 4) GET by id volta 200 (não mais 500)
$one = Invoke-RestMethod -Uri "http://localhost:3100/api/incidents/$($s5[0].id)" -Headers $h
if ($one.decision -ne "pending_council") { throw "[T4] GET by id errado" }

# 5) Approve
Invoke-RestMethod -Uri "http://localhost:3100/api/incidents/$($s5[0].id)/approve" `
  -Method POST -Headers $h -ContentType "application/json" `
  -Body '{"approved":true,"reason":"V1.1 smoke"}'

# 6) Estado final: decision=approved + resolved_at não nulo
$after = Invoke-RestMethod -Uri "http://localhost:3100/api/incidents/$($s5[0].id)" -Headers $h
if ($after.decision -ne "approved") { throw "[T6] approve não persistiu" }

# 7) Undo em auto_healed sem janela deve voltar 400 (não 500)
$auto = Invoke-RestMethod -Uri "http://localhost:3100/api/incidents?status=auto_healed" -Headers $h
if ($auto.Count -gt 0) {
  $noWindow = $auto | Where-Object { -not $_.undoExpiresAt } | Select-Object -First 1
  if ($noWindow) {
    try {
      Invoke-RestMethod -Uri "http://localhost:3100/api/incidents/$($noWindow.id)/undo" -Method POST -Headers $h -ContentType "application/json" -Body '{}'
      throw "[T7] undo devia falhar 400"
    } catch {
      if ($_.Exception.Response.StatusCode -ne 400) { throw "[T7] status errado: $($_.Exception.Response.StatusCode)" }
    }
  }
}

Write-Host "smoke V1.1 OK"
```

**Critérios:**
- [ ] **Fix 0:** após `login`, nenhum `permission denied` em mutações do Doctor; clients `service_role` e anon separados (ver § Fix 0).
- [ ] T1 baseline vazio (ou explicitar por que não).
- [ ] T3 encontra 1 `burn_rate_anomaly` em Atlas (agente offline → S5 deve disparar mesmo assim, ver Fix 5).
- [ ] T4 `GET /incidents/:id` responde 200.
- [ ] T5 approve persiste em Postgres (validar via MCP select).
- [ ] T7 `POST .../undo` com janela inválida (`undo_expires_at` nulo **ou** no passado) responde **400** com `detail=undo_window_expired` — nunca 500.
- [ ] Validação MCP: `select count(*) from vectraclip.incidents where decision='approved'` ≥ 1 + `select count(*) from vectraclip.incident_audit where event='council_approved'` ≥ 1.

---

## Fora de escopo

- **Não rodar SQL de migration, schema, RLS, grants ou seed.** Migrations desta VEC já foram aplicadas pelo VectraClip via MCP Supabase. Cláusula permanente a partir daqui.
- **Não rodar `UPDATE`/`DELETE` ad-hoc** em `vectraclip.incidents` ou `vectraclip.incident_audit` para "limpar" dados de teste. Reset é do VectraClip via MCP.
- **Não refatorar o severity score.** Matriz 5-dim do V1 (§4.3) fica como está; só garantir que D5 agora lê `companies.tier` real.
- **Não editar `VectraClip/*`.** Contrato Zod `Incident` é atualizado em PR paralelo no frontend.
- **Não implementar rollback semântico de Undo.** V1.1 ainda só marca `decision=undone` + audit. Rollback por fix (restaurar `task.status` anterior) fica pra V1.2.
- **Não adicionar novos sintomas ou fixes.** Catálogo da V1 é suficiente; S5 só muda de escopo (Fix 5), sem entrar novo detector.

---

## Rastreio

- **Linear:** [VEC-200 — Heartbeat Doctor em Postgres (sair do in-memory)](https://linear.app/vectra-cargo/issue/VEC-200) (criada junto com este doc, blocada por VEC-199).
- **PR / branch sugerido:** `marceloabissulo/vec-199b-doctor-postgres`.
- **Dependências:** VEC-197b ✅ (grants em `vectraclip.*`), VEC-194 ✅ (JWT real + RLS), **VEC-199 reaberta** até V1.1 passar.
- **Pós-V1.1:** V1.2 (rollback semântico de Undo), V2 (adapter externo + restart real).
