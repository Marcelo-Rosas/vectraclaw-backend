# `src/managed_agents/` — Abstração multi-provider

Camada que decide entre **Harness** (daemon nativo) e **CMA** (Managed Agent — execução stateless via SDK do provider) e, quando CMA, qual provider usar.

---

## Pipeline de uma task CMA

```
                  ┌─────────────────────────┐
   task           │  decision_engine        │   score >= 50?
   ──────────────▶│  should_use_managed_..  │ ─────────────┐
                  └─────────────────────────┘              │
                                                            ▼
                                              ┌──────────────────────────┐
                                              │  router.route_task_exec  │
                                              │  ─ resolve provider via  │
                                              │    agent_adapter_configs │
                                              │    JOIN adapter_catalog  │
                                              └──────────────┬───────────┘
                                                             ▼
                                              ┌──────────────────────────┐
                                              │  agent_client_factory    │
                                              │  get_agent_client(prov)  │
                                              └──────────────┬───────────┘
                                                             ▼
                          ┌──────────────────────────────────┴──────────────────┐
                          ▼                          ▼                          ▼
                  ManagedAgentClient        OllamaAgentClient        HuggingFaceAgentClient
                  (Anthropic SDK)           (openai SDK → Ollama)    (openai SDK → HF router)
                          │                          │                          │
                          └──────────────────────────┼──────────────────────────┘
                                                     ▼
                                              ┌────────────────┐
                                              │ ExecutionResult│
                                              └────────┬───────┘
                                                       ▼
                                            router._emit_run_heartbeat
                                            (best-effort, falha silenciosa)
```

---

## Decision Engine

`decision_engine.py` decide CMA × harness. Threshold: **score >= 50 → CMA**.

### Tabela `_OPERATION_TYPE_SCORES`

| operation_type | Score | Razão |
|---|---|---|
| `orchestration` | 0 | coordenação multi-step → harness |
| `email_lead` | 10 | HermesReporter daemon trata nativamente; CMA quebra com chave de IMAP |
| `code_generation` | 15 | precisa de bash/file tools → harness |
| `qa_testing` | 35 | pode precisar de execução real → lean harness |
| `other` | 60 | padrão simples → lean CMA |
| `code_review` | 65 | análise pura → CMA |
| `document_generation` | 75 | síntese estruturada → CMA |
| `freight-quotation` | 80 | extração de briefing + cotação → CMA |
| `research` | 85 | síntese de informação → CMA |

Modificadores: descrição muito longa penaliza, budget apertado favorece CMA.

**Ao adicionar novo `operation_type`:** decidir o score com base em "precisa de tools de execução real?" (harness) vs "é síntese / análise pura?" (CMA).

---

## `ExecutionResult` — contrato compartilhado

Todos os 3 clients devolvem o mesmo dataclass (`managed_agent_client.ExecutionResult`):

```python
ExecutionResult(
    success: bool,
    content: str,
    tool_calls: List[Dict[str, Any]] = [],
    turn_count: int = 0,
    tokens_input: int = 0,
    tokens_output: int = 0,
    execution_time_seconds: float = 0.0,
    tokens_per_second: float = 0.0,  # eval-only (exclui dispatch_tool_call)
    error: Optional[str] = None,
)
```

**Ao adicionar novo provider:** todos os campos devem ser populados, especialmente `tokens_per_second` (router usa para heartbeat e painel de burn rate). Se o SDK não devolver `usage` confiável, deixar 0.0.

---

## Factory pattern

`agent_client_factory.py`:
- `PROVIDER_CLIENT_MAP: Dict[str, Optional[type]]` — mapping provider → classe. `None` marca slot reservado.
- `get_agent_client(provider, model, config)` — instancia cliente certo.
  - `anthropic` → `ManagedAgentClient(model=model)` (recebe model como kwarg)
  - `ollama`/`huggingface` → `cls(config=config or {})` (config dict do `field_values_json`)
  - `openai`/`google` → `NotImplementedError` (slot reservado, instrutivo)
  - desconhecido → `ValueError`

