-- W13.1 — AI Gateway core: tabela llm_api_keys (espelho pattern NAVI ai-gateway)
--
-- Centraliza credenciais de provider LLM com fallback automático por priority.
-- Cada client (anthropic/groq/gemini/huggingface/ollama/openai/...) consulta o
-- gateway pra obter a próxima key ativa. Erros 429/quota/billing → marca
-- status=exhausted automaticamente e tenta próxima.
--
-- Substitui patterns problemáticos atuais:
-- - os.getenv("ANTHROPIC_API_KEY") sem fallback (managed_agent_client.py:51)
-- - os.getenv("GROQ_API_KEY") (groq_agent_client.py:65)
-- - EmbedderChain([Gemini, OpenAI]) hardcoded em mnemos.py:13
-- - 0 fallback automático quando provider retorna 429
--
-- Auditor pré-impl 2026-05-18 — APROVADO COM 5 AJUSTES (todos endereçados):
-- A1: CHECK (provider IN (...)) com 8 slugs LLM-relevantes (excluído github/imap/meta/slack
--     que são integrações de canal, não LLM)
-- A2: CHECK (provider='ollama' OR vault_secret_id IS NOT NULL) — Ollama é local sem auth
-- A3: filtro company_id EXPLÍCITO no service (P1.3 W15.1 — service_role bypassa RLS)
-- A4: contrato Awaitable documentado na docstring do service
-- A5: NULL da vault RPC = erro explícito, não string vazia

CREATE TABLE IF NOT EXISTS vectraclip.llm_api_keys (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES vectraclip.companies(company_id) ON DELETE CASCADE,

  -- Provider — CHECK ENUM (auditor A1: slugs reais do adapter_catalog, sem typo)
  -- 8 providers LLM-relevantes. github/imap/meta/slack ficaram fora — são canais,
  -- não LLM. Pra adicionar provider novo: ALTER CHECK + nova row.
  provider text NOT NULL CHECK (provider IN (
    'anthropic',
    'claude_cli_subscription',
    'google',
    'groq',
    'huggingface',
    'nous_hermes',
    'ollama',
    'openai'
  )),

  -- Model opcional. NULL = key aceita qualquer modelo do provider.
  -- Quando preenchido, deveria casar com llm_models.id (mas FK soft pra
  -- evitar acoplar versão de llm_models.id que é PK composta (id, effective_from)).
  model_id text,

  -- Credencial via vault (Regra Vault SSOT W4/W5). Auditor A2: pode ser NULL
  -- pra Ollama (provider local sem auth) — daí o CHECK condicional abaixo.
  vault_secret_id uuid REFERENCES vault.secrets(id),
  CONSTRAINT vault_required_for_remote_providers CHECK (
    provider = 'ollama' OR vault_secret_id IS NOT NULL
  ),

  -- Priority + status — gateway itera por priority crescente filtrando active
  priority int NOT NULL DEFAULT 100,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'exhausted', 'disabled')),

  -- Diagnostics
  last_error text,
  exhausted_at timestamptz,
  last_used_at timestamptz,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,

  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Unique (company, provider, model_id, priority) — evita 2 keys mesma posição.
-- COALESCE pra tratar model_id NULL como "wildcard slot".
CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_api_keys_priority
  ON vectraclip.llm_api_keys (company_id, provider, COALESCE(model_id, ''), priority);

-- Index pra lookup do gateway (hot path)
CREATE INDEX IF NOT EXISTS idx_llm_api_keys_lookup
  ON vectraclip.llm_api_keys (company_id, provider, status, priority)
  WHERE status = 'active';

COMMENT ON TABLE vectraclip.llm_api_keys IS
  'AI Gateway: keys por company+provider+model com fallback automático por priority. Service src/services/ai_gateway.py marca status=exhausted ao detectar 429/quota/billing.';
COMMENT ON COLUMN vectraclip.llm_api_keys.vault_secret_id IS
  'FK pra vault.secrets — credencial cifrada. NULL apenas pra provider=ollama (local sem auth).';
COMMENT ON COLUMN vectraclip.llm_api_keys.model_id IS
  'NULL = key aceita qualquer modelo do provider. Quando preenchido, identifica modelo específico (soft ref a llm_models.id).';
COMMENT ON COLUMN vectraclip.llm_api_keys.priority IS
  'Menor = primeiro tentado. Gateway itera por priority crescente filtrando status=active.';
COMMENT ON COLUMN vectraclip.llm_api_keys.status IS
  'active = elegível; exhausted = atingiu quota (gateway marca auto, reset manual ou via cron W13.5); disabled = admin desativou.';

-- RLS — leitura via company; escrita só service_role (admin endpoints)
ALTER TABLE vectraclip.llm_api_keys ENABLE ROW LEVEL SECURITY;

CREATE POLICY llm_api_keys_read_own_company
  ON vectraclip.llm_api_keys FOR SELECT
  TO authenticated
  USING (
    company_id IN (
      SELECT company_id FROM vectraclip.app_users WHERE id = auth.uid()
    )
  );

DO $$
DECLARE
  count_active int;
BEGIN
  SELECT count(*) INTO count_active FROM vectraclip.llm_api_keys WHERE status = 'active';
  RAISE NOTICE '[W13.1] llm_api_keys created. active rows: %', count_active;
END $$;
