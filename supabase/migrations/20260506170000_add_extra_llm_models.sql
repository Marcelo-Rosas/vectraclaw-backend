-- VEC: Adiciona 6 modelos HuggingFace + 1 modelo Ollama em vectraclip.llm_models.
-- Padrão herdado de 20260506150000_add_huggingface_adapter.sql:
--   * llm_models é global (sem company_id). PK (id, effective_from).
--   * HF id = slug real do HuggingFace.
--   * Ollama id segue formato llm_<timestamp> e display_name = tag Ollama.
--   * Custos zerados como placeholder (HF Inference Providers não publica
--     pricing público estável; Ollama é self-hosted local).
--   * effective_from = 2026-05-06.

INSERT INTO vectraclip.llm_models (
  id, provider, display_name,
  input_cost_per_1m, output_cost_per_1m, cache_read_cost_per_1m,
  context_window_k, is_active, effective_from
) VALUES
  -- HuggingFace
  ('Qwen/Qwen3-Coder-30B-A3B-Instruct', 'huggingface', 'Qwen3 Coder 30B A3B Instruct', 0.00, 0.00, 0.00, 262,  true, '2026-05-06'),
  ('zai-org/GLM-5.1',                   'huggingface', 'GLM 5.1',                       0.00, 0.00, 0.00, 128,  true, '2026-05-06'),
  ('deepseek-ai/DeepSeek-V4-Pro',       'huggingface', 'DeepSeek V4 Pro',               0.00, 0.00, 0.00, 128,  true, '2026-05-06'),
  ('deepseek-ai/DeepSeek-V4-Flash',     'huggingface', 'DeepSeek V4 Flash',             0.00, 0.00, 0.00, 1000, true, '2026-05-06'),
  ('openai/gpt-oss-20b',                'huggingface', 'GPT OSS 20B',                   0.00, 0.00, 0.00, 128,  true, '2026-05-06'),
  ('openai/gpt-oss-120b',               'huggingface', 'GPT OSS 120B',                  0.00, 0.00, 0.00, 128,  true, '2026-05-06'),
  -- Ollama
  ('llm_1778038900',                    'ollama',      'qwen3:0.6b',                    0.00, 0.00, 0.00, 40,   true, '2026-05-06')
ON CONFLICT (id, effective_from) DO NOTHING;
