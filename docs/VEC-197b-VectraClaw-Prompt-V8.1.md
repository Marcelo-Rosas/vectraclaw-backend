# VEC-197b — VectraClaw Prompt V8.1 (resume→idle + kill zera burn + PATCH /agents/:id)

**Issue Linear:** VEC-197b — Resíduos do V8 após auditoria end-to-end
**Repositório alvo:** `VectraClaw` — `src/api.py`
**Documento anterior:** [`docs/VEC-197-VectraClaw-Prompt-V8.md`](./VEC-197-VectraClaw-Prompt-V8.md)
**Relaciona-se com:** `VEC-197` (concluída parcialmente), `VEC-196` (bloqueada por isto)

---

## 🗺️ Território

> Convenção permanente a partir desta VEC: toda spec Claw tem esta seção. Template em [`docs/_VectraClaw-Prompt-TEMPLATE.md`](./_VectraClaw-Prompt-TEMPLATE.md).

| Responsabilidade                              | Dono       | Onde (para esta VEC)                                                       |
|-----------------------------------------------|------------|----------------------------------------------------------------------------|
| Handlers `pause/resume/kill/patch` + AgentStatus enum | VectraClaw | `VectraClaw/src/api.py` (+ eventual `src/models.py` para `AgentPatch`)     |
| Policy RLS em `vectraclip.agents`             | já aplicada | `supabase/migrations/` — **não recriar**                                   |
| Grant de tabela `authenticated` nas writes    | já aplicado pelo VectraClip via MCP | migration `vec_197_vectraclip_write_grants_authenticated` — **não recriar** |
| Reset/restore do seed após smoke              | VectraClip | MCP Supabase — **Claw não executa UPDATE direto**                          |
| Mock MSW correspondente (`PATCH agents`)      | VectraClip | `src/mocks/handlers.ts` — **Claw não toca**                                |
| Hook React Query / UI das ações de agente     | VectraClip | `src/lib/queries/agents.ts`, `src/components/agents/*`                     |

Cláusulas permanentes continuam valendo (ver §7 do template: sem cross-repo, sem UPDATE ad-hoc, sem assinatura IA nos commits, etc.).

---

## Contexto — o que o V8 entregou e o que ficou em aberto

Depois do walkthrough V8, rodamos uma auditoria end-to-end contra o Claw (`http://localhost:3100`) com JWT real do `marcelo.rosas@vectracargo.com.br` (role `admin`) e inspeção direta do schema `vectraclip` via MCP do Supabase.

### ✅ Confirmados OK

- **CORS em 500/401**: `Access-Control-Allow-Origin: http://localhost:3000` presente em todas as respostas testadas (Fix 4 do V8 aplicado).
- **Policies RLS em `vectraclip.agents`**: `agents_update_own_company_admin_op`, `agents_insert_own_company_admin_op`, `agents_select_own_company`, `agents_delete_own_company_admin` — todas presentes e corretas (gate por `company_id` + `role ∈ {admin, operator}`).
- **Pause zera `current_burn_rate`**: `POST /pause` em Iris retornou `status=paused, currentBurnRate=0`.

### ❌ Resíduos detectados pela auditoria

Três claims do walkthrough V8 **não passaram** no smoke real:

| # | Endpoint | Esperado | Observado | Status |
|---|---|---|---|---|
| 1 | `POST /api/agents/:id/resume` (paused→idle) | `status: "idle"` | `status: "working"` | ❌ |
| 2 | `POST /api/agents/:id/resume` (offline→idle, "Reativar") | `status: "idle"` | `status: "working"` | ❌ |
| 3 | `POST /api/agents/:id/kill` | `currentBurnRate: 0` | `currentBurnRate: 85000` (preservado) | ❌ |
| 4 | `PATCH /api/agents/:id` | `200 OK` com campo atualizado | `405 Method Not Allowed` | ❌ |

### ℹ️ Contexto adicional (já resolvido pelo frontend)

O bug raiz do 500/42501 era **table-level grant** em `vectraclip.agents` (role `authenticated` só tinha `SELECT`). A policy RLS já existia e estava correta, mas o Postgres avalia grant **antes** de RLS — por isso `permission denied`.

Aplicado via MCP na migration `vec_197_vectraclip_write_grants_authenticated` (já no banco):

```sql
grant insert, update, delete on vectraclip.agents     to authenticated;
grant insert, update, delete on vectraclip.tasks      to authenticated;
grant insert, update, delete on vectraclip.heartbeats to authenticated;
```

**Não precisa reaplicar no Claw.** Só mencionado aqui pra constar.

---

