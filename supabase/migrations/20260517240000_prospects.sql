-- Migration: prospects
-- Tabela de leads do produto de prospecção GymSite.
-- Captura CNPJs com CNAE 9313-1/00 (academias) recém-abertos via
-- monitoramento automático do dump mensal da Receita Federal.
--
-- Schema: vectraclip (NUNCA public)
-- Idempotente: CREATE TABLE IF NOT EXISTS + ON CONFLICT DO NOTHING

-- =============================================================================
-- 1. Tabela principal: vectraclip.prospects
-- =============================================================================

CREATE TABLE IF NOT EXISTS "vectraclip"."prospects" (
      "id"                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
      "company_id"        UUID        NOT NULL REFERENCES "vectraclip"."companies"("id") ON DELETE CASCADE,

    -- Dados da Receita Federal
    "cnpj"              TEXT        NOT NULL,
      "razao_social"      TEXT,
      "nome_fantasia"     TEXT,
      "cnae_fiscal"       TEXT        NOT NULL DEFAULT '9313100',
      "cnae_descricao"    TEXT,
      "data_abertura"     DATE,
      "situacao_cadastral" TEXT,       -- ATIVA | INAPTA | SUSPENSA | BAIXADA

    -- Localização
    "logradouro"        TEXT,
      "numero"            TEXT,
      "complemento"       TEXT,
      "bairro"            TEXT,
      "municipio"         TEXT,
      "uf"                CHAR(2),
      "cep"               TEXT,

    -- Contato direto
    "telefone"          TEXT,
      "email"             TEXT,

    -- Dados societários (QSA da Receita)
    "socios"            JSONB       DEFAULT '[]',
      "capital_social"    NUMERIC(15,2),
      "natureza_juridica" TEXT,
      "porte"             TEXT,

    -- Score de qualificação automático
    "score_prospeccao"  SMALLINT    CHECK (score_prospeccao BETWEEN 0 AND 100),
      "score_breakdown"   JSONB       DEFAULT '{}',
      "status"            TEXT        NOT NULL DEFAULT 'COLD'
                                      CHECK (status IN ('HOT', 'WARM', 'COLD', 'CONTACTED', 'CONVERTED', 'DISQUALIFIED')),

    -- Enriquecimento via Oracle
    "oracle_research"   JSONB       DEFAULT '{}',
      "oracle_task_id"    UUID        REFERENCES "vectraclip"."tasks"("id") ON DELETE SET NULL,

    -- Rastreabilidade
    "source"            TEXT        NOT NULL DEFAULT 'cnpj-monitor',
      "source_batch"      TEXT,       -- ex: '2026-05' (mês do dump RFB)
    "dias_aberto"       SMALLINT,   -- calculado no momento da captura

    -- Ações de contato
    "contacted_at"      TIMESTAMPTZ,
      "contacted_via"     TEXT        CHECK (contacted_via IN ('whatsapp', 'email', 'phone', 'other')),
      "contact_notes"     TEXT,

    -- Timestamps
    "captured_at"       TIMESTAMPTZ NOT NULL DEFAULT now(),
      "converted_at"      TIMESTAMPTZ,
      "created_at"        TIMESTAMPTZ NOT NULL DEFAULT now(),
      "updated_at"        TIMESTAMPTZ NOT NULL DEFAULT now()
  );

-- =============================================================================
-- 2. Constraint única: um CNPJ por company
-- =============================================================================

CREATE UNIQUE INDEX IF NOT EXISTS "uq_prospects_cnpj_company"
    ON "vectraclip"."prospects" ("company_id", "cnpj");

-- =============================================================================
-- 3. Índices de performance
-- =============================================================================

CREATE INDEX IF NOT EXISTS "idx_prospects_company_id"
    ON "vectraclip"."prospects" ("company_id");

CREATE INDEX IF NOT EXISTS "idx_prospects_status"
    ON "vectraclip"."prospects" ("company_id", "status");

CREATE INDEX IF NOT EXISTS "idx_prospects_uf_municipio"
    ON "vectraclip"."prospects" ("uf", "municipio");

CREATE INDEX IF NOT EXISTS "idx_prospects_data_abertura"
    ON "vectraclip"."prospects" ("data_abertura" DESC);

CREATE INDEX IF NOT EXISTS "idx_prospects_score"
    ON "vectraclip"."prospects" ("score_prospeccao" DESC)
    WHERE status IN ('HOT', 'WARM');

-- =============================================================================
-- 4. Trigger: atualiza updated_at automaticamente
-- =============================================================================

CREATE OR REPLACE FUNCTION vectraclip.fn_prospects_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = vectraclip
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_prospects_updated_at ON "vectraclip"."prospects";
CREATE TRIGGER trg_prospects_updated_at
    BEFORE UPDATE ON "vectraclip"."prospects"
    FOR EACH ROW EXECUTE FUNCTION vectraclip.fn_prospects_updated_at();

-- =============================================================================
-- 5. RLS — Row Level Security
-- =============================================================================

ALTER TABLE "vectraclip"."prospects" ENABLE ROW LEVEL SECURITY;

-- service_role: acesso total (skill Hermes/Nous, API interna)
DROP POLICY IF EXISTS "prospects_service_role_all" ON "vectraclip"."prospects";
CREATE POLICY "prospects_service_role_all"
    ON "vectraclip"."prospects"
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- authenticated: lê e escreve apenas prospects da sua company
DROP POLICY IF EXISTS "prospects_authenticated_all" ON "vectraclip"."prospects";
CREATE POLICY "prospects_authenticated_all"
    ON "vectraclip"."prospects"
    FOR ALL
    TO authenticated
    USING (
          company_id IN (
              SELECT company_id FROM vectraclip.company_users
              WHERE user_id = auth.uid()
          )
      )
    WITH CHECK (
          company_id IN (
              SELECT company_id FROM vectraclip.company_users
              WHERE user_id = auth.uid()
          )
      );

-- =============================================================================
-- 6. Comentários
-- =============================================================================

COMMENT ON TABLE "vectraclip"."prospects" IS
    'Leads do produto de prospecção GymSite. '
    'Captura CNPJs com CNAE 9313-1/00 (academias) recém-abertos via monitoramento '
    'automático do dump mensal RFB + BrasilAPI. Pipeline: skill Hermes/Nous → '
    'oracle-research → Navi WhatsApp.';

COMMENT ON COLUMN "vectraclip"."prospects"."cnpj"             IS 'CNPJ sem formatação (14 dígitos)';
COMMENT ON COLUMN "vectraclip"."prospects"."score_prospeccao" IS 'Score 0-100: janela_ideal+25, tem_contato+20, capital+15, municipio_target+15, is_matriz+7, simples+8, tem_fantasia+10';
COMMENT ON COLUMN "vectraclip"."prospects"."status"           IS 'HOT>70 / WARM 40-70 / COLD<40 / CONTACTED / CONVERTED / DISQUALIFIED';
COMMENT ON COLUMN "vectraclip"."prospects"."source_batch"     IS 'Mês do dump RFB processado, ex: 2026-05. Permite idempotência ao reprocessar o mesmo dump.';
COMMENT ON COLUMN "vectraclip"."prospects"."socios"           IS 'Array JSONB do QSA da Receita: [{nome, qualificacao, data_entrada_sociedade}]';
COMMENT ON COLUMN "vectraclip"."prospects"."oracle_research"  IS 'Output do handler oracle-research: presença digital, avaliações, redes sociais, site.';
