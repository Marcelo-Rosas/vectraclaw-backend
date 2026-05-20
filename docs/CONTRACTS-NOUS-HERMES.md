# Contrato Nous Hermes — Runtime × Adapter × API

> **Extraído de:** [`PRD-NOUS-HERMES-INTEGRATION.md`](./PRD-NOUS-HERMES-INTEGRATION.md) (narrativa e roadmap).  
> **Este arquivo** é o contrato técnico que faltava no repositório (antes só existia o PRD).  
> **Parent:** [`CONTRACTS-AGENT-CAPABILITIES.md`](./CONTRACTS-AGENT-CAPABILITIES.md) §9 F4 — Nous entra no bundle como `adapter.catalog_slug = "nous-hermes"`.

---

## 0. Naming (obrigatório)

| Conceito | Valor | Não confundir com |
|----------|-------|-------------------|
| Daemon IMAP | `Hermes` — AGENT_ID `59b7a69e-cc53-4063-85f9-5dcc5619ac96` | — |
| Daemon SMTP reports | `HermesReporter` | — |
| Runtime Nous Research | serviço Docker `nous-hermes-runtime` | daemons acima |
| Adapter slug | `nous-hermes` (kebab) | — |
| Provider key | `nous_hermes` (snake) | `hermes` |
| Env infra única | `NOUS_HERMES_RUNTIME_URL` | sem API keys em env |

---

## 1. Fases e status (2026-05-19)

| Fase | Entregável | Status |
|------|------------|--------|
| **F1** | Container + wrapper HTTP + `/api/nous-hermes/health` + `/exec` | ✅ |
| **F2** | MCP server VectraClaw exposto ao Hermes | ❌ backlog PRD |
| **F3** | `NousHermesAgentClient` + task via CMA | ⚠️ client existe; E2E opt-in |
| **F4** | Gateway multi-canal cliente (WhatsApp/Telegram/…) | 📋 **No escopo** — decisão 2026-05-19: Hermes Gateway; OpenClaw descartado. Ver ADR canal + PRD §10 |
| **F5** | Trajectory / tokens via `hermes sessions export` | ❌ PRD trajectory |

---

## 2. Infraestrutura

### 2.1 Docker Compose

```yaml
# serviço (referência)
nous-hermes-runtime:
  build: ./nous-hermes-runtime
  ports: []  # rede interna
  environment:
    - NOUS_HERMES_RUNTIME_URL=http://nous-hermes-runtime:9120  # só no backend consumer
  volumes:
    - nous-hermes-config:/root/.hermes
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:9120/health"]
```

Backend: `depends_on: nous-hermes-runtime: service_healthy` (quando stack completa).

### 2.2 Runtime wrapper (`nous-hermes-runtime/wrapper.py`)

| Método | Path | Request | Response |
|--------|------|---------|----------|
| GET | `/health` | — | `{ status, hermes_version?, provider?, model? }` |
| POST | `/exec` | ver §3.2 | `{ success, content, exit_code, duration_ms }` |

**Bootstrap config (TO-BE completo no PRD):** no startup, ler `adapter_catalog` + `company_adapter_values` — hoje parcial via payload do backend no exec.

---

## 3. API VectraClaw (F1)

Router: `src/api_routes/nous_hermes.py` (incluído em `src/api.py`).

### 3.1 Auth

- Header `Authorization: Bearer <jwt>`
- Roles: `admin` \| `platform_admin` \| `company_admin`
- `company_id` do JWT / header tenant

### 3.2 `GET /api/nous-hermes/health`

**Response 200:**

```json
{
  "runtime": { "status": "ok", "hermes_version": "…" },
  "runtime_url": "http://nous-hermes-runtime:9120"
}
```

**503:** runtime unreachable.

### 3.3 `POST /api/nous-hermes/exec`

**Body:**

```json
{
  "prompt": "string (1..200000)",
  "agent_id": "uuid opcional — override agent_adapter_configs",
  "max_turns": 1,
  "timeout_seconds": 180
}
```

**Pré-condição:** `adapter_catalog.slug = 'nous-hermes' AND is_active = true` para `company_id`.

**503:** `adapter_nous_hermes_inactive — ative em Admin Connectors`.

**Response 200:**

