-- VEC-327: HuggingFace Inference Providers adapter.
-- Espelha o padrão da vec_326 (Ollama). Inclui:
--   1. adapter_catalog (slug 'huggingface', provider 'huggingface') por company.
--   2. adapter_field_definitions: 5 campos (hf_token secret, model_id select->llm_models,
--      provider select com 8 valores, temperature number, max_tokens number) por company.
--   3. llm_models: 7 modelos HF com preços públicos (effective_from 2026-05-06).
--
-- Notas de schema (vs briefing):
--   * adapter_catalog NÃO tem colunas description/sort_order — omitidas.
--   * llm_models usa input_cost_per_1m / output_cost_per_1m / cache_read_cost_per_1m
--     (não _price_) e context_window_k em milhares (não em tokens absolutos).
--   * effective_from (não effective_date). PK composto (id, effective_from).

DO $$
DECLARE
  rec RECORD;
  v_adapter_id UUID;
BEGIN
  FOR rec IN SELECT company_id FROM vectraclip.companies LOOP
    INSERT INTO vectraclip.adapter_catalog (company_id, slug, display_name, provider, is_active)
    VALUES (rec.company_id, 'huggingface', 'HuggingFace Inference', 'huggingface', true)
    ON CONFLICT (company_id, slug) DO NOTHING;

    SELECT id INTO v_adapter_id FROM vectraclip.adapter_catalog
    WHERE company_id = rec.company_id AND slug = 'huggingface';

    INSERT INTO vectraclip.adapter_field_definitions
      (company_id, adapter_id, field_key, field_label, field_type,
       is_required, options_json, sort_order, is_active)
    VALUES
      (rec.company_id, v_adapter_id,
       'hf_token',    'Token HuggingFace (HF_TOKEN)',          'secret', true,
       NULL,                                                            10, true),
      (rec.company_id, v_adapter_id,
       'model_id',    'Modelo',                                'select', true,
       '{"source":"llm_models","provider":"huggingface"}'::jsonb,        20, true),
      (rec.company_id, v_adapter_id,
       'provider',    'Inference Provider (auto = HF roteia)', 'select', false,
       '{"values":["auto","groq","cerebras","together","fireworks","sambanova","novita","deepinfra"]}'::jsonb,
       30, true),
      (rec.company_id, v_adapter_id,
       'temperature', 'Temperature',                           'number', false,
       NULL,                                                            40, true),
      (rec.company_id, v_adapter_id,
       'max_tokens',  'Max tokens',                            'number', false,
       NULL,                                                            50, true)
    ON CONFLICT (company_id, adapter_id, field_key) DO NOTHING;
  END LOOP;
END $$;

-- llm_models é global (sem company_id). PK (id, effective_from).
INSERT INTO vectraclip.llm_models (
  id, provider, display_name,
  input_cost_per_1m, output_cost_per_1m, cache_read_cost_per_1m,
  context_window_k, is_active, effective_from
) VALUES
  ('meta-llama/Llama-3.3-70B-Instruct',  'huggingface', 'Llama 3.3 70B Instruct',  0.59, 0.79, 0.0, 128, true, '2026-05-06'),
  ('meta-llama/Llama-3.1-8B-Instruct',   'huggingface', 'Llama 3.1 8B Instruct',   0.18, 0.18, 0.0, 128, true, '2026-05-06'),
  ('Qwen/Qwen2.5-72B-Instruct',          'huggingface', 'Qwen 2.5 72B Instruct',   0.79, 0.79, 0.0, 131, true, '2026-05-06'),
  ('Qwen/Qwen3-235B-A22B',               'huggingface', 'Qwen3 235B A22B',         0.20, 0.60, 0.0,  41, true, '2026-05-06'),
  ('moonshotai/Kimi-K2-Instruct-0905',   'huggingface', 'Kimi K2 Instruct',        0.60, 2.50, 0.0, 131, true, '2026-05-06'),
  ('deepseek-ai/DeepSeek-R1',            'huggingface', 'DeepSeek R1',             3.00, 8.00, 0.0, 164, true, '2026-05-06'),
  ('mistralai/Mistral-7B-Instruct-v0.3', 'huggingface', 'Mistral 7B Instruct v0.3', 0.20, 0.20, 0.0,  33, true, '2026-05-06')
ON CONFLICT (id, effective_from) DO NOTHING;
