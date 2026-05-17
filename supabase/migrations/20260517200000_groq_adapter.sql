-- ESPELHEI ANTES: SELECT shape em vectraclip.adapter_catalog (PK id, NOT NULL
--                 company_id+slug+display_name+provider+is_active, UNIQUE
--                 (company_id, slug)) e em adapter_field_definitions (PK id,
--                 NOT NULL company_id+adapter_id+field_key+..., FK composta
--                 (company_id, adapter_id) -> adapter_catalog(company_id, id),
--                 UNIQUE (company_id, adapter_id, field_key)).
-- PADRÃO ADOTADO: loop por companies (mesmo que migrations
--                 20260506150000_add_huggingface_adapter.sql) — adapter por
--                 company, gen_random_uuid() por (company, slug). Field defs
--                 espelham adapter ollama (base_url text req, model_id select).
--
-- Adiciona adapter `groq` (per-company) + HF base_url field_def (per-company)
-- + supports_tool_calling em llm_models (global, sem company_id).
--
-- Origem: 2026-05-17 — Marcelo trouxe API key Groq direta. Em paralelo ao
-- HuggingFaceAgentClient (que roteia pra Groq via HF Router), este adapter
-- chama Groq direto. Vantagem: menos hop, ~30% mais rápido (smoke: 0.55s
-- direto vs 0.82s via HF Router).
-- Adiciona adapter `groq` ao catálogo, com field_definitions pra UI editar
-- config (api_key, model_id, temperature, max_tokens) + seed 4 modelos Groq
-- populares em llm_models pra alimentar o select de model_id.
--
-- Origem: 2026-05-17 — Marcelo trouxe API key Groq direta. Em paralelo ao
-- HuggingFaceAgentClient (que roteia pra Groq via HF Router), este adapter
-- chama Groq direto (https://api.groq.com/openai/v1). Vantagem: menos hop,
-- ~30% mais rápido (smoke: 0.55s direto vs 0.82s via HF Router).
--
-- Cliente Python: src/managed_agents/groq_agent_client.py (registrado em
-- PROVIDER_CLIENT_MAP['groq'] do factory).
--
-- Regra de Ouro #2 (NO HARDCODE — 2 violações pegas hoje, ver
-- docs/CODE-PATTERNS.md §P1 "Caso real 2026-05-17"):
--   - URL do provider → adapter_field_definitions.base_url (não GROQ_BASE_URL)
--   - Capacidades modelo (tool calling) → llm_models.supports_tool_calling
--     (não GROQ_TOOL_CAPABLE_MODELS set)
--
-- Risco: zero. Idempotente via ON CONFLICT (company_id, slug) e
--        ON CONFLICT (company_id, adapter_id, field_key).

-- 1. Adapter Groq + field_definitions, por company (mesmo pattern do HF adapter).
DO $$
DECLARE
  c           RECORD;
  adapter_uid uuid;
BEGIN
  FOR c IN SELECT company_id FROM vectraclip.companies LOOP
    -- INSERT idempotente — se já existe, recupera id via SELECT (não DO UPDATE,
    -- pra preservar id pré-existente referenciado por agent_adapter_configs).
    INSERT INTO vectraclip.adapter_catalog
      (id, company_id, slug, display_name, provider, is_active)
    VALUES
      (gen_random_uuid(), c.company_id, 'groq', 'Groq Cloud', 'groq', true)
    ON CONFLICT (company_id, slug) DO NOTHING;

    SELECT id INTO adapter_uid
      FROM vectraclip.adapter_catalog
      WHERE company_id = c.company_id AND slug = 'groq';

    -- 5 field defs: base_url (espelha ollama, sort_order=5 antes do api_key),
    -- api_key, model_id, temperature, max_tokens.
    INSERT INTO vectraclip.adapter_field_definitions
      (id, company_id, adapter_id, field_key, field_label, field_type,
       is_required, options_json, sort_order, is_active)
    VALUES
      (gen_random_uuid(), c.company_id, adapter_uid, 'base_url',
       'URL do endpoint Groq', 'text', true,
       jsonb_build_object('default', 'https://api.groq.com/openai/v1'),
       5, true),
      (gen_random_uuid(), c.company_id, adapter_uid, 'api_key',
       'API Key Groq', 'secret', true, NULL, 10, true),
      (gen_random_uuid(), c.company_id, adapter_uid, 'model_id',
       'Modelo', 'select', true,
       jsonb_build_object('source', 'llm_models', 'provider', 'groq'),
       20, true),
      (gen_random_uuid(), c.company_id, adapter_uid, 'temperature',
       'Temperature', 'number', false, NULL, 30, true),
      (gen_random_uuid(), c.company_id, adapter_uid, 'max_tokens',
       'Max tokens', 'number', false, NULL, 40, true)
    ON CONFLICT (company_id, adapter_id, field_key) DO NOTHING;
  END LOOP;