## Evidência do smoke (pós-grant, pré-V8.1)

Rodado contra `http://localhost:3100` com JWT válido e `Origin: http://localhost:3000`:

```
[T1 pause Iris]                OK 200 cors=http://localhost:3000 | status=paused  burn=0      ✅
[T2 resume Iris]               OK 200 cors=http://localhost:3000 | status=working burn=0      ❌ devia ser idle
[T3 Reativar Atlas (off→idle)] OK 200 cors=http://localhost:3000 | status=working burn=60000  ❌ devia ser idle
[T4 kill Helios]               OK 200 cors=http://localhost:3000 | status=offline burn=85000  ❌ devia zerar burn
[T5 revert Helios]             OK 200 cors=http://localhost:3000 | status=working burn=85000

=== PATCH /api/agents/:id ===
PATCH FAIL 405: Method Not Allowed                                                            ❌
```

---

## Fix 1 — 🔴 `resume_agent` voltando `working` em vez de `idle`

O V8 prometeu corrigir a linha 716 de `"offline"` para `"idle"`. O AgentStatus enum (V8 Fix 2b) existe mas o endpoint **ainda não chama `AgentStatus.IDLE`**. Sintoma novo: em vez de `offline`, agora volta `working` — ou seja, o valor foi trocado, mas pelo **pior** candidato possível (pause→resume vira um no-op semântico, reativar não reativa).

**Ação:** em `src/api.py`, procurar o handler de `/resume`:

```python
@app.post("/api/agents/{agent_id}/resume")
@app.post("/agents/{agent_id}/resume")
async def resume_agent(agent_id: str, request: Request):
    # Reusa /resume para duas transições idempotentes:
    #   paused  → idle  (botão "Retomar")
    #   offline → idle  (botão "Reativar", VEC-196)
    return await supabase_update_agent_status(
        request.state.token,
        agent_id,
        AgentStatus.IDLE,     # ← NÃO WORKING, NÃO OFFLINE
    )
```

Auditar os três irmãos (pause/resume/kill) no mesmo commit:

| Endpoint | `new_status` correto |
|---|---|
| `pause_agent`  | `AgentStatus.PAUSED`  |
| `resume_agent` | `AgentStatus.IDLE`    |
| `kill_agent`   | `AgentStatus.OFFLINE` |

> **Regra de estilo:** usar **sempre** `AgentStatus.X`, nunca string literal. Erro de digitação vira `AttributeError` em import time em vez de bug silencioso em produção.

---

## Fix 2 — 🔴 Kill não zera `current_burn_rate`

A função `supabase_update_agent_status` (ou o endpoint kill) não aplica o mesmo ramo que pause. O frontend (`useKillAgent` em `src/lib/queries/agents.ts`) faz optimistic update com `currentBurnRate: 0` — quando o backend responde `85000`, o React Query sobrescreve o otimismo e o card "ressuscita" o número. É só parte da spec que ficou só pra pause.

**Ação:** dentro de `supabase_update_agent_status`, manter um único ramo que cobre **tanto paused quanto offline**:

```python
async def supabase_update_agent_status(
    token: str, agent_id: str, new_status: str
) -> dict:
    patch: dict = {"status": new_status}

    # Agente sem CPU consumindo = burn zero. Vale para os dois terminais:
    #   - paused  (pausa humana)
    #   - offline (kill lógico)
    if new_status in (AgentStatus.PAUSED, AgentStatus.OFFLINE):
        patch["current_burn_rate"] = 0

    client = get_authenticated_client(token)
    result = (
        client.schema("vectraclip")
              .table("agents")
              .update(patch)
              .eq("id", agent_id)
              .execute()
    )
    # ... retorno serializado via AgentModel (camelCase) ...
```

Reforço: a regra **não deve** zerar quando transição é para `idle` (reativar ou retomar). Burn em idle é computado pelos heartbeats — não é tarefa deste endpoint.

---

## Fix 3 — 🔴 `PATCH /api/agents/:id` retorna 405 (VEC-196 ainda não existe)

O walkthrough V8 listou "Adicionado suporte a PATCH" mas o endpoint não foi registrado. `PATCH` em qualquer agente responde **405 Method Not Allowed** — ou seja, a rota simplesmente não existe no FastAPI app.

Dois candidatos prováveis:

1. Decorator comentado / esquecido.
2. Handler escrito mas não incluído no router montado por `main.py`.

**Ação:** aplicar a spec do [VEC-196 / V7](./VEC-196-VectraClaw-Prompt-V7.md) — a policy `agents_update_own_company_admin_op` **já cobre** o PATCH (sinergia gratuita), falta só o handler em Python:

