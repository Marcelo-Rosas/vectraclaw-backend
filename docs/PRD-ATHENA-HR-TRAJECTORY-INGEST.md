# PRD — Athena HR Trajectory Ingest (Hermes Sessions → agent_prompt_history)

> **Status:** Draft — aprovação pendente
> **Owner:** Marcelo Rosas
> **Criado:** 2026-05-17
> **Escopo:** Pipeline de ingestão de trajectories do Hermes-Nous (Fase 5.1 — Hermes-only). Expansão multi-provider (Fase 5.2) deferida.
> **PRDs relacionados:** [`PRD-NOUS-HERMES-INTEGRATION.md`](./PRD-NOUS-HERMES-INTEGRATION.md) (Fase 3 deste PRD é pré-requisito)

---

## 1. Context

A memória `project_athena_hr_telemetry_optimization` registra a visão: **Athena HR ganha recomendações de modelo** (downgrade / upgrade / migrate_runtime / tune_thinking_budget) com **evidência estatística + rollback automático**. Hoje a matéria-prima vem de `vectraclip.agent_prompt_history` (criado em `20260511201200_vec408_agent_prompt_history.sql`) — captura **somente execuções dos daemons VectraClaw nativos** (Anthropic via `router._emit_run_heartbeat`).

Quando o PRD `PRD-NOUS-HERMES-INTEGRATION.md` for entregue (Fases 1-3), Hermes-Nous passa a executar tasks via `nous_hermes_agent_client` no mesmo pipeline. **Sem este PRD, essas execuções ficam invisíveis pro Athena HR** — Hermes vira caixa-preta e Athena não consegue comparar performance de modelos Nous (Hermes-4 / Nomos / Psyche) contra Anthropic/Gemini no mesmo `operation_type`.

**Boa notícia:** Hermes-Nous tem trajectory export **nativo** (`hermes sessions export <out>.jsonl --since 1h`). Zero código novo de instrumentação. Este PRD é apenas o pipeline de ingestão + mascaramento PII + agregação.

---

## 2. Goals

- **G1.** Capturar 100% das execuções via `nous_hermes_agent_client` em `agent_prompt_history` (post-F3 do PRD principal)
- **G2.** Correlacionar trajectory ↔ task VectraClaw via injeção de `[TASK_ID: <uuid>]` no prompt enviado ao Hermes
- **G3.** Alimentar `athena_recommendations` (já existente em `20260511201201_vec408_athena_recommendations.sql`) com agregações `(agent_id, model, operation_type)` em ciclo semanal
- **G4.** Zero PII em colunas de prompt/content após mascaramento

## 3. Non-goals

- ❌ Trajectory de Anthropic — já é capturada por `router._emit_run_heartbeat`; não duplicar
- ❌ Trajectory de Gemini / Ollama — gap conhecido, vira Fase 5.2 separada
- ❌ Fine-tune efetivo de modelo Nous custom — depende de volume substancial; out of scope (vira PRD próprio quando houver ≥ 10k trajectories)
- ❌ Replay de trajectory em sandbox — útil mas não MVP

---

## 4. Decisões já tomadas

| # | Decisão | Razão |
|---|---|---|
| D1 | **Cron:** Hermes nativo (`hermes cron create`) em vez de Kronos | Evita Kronos depender de container externo; cron Hermes já isolado no `nous-hermes-runtime` |
| D2 | **Correlação task↔trajectory:** sufixo `[TASK_ID: <uuid>]` no prompt enviado pelo `nous_hermes_agent_client` | Hermes-Nous não conhece schema VectraClaw; sufixo é o único canal de side-channel limpo |
| D3 | **Granularidade da agregação:** `(agent_id, model, operation_type)` | Match com cardinalidade do `agent_prompt_history` existente |
| D4 | **Mascaramento PII pré-upload é mandatório** | Reusar pattern do logger atual (token redaction); CNPJ/CPF/telefone/email → `[REDACTED]` |
| D5 | **Bucket Storage:** `hermes-trajectories/YYYY-MM-DD/HH.jsonl` | Particionado por hora; facilita lifecycle policy |
| D6 | **Retenção raw:** lifecycle 90 dias | Trade-off entre poder de re-análise e custo storage |

---

## 5. Escopo Fase 5.1 (MVP — Hermes-only)

### 5.1 Pipeline

```
nous-hermes-runtime
    │ (cron interno horário)
    ▼
 hermes sessions export ./out.jsonl --since 1h
    │
    ▼
 cron.sh: mascara PII + curl upload
    │
    ▼
 Supabase Storage: hermes-trajectories/2026-05-17/14.jsonl
    │
    ▼
 task `athena-trajectory-ingest` (handler Athena)
    │
    ▼
 parser JSONL → schema interno → upsert em agent_prompt_history
    │
    ▼
 ciclo semanal: agg → athena_recommendations
```

### 5.2 Arquivos novos

