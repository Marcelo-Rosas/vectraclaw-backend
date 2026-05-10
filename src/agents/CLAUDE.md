# `src/agents/` — Contratos de agentes

Cada agente é despachado pelo `agent_daemon.py` quando uma `vectraclip.task` chega com `assigned_to_agent_id` correspondente. O daemon roteia por `operation_type` para o handler correto.

---

## Mapa de agentes

| Agente | AGENT_ID | Operation types | Arquivo principal |
|---|---|---|---|
| Morpheus | `00000000-0000-0000-0000-000000000001` | orquestração; `route-cost-calculation` está em `EXCLUDED_TYPES` | (em `agent_daemon.py`) |
| **Oracle** | `00000000-0000-0000-0000-000000000002` | `oracle-research`, SIPOC chat (via `/api/oracle/chat` SSE) | `oracle.py`, `oracle_maker.py`, `oracle_checker.py`, `oracle_runner.py` |
| Hermes | `59b7a69e-cc53-4063-85f9-5dcc5619ac96` | `email_lead`, IMAP polling | (em api.py + serviços) |
| **HermesReporter** | `360a96cb-b1c3-4b65-b9fa-2b9cbb59dac1` | `oracle-report` (envio SMTP) | `hermes_reporter.py` |
| Mercator | `c7de1b0f-7c74-42f1-9de4-7210349e668e` | comercial, cotações | `mercator.py` |
| Plutus | `80fd6d0e-53ab-4638-b6e9-05cbbd121092` | financeiro | `plutus.py` |
| Hodos | `0d6e56cc-28b6-4382-96cd-1952b890d412` | qualp / rotas | `hodos.py` |
| **Kronos** | `9c8d7e6f-5a4b-4321-9876-543210fedcba` | `scrape-backlog`, `entrypoint-backlog`, `conciliacao-backlog`, `audit`, `apply` | `kronos.py`, `kronos_scrape.py`, `kronos_apply.py` |
| **Mnemos** | `00000000-0000-0000-0000-000000000003` | `rag-ingest` (RAG corpus curator) | `mnemos.py` |
| **Athena** | `ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d` | `athena-classify`, `athena-charter`, `athena-stakeholder-map`, `athena-risk-register`, `athena-evm`, `athena-rag-ingest`, `athena-audit`, `athena-recommend`, `athena-prioritize` | `athena.py`, `athena_schemas.py` (PR2: `src/services/athena_rag.py`) |

**SipocResearcher** é serviço (não agente próprio): `sipoc_researcher.py` é chamado via `/api/sipoc/research` (não tem AGENT_ID).

---

## Oracle — state machine SIPOC ⚠️ regras críticas

Oracle implementa um chat estagiado para mapear SIPOC + 5W2H de cada atividade. Usa langgraph para alternar entre **maker** (gera próxima fala) e **checker** (valida resposta antes de mandar pro usuário).

### Eventos do `oracle_maker`

| Evento | Quando dispara | Contexto que **DEVE** receber |
|---|---|---|
| `stage_intro` | Início de um estágio (suppliers/inputs/activities/outputs/customers) | `component_type` |
| `component_ack` | Usuário forneceu novo componente | `component_type`, `value` (msg do user) |
| `w2h_question` | Próxima pergunta 5W2H da atividade corrente | `w2h_field`, `activity_name`, **`previous_answers`** ⭐ |
| `w2h_analysis` | Atividade completou 5W2H, gera score Vectra Rubric | `activity_name`, `w2h_data` (cumulativo) |
| `meta_input` | Usuário enviou pergunta/correção fora de fluxo | (texto livre) |

### ⭐ INVARIANTE — contexto cumulativo em `w2h_question`

**Todo evento de pergunta-guia 5W2H deve ler `pending_activity.w2h_data` e passar como `previous_answers` ao prompt.** Caso contrário, o LLM gera exemplos incoerentes com respostas anteriores (ex: usuário responde "Onde = pasta física" e depois recebe exemplo "Como = acessar o sistema X").

**Implementação correta** (`oracle_maker._build_context_from_state`):
```python
if event == "w2h_question":
    pending = state.get("pending_activity") or {}
    return {
        "w2h_field": field or "what",
        "activity_name": activity,
        "previous_answers": pending.get("w2h_data", {}),
    }
```

**Implementação correta no template** (`oracle.build_oracle_prompt`):
```python
elif event == "w2h_question":
    previous = context.get("previous_answers") or {}
    answered = {_W2H_LABELS.get(k, k): v for k, v in previous.items() if v}
    # renderiza bloco de coerência no prompt + instrução explícita ao LLM
```

**Esta regra vale para qualquer evento futuro** que se beneficie de estado acumulado da atividade. Ao adicionar um novo evento, pergunte: "este evento se beneficia de saber o que já foi respondido nesta atividade?" — se sim, adicione `previous_answers` ao contexto.

### Sessão e GC