```python
from pydantic import BaseModel, Field
from typing import Optional

class AgentPatch(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    token_budget: Optional[int] = Field(default=None, alias="tokenBudget")
    reports_to_id: Optional[str] = Field(default=None, alias="reportsToId")

    model_config = {"populate_by_name": True, "extra": "ignore"}


@app.patch("/api/agents/{agent_id}")
@app.patch("/agents/{agent_id}")
async def patch_agent(agent_id: str, patch: AgentPatch, request: Request) -> dict:
    # Só envia o que o cliente mandou (partial update verdadeiro).
    payload = patch.model_dump(by_alias=False, exclude_none=True)
    if not payload:
        raise HTTPException(status_code=400, detail="empty_patch")

    client = get_authenticated_client(request.state.token)
    result = (
        client.schema("vectraclip")
              .table("agents")
              .update(payload)
              .eq("id", agent_id)
              .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="agent_not_found")

    return AgentModel.model_validate(result.data[0]).model_dump(by_alias=True)
```

Campos imutáveis (`id`, `companyId`, `adapterType`, `createdAt`, `status`, `currentBurnRate`) **não** aceitos no body — se o cliente mandar, ignorar silenciosamente (`extra: "ignore"` no Pydantic). Status só muda via `/pause`, `/resume`, `/kill`.

---

## Smoke test pós-patch (obrigatório antes de marcar done)

```powershell
$tok = (Invoke-RestMethod -Uri "http://localhost:3100/api/auth/login" -Method POST `
  -ContentType "application/json" `
  -Body '{"email":"marcelo.rosas@vectracargo.com.br","password":"vectra123"}').accessToken
$h = @{"Authorization"="Bearer $tok"; "Origin"="http://localhost:3000"}

$iris   = "a0000000-0000-4000-8000-000000000002"  # idle
$helios = "a0000000-0000-4000-8000-000000000003"  # working, burn 85000
$atlas  = "a0000000-0000-4000-8000-000000000004"  # offline, burn 60000

# 1) pause Iris    → status=paused,  burn=0
Invoke-RestMethod -Uri "http://localhost:3100/api/agents/$iris/pause"  -Method POST -Headers $h

# 2) resume Iris   → status=IDLE     (NÃO working, NÃO offline)
Invoke-RestMethod -Uri "http://localhost:3100/api/agents/$iris/resume" -Method POST -Headers $h

# 3) Reativar Atlas (offline → idle) → status=IDLE
Invoke-RestMethod -Uri "http://localhost:3100/api/agents/$atlas/resume" -Method POST -Headers $h

# 4) kill Helios   → status=offline, burn=0    (era 85000)
Invoke-RestMethod -Uri "http://localhost:3100/api/agents/$helios/kill" -Method POST -Headers $h

# 5) revert        → status=idle
Invoke-RestMethod -Uri "http://localhost:3100/api/agents/$helios/resume" -Method POST -Headers $h

# 6) PATCH name    → 200 OK com name atualizado
Invoke-RestMethod -Uri "http://localhost:3100/api/agents/$iris" `
  -Method PATCH -Headers $h -ContentType "application/json" `
  -Body '{"name":"Iris V8.1"}'

# 7) PATCH revert  → 200 OK
Invoke-RestMethod -Uri "http://localhost:3100/api/agents/$iris" `
  -Method PATCH -Headers $h -ContentType "application/json" `
  -Body '{"name":"Iris"}'
```

**Critério de aceite:** os 7 casos passam sem erro, retornos com o `status` e `currentBurnRate` exatamente como indicado.

> ⚠️ **Não executar SQL de reset do seed.** A restauração do estado dos agentes (`Atlas → offline/60000`, `Iris → idle/0`) após o smoke é **responsabilidade do VectraClip** (rodamos via MCP do Supabase do nosso lado). O Claw **não deve** executar nenhum `UPDATE vectraclip.agents` manual — dados de teste são gerenciados pelas migrations de seed oficiais (`vec_191_*`, `vec_192_*`, `vec_193_*`) e pelos endpoints normais do próprio VectraClaw. Se o smoke deixar o banco fora do estado esperado, apenas sinalize — a gente restaura.

---

## Fora de escopo

- Não mexer nas policies RLS — estão certas. Bug era só grant, já resolvido.
- Não alterar o ramo de `idle` em `supabase_update_agent_status` pra mexer em burn — burn de idle é calculado por heartbeat, não por endpoint de transição.
- Não adicionar policy/endpoint de DELETE. Kill continua lógico.
- **Não rodar SQL direto no banco para reset de seed** — reset é do VectraClip (MCP Supabase).
