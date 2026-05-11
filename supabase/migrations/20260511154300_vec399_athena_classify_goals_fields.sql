-- =============================================================================
-- VEC-399 (VEC-388 PR3) — Athena classify: campos PMOia em vectraclip.goals
-- =============================================================================
-- Adiciona colunas necessárias para o handler `athena-classify` persistir a
-- classificação PMBOK (project vs operation) + confidence + business_case +
-- breakdown SMART em metadata jsonb.
--
-- ⚠️ SEGURANÇA E NÃO-QUEBRA:
-- - `vectraclip.goals` está VAZIA em prod (verificado 2026-05-11 — 0 rows em
--   todas as companies). Logo, ADD COLUMN é instantâneo e SEM table-rewrite.
-- - Todas as colunas são NULLABLE — nenhum INSERT/UPDATE existente é rejeitado.
-- - SEM CHECK constraint, SEM DROP, SEM NOT NULL forçado.
-- - `pmoia_metadata` tem DEFAULT '{}'::jsonb (semântica = "ainda não classificado").
-- - Idempotente via IF NOT EXISTS — rodar 2x não quebra.
-- =============================================================================

ALTER TABLE vectraclip.goals
  ADD COLUMN IF NOT EXISTS kind text;
COMMENT ON COLUMN vectraclip.goals.kind IS
  'PMBOK classification: project | operation | undecided. NULL = ainda não classificado pelo athena-classify.';

ALTER TABLE vectraclip.goals
  ADD COLUMN IF NOT EXISTS confidence numeric;
COMMENT ON COLUMN vectraclip.goals.confidence IS
  'Confiança da classificação em [0..1]. Validado pelo Pydantic no handler. NULL = ainda não classificado.';

ALTER TABLE vectraclip.goals
  ADD COLUMN IF NOT EXISTS business_case_strength text;
COMMENT ON COLUMN vectraclip.goals.business_case_strength IS
  'Avaliação PMBOK do business case: strong | adequate | weak | absent. NULL = ainda não classificado.';

ALTER TABLE vectraclip.goals
  ADD COLUMN IF NOT EXISTS promoted_project_id uuid;
COMMENT ON COLUMN vectraclip.goals.promoted_project_id IS
  'Quando athena-charter (PR4) for criado, recebe o ID do vectraclip.projects gerado a partir deste goal. Hoje NULL — PR3 não preenche.';

ALTER TABLE vectraclip.goals
  ADD COLUMN IF NOT EXISTS pmoia_metadata jsonb NOT NULL DEFAULT '{}'::jsonb;
COMMENT ON COLUMN vectraclip.goals.pmoia_metadata IS
  'Estrutura PMOia adicional: smart_breakdown, classification_rationale, organizational_calibration, citations[]. Empty {} = não classificado.';

ALTER TABLE vectraclip.goals
  ADD COLUMN IF NOT EXISTS classified_at timestamptz;
COMMENT ON COLUMN vectraclip.goals.classified_at IS
  'Timestamp do UPDATE bem-sucedido feito pelo handler athena-classify. NULL = ainda não classificado.';

NOTIFY pgrst, 'reload schema';
