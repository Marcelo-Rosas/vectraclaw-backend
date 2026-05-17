-- ESPELHEI ANTES: SELECT slug, provider FROM adapter_catalog WHERE slug='gemini'
--                 (achei provider='Google' com G maiúsculo; demais usam minúsculo).
--                 SELECT field_values_json FROM agent_adapter_configs WHERE agent_id IN (Oracle, Athena)
--                 (achei field_key='model' em vez de 'model_id' do schema).
--                 SELECT field_key FROM adapter_field_definitions WHERE adapter='gemini'
--                 (achei 'GEMINI_API_KEY' em UPPERCASE, letra morta — gemini_client.py
--                 lê só de env, ignora field_values_json).
-- PADRÃO ADOTADO: convenção da casa — provider em minúsculo (mesmo case usado em
--                 llm_models.provider='google' e PROVIDER_CLIENT_MAP); field_key
--                 em snake_case ('model_id', 'api_key'); secret de plataforma
--                 (Gemini, Anthropic) gerenciado via env, NÃO via field_def.
--
-- Hygiene pós-auditoria hardcode-auditor (PR #194 ampliado). Corrige 3 itens:
--
--   1. adapter_catalog.provider 'Google' → 'google' (case mismatch risk)
--   2. agent_adapter_configs Oracle+Athena: renomeia 'model' → 'model_id'
--      (causa fallback silencioso porque clients buscam config.get('model_id'))
--   3. Remove field_def 'GEMINI_API_KEY' do adapter gemini (letra morta —
--      gemini é key de plataforma como Anthropic, vive em env GEMINI_API_KEY)
--
-- Risco: baixo. Item 1 é UPDATE de 1 linha. Item 2 toca 2 rows e é idempotente
-- (NOT field_values_json ? 'model_id' garante que não sobrescreve valor correto).
-- Item 3 é DELETE de 1 row letra-morta (operador na UI vai parar de ver field
-- confuso).

-- 1. Normaliza case do provider no adapter gemini
UPDATE vectraclip.adapter_catalog
SET provider = 'google', updated_at = now()
WHERE slug = 'gemini' AND provider <> 'google';

-- 2. Backfill agent_adapter_configs: 'model' → 'model_id'
--    Idempotente: só renomeia se 'model_id' ainda não estiver presente.
UPDATE vectraclip.agent_adapter_configs
SET field_values_json = (field_values_json - 'model')
                        || jsonb_build_object('model_id', field_values_json -> 'model'),
    updated_at = now()
WHERE field_values_json ? 'model'
  AND NOT (field_values_json ? 'model_id');

-- 3. Drop field_def 'GEMINI_API_KEY' (letra morta — gemini_client lê só de env).
--    Idempotente via WHERE clause.
DELETE FROM vectraclip.adapter_field_definitions afd
USING vectraclip.adapter_catalog ac
WHERE afd.adapter_id = ac.id
  AND ac.slug = 'gemini'
  AND afd.field_key = 'GEMINI_API_KEY';

-- Verificação shadow-replay safe
DO $$
DECLARE
  n_gemini_googlecase  int;
  n_configs_model      int;
  n_configs_model_id   int;
  n_gemini_apikey_def  int;
BEGIN
  SELECT count(*) INTO n_gemini_googlecase
    FROM vectraclip.adapter_catalog WHERE slug = 'gemini' AND provider = 'google';
  SELECT count(*) INTO n_configs_model
    FROM vectraclip.agent_adapter_configs WHERE field_values_json ? 'model';
  SELECT count(*) INTO n_configs_model_id
    FROM vectraclip.agent_adapter_configs WHERE field_values_json ? 'model_id';
  SELECT count(*) INTO n_gemini_apikey_def
    FROM vectraclip.adapter_field_definitions afd
    JOIN vectraclip.adapter_catalog ac ON ac.id = afd.adapter_id
    WHERE ac.slug = 'gemini' AND afd.field_key = 'GEMINI_API_KEY';
  RAISE NOTICE 'gemini provider googlecase: % (esperado 1) | configs com model: % (esperado 0) | configs com model_id: % (esperado >= 2 — Oracle+Athena+claude_code) | gemini API key field_def: % (esperado 0)',
    n_gemini_googlecase, n_configs_model, n_configs_model_id, n_gemini_apikey_def;
END $$;

NOTIFY pgrst, 'reload schema';
