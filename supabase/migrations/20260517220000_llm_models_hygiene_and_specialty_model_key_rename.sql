-- ESPELHEI ANTES:
--   (1) SELECT id, COUNT(*) FROM llm_models WHERE is_active GROUP BY id HAVING COUNT(*)>1
--       → 4 modelos com versões duplicadas active: gemini-2.0-flash (2),
--       gemini-2.5-flash (2), gemini-2.5-pro (2), llm_1778038864 (3).
--   (2) SELECT count FROM agent_specialty_configs WHERE values ? 'model' AND NOT values ? 'model_id'
--       → 9 rows (Daedalus.bpmn-modeling, Hodos.sp_1777325919, Mercator.freight-quotation,
--       Oracle.{extract,rag,research,summarize,vision}, Plutus.crm-fill).
--   (3) SELECT count FROM agent_specialties WHERE config_schema citing key='model'
--       → 10 schemas (bpmn-modeling, crm-fill, freight-quotation, oracle-extract,
--       oracle-rag, oracle-report, oracle-research, oracle-summarize, oracle-vision,
--       route-cost-calculation).
-- PADRÃO ADOTADO:
--   (1) Versionamento "1 ativa + N histórico inativo" (PR #195 introduziu hygiene
--       similar pra adapter_catalog provider case). max(effective_from) por id fica
--       is_active=true; demais viram is_active=false sem deletar (preserva auditoria).
--   (2) Convenção `model_id` snake_case + sufixo `_id` (FK lógica a llm_models.id) —
--       mesmo padrão de agent_adapter_configs.field_values_json normalizado pela
--       migration 20260517210000_adapter_catalog_hygiene.
--   (3) config_schema é list of {key,type,label,...} (ver
--       MOCK_AGENT_SPECIALTIES em api.py e specialty_resolver.ResolvedSpecialty).
--       jsonb_set por elemento com WHERE key='model'.
--
-- F4 do GSD (PR ampliado) — pré-requisito pra F2 (catalog-drive defaults Python).
-- Resolve 3 itens distintos numa única migration coesa: todos tocam catálogos de
-- modelo e devem ser aplicados juntos pra evitar drift entre data + schema.
--
-- Risco: BAIXO.
--  1. Desativar versions antigas: llm_cost.py:_load_llm_cost já filtra ativa mais
--     recente — sem mudança de comportamento em produção. Auditoria F1 confirmou
--     0 callers referenciando versão específica (effective_from).
--  2. Rename 'model'→'model_id' em values: campo é WRITE-ONLY hoje (auditoria F1
--     confirmou ZERO handlers lêem `_resolved_config.get("model")`). Risco zero.
--  3. Rename 'model'→'model_id' em config_schema: muda o nome do field renderizado
--     pela UI. Próximas escritas via PUT /api/agents/{id}/specialty-config vão usar
--     model_id naturalmente. Rows existentes já normalizadas pelo step 2.

-- 1. Hygiene de versionamento llm_models: desativar versões NÃO-mais-recentes
WITH latest AS (
  SELECT id, MAX(effective_from) AS latest_eff
  FROM vectraclip.llm_models
  WHERE is_active = true
  GROUP BY id
  HAVING COUNT(*) > 1
)
UPDATE vectraclip.llm_models lm
SET is_active = false
FROM latest
WHERE lm.id = latest.id
  AND lm.effective_from <> latest.latest_eff
  AND lm.is_active = true;

-- 2. Backfill agent_specialty_configs.values: renomear key 'model' → 'model_id'
--    Idempotente: NOT values ? 'model_id' garante que não sobrescreve normalização
--    prévia (PR #195 já normalizou agent_adapter_configs do mesmo pattern).
UPDATE vectraclip.agent_specialty_configs
SET values = jsonb_set(values - 'model', '{model_id}', values->'model'),
    updated_at = now()
WHERE values ? 'model' AND NOT (values ? 'model_id');

-- 3. Rename key 'model' → 'model_id' em agent_specialties.config_schema (10 rows)
--    jsonb_array_elements + jsonb_set elemento-por-elemento + jsonb_agg recompõe.
--    WHERE EXISTS evita touch em schemas que já não têm a key (idempotente).
UPDATE vectraclip.agent_specialties
SET config_schema = (
  SELECT jsonb_agg(
    CASE
      WHEN field->>'key' = 'model' THEN jsonb_set(field, '{key}', '"model_id"'::jsonb)
      ELSE field
    END
    ORDER BY ord
  )
  FROM jsonb_array_elements(config_schema) WITH ORDINALITY AS t(field, ord)
)
WHERE config_schema IS NOT NULL
  AND EXISTS (
    SELECT 1 FROM jsonb_array_elements(config_schema) AS field
    WHERE field->>'key' = 'model'
  );

-- Verificação shadow-replay safe
DO $$
DECLARE
  n_active_dups_left  int;
  n_configs_with_model int;
  n_schemas_with_model int;
  n_models_left_active int;
BEGIN
  SELECT COUNT(*) INTO n_active_dups_left FROM (
    SELECT id FROM vectraclip.llm_models WHERE is_active = true GROUP BY id HAVING COUNT(*) > 1
  ) AS dups;

  SELECT COUNT(*) INTO n_configs_with_model
  FROM vectraclip.agent_specialty_configs
  WHERE values ? 'model' AND NOT (values ? 'model_id');

  SELECT COUNT(*) INTO n_schemas_with_model
  FROM vectraclip.agent_specialties
  WHERE config_schema IS NOT NULL
    AND EXISTS (
      SELECT 1 FROM jsonb_array_elements(config_schema) AS f WHERE f->>'key' = 'model'
    );

  SELECT COUNT(*) INTO n_models_left_active
  FROM vectraclip.llm_models WHERE is_active = true;

  RAISE NOTICE 'F4 hygiene: % duplicatas ativas restantes (esperado 0) | % configs com key model (esperado 0) | % schemas com key model (esperado 0) | total modelos ativos: %',
    n_active_dups_left, n_configs_with_model, n_schemas_with_model, n_models_left_active;
END $$;

NOTIFY pgrst, 'reload schema';
