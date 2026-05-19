# `src/services/` — Camada de serviços puros

Contém wrappers e calculadoras que **não tocam Supabase diretamente** (com poucas exceções controladas). Usados por `api.py`, `agent_daemon.py`, ou agentes específicos. Foco: lógica reutilizável e testável sem mock de DB.

---

## Mapa de serviços

| Serviço | Arquivo | Papel | Side-effects |
|---|---|---|---|
| **Heartbeat Doctor** | `heartbeat_doctor/` | Loop autônomo que monitora burn rate, detecta agentes "stuck" e aplica fixes (rate limit, retry) | DB writes (incidents) |
| **Hermes IMAP** | `hermes_imap.py` | Wrapper IMAP puro (login, fetch INBOX, mark seen) | Nenhum (stateless) |
| **Hermes SMTP** | `hermes_smtp.py` | Wrapper SMTP (envio HTML/text via TLS) | Side-effect externo (envia email) |
| **Oracle Session** | `oracle_session.py` | Store in-memory de sessões Oracle (chat, snapshot SIPOC, w2h coletado) | Nenhum (RAM apenas) |
| **Gemini Client** | `gemini_client.py` | Wrapper sync para `google.generativeai` (Gemini API) | Externo (API call) |
| **Gemini Interactions** | `gemini_interactions.py` | Wrapper para Gemini Interactions API (multi-turn streaming, function calling) | Externo |
| **Prompt Compiler** | `prompt_compiler.py` | Compõe prompts para agentes a partir de templates | Nenhum |
| **Prospect Research Capture** | `prospect_research_capture.py` | Playwright + upload Storage para snapshots LinkedIn/Instagram | DB write (`prospect_profiles.artifacts`), Storage write |
| **Flow Orchestrator** | `flow_orchestrator.py` | Coordena fluxo entre nós de workflow (langgraph) | Lê/escreve estado de workflow |
| **Workflow Engine** | (referenciado) | Execução de workflows configurados pelo usuário | DB writes |
| **Workflow Graph** | (referenciado) | Validação de DAG, ordenação topológica | Nenhum |
| **Task Factory** | `task_factory.py` | Cria tasks a partir de gabaritos (com defaults consistentes) | DB write |
| **Freight Calculator** | `freight/calculator.py` | Cálculo de cubagem, capacidade veicular, peso taxável | Nenhum |
| **CNPJ Lookup** | `cnpj_lookup.py` | BrasilAPI + cache local | Externo + cache |
| **Logistics BL/PL Parser** | `logistics/bl_pl_parser.py` | OCR + parsing de Bill of Lading e Packing List (pdfplumber) | Nenhum |
| **Brain — DB Failover** | `brain/db_failover.py` | Wrapper resiliente em volta do client Supabase (retry, circuit breaker) | Nenhum |
| **Brain — System Prompt** | `brain/system_prompt.py` | Prompt fixo base do "Brain" coordenador | Nenhum |
| **Brain — Workflow Aduaneiro** | `brain/workflow_aduaneiro.py` | Lógica de fluxo específica para despacho aduaneiro | Variado |
| **MCP Client** | `mcp_client.py` | Wrapper para chamar tools de MCP servers externos | Externo |
| **Morpheus Dispatcher** | `morpheus_dispatcher.py` | Despachador de tasks para Morpheus (orquestrador) | DB write |
| **Research Events** | `research_events.py` | Pub/sub de eventos de pesquisa (Oracle research) | DB write |
| **Research Template Renderer** | `research_template_renderer.py` | Aplica template de output em research result | Nenhum |
| **ROI Calculator** | `roi_calculator.py` | Cálculo de ROI de automação por atividade SIPOC | Nenhum |
| **Routine Runner** | `routine_runner.py` | Executor de rotinas agendadas (cron) | DB writes |
| **SIPOC Analytics** | `sipoc_analytics.py` | KPIs e agregados sobre SIPOC mapeados | DB read |

---

## Heartbeat Doctor (subdiretório)

Sistema autônomo que roda em loop separado e supervisiona os daemons.

