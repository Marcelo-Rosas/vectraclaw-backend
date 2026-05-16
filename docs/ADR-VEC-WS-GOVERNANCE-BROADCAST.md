# ADR — WS broadcast em endpoints Governance (G1.4)

> **Status:** parqueado — aguarda demanda do frontend
> **Owner:** plataforma + frontend (decisão conjunta)
> **Origem:** gap 🟠 INFO da Camada 1 em `docs/AUDIT-HANDLERS-2026-05-16.md`
> **Data:** 2026-05-16

## Contexto

Endpoints REST de governance **não emitem WS broadcasts**:
- `POST /api/approvals/{id}/approve|reject` (compliance — quem aprovou)
- `POST /api/risks/{id}/transition` (lifecycle PMBOK — mudança de status)
- `POST /api/sipoc/raci` (responsabilidade muda)
- `PATCH /api/app_users/{id}` (role muda — segurança)
- `POST /api/risks` / `DELETE` (criação/remoção de risco)

Outras camadas emitem (`task_updated`, `agent_updated`, `heartbeat`, `incident_updated`).

**Tabela de eventos WS atuais (`ws_manager.py`):**
- `hello`, `heartbeat`
- `task_updated`, `agent_updated`, `incident_updated`

## Por que NÃO atacar agora

1. **Frontend não consome eventos governance.** UI atual de approvals/risks é **polling-based** (refetch via TanStack Query a cada N segundos). Adicionar broadcast no backend sem consumer no frontend = código morto.

2. **Audit log resolve compliance.** Quem aprovou/transicionou/mudou role já fica em `audit_log` (G1.1 PR #167, G1.6 PR #170). WS broadcast é **otimização UX** (real-time vs polling), não requisito de compliance.

3. **Custo manutenção.** Cada broadcast precisa: payload camelCase consistente, schema documentado, cliente WS no frontend, gestão de reconexão. Sem demanda concreta, adicionar agora é YAGNI.

## Quando reverter (condição de saída)

Quando UI implementar `/governance` page (ou tabs em `/agents`, `/risks`, `/council`) e PM pedir **"quero ver aprovações entrando em real-time sem refresh"**.

Sinais:
- Frontend abre issue tipo "real-time approval feed"
- Demanda de feature collaborative editing (2 users vendo mesma matriz RACI)
- SLA UX requer notificação <1s pra approval pendente

## Implementação esperada (quando vier)

3 eventos novos no `ws_manager.py`:

| Evento | Payload | Disparado em |
|---|---|---|
| `approval_updated` | `CouncilApproval` camelCase | `_set_approval_status` |
| `risk_updated` | `Risk` camelCase + `event_type` (create/patch/transition/delete) | endpoints create_risk, patch_risk, transition_risk, delete_risk |
| `raci_updated` | `{processId, componentId, positionId, role, action}` | `update_raci_cell`, `delete_raci_cell` |

Padrão de chamada (já existe em `api.py`):
```python
await ws_manager.broadcast_company(company_id, {
    "type": "approval_updated",
    "payload": CouncilApproval(**row).to_zod_dict(),
})
```

Esforço: ~2h (3 endpoints × ~30min + smoke + 1 doc client-side reference).

## Decisão

Parquear até frontend pedir. Quando vier, este ADR vira issue concreto.

## Por que ADR e não issue direto

Issue corre o risco de virar backlog perpétuo sem contexto. ADR registra **razão de não fazer** — próxima sessão (humana ou IA) que olhar o AUDIT vê "🟠 INFO postpone" com link aqui, lê 2min, entende e não re-abre debate.