| Caminho | Propósito |
|---|---|
| `nous-hermes-runtime/cron.sh` | `hermes sessions export` + mask PII + `curl -X POST` pra Storage |
| `nous-hermes-runtime/mask_pii.py` | Funções de redação (CNPJ, CPF, telefone, email) — output JSONL com prompts/content sanitizados |
| `src/services/trajectory_ingest.py` | Parser JSONL → schema interno. Extrai por sessão: `agent_id`, `task_id` (via regex no prompt), `model_used`, `tokens_input/output`, `latency_ms`, `tool_calls_count`, `final_success`, `retries`. Upsert em `agent_prompt_history` |
| `supabase/migrations/YYYYMMDDHHMMSS_hermes_trajectory_corpus.sql` | (a) Bucket `hermes-trajectories` no Storage; (b) Extender `agent_prompt_history` com colunas `runtime_source TEXT DEFAULT 'native'`, `trajectory_session_id TEXT`; (c) Adicionar `athena-trajectory-ingest` ao CHECK de `operation_type` |

### 5.3 Arquivos modificados

| Caminho | Mudança |
|---|---|
| `src/agents/athena.py` | Registrar handler `athena-trajectory-ingest` no `_SPECIALTY_DISPATCH` — recebe `{bucket_key}`, chama `trajectory_ingest.process_jsonl(bucket_key)` |
| `src/managed_agents/nous_hermes_agent_client.py` (do PRD principal) | Modificar `execute_task` pra **prepender** `[TASK_ID: <uuid>]\n\n` ao prompt antes de enviar pro Hermes runtime. Reads `task.id` do dispatch context |
| `nous-hermes-runtime/entrypoint.sh` (do PRD principal) | Adicionar `hermes cron create "/cron.sh" --schedule "@hourly"` após config setup |

### 5.4 Reuso de patterns existentes

| Pattern | Onde | Como aproveitar |
|---|---|---|
| `agent_prompt_history` schema | Migration `20260511201200` | Estender com colunas novas (`runtime_source`, `trajectory_session_id`), zero breaking |
| `athena_recommendations` schema | Migration `20260511201201` | Reusar tabela existente; só novo `source='trajectory_ingest'` |
| Athena `_SPECIALTY_DISPATCH` | `src/agents/athena.py` | Mesmo pattern dos demais `athena-*` (classify, charter, evm, audit, recommend) |
| Supabase Storage upload via curl | Padrão dos buckets `prospect-research`, `rag-documents` | Reusar URL signed + headers |
| PII redaction | Logger filter de tokens (`router._emit_run_heartbeat` mascara secrets) | Mesmo princípio, regex diferente |

---

## 6. Decisões abertas (resolver no PR / refino)

1. **Rate-limit do `enqueue_task` de `athena-trajectory-ingest`** — cron horário gera 1 task/hora. OK pra MVP. Se virar daily summary depois, repensar
2. **Granularidade do bucket key:** `YYYY-MM-DD/HH.jsonl` ou `YYYY-MM-DD/HH_<runtime_instance>.jsonl`? Pra MVP single-instance, primeira opção
3. **Schema interno do trajectory** — propor `dataclass TrajectoryRecord` no `trajectory_ingest.py` com campos canônicos
4. **O que fazer se `[TASK_ID: ...]` não estiver no prompt** (caso onde alguém chamou `/api/nous-hermes/exec` direto, sem passar por adapter)? Salvar com `task_id=NULL`, fonte `external_api`
5. **Cron Hermes vai escrever em `/root/.hermes/cron.log` dentro do container** — montar volume ou ler via `docker exec` quando precisar debugar?
6. **Encoding do JSONL** — Hermes default UTF-8, mas prompts pt-BR têm acentos. Validar handling em mask_pii.py

---

## 7. Critério de aceite

- ✅ JSONL produzido a cada hora, sem perda entre janelas (validar 24h contínuas sem gap)
- ✅ 100% das sessões originadas via `nous_hermes_agent_client` correlacionadas com `task_id` (zero órfãs com prefixo `[TASK_ID:...]`)
- ✅ Zero PII em colunas de prompt/content (audit manual em sample de 50 rows + grep CNPJ/CPF/telefone)
- ✅ Athena HR gera primeira `athena_recommendations.source='trajectory_ingest'` em < 7 dias de operação contínua
- ✅ Custo Storage projetado < $5/mo para volume estimado (validar com 24h reais antes do PR final)

---

## 8. Verification (após implementação)

```powershell
# 1. Disparar 5 execuções via /api/nous-hermes/exec (após F3 do PRD principal)
foreach ($i in 1..5) {
  Invoke-RestMethod -Method POST -Uri "http://localhost:3100/api/nous-hermes/exec" `
    -Headers @{ Authorization = "Bearer $token" } `
    -ContentType "application/json" `
    -Body "{`"prompt`":`"Teste $i: liste 3 cidades brasileiras`"}"
}

# 2. Forçar cron tick (dev)
docker compose exec nous-hermes-runtime /cron.sh
docker compose exec nous-hermes-runtime cat /tmp/test.jsonl | head -5

