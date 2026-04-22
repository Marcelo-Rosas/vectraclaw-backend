# VEC-183 — VectraClaw Prompt (WebSocket: eventos em tempo real por company)

**Issue Linear:** [VEC-183 — Configurar emissão de eventos WebSocket para status em tempo real](https://linear.app/vectra-cargo/issue/VEC-183)
**Repositório alvo:** `VectraClaw` — `src/ws_manager.py` (novo), `src/api.py`, `src/services/heartbeat_doctor/loop.py`
**Relaciona-se com:** `VEC-145` (cliente WS no VectraClip), `VEC-182` (task mutations agora emitem eventos), `VEC-183`

---

## 🗺️ Território

| Responsabilidade                                             | Dono           | Onde                                                                    |
|--------------------------------------------------------------|----------------|-------------------------------------------------------------------------|
| `ConnectionManager` — broadcast por `company_id`            | **VectraClaw** | `src/ws_manager.py` (novo)                                              |
| Rota `/ws/companies/{company_id}` + auth token query param  | **VectraClaw** | `src/api.py`                                                            |
| `POST /api/heartbeats` — agente reporta, WS emite           | **VectraClaw** | `src/api.py`                                                            |
| Broadcast `task_updated` em claim / complete / patch         | **VectraClaw** | `src/api.py` — `claim_task`, `complete_task`, `patch_task`             |
| Broadcast `agent_updated` em pause / resume / kill / patch  | **VectraClaw** | `src/api.py` — `supabase_update_agent_status`, `patch_agent`           |
| Broadcast `heartbeat` a partir do Doctor loop               | **VectraClaw** | `src/services/heartbeat_doctor/loop.py` — `doctor_tick`                |
| Hook React `useWebSocket` / reconexão                       | VectraClip     | `VEC-145` — **fora deste escopo**                                       |
| Mock WS `startWsMock` / `stopWsMock`                        | VectraClip     | `src/mocks/ws.ts` — já existia, formato alinhado                        |
| `/ws` (rota legacy)                                         | deprecated     | Fecha com `{ type: "error" }` + código 4000                             |

---

## Contexto — estado antes da VEC

`@app.websocket("/ws")` existia mas só recebia texto em loop e logava. Nenhum broadcast, nenhuma autenticação, nenhum namespace por company. O mock do VectraClip (`ws.ts`) já definia o contrato: rota `/ws/companies/:id`, evento `hello` no connect, `heartbeat` periódico.

---

## Contrato de mensagens (JSON wire)

```jsonc
// Enviado pelo servidor ao conectar
{ "type": "hello",            "companyId": "uuid" }

// Heartbeat de agente (Doctor scan ou POST /api/heartbeats)
{ "type": "heartbeat",        "payload": <Heartbeat camelCase> }

// Mutações de agente (pause / resume / kill / patch)
{ "type": "agent_updated",    "payload": <Agent camelCase> }

// Mutações de task (claim / complete / patch)
{ "type": "task_updated",     "payload": <Task camelCase> }

// Mutação de incidente (approve / undo) — preparado, emissão futura
{ "type": "incident_updated", "payload": <Incident camelCase> }
```

O cliente pode enviar qualquer texto (keep-alive / ping) — ignorado pelo servidor.

---

## Fix 1 — `src/ws_manager.py` (novo)

`ConnectionManager` singleton com:

- `connect(ws, company_id)` / `disconnect(ws, company_id)` — lifecycle
- `broadcast(company_id, message)` — async, remove sockets mortos automaticamente
- `emit_hello / emit_heartbeat / emit_agent_updated / emit_task_updated / emit_incident_updated` — wrappers tipados
- `broadcast_nowait(company_id, message)` — versão sync-safe para o Doctor loop (usa `loop.create_task`)

---

## Fix 2 — `/ws/companies/{company_id}` com auth

```python
@app.websocket("/ws/companies/{company_id}")
async def websocket_companies(websocket, company_id, token=Query(None)):
    # Valida JWT se fornecido; rejeita com 4001 em token inválido ou company mismatch
    # Adiciona ao ConnectionManager, emite hello, fica em loop até disconnect
```

Auth via query param `?token=<jwt>` (WebSocket API do browser não permite headers customizados).

Rota legacy `/ws` mantida: fecha imediatamente com `{ type: "error" }` + code 4000.

---

## Fix 3 — `POST /api/heartbeats`

Endpoint para agentes reportarem status. Persiste no DB via service_role, busca `company_id` do agente e emite `heartbeat` WS.

---

## Fix 4 — Broadcasts nas mutations existentes

| Endpoint mutado          | Evento WS emitido  |
|--------------------------|--------------------|
| `claim_task`             | `task_updated`     |
| `complete_task`          | `task_updated`     |
| `patch_task`             | `task_updated`     |
| `pause/resume/kill agent`| `agent_updated`    |
| `patch_agent`            | `agent_updated`    |

Broadcast ocorre **após** o `execute()` bem-sucedido — nunca em falhas.

---

## Fix 5 — Doctor loop emite `heartbeat` por tick

No `doctor_tick`, após ler o último heartbeat de cada agente, emite WS via `broadcast_nowait` (fire-and-forget sync-safe). Só emite se houver ao menos 1 socket conectado na company (evita serialização desnecessária).

---

## Smoke test / Critério de aceite

Script: `tests/test_vec183_ws_smoke.py`

```
[OK] login
[OK] /ws/companies/{id} → hello recebido, desconecta limpo
[OK] /ws/companies/{id}?token=<valid> → hello recebido
[OK] PATCH task → task_updated recebido (id=4f22a838...)
[OK] pause agent → agent_updated recebido (id=a0000000...)
[OK] /ws (legacy) → erro enviado + conexão fechada

ALL OK — VEC-183 WebSocket eventos em tempo real
```

Critérios:
- [x] `/ws/companies/{id}` aceita conexão e envia `hello`
- [x] Token JWT válido aceito; company mismatch fecha com 4001
- [x] `PATCH /api/tasks/{id}` dispara `task_updated` em todos os sockets da company
- [x] `POST /api/agents/{id}/pause` dispara `agent_updated`
- [x] `/ws` (legacy) fecha com mensagem de erro
- [x] `POST /api/heartbeats` endpoint disponível (novo)
- [x] Doctor loop emite `heartbeat` por agent por tick quando há sockets conectados

---

## Fora de escopo

- Hook React `useWebSocket` + reconexão automática — `VEC-145`
- Emit `incident_updated` em approve / undo — infra preparada, pendente integração na VEC de Council
- Autenticação obrigatória no WS (token opcional agora, obrigatório em hardening futuro)
- Multiplex de namespaces (uma conexão = uma company)

---

*Última atualização: 20/Abr/2026 — VEC-183 encerrada como Done.*