- `_OracleSession` em `services/oracle_session.py` é **in-memory** (dict global por `session_id`). Não persiste em DB.
- GC roda quando alguém chama `gc_inactive_sessions(max_age_hours=2.0)`.
- `messages` (chat history), `sipoc_snapshot`, `collected_5w2h`, `current_stage`, `last_active` ficam em memória até o reload do servidor ou GC.
- **Não trate session como persistente.** Restart de `start_server.py` derruba todas as sessões.

---

## Kronos — auditor financeiro

Pipeline em 5 fases distintas que rodam por `operation_type` distintos:

| operation_type | O que faz | Próxima task gerada |
|---|---|---|
| `scrape-backlog` | Scrape de transações novas no Meu Planner via Playwright | `entrypoint-backlog` por entry candidato |
| `entrypoint-backlog` | Cria entrypoint na planilha p/ cada transação não-categorizada | (terminal) |
| `conciliacao-backlog` | Reconcilia OFX × Planner (gap detection) | `audit` se houver discrepância |
| `audit` | Gera relatório markdown + cria task `oracle-report` para HermesReporter | `oracle-report` |
| `apply` | Aplica correções no Planner (escrita) | (terminal) |

**Inputs via `task.description` (formato KEY=VALUE em linhas):**
```
OFX_PATH=C:\Users\marce\OFX-C6\abril.ofx
PLANNER_PATH=C:\Users\marce\OFX-C6\planner-abril.csv
PERIODO_INICIO=2026-04-01    (opcional)
PERIODO_FIM=2026-04-30       (opcional)
RECIPIENT=email@ex.com       (opcional, default marcelo.rosas@vectracargo.com.br)
```

**input_json** também aceito; chaves são normalizadas para MAIÚSCULO (corrigido em `0b7aff0`).

Resultados em `audit-results/` (gitignored).

---

## Hermes — split em 3 papéis

| Papel | Onde mora | Responsabilidade |
|---|---|---|
| Daemon polling IMAP | (em api.py + serviços) | Lê inbox via IMAP a cada N segundos, cria tasks `email_lead` |
| `hermes_reporter.py` | `agents/` | Recebe task `oracle-report`, formata HTML fixo, envia SMTP |
| `services/hermes_imap.py` | `services/` | Wrapper IMAP puro (não toca Supabase) |
| `services/hermes_smtp.py` | `services/` | Wrapper SMTP puro |

**Decision engine** atribui `email_lead` score 10 → harness, NÃO CMA. Isso é proposital: o daemon Hermes nativo lida com credenciais IMAP da company; via CMA o roteamento de chave quebra.

---

## Plutus / Mercator / Hodos / Morpheus

Cada um é responsável por sua área (financeiro, comercial, rotas, orquestração). Estrutura típica:
- 1 arquivo `<agente>.py` em `agents/`
- Handler dispatchado por `operation_type` no `agent_daemon._execute_task`
- Side-effects: criar tasks derivadas, atualizar status no DB, broadcastar via `ws_manager`

Detalhes específicos quando o agente for trabalhado.

---

## Padrões obrigatórios para novos agentes

1. **AGENT_ID estável.** Gerar UUID v4 uma vez e tratar como imutável (FK em tasks). Documentar aqui.
2. **Lock via `.daemon_locks/<AGENT_ID>.lock`.** Já gerenciado pelo `agent_daemon.py`. Não duplicar.
3. **Operation_type em snake-kebab consistente.** Ex: `oracle-research`, `email_lead`, `freight-quotation`. Case-sensitive — alinhar com decision_engine se for CMA-routable.
4. **Logger nomeado.** `logging.getLogger("<NomeDoAgente>")`. Aparece em `daemon-<nome-lower>.log`.
5. **Side-effect padrão:** ao terminar uma task, criar próxima task derivada (se houver) **antes** de marcar status `done` — para não criar janela de zero-task que confunde dashboard.
6. **WS broadcast:** após mudar status de task ou agent, chamar `ws_manager.broadcast_company(...)` com payload em camelCase (alinhado com mock VectraClip).
7. **Heartbeat:** ao iniciar/concluir task, emitir heartbeat via `_emit_heartbeat_internal` (em `api.py`) — alimenta painel de burn rate.

---

## Pitfalls conhecidos

- **`route-cost-calculation`** é `EXCLUDED_TYPES` no `agent_daemon` (ver Morpheus). Foi quebrado em fase de transição; reverter o EXCLUDED só depois de validar handler.
- **`oracle-research` em `executor_type=managed_agent`** trava o Hermes — fluxo CMA não foi feito pra rotear research. Filtrar `executor_type=neq.managed_agent` no polling do Oracle daemon (já feito em `agent_daemon.py:343`).
- **Tasks órfãs** com `assigned_to_agent_id` mas `status=queued` por horas: bug histórico. `agent_daemon._stale_task_recovery` tenta resolver, mas confirmar que está ativo no agente em questão.