```json
{
  "success": true,
  "content": "…",
  "exit_code": 0,
  "duration_ms": 12345,
  "metadata": {}
}
```

### 3.4 Feature flag

**Não usar** `NOUS_HERMES_ENABLED` nem API keys em `.env`.

Flag = `vectraclip.adapter_catalog.is_active` per company (seed migration com `is_active=false`).

---

## 4. Catálogo DB

Migration: `supabase/migrations/20260518150000_nous_hermes_adapter.sql`

### 4.1 `adapter_catalog` (por company)

| Campo | Valor seed |
|-------|------------|
| `slug` | `nous-hermes` |
| `display_name` | `Nous Hermes Agent` |
| `provider` | `nous_hermes` |
| `is_active` | `false` (admin ativa) |

### 4.2 `adapter_field_definitions`

| field_key | Tipo | Obrigatório |
|-----------|------|-------------|
| `inference_provider` | select: ollama, openrouter, anthropic | sim |
| `model_id` | text | sim |
| `api_key` | secret | não |
| `approval_mode` | select: none, smart, auto | sim |
| `max_turns` | text | sim |
| `ollama_base_url` | text | não |
| `system_prompt` | textarea | não |
| `timeout_seconds` | text | sim |

### 4.3 `company_adapter_values`

Defaults dev em `field_values_json` (ollama/llama3.2 no seed) — editável em `/admin/connectors`.

### 4.4 `llm_models` (F3)

Rows para modelos OpenRouter Nous (`hermes-4`, etc.) — ver PRD §8.2.

---

## 5. Daemon / CMA (F3)

### 5.1 Client

`src/managed_agents/nous_hermes_agent_client.py`

```python
class ExecutionResult:
    success: bool
    content: str
    tool_calls: list  # v0 sempre []
    turn_count: int     # v0 0
    tokens_input: int   # v0 0
    tokens_output: int  # v0 0
    execution_time_seconds: float
    tokens_per_second: float  # v0 0.0
    error: Optional[str]
```

### 5.2 Factory

`agent_client_factory.PROVIDER_CLIENT_MAP["nous_hermes"] = NousHermesAgentClient`

### 5.3 Operation types compatíveis v0

✅ `document_generation`, `code_review` (JSON livre).  
❌ Handlers Athena PMBOK, `oracle-research`, outputs JSON estritos.

### 5.4 Telemetria

Tasks `provider=nous_hermes` **excluídas** de burn rate até parser trajectory (PRD §8.5).

---

## 6. UI VectraClip (TO-BE / parcial)

| Rota | Componente | API |
|------|------------|-----|
| `/admin/connectors` | toggle adapter `nous-hermes` | adapter_catalog |
| **TO-BE** `/admin/nous-hermes` | `RuntimeHealthCard`, `RuntimeSmokeForm` | health, exec |

---

## 7. Integração com Agent Capability Bundle

Quando [`CONTRACTS-AGENT-CAPABILITIES.md`](./CONTRACTS-AGENT-CAPABILITIES.md) apply rodar:

```json
{
  "adapter": {
    "catalog_slug": "nous-hermes",
    "field_values_json": {
      "inference_provider": "openrouter",
      "model_id": "nousresearch/hermes-4",
      "approval_mode": "smart",
      "max_turns": "20"
    }
  }
}
```

→ `INSERT agent_adapter_configs` → daemon usa `NousHermesAgentClient` nas tasks dessa specialty.

---

## 8. Smoke

```powershell
docker compose up -d nous-hermes-runtime
curl -H "Authorization: Bearer $TOKEN" http://localhost:3100/api/nous-hermes/health
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" `
  -d '{"prompt":"Say OK"}' http://localhost:3100/api/nous-hermes/exec
```

Pré-requisito: ativar adapter em Connectors para a company do JWT.

---

## 9. Referências

- PRD completo: [`PRD-NOUS-HERMES-INTEGRATION.md`](./PRD-NOUS-HERMES-INTEGRATION.md)
- ADR canal cliente: [`ADR-VEC-CANAL-CLIENTE-OPENCLAW-VS-HERMES.md`](./ADR-VEC-CANAL-CLIENTE-OPENCLAW-VS-HERMES.md)
- Código: `src/services/nous_hermes.py`, `src/api_routes/nous_hermes.py`
