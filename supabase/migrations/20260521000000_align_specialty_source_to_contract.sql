-- =============================================================================
-- Bloco A / Migration 1 — alinhar agent_specialties.source ao contrato §2.1
-- =============================================================================
-- ESPELHEI ANTES (Regra #1 / P7):
--   SELECT source, count(*) FROM vectraclip.agent_specialties GROUP BY 1;
--     → internal=30, skillforge=10 (2026-05-20)
--   pg_constraint contype='c' ILIKE '%source%' → NENHUM CHECK existente.
--
-- Contrato CONTRACTS-AGENT-CAPABILITIES.md §2.1: source ∈
--   seed | athena | import_csv | markdown_upload.
-- Backfill ANTES do CHECK (senão a constraint rejeita as linhas legadas):
--   internal → seed ; skillforge → import_csv (decisão Marcelo 2026-05-20).
-- Catálogo agent_specialties continua GLOBAL SSOT (sem company_id — §0).
-- =============================================================================

UPDATE vectraclip.agent_specialties SET source = 'seed'       WHERE source IN ('internal', 'seed');
UPDATE vectraclip.agent_specialties SET source = 'import_csv' WHERE source = 'skillforge';

ALTER TABLE vectraclip.agent_specialties DROP CONSTRAINT IF EXISTS agent_specialties_source_check;
ALTER TABLE vectraclip.agent_specialties
  ADD CONSTRAINT agent_specialties_source_check
  CHECK (source IN ('seed', 'athena', 'import_csv', 'markdown_upload'));
ALTER TABLE vectraclip.agent_specialties ALTER COLUMN source SET DEFAULT 'seed';

DO $$ BEGIN RAISE NOTICE 'agent_specialties.source alinhado ao contrato §2.1'; END $$;

NOTIFY pgrst, 'reload schema';