# 3. Verificar upload no bucket
supabase storage list hermes-trajectories/$(Get-Date -Format "yyyy-MM-dd")/

# 4. Disparar task athena-trajectory-ingest manual
$bucketKey = "hermes-trajectories/2026-05-17/14.jsonl"
Invoke-RestMethod -Method POST -Uri "http://localhost:3100/api/tasks" `
  -Headers @{ Authorization = "Bearer $token" } `
  -ContentType "application/json" `
  -Body @{ operation_type="athena-trajectory-ingest"; payload=@{ bucket_key=$bucketKey } } | ConvertTo-Json

# 5. Verificar ingestão
$query = @"
SELECT agent_id, model, runtime_source, count(*)
FROM vectraclip.agent_prompt_history
WHERE runtime_source='nous_hermes'
GROUP BY 1,2,3 ORDER BY 4 DESC;
"@
# (via psql / Supabase SQL Editor)

# 6. Verificar PII em sample
$auditQuery = @"
SELECT id, prompt_excerpt, content_excerpt
FROM vectraclip.agent_prompt_history
WHERE runtime_source='nous_hermes'
ORDER BY created_at DESC LIMIT 50;
"@
# grep manual: CNPJ pattern (\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}), CPF, email, telefone

# 7. Aguardar 7 dias → verificar recomendação Athena
$recQuery = @"
SELECT * FROM vectraclip.athena_recommendations
WHERE source='trajectory_ingest'
ORDER BY created_at DESC LIMIT 5;
"@
```

---

## 9. Riscos e dívidas técnicas

1. **Volume inicial baixo bloqueia recomendação** — Athena HR precisa de evidência estatística. Em smoke (< 10 execuções), nenhuma `recommendation` válida. Comunicar: "primeira recomendação em < 7 dias de operação contínua" depende de volume real
2. **Hermes runtime single-instance hoje** — se escalar pra N instances (Fase 4 do PRD principal: 1 per company), cron pode rodar N vezes e duplicar uploads. Solução futura: cron centralizado (Kronos) ou lock distribuído
3. **Mascaramento de PII é blocker de LGPD** — não shippar Fase 5.1 sem validação manual de PII em 50+ samples reais. **Se algum CNPJ escapar, é incidente**
4. **`[TASK_ID:...]` no prompt vaza pro modelo** — pode confundir Hermes ("o que é esse UUID?"). Mitigação: prompt-engineering no system message do Hermes ignorando linhas com prefixo `[TASK_ID:`
5. **Hermes pode escolher chamar tools de forma diferente** — trajectory mostra como Hermes "pensa", não como daemon nativo pensa. Comparações `model='hermes-4'` vs `model='claude-sonnet-4-6'` precisam normalizar por `success_rate` e `latency`, não por contagem bruta de tool calls
6. **Sem deduplicação** entre cron ticks — se cron roda 14:00 com `--since 1h`, e 15:00 com `--since 1h`, sessões na borda podem aparecer 2x. Solução: usar `trajectory_session_id` como unique key no upsert

---

## 10. Fase 5.2 (deferida) — Expansão multi-provider

Capturar trajectories de:
- ✅ Anthropic — **já existe** via `router._emit_run_heartbeat`. Só padronizar shape pra match com `agent_prompt_history` extendido
- ❌ Gemini — gap. Wrapper em `src/services/gemini_interactions.py` precisa instrumentar tool calls + latency
- ❌ Ollama — gap. Wrapper em `src/managed_agents/ollama_agent_client.py` precisa expor `ExecutionResult.tokens_per_second` real (hoje é eval-only)
- ❌ HuggingFace — gap similar a Ollama

**Quando entra:** após F5.1 mostrar valor (Athena gerar pelo menos 1 recomendação acionada). Vira PRD próprio.

---

## 11. Glossário

- **Trajectory:** sequência completa de uma execução de agente (prompt → tool calls → tool results → next prompt → ... → final answer). Hermes-Nous exporta como JSONL com um record por sessão
- **Session:** unidade de conversação Hermes — 1 prompt user + N turns do agente até resposta final
- **`agent_prompt_history`:** tabela existente (`20260511201200`) que registra cada execução de daemon Anthropic. Este PRD a estende
- **`athena_recommendations`:** tabela existente (`20260511201201`) — saída agregada do Athena HR (downgrade, upgrade, migrate_runtime, tune_thinking_budget)
- **PII (Personally Identifiable Information):** CNPJ, CPF, telefone, email, endereço — sensíveis sob LGPD

---

## 12. Anexos

- Plano de execução interno: `~/.claude/plans/graceful-sparking-flamingo.md`
- Memória relacionada: `project_athena_hr_telemetry_optimization.md`
- PRD principal: `docs/PRD-NOUS-HERMES-INTEGRATION.md`
- Hermes sessions export docs: https://hermes-agent.nousresearch.com/docs/reference/cli-commands (seção "Session Export & Trajectory")
