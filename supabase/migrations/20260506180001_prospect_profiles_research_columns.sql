-- =============================================================================
-- VEC-XXX — prospect_profiles: colunas para pesquisa Oracle
-- Adiciona campos de classificação, URLs adicionais, snapshot do BrasilAPI,
-- vínculo com research_templates, status/progress da pesquisa e cron.
-- =============================================================================

ALTER TABLE vectraclip.prospect_profiles
    ADD COLUMN IF NOT EXISTS tipo                 text,
    ADD COLUMN IF NOT EXISTS linkedin_url         text,
    ADD COLUMN IF NOT EXISTS instagram_handle     text,
    ADD COLUMN IF NOT EXISTS extra_urls           jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS cnpj_lookup_data     jsonb,
    ADD COLUMN IF NOT EXISTS qsa                  jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS research_template_id uuid REFERENCES vectraclip.research_templates(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS research_status      text NOT NULL DEFAULT 'idle',
    ADD COLUMN IF NOT EXISTS research_progress    jsonb,
    ADD COLUMN IF NOT EXISTS research_cron_expr   text,
    ADD COLUMN IF NOT EXISTS next_research_at     timestamp with time zone,
    ADD COLUMN IF NOT EXISTS last_research_at     timestamp with time zone;

-- Constraint de domínio em research_status
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'prospect_profiles_research_status_check'
    ) THEN
        ALTER TABLE vectraclip.prospect_profiles
            ADD CONSTRAINT prospect_profiles_research_status_check
            CHECK (research_status IN ('idle','queued','running','review','done','failed','cancelled'));
    END IF;
END $$;

-- Constraint de domínio em tipo (nullable; quando preenchido, deve estar na lista)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'prospect_profiles_tipo_check'
    ) THEN
        ALTER TABLE vectraclip.prospect_profiles
            ADD CONSTRAINT prospect_profiles_tipo_check
            CHECK (tipo IS NULL OR tipo IN ('transportadora','embarcador','concorrente','outro'));
    END IF;
END $$;

COMMENT ON COLUMN vectraclip.prospect_profiles.tipo                 IS 'Classificação: transportadora | embarcador | concorrente | outro';
COMMENT ON COLUMN vectraclip.prospect_profiles.linkedin_url         IS 'URL completa /company/<handle> ou handle puro (normalizado no app)';
COMMENT ON COLUMN vectraclip.prospect_profiles.instagram_handle     IS 'Handle Instagram (com ou sem @, normalizado no app)';
COMMENT ON COLUMN vectraclip.prospect_profiles.extra_urls           IS 'Array dinâmico [{label,url}] para fontes adicionais (ad library, posts, articles, etc)';
COMMENT ON COLUMN vectraclip.prospect_profiles.cnpj_lookup_data     IS 'Snapshot bruto da BrasilAPI (CnpjLookupResult) para auditoria e re-uso';
COMMENT ON COLUMN vectraclip.prospect_profiles.qsa                  IS 'Sócios/representantes (QSA) extraídos do BrasilAPI — candidatos a decisor';
COMMENT ON COLUMN vectraclip.prospect_profiles.research_status      IS 'idle | queued | running | review | done | failed | cancelled';
COMMENT ON COLUMN vectraclip.prospect_profiles.research_progress    IS 'JSON: {step, total, message, eta_sec, fontes_lidas}';
COMMENT ON COLUMN vectraclip.prospect_profiles.research_cron_expr   IS 'Expressão cron 5 campos (m h dom mon dow), ex: "0 8 * * 1" para semanal segunda 8h';
COMMENT ON COLUMN vectraclip.prospect_profiles.next_research_at     IS 'Próxima execução agendada (varrida pelo worker cron)';
COMMENT ON COLUMN vectraclip.prospect_profiles.last_research_at     IS 'Última execução concluída (done ou failed)';

-- Index parcial para o worker cron
CREATE INDEX IF NOT EXISTS idx_prospect_profiles_next_research
    ON vectraclip.prospect_profiles (next_research_at)
    WHERE next_research_at IS NOT NULL
      AND research_status NOT IN ('running','queued');

-- Index para lookup por status (UI de fila)
CREATE INDEX IF NOT EXISTS idx_prospect_profiles_research_status
    ON vectraclip.prospect_profiles (company_id, research_status)
    WHERE research_status NOT IN ('idle','done');
