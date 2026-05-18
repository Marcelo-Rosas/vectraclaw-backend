-- ESPELHEI ANTES (Regra Ouro #1):
--   (1) adapter_catalog: id uuid PK, company_id, slug, display_name, provider,
--       is_active, created_at, updated_at. UNIQUE (company_id, slug).
--   (2) adapter_field_definitions: field_key, field_type, options_json, sort_order.
--   (3) company_adapter_values: field_values_json por (company_id, adapter_id).
--   (4) llm_models: PK (id, effective_from), provider, custos, context_window_k.
--   Padrão: 20260506150000_add_huggingface_adapter.sql,
--            20260518124224_claude_code_cli_adapter.sql.
--
-- Regra Ouro #2: defaults de produto em field_values_json (seed), não em Python.
-- Provider `nous_hermes` alinha agent_client_factory.PROVIDER_CLIENT_MAP.
-- Slug `nous-hermes` (kebab) alinha src/services/nous_hermes.NOUS_HERMES_SLUG.
-- is_active=false até admin ativar em Connectors (feature flag em catálogo).

-- ============================================================================
-- 1. adapter_catalog (1 row por company)
-- ============================================================================
INSERT INTO vectraclip.adapter_catalog
    (company_id, slug, display_name, provider, is_active)
SELECT
    company_id,
    'nous-hermes',
    'Nous Hermes Agent',
    'nous_hermes',
    false
FROM vectraclip.companies
WHERE NOT EXISTS (
    SELECT 1 FROM vectraclip.adapter_catalog ac2
    WHERE ac2.company_id = companies.company_id
      AND ac2.slug = 'nous-hermes'
);

-- ============================================================================
-- 2. adapter_field_definitions
-- ============================================================================
INSERT INTO vectraclip.adapter_field_definitions
    (company_id, adapter_id, field_key, field_label, field_type,
     is_required, options_json, sort_order, is_active)
SELECT
    ac.company_id,
    ac.id,
    fk.field_key,
    fk.field_label,
    fk.field_type,
    fk.is_required,
    fk.options_json::jsonb,
    fk.sort_order,
    true
FROM vectraclip.adapter_catalog ac
CROSS JOIN (VALUES
    ('inference_provider', 'Provider de inferência', 'select', true,
     '{"values":["ollama","openrouter","anthropic"]}', 10),
    ('model_id', 'Modelo (tag Ollama ou ID cloud)', 'text', true, NULL, 20),
    ('api_key', 'API Key (OpenRouter / Anthropic)', 'secret', false, NULL, 30),
    ('approval_mode', 'Modo de aprovação (Hermes CLI)', 'select', true,
     '{"values":["none","smart","auto"]}', 40),
    ('max_turns', 'Max turns', 'text', true, NULL, 50),
    ('ollama_base_url', 'Ollama base URL (sem /v1)', 'text', false, NULL, 60),
    ('system_prompt', 'System prompt (opcional)', 'textarea', false, NULL, 70),
    ('timeout_seconds', 'Timeout execução (segundos)', 'text', true, NULL, 80)
) AS fk(field_key, field_label, field_type, is_required, options_json, sort_order)
WHERE ac.slug = 'nous-hermes'
  AND NOT EXISTS (
      SELECT 1 FROM vectraclip.adapter_field_definitions afd
      WHERE afd.adapter_id = ac.id AND afd.field_key = fk.field_key
  );

-- ============================================================================
-- 3. company_adapter_values — defaults de dev (editáveis na UI W4)
-- ============================================================================
INSERT INTO vectraclip.company_adapter_values
    (company_id, adapter_id, field_values_json, is_active)
SELECT
    ac.company_id,
    ac.id,
    '{
      "inference_provider": "ollama",
      "model_id": "llama3.2",
      "approval_mode": "smart",
      "max_turns": "20",
      "ollama_base_url": "http://host.docker.internal:11434",
      "timeout_seconds": "180"
    }'::jsonb,
    true
FROM vectraclip.adapter_catalog ac
WHERE ac.slug = 'nous-hermes'
  AND NOT EXISTS (
      SELECT 1 FROM vectraclip.company_adapter_values cav
      WHERE cav.company_id = ac.company_id AND cav.adapter_id = ac.id
  );

-- ============================================================================
-- 4. llm_models (referência / UI futura; Ollama usa model_id livre no adapter)
-- ============================================================================
INSERT INTO vectraclip.llm_models (
    id, provider, display_name,
    input_cost_per_1m, output_cost_per_1m, cache_read_cost_per_1m,
    context_window_k, is_active, effective_from
) VALUES
    ('hermes-4', 'nous_hermes', 'Hermes 4', 0.0, 0.0, 0.0, 128, true, '2026-05-18'),
    ('nomos-1', 'nous_hermes', 'Nomos 1', 0.0, 0.0, 0.0, 128, true, '2026-05-18'),
    ('psyche-1', 'nous_hermes', 'Psyche 1', 0.0, 0.0, 0.0, 128, true, '2026-05-18')
ON CONFLICT (id, effective_from) DO NOTHING;

DO $$
DECLARE
    v_adapters int;
    v_fields int;
    v_values int;
BEGIN
    SELECT count(*) INTO v_adapters FROM vectraclip.adapter_catalog
        WHERE slug = 'nous-hermes';
    SELECT count(*) INTO v_fields FROM vectraclip.adapter_field_definitions afd
        JOIN vectraclip.adapter_catalog ac ON ac.id = afd.adapter_id
        WHERE ac.slug = 'nous-hermes';
    SELECT count(*) INTO v_values FROM vectraclip.company_adapter_values cav
        JOIN vectraclip.adapter_catalog ac ON ac.id = cav.adapter_id
        WHERE ac.slug = 'nous-hermes';
    RAISE NOTICE 'nous-hermes: adapters=% fields=% company_values=%',
        v_adapters, v_fields, v_values;
END $$;
