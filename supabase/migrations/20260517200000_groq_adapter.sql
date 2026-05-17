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
-- Regras de Ouro:
--   #1 espelhei shape dos campos do adapter ollama (mesma estrutura
--      OpenAI-compat, mesma assinatura) e huggingface (model_id select
--      apontando pra llm_models WHERE provider=...)
--   #2 NO HARDCODE: api_key vai em agent_adapter_configs.field_values_json
--      OU via env GROQ_API_KEY (fallback no GroqAgentClient)
--
-- Risco: zero. Apenas INSERTs idempotentes (ON CONFLICT DO NOTHING).

-- 1. Adapter no catálogo
INSERT INTO vectraclip.adapter_catalog (id, slug, provider, is_active)
VALUES (
  '7a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d',
  'groq',
  'groq',
  true
) ON CONFLICT (id) DO NOTHING;

-- 2. Field definitions (4 campos)
INSERT INTO vectraclip.adapter_field_definitions (
  id, adapter_id, field_key, field_label, field_type,
  is_required, options_json, sort_order, is_active
) VALUES
  (
    '7a1b2c3d-4e5f-6a7b-8c9d-aaaaaaaaaaaa',
    '7a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d',
    'api_key', 'API Key Groq', 'secret',
    true, NULL, 10, true
  ),
  (
    '7a1b2c3d-4e5f-6a7b-8c9d-bbbbbbbbbbbb',
    '7a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d',
    'model_id', 'Modelo', 'select',
    true,
    jsonb_build_object('source', 'llm_models', 'provider', 'groq'),
    20, true
  ),
  (
    '7a1b2c3d-4e5f-6a7b-8c9d-cccccccccccc',
    '7a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d',
    'temperature', 'Temperature', 'number',
    false, NULL, 30, true
  ),
  (
    '7a1b2c3d-4e5f-6a7b-8c9d-dddddddddddd',
    '7a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d',
    'max_tokens', 'Max tokens', 'number',
    false, NULL, 40, true
  )
ON CONFLICT (id) DO NOTHING;

-- 3. Seed 4 modelos Groq mais usados em llm_models (alimenta o select model_id).
--    Free tier ativo (sem custo) — input/output_cost_per_1m = 0.
--    Fonte: https://console.groq.com/docs/models (2026-05-17)
INSERT INTO vectraclip.llm_models (
  id, provider, display_name,
  input_cost_per_1m, output_cost_per_1m, cache_read_cost_per_1m,
  context_window_k, effective_from, is_active
) VALUES
  ('llama-3.3-70b-versatile', 'groq', 'Llama 3.3 70B (Versatile)',  0, 0, 0, 128, '2024-12-01', true),
  ('llama-3.1-8b-instant',    'groq', 'Llama 3.1 8B (Instant)',     0, 0, 0, 128, '2024-09-01', true),
  ('qwen-2.5-32b',            'groq', 'Qwen 2.5 32B',               0, 0, 0,  32, '2024-12-01', true),
  ('mixtral-8x7b-32768',      'groq', 'Mixtral 8x7B (32k context)', 0, 0, 0,  32, '2024-04-01', true)
ON CONFLICT (id, effective_from) DO NOTHING;

-- Verificação shadow-replay safe
DO $$
DECLARE n_adapter int; n_fields int; n_models int;
BEGIN
  SELECT count(*) INTO n_adapter FROM vectraclip.adapter_catalog WHERE slug = 'groq';
  SELECT count(*) INTO n_fields FROM vectraclip.adapter_field_definitions WHERE adapter_id = '7a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d';
  SELECT count(*) INTO n_models FROM vectraclip.llm_models WHERE provider = 'groq';
  RAISE NOTICE 'groq adapter: % rows in catalog, % field defs, % models', n_adapter, n_fields, n_models;
END $$;

NOTIFY pgrst, 'reload schema';