END $$;

-- 2. base_url field_def para HuggingFace (que tinha HF_BASE_URL hardcoded
--    no Python). Loop por company, espelhando pattern do step 1.
DO $$
DECLARE
  c              RECORD;
  hf_adapter_uid uuid;
BEGIN
  FOR c IN SELECT company_id FROM vectraclip.companies LOOP
    SELECT id INTO hf_adapter_uid
      FROM vectraclip.adapter_catalog
      WHERE company_id = c.company_id AND slug = 'huggingface';

    -- Pula companies sem adapter HF (futuras adições do HF preenchem por aqui).
    IF hf_adapter_uid IS NOT NULL THEN
      INSERT INTO vectraclip.adapter_field_definitions
        (id, company_id, adapter_id, field_key, field_label, field_type,
         is_required, options_json, sort_order, is_active)
      VALUES
        (gen_random_uuid(), c.company_id, hf_adapter_uid, 'base_url',
         'URL do roteador HuggingFace', 'text', true,
         jsonb_build_object('default', 'https://router.huggingface.co/v1'),
         5, true)
      ON CONFLICT (company_id, adapter_id, field_key) DO NOTHING;
    END IF;
  END LOOP;
END $$;

-- 3. supports_tool_calling em llm_models (substitui sets HARDCODED
--    OLLAMA_TOOL_CAPABLE_MODELS, HF_TOOL_CAPABLE_MODELS, GROQ_TOOL_CAPABLE_MODELS).
--    llm_models é GLOBAL (sem company_id) — uma única coluna serve todos.
ALTER TABLE vectraclip.llm_models
  ADD COLUMN IF NOT EXISTS supports_tool_calling BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN vectraclip.llm_models.supports_tool_calling IS
  'Modelo suporta tool/function calling. TRUE default (LLMs instruct modernos). FALSE em guards/embeddings/legados. Lido por src.services.llm_cost.is_tool_capable() — substitui constantes hardcoded por client (PR #194).';

-- 4. Rate limits em llm_models (Free tier Groq/Gemini/OpenRouter).
ALTER TABLE vectraclip.llm_models
  ADD COLUMN IF NOT EXISTS rate_limit_req_per_min INTEGER,
  ADD COLUMN IF NOT EXISTS rate_limit_req_per_day INTEGER,
  ADD COLUMN IF NOT EXISTS rate_limit_tok_per_min INTEGER,
  ADD COLUMN IF NOT EXISTS rate_limit_tok_per_day INTEGER;

COMMENT ON COLUMN vectraclip.llm_models.rate_limit_req_per_min IS
  'Free tier: máximo de requests por minuto. NULL = sem limite documentado ou paid tier sem cap.';
COMMENT ON COLUMN vectraclip.llm_models.rate_limit_req_per_day IS
  'Free tier: máximo de requests por dia.';
COMMENT ON COLUMN vectraclip.llm_models.rate_limit_tok_per_min IS
  'Free tier: máximo de tokens (input+output) por minuto.';
COMMENT ON COLUMN vectraclip.llm_models.rate_limit_tok_per_day IS
  'Free tier: máximo de tokens por dia.';

