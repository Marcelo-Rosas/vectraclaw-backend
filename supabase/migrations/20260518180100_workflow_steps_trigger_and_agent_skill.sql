-- W15.1 (2/2) — workflow_steps ADD trigger_type + trigger_config + agent_specialty_config_id
--
-- REQUER: migration 20260518180000 já aplicada (insere slug 'realtime' em
-- workflow_trigger_types — necessário pro DEFAULT da coluna trigger_type abaixo
-- passar na FK constraint).
--
-- Refator arquitetural (Marcelo 2026-05-18):
-- 1. trigger sai do AGENTE pro STEP — cada step decide como dispara (realtime/cron/webhook/manual/event)
-- 2. agent_specialty_config_id substitui specialty_slug livre — FK pra combo agente+specialty
--    em agent_specialty_configs (values jsonb carrega operation_types[], model_id, prompt overrides)
--
-- NÃO REMOVE specialty_slug nem current/next/default_operation_type neste PR.
-- Deprecação vai depender de:
--   - W15.2 (frontend canvas refatorado consumir novos campos)
--   - W15.5 (task_factory refator pra derivar op_type via FK)
--
-- workflow_steps tem 0 rows hoje → zero risco de backfill.
-- tasks.workflow_step_id também 0 — zero risco de FK órfã.
--
-- Auditor pré-impl 2026-05-18: APROVADO COM AJUSTES (todos endereçados aqui).

ALTER TABLE vectraclip.workflow_steps
  ADD COLUMN IF NOT EXISTS trigger_type text REFERENCES vectraclip.workflow_trigger_types(slug)
    DEFAULT 'realtime',
  ADD COLUMN IF NOT EXISTS trigger_config jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS agent_specialty_config_id uuid
    REFERENCES vectraclip.agent_specialty_configs(id) ON DELETE SET NULL;

COMMENT ON COLUMN vectraclip.workflow_steps.trigger_type IS
  'Modo de disparo do step. FK pra catalog. Ver vectraclip.workflow_trigger_types para slugs válidos.';
COMMENT ON COLUMN vectraclip.workflow_steps.trigger_config IS
  'Config específica do trigger_type — formato livre jsonb. Ex CRON: {"cron_expression":"0 8 * * *","timezone":"America/Sao_Paulo"}. Ex WEBHOOK: {"webhook_url":"...","secret_ref":"..."}. Ex REALTIME: {} (sem config).';
COMMENT ON COLUMN vectraclip.workflow_steps.agent_specialty_config_id IS
  'FK pra agent_specialty_configs — combo agente+specialty escolhido no canvas. values jsonb embute operation_types[], model_id, prompt overrides, role. Substitui specialty_slug livre quando responsável=Agente. NULL quando responsável=Humano ou Sistema.';

-- Index pra lookup eficiente quando engine W15.4 buscar steps por trigger_type
CREATE INDEX IF NOT EXISTS idx_workflow_steps_trigger_type
  ON vectraclip.workflow_steps (trigger_type)
  WHERE active = true;

-- Index pra lookup por agent_specialty_config (ex: "qual step usa essa skill?")
CREATE INDEX IF NOT EXISTS idx_workflow_steps_agent_specialty_config
  ON vectraclip.workflow_steps (agent_specialty_config_id)
  WHERE agent_specialty_config_id IS NOT NULL;

DO $$
DECLARE
  steps_total int;
  steps_with_trigger int;
BEGIN
  SELECT count(*) INTO steps_total FROM vectraclip.workflow_steps;
  SELECT count(*) INTO steps_with_trigger FROM vectraclip.workflow_steps WHERE trigger_type IS NOT NULL;
  RAISE NOTICE '[W15.1 M2/2] workflow_steps total=%, com trigger_type=% (default realtime)', steps_total, steps_with_trigger;
END $$;
