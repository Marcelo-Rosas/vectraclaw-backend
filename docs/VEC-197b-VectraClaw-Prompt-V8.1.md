# VEC-197b — VectraClaw Prompt V8.1 (resume→idle + kill zera burn + PATCH /agents/:id)

**Issue Linear:** VEC-197b — Resíduos do V8 após auditoria end-to-end
**Repositório alvo:** `VectraClaw` — `src/api.py`
**Documento anterior:** [`docs/VEC-197-VectraClaw-Prompt-V8.md`](./VEC-197-VectraClaw-Prompt-V8.md)
**Relaciona-se com:** `VEC-197` (concluída parcialmente), `VEC-196` (bloqueada por isto)

---

## 🗺️ Território

| Responsabilidade                              | Dono       | Onde (para esta VEC)                                                       |
|-----------------------------------------------|------------|----------------------------------------------------------------------------|
| Handlers `pause/resume/kill/patch` + AgentStatus enum | VectraClaw | `VectraClaw/src/api.py` (+ eventual `src/models.py` para `AgentPatch`)     |
| Policy RLS em `vectraclip.agents`             | já aplicada | `supabase/migrations/` — **não recriar**                                   |
| Grant de tabela `authenticated` nas writes    | já aplicado pelo VectraClip via MCP | migration `vec_197_vectraclip_write_grants_authenticated` — **não recriar** |
| Reset/restore do seed após smoke              | VectraClip | MCP Supabase — **Claw não executa UPDATE direto**                          |
| Mock MSW correspondente (`PATCH agents`)      | VectraClip | `src/mocks/handlers.ts` — **Claw não toca**                                |
| Hook React Query / UI das ações de agente     | VectraClip | `src/lib/queries/agents.ts`, `src/components/agents/*`                     |

---

## Contexto — o que o V8 entregou e o que ficou em aberto

Depois do walkthrough V8, rodamos uma auditoria end-to-end contra o Claw (`http://localhost:3100`) com JWT real do `marcelo.rosas@vectracargo.com.br` (role `admin`) e inspeção direta do schema `vectraclip` via MCP do Supabase.

### ✅ Confirmados OK

- **CORS em 500/401**: `Access-Control-Allow-Origin: http://localhost:3000` presente em todas as respostas testadas.
- **Policies RLS em `vectraclip.agents`**: `agents_update_own_company_admin_op`, etc. todas corretas.
- **Pause zera `current_burn_rate`**: OK.

### ❌ Resíduos detectados pela auditoria

| # | Endpoint | Esperado | Observado | Status |
|---|---|---|---|---|
| 1 | `POST /api/agents/:id/resume` (paused→idle) | `status: "idle"` | `status: "working"` | ❌ |
| 2 | `POST /api/agents/:id/resume` (offline→idle, "Reativar") | `status: "idle"` | `status: "working"` | ❌ |
| 3 | `POST /api/agents/:id/kill` | `currentBurnRate: 0` | `currentBurnRate: 85000` (preservado) | ❌ |
| 4 | `PATCH /api/agents/:id` | `200 OK` com campo atualizado | `405 Method Not Allowed` | ❌ |

---

## Fix 1 — 🔴 `resume_agent` voltando `working` em vez de `idle`

**Ação:** em `src/api.py`, garantir que `/resume` retorne `AgentStatus.IDLE`.

```python
@app.post("/api/agents/{agent_id}/resume")
@app.post("/agents/{agent_id}/resume")
async def resume_agent(agent_id: str, request: Request):
    return await supabase_update_agent_status(
        request.state.token,
        agent_id,
        AgentStatus.IDLE,
    )
```

---

## Fix 2 — 🔴 Kill não zera `current_burn_rate`

**Ação:** em `supabase_update_agent_status`, zerar burn para `AgentStatus.OFFLINE`.

```python
    if new_status in (AgentStatus.PAUSED, AgentStatus.OFFLINE):
        patch["current_burn_rate"] = 0
```

---

## Fix 3 — 🔴 `PATCH /api/agents/:id` retorna 405

**Ação:** Registrar e implementar o endpoint `PATCH`.

```python
@app.patch("/api/agents/{agent_id}")
@app.patch("/agents/{agent_id}")
async def patch_agent(agent_id: str, patch: AgentPatch, request: Request) -> dict:
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

---

## Smoke test pós-patch (obrigatório antes de marcar done)

(Consultar prompt original para os comandos curl/powershell detalhados).

---

*Última atualização: 20/Abr/2026 — patch pós-auditoria V8.1.*