**Ao adicionar provider novo (ex: `"openai"`):**
1. Criar `<provider>_agent_client.py` com `class XAgentClient: async def execute_task(...) -> ExecutionResult`
2. Registrar em `PROVIDER_CLIENT_MAP[provider] = XAgentClient`
3. Exportar em `__init__.py`
4. Criar migration de adapter (`adapter_catalog`, `adapter_field_definitions` por company)
5. Avaliar se entra na whitelist do `router._emit_run_heartbeat` (`provider in ("anthropic", "ollama", "huggingface")`)

---

## Tool translator — fonte da verdade

`tool_translator.py` mantém **2 formatos** das mesmas tools:

| Formato | Onde usado | Como é gerado |
|---|---|---|
| `ANTHROPIC_TOOLS` (lista de dicts com `input_schema`) | `ManagedAgentClient` | **Source of truth** — definido manualmente |
| `OPENAI_TOOLS` (lista de dicts com `type:"function"`/`parameters`) | `OllamaAgentClient`, `HuggingFaceAgentClient` | **Derivado automaticamente** via list comprehension |

**Ao adicionar nova tool:**
1. Adicionar entrada em `ANTHROPIC_TOOLS` (com `name`, `description`, `input_schema`).
2. Adicionar dispatcher em `_TOOL_MAP` (no `_load_tools()`).
3. `OPENAI_TOOLS` reflete automaticamente — não duplicar.
4. Implementar a função em `src/m3_tools.py` ou inline (ex: `_read_hermes_inbox`).

**Tool inline:** se a tool depende de helpers de `src.api`, usar **lazy import** dentro da função (evita circular).

---

## Provider lookup no router

`router.route_task_execution` lê:
```sql
SELECT field_values_json, adapter_catalog!inner(provider)
FROM vectraclip.agent_adapter_configs
WHERE agent_id = <agent_id>
LIMIT 1
```

- Se houver linha → usa `provider` retornado.
- Se não houver / falha → fallback **`"anthropic"`** (retrocompat com agentes pré-CMA).

**Migrações que sustentam isso:**
- `adapter_catalog` por company (1 linha por (company_id, slug))
- `adapter_field_definitions` define os campos do form (token, model_id, temperature, etc.)
- `agent_adapter_configs.field_values_json` armazena os valores preenchidos

---

## Heartbeat após CMA — best-effort

`router._emit_run_heartbeat` emite heartbeat sintético após cada execução CMA:
- Whitelist providers: `("anthropic", "ollama", "huggingface")`
- Lazy import de `src.api._emit_heartbeat_internal` (caso ainda não exista — ex: durante transição de PR — falha em try/except, log de warning, task **completa normal**).
- `tokensUsed = tokens_input + tokens_output`
- `logExcerpt` formato: `"<Provider>: <tokens_output> tokens em <tps> tok/s"`

**Não bloqueante.** Se cair, usuário vê task done sem heartbeat — burn rate desatualiza, mas dados não corrompem.

---

## Pitfalls conhecidos

- **Modelos sem tool calling** podem entrar em loop infinito. Capacidade vive em `vectraclip.llm_models.supports_tool_calling` (PR #194 — aposentou constantes `*_TOOL_CAPABLE_MODELS` em cada client). Quem deve checar antes de rotear é o `decision_engine` via `src.services.llm_cost.is_tool_capable(supabase, model_id) -> Optional[bool]`. `_MAX_TURNS = 20` é a rede de proteção quando a checagem falha (modelo desconhecido).
- **`tokens_per_second` é eval-only** — exclui tempo de `dispatch_tool_call`. Se a tool é lenta, `execution_time_seconds` cresce mas `tokens_per_second` não cai (porque mede só inferência).
- **Ollama ignora `api_key`** mas o SDK exige string não vazia → passar `"ollama"`. Não usar `""`.
- **Pacote `anthropic` ou `openai` ausente** → `__init__` do client levanta erro. Cobrir em decision_engine para não rotear pra provider sem SDK.