-- 5. Seed modelos Groq (catálogo global). Free tier: input/output/cache_read = 0.
--    Fonte: console.groq.com/dashboard/limits + console.groq.com/docs/models
INSERT INTO vectraclip.llm_models (
  id, provider, display_name,
  input_cost_per_1m, output_cost_per_1m, cache_read_cost_per_1m,
  context_window_k, effective_from, is_active,
  rate_limit_req_per_min, rate_limit_req_per_day,
  rate_limit_tok_per_min, rate_limit_tok_per_day
) VALUES
  -- Production tier
  ('llama-3.3-70b-versatile',                  'groq', 'Llama 3.3 70B (Versatile)',        0, 0, 0, 128, '2024-12-05', true,
    30,  1000, 12000, 100000),
  ('llama-3.1-8b-instant',                     'groq', 'Llama 3.1 8B (Instant)',           0, 0, 0, 128, '2024-09-03', true,
    30, 14400,  6000, 500000),
  -- Preview tier — pode mudar/sair sem aviso
  ('meta-llama/llama-4-scout-17b-16e-instruct','groq', 'Llama 4 Scout 17B 16E (preview)',  0, 0, 0, 131, '2026-04-05', true,
    30,  1000, 30000, 500000),
  ('meta-llama/llama-prompt-guard-2-22m',      'groq', 'Llama Prompt Guard 2 22M (guard)', 0, 0, 0,   2, '2026-05-30', true,
    30, 14400, 15000, 500000),
  ('meta-llama/llama-prompt-guard-2-86m',      'groq', 'Llama Prompt Guard 2 86M (guard)', 0, 0, 0,   2, '2026-05-30', true,
    30, 14400, 15000, 500000),
  -- Legados
  ('qwen-2.5-32b',                             'groq', 'Qwen 2.5 32B',                     0, 0, 0,  32, '2024-12-01', true,
    NULL, NULL, NULL, NULL),
  ('mixtral-8x7b-32768',                       'groq', 'Mixtral 8x7B (32k context)',       0, 0, 0,  32, '2024-04-01', true,
    NULL, NULL, NULL, NULL)
ON CONFLICT (id, effective_from) DO NOTHING;

-- 6. Backfill supports_tool_calling=false em guards/embeddings sem function calling.
UPDATE vectraclip.llm_models
SET supports_tool_calling = false
WHERE id IN (
  'meta-llama/llama-prompt-guard-2-22m',
  'meta-llama/llama-prompt-guard-2-86m'
);

-- Verificação shadow-replay safe
DO $$
DECLARE
  n_companies     int;
  n_groq_adapters int;
  n_groq_fields   int;
  n_hf_base_url   int;
  n_models        int;
  n_with_limits   int;
  n_guards        int;
BEGIN
  SELECT count(*) INTO n_companies     FROM vectraclip.companies;
  SELECT count(*) INTO n_groq_adapters FROM vectraclip.adapter_catalog WHERE slug = 'groq';
  SELECT count(*) INTO n_groq_fields
    FROM vectraclip.adapter_field_definitions afd
    JOIN vectraclip.adapter_catalog ac ON ac.id = afd.adapter_id
    WHERE ac.slug = 'groq';
  SELECT count(*) INTO n_hf_base_url
    FROM vectraclip.adapter_field_definitions afd
    JOIN vectraclip.adapter_catalog ac ON ac.id = afd.adapter_id
    WHERE ac.slug = 'huggingface' AND afd.field_key = 'base_url';
  SELECT count(*) INTO n_models        FROM vectraclip.llm_models WHERE provider = 'groq';
  SELECT count(*) INTO n_with_limits   FROM vectraclip.llm_models WHERE provider = 'groq' AND rate_limit_req_per_day IS NOT NULL;
  SELECT count(*) INTO n_guards        FROM vectraclip.llm_models WHERE supports_tool_calling = false;
  RAISE NOTICE 'companies: % | groq adapters: % (esperado %) | groq fields: % (esperado % = 5 * %) | HF base_url defs: % (esperado <= %) | models groq: % (% c/limits) | guards no-tool: % (esperado >= 2)',
    n_companies, n_groq_adapters, n_companies,
    n_groq_fields, (5 * n_companies), n_companies,
    n_hf_base_url, n_companies,
    n_models, n_with_limits, n_guards;
END $$;

NOTIFY pgrst, 'reload schema';
