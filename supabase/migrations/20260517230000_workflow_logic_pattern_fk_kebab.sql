-- ESPELHEI ANTES:
--   (1) SELECT pg_get_constraintdef WHERE conname='workflow_steps_logic_pattern_check'
--       → CHECK SCREAMING (SIMPLE, SPLIT, MERGE, LOOP-FOR-EACH, LOOP-WHILE,
--       WAIT-EVENT, WAIT-TIME, SUBFLOW, ERROR-HANDLER, FORCE-FAIL, MANUAL).
--   (2) SELECT id FROM workflow_logic_patterns
--       → 8 rows kebab (error-handler, loop-batch, merge-by-key, simple,
--       split-if, split-switch, subflow, wait-event).
--   (3) SELECT count FROM workflow_steps WHERE logic_pattern ~ ...
--       → 0 rows com SCREAMING ou kebab (coluna vazia, sem backfill necessário).
-- PADRÃO ADOTADO: Catalog kebab vence (Marcelo aprovou em 2026-05-17 — banco/
--   catalog é fonte da verdade). Drop CHECK SCREAMING (vocabulário divergente
--   vs catalog refinado). FK pra workflow_logic_patterns.id (catalog kebab).
--
-- Wave 1A — AUDIT-002 do PRD-CONTRATOS (resolve INSERT 500 quando frontend
-- consome catalog kebab via API mas CHECK exige SCREAMING).
--
-- Conflito vocabulário identificado:
--   CHECK    `LOOP-FOR-EACH, LOOP-WHILE`            (2 distintos)
--   Catalog  `loop-batch`                            (1 unificado)
--   CHECK    `SPLIT`                                 (genérico)
--   Catalog  `split-if, split-switch`                (refinado)
--   CHECK    `MERGE`                                 (genérico)
--   Catalog  `merge-by-key`                          (refinado)
--   CHECK    `WAIT-TIME, FORCE-FAIL, MANUAL`         (sem equivalente catalog)
--   Catalog  só `wait-event`                          (subset)
--
-- Decisão: catalog kebab é a fonte da verdade DAQUI PRA FRENTE. CHECK era de
-- design anterior, kebab refletiu evolução. Se algum dia precisar `WAIT-TIME`
-- ou outros, INSERT em workflow_logic_patterns + FK aceita.
--
-- Risco: BAIXO. 0 rows afetadas (coluna vazia). Code que tente INSERT/UPDATE
-- com SCREAMING pós-migration vai dar FK violation com mensagem clara.

-- 1. Drop CHECK SCREAMING (era violação Regra Ouro #2 — duplicava catalog).
ALTER TABLE vectraclip.workflow_steps
  DROP CONSTRAINT IF EXISTS workflow_steps_logic_pattern_check;

-- 2. Add FK pra workflow_logic_patterns.id (catalog kebab).
--    ON DELETE SET NULL: se catalog row for desativada/removida, step.logic_pattern
--    vira NULL (não bloqueia delete do catalog).
ALTER TABLE vectraclip.workflow_steps
  ADD CONSTRAINT workflow_steps_logic_pattern_fk
  FOREIGN KEY (logic_pattern)
  REFERENCES vectraclip.workflow_logic_patterns(id)
  ON DELETE SET NULL;

-- Verificação shadow-replay safe
DO $$
DECLARE
  n_check_left       int;
  n_fk_created       int;
  n_steps_with_bad_pattern int;
BEGIN
  SELECT count(*) INTO n_check_left
  FROM pg_constraint
  WHERE conrelid = 'vectraclip.workflow_steps'::regclass
    AND conname = 'workflow_steps_logic_pattern_check';

  SELECT count(*) INTO n_fk_created
  FROM pg_constraint
  WHERE conrelid = 'vectraclip.workflow_steps'::regclass
    AND conname = 'workflow_steps_logic_pattern_fk';

  SELECT count(*) INTO n_steps_with_bad_pattern
  FROM vectraclip.workflow_steps ws
  WHERE ws.logic_pattern IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM vectraclip.workflow_logic_patterns wlp
      WHERE wlp.id = ws.logic_pattern
    );

  RAISE NOTICE 'AUDIT-002 hygiene: CHECK SCREAMING removido (esperado 0): % | FK kebab criada (esperado 1): % | steps com logic_pattern inválido (esperado 0): %',
    n_check_left, n_fk_created, n_steps_with_bad_pattern;
END $$;

NOTIFY pgrst, 'reload schema';
