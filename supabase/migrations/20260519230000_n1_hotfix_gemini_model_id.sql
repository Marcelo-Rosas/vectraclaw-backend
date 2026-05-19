-- N1 Hotfix: Oracle agent_adapter_configs row Gemini com model_id=null
-- desde W3 (PR #84 #181). Athena foi populada em algum PR posterior, Oracle
-- ficou. Em runtime o GeminiClient falha silenciosamente (None passa pro
-- google-genai SDK que retorna 400 vazio) e cai no fallback HuggingFace.
--
-- ESPELHEI ANTES (Regra #1):
--   SELECT em vectraclip.agent_adapter_configs WHERE adapter='gemini' →
--   2 rows: Oracle ({"model_id":null}) BROKEN, Athena ({"model_id":"gemini-2.5-pro"}) OK
--   Match: setar Oracle igual Athena pra paridade.
--
-- Aplicação:
--   1. UPDATE field_values_json populando model_id='gemini-2.5-pro' SE NULL

UPDATE vectraclip.agent_adapter_configs
SET field_values_json = jsonb_set(
  field_values_json,
  '{model_id}',
  '"gemini-2.5-pro"'::jsonb,
  true
)
WHERE adapter_id = (SELECT id FROM vectraclip.adapter_catalog WHERE slug = 'gemini')
  AND (field_values_json->>'model_id') IS NULL;
