-- PR0b — Backfill agent_specialty_configs.values.operation_types pra Daedalus
--
-- Auditor quíntuplo 2026-05-18:
--   - 9 dos 13 agent_specialty_configs em prod estão com values.operation_types=NULL
--   - Athena é a única com array preenchido (8 op_types em oracle-rag)
--   - Daedalus tem values={"model_id","max_nodes","auto_layout"} sem op_types
--
-- Implicação atual: dispatch agent_daemon.py:573-583 hardcoded por prefix
-- (if op_type.startswith("bpmn-")) FUNCIONA porque cobre o caso, mas pattern
-- catalog-driven (lookup specialty por operation_type) falha — values.operation_types
-- é NULL → JOIN/WHERE retorna vazio.
--
-- Este PR0b habilita o pattern catalog-driven prepara PR0d (refactor dispatch
-- agent_daemon pra lookup dinâmico via agent_specialty_configs).
--
-- Roadmap completo dos 3 op_types da especialidade bpmn-modeling do Daedalus:
--   - bpmn-generate (existe no catalog HOJE — primary_agent = Daedalus)
--   - sipoc-to-bpmn (proposto PR6 — Daedalus dispara automático após SIPOC aprovado)
--   - bpmn-approved-to-workflow (proposto PR6 — board aprovou BPMN → gera workflow_steps)
--
-- Decisão: incluir os 3 desde já pra não precisar nova migration quando PR6 entrar.

UPDATE vectraclip.agent_specialty_configs
SET values = jsonb_set(
    values,
    '{operation_types}',
    '["bpmn-generate", "sipoc-to-bpmn", "bpmn-approved-to-workflow"]'::jsonb,
    true  -- create_missing
),
    updated_at = now()
WHERE agent_id = 'd4ed4145-0000-4000-8000-000000000005'
  AND specialty_id = 'bpmn-modeling';

-- Verificação shadow-replay-safe (pattern cravado PR #222 hotfix)
DO $$
DECLARE
    v_daedalus_exists int;
    v_op_types_set int;
    v_op_types_count int;
BEGIN
    SELECT count(*) INTO v_daedalus_exists FROM vectraclip.agents
        WHERE id = 'd4ed4145-0000-4000-8000-000000000005';
    SELECT count(*) INTO v_op_types_set FROM vectraclip.agent_specialty_configs
        WHERE agent_id = 'd4ed4145-0000-4000-8000-000000000005'
          AND specialty_id = 'bpmn-modeling'
          AND values ? 'operation_types';
    SELECT COALESCE(jsonb_array_length(values->'operation_types'), 0)
        INTO v_op_types_count
    FROM vectraclip.agent_specialty_configs
    WHERE agent_id = 'd4ed4145-0000-4000-8000-000000000005'
      AND specialty_id = 'bpmn-modeling'
    LIMIT 1;
    RAISE NOTICE 'PR0b Daedalus backfill: agent_exists=%, op_types_set=%, count=%',
        v_daedalus_exists, v_op_types_set, v_op_types_count;
    -- Assert condicional: só falha se Daedalus EXISTIA + config existia
    -- mas backfill não funcionou (count=0 inesperado)
    IF v_daedalus_exists > 0 AND v_op_types_set > 0 AND v_op_types_count = 0 THEN
        RAISE EXCEPTION 'PR0b: Daedalus + config existem mas operation_types ficou vazio';
    END IF;
END $$;

NOTIFY pgrst, 'reload schema';
