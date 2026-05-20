-- S3-A (PRD Skills Library v2 §3.3) — governance columns on agent_specialties.
-- Additive only: no RLS/policy changes; existing rows backfill via DEFAULT.
--
-- AUDIT BEFORE (run manually / document in comment):
-- SELECT count(*), array_agg(slug ORDER BY slug) FROM vectraclip.agent_specialties;
--
-- ESPELHEI ANTES (Regra Ouro #1):
--   vectraclip.agent_specialties: id text PK, slug, name, domain FK, config_schema jsonb,
--   is_active bool. Cross-tenant catalog; RLS select authenticated (remote_schema).

ALTER TABLE vectraclip.agent_specialties
  ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active',
  ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'internal';

ALTER TABLE vectraclip.agent_specialties
  DROP CONSTRAINT IF EXISTS agent_specialties_status_check;

ALTER TABLE vectraclip.agent_specialties
  ADD CONSTRAINT agent_specialties_status_check
    CHECK (status IN ('active', 'deprecated', 'experimental', 'community'));

ALTER TABLE vectraclip.agent_specialties
  DROP CONSTRAINT IF EXISTS agent_specialties_source_check;

ALTER TABLE vectraclip.agent_specialties
  ADD CONSTRAINT agent_specialties_source_check
    CHECK (source IN ('internal', 'import_csv', 'athena', 'skillforge'));

COMMENT ON COLUMN vectraclip.agent_specialties.status IS
  'Governança do catálogo: active | deprecated | experimental | community (S3-A).';

COMMENT ON COLUMN vectraclip.agent_specialties.source IS
  'Origem da specialty: internal | import_csv | athena | skillforge (S3-A).';

-- AUDIT AFTER:
-- SELECT status, source, count(*) FROM vectraclip.agent_specialties GROUP BY 1, 2;