| Componente | Papel |
|---|---|
| `loop.py` | Loop principal — tick a cada N segundos |
| `audit.py` | Detecta sintomas: tasks órfãs, daemons sem heartbeat há X min, retries acima do threshold |
| `symptoms.py` | Catálogo de sintomas (cada um com função detector) |
| `fixes.py` | Catálogo de remediações (re-queue task, restart hint, etc.) |
| `rate_limit.py` | Limites de quanto pode aplicar fix em janela de tempo (evita storm) |
| `managed_agent_monitor.py` | Específico para CMA: detecta token spike, latency anomaly |
| `store.py` | Persistência (history de sintomas + fixes aplicados) |

**Princípio:** detecta → registra incidente → aplica fix se rate-limit permitir → broadcast WS. Nunca trava daemon supervisionado.

---

## Oracle Session — atenção: in-memory

`oracle_session.py` define `_OracleSession` com:
- `messages: List[Dict]` — chat history
- `sipoc_snapshot: Dict` — snapshot do SIPOC sendo construído
- `collected_5w2h: Dict[activity_id, Dict[w2h_field, str]]` — cumulativo
- `current_stage: str` — estágio atual da entrevista
- `last_active: float` — timestamp para GC

⚠️ **Tudo in-memory.** Restart do `start_server.py` perde TODAS as sessões ativas. Atualmente o Oracle chat **não** popula esses dicts — apenas guarda mensagens (F-008 do autopilot night 2026-05-19). Para materializar SIPOC no DB, use o endpoint `POST /api/sipoc/sessions/{id}/commit` (PR2.3 #233) que aceita estado completo no body — frontend monta a partir do histórico do chat. Tabela `sipoc_drafts` mencionada em iteração anterior **não existe** e foi descartada (Opção B do F-008).

`gc_inactive_sessions(max_age_hours=2.0)` remove sessões ociosas. Chamada em endpoint dedicado ou em background task.

---

## Hermes IMAP / SMTP — exemplos de import lazy

Estes serviços expõem funções stateless. São importados:
- Pelo daemon Hermes (polling IMAP)
- Pelo `hermes_reporter` (SMTP send)
- Pelo `tool_translator._read_hermes_inbox` (CMA tool — lê inbox de outro agente)

Não criam estado global. Seguros para uso concorrente.

**Convenção de credenciais:** sempre vêm de `agent_adapter_configs.field_values_json` resolvido por `_resolve_imap_field` / `_resolve_field_value` (em `api.py`). Nunca hardcoded.

---

## Prospect Research Capture — única exceção que toca Storage

Captura HTML de LinkedIn/Instagram com Playwright autenticado e faz upload pra bucket `prospect-research`.

**Variáveis de env:**
- `PROSPECT_PLAYWRIGHT_ENABLED=true` — liga captura
- `PROSPECT_PLAYWRIGHT_STORAGE_STATE` — path absoluto pro `storage_state.json` (login persistido)
- `PROSPECT_STORAGE_BUCKET` — default `prospect-research`

**Pré-requisito:** rodar `salvar_sessao.py` (script utilitário) uma vez para fazer login real no LinkedIn/Instagram e gerar o storage_state.json. Após mudar credenciais, regerar e reiniciar daemon Oracle.

---

## Padrões para adicionar novo serviço

1. **Pure-by-default.** Side-effects de DB/HTTP só quando estritamente necessário.
2. **Sync ou async claro.** Wrappers de SDK sync → expor função sync; chamadas externas em ambiente async → usar `asyncio.to_thread`.
3. **Retornos consistentes.** Para tools dispatcháveis, retornar JSON string `{"success": bool, "result": ..., "error": ...}`.
4. **Logger nomeado.** `logging.getLogger("Vectra.<área>")`.
5. **Configuração via env ou arg, nunca hardcoded.** Exceções: defaults de teste em dev (com env override).
6. **Test em `tests/test_<service>.py`.** Mock de SDK externo via `monkeypatch.setattr`.

---

## Pitfalls

- **Side-effects ocultos:** se um service mexe em DB ou WS, **documentar na docstring**. Quem revisar import vê.
- **Singletons globais:** evitar. `oracle_session._SESSIONS` é um caso justificado (sessão de chat); não replicar em outros services.
- **Imports de `src.api`:** se um service importa de `api.py`, **provavelmente está no nível errado** — service deveria ser primitivo abaixo de api, não acima. Exceção: lazy import dentro de função para usar helpers (`_resolve_field_value`, etc.).
