-- Adiciona custo POR-REQUISIÇÃO em `llm_models` para cobrir features cobradas
-- separadamente de tokens (Google Search Grounding, etc.).
--
-- Origem do PR: análise 2026-05-17 do pricing oficial Gemini API
-- (https://ai.google.dev/gemini-api/docs/pricing) revelou que Deep Research
-- NÃO é modelo standalone — é AGENT que cobra:
-- 1. Tokens do modelo base (Gemini 2.5 Pro: $1.25 / $10.00 per 1M)
-- 2. Google Search Grounding: $35/1k commands (Gemini 2.5) após free tier
--    1.500 RPD, ou $14/1k pra Gemini 3 (5k monthly grátis)
--
-- ANTES: helper `src/services/llm_cost.py` calculava só tokens. Tasks
-- oracle-research Deep Research caíam em cost_usd=0.0 (modelo não estava
-- em llm_models). Smoke do PR #189 (Marcelo 2026-05-17) confirmou o gap.
--
-- DEPOIS: nova coluna `per_request_cost_usd` registra custo por chamada de
-- tool/feature. Helper expandido (`calc_llm_cost` recebe `n_requests`)
-- soma tokens × preço + n_requests × per_request_cost.
--
-- Risco operacional: ZERO. ADD COLUMN aditivo com DEFAULT 0 (rows existentes
-- ficam com cost por-request = 0, comportamento atual preservado).

ALTER TABLE vectraclip.llm_models
  ADD COLUMN IF NOT EXISTS per_request_cost_usd NUMERIC(10, 6) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS per_request_unit TEXT;

COMMENT ON COLUMN vectraclip.llm_models.per_request_cost_usd IS
  'Custo USD POR REQUEST de tool/feature (ex: Google Search Grounding $0.035/command). Somado ao cost de tokens em calc_llm_cost(supabase, model_id, tokens, n_requests). Default 0 = cobra só tokens. Catalog-driven (Regra de Ouro #2).';

COMMENT ON COLUMN vectraclip.llm_models.per_request_unit IS
  'Unidade do per_request_cost_usd (ex: "search_command", "tool_call", "image_generation"). Documentação humana — não validado.';

-- Entry pro Deep Research: alias dos preços do Gemini 2.5 Pro +
-- Search Grounding $0.035/search (tier paid Gemini 2.5, após free 1.5k RPD).
-- DEEP_RESEARCH_AGENT em src/services/gemini_interactions.py:8 grava esse id.
INSERT INTO vectraclip.llm_models (
  id, provider, display_name,
  input_cost_per_1m, output_cost_per_1m,
  per_request_cost_usd, per_request_unit,
  context_window_k, effective_from, is_active
) VALUES (
  'deep-research-preview-04-2026',
  'google',
  'Deep Research (Gemini 2.5 Pro + Search Grounding)',
  1.25, 10.00,
  0.035, 'search_command',
  2000, '2026-01-01', true
) ON CONFLICT (id, effective_from) DO NOTHING;

-- Verificação shadow-replay safe
DO $$
DECLARE n_per_request int; n_deep_research int;
BEGIN
  SELECT count(*) INTO n_per_request FROM vectraclip.llm_models WHERE per_request_cost_usd > 0;
  SELECT count(*) INTO n_deep_research FROM vectraclip.llm_models WHERE id = 'deep-research-preview-04-2026';
  RAISE NOTICE 'llm_models: % rows com per_request_cost > 0, % rows pra Deep Research', n_per_request, n_deep_research;
END $$;

NOTIFY pgrst, 'reload schema';
