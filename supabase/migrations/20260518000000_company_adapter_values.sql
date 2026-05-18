-- ESPELHEI ANTES:
--   SELECT column_name FROM information_schema.columns
--   WHERE table_schema='vectraclip' AND table_name='agent_adapter_configs'
--   → (id, company_id, agent_id, adapter_id, field_values_json, is_active,
--      created_at, updated_at)
--   Espelha esse shape sem agent_id: per-company-adapter, não per-agent.
--
-- PADRÃO ADOTADO:
--   Shape idêntico a agent_adapter_configs SEM agent_id. UNIQUE(company_id,
--   adapter_id) garante 1 row por adapter por company.
--   field_values_json segue convenção W4: text/url direto, secret como
--   `vault://<vault_secret_id>` (refs pra company_secrets/vault).
--
-- W5 — Marcelo cravou 2026-05-17: secrets de API (Meta access_token, Anthropic
-- key, etc.) devem ser preenchidos UMA VEZ por company em /admin/connectors,
-- não por agente. agent_adapter_configs vira override de EXCEÇÃO (debug/recovery),
-- não default genérico. Resolver backend faz lookup ordem agent→company→None.

CREATE TABLE IF NOT EXISTS "vectraclip"."company_adapter_values" (
    "id"                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    "company_id"         UUID        NOT NULL REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE,
    "adapter_id"         UUID        NOT NULL REFERENCES "vectraclip"."adapter_catalog"("id") ON DELETE CASCADE,
    "field_values_json"  JSONB       NOT NULL DEFAULT '{}',
    "is_active"          BOOLEAN     NOT NULL DEFAULT true,
    "created_at"         TIMESTAMPTZ NOT NULL DEFAULT now(),
    "updated_at"         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS "uq_company_adapter_values_company_adapter"
    ON "vectraclip"."company_adapter_values" ("company_id", "adapter_id");

CREATE INDEX IF NOT EXISTS "idx_company_adapter_values_company"
    ON "vectraclip"."company_adapter_values" ("company_id");

-- Trigger updated_at
CREATE OR REPLACE FUNCTION vectraclip.fn_company_adapter_values_updated_at()
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

DROP TRIGGER IF EXISTS trg_company_adapter_values_updated_at ON "vectraclip"."company_adapter_values";
CREATE TRIGGER trg_company_adapter_values_updated_at
    BEFORE UPDATE ON "vectraclip"."company_adapter_values"
    FOR EACH ROW EXECUTE FUNCTION vectraclip.fn_company_adapter_values_updated_at();

-- RLS
ALTER TABLE "vectraclip"."company_adapter_values" ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "company_adapter_values_service_role_all" ON "vectraclip"."company_adapter_values";
CREATE POLICY "company_adapter_values_service_role_all"
    ON "vectraclip"."company_adapter_values"
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "company_adapter_values_authenticated_all" ON "vectraclip"."company_adapter_values";
CREATE POLICY "company_adapter_values_authenticated_all"
    ON "vectraclip"."company_adapter_values"
    FOR ALL
    TO authenticated
    USING (
        company_id IN (
            SELECT company_id FROM vectraclip.app_users WHERE id = auth.uid()
        )
    )
    WITH CHECK (
        company_id IN (
            SELECT company_id FROM vectraclip.app_users WHERE id = auth.uid()
        )
    );

COMMENT ON TABLE "vectraclip"."company_adapter_values" IS
    'W5 — valores de adapter no nível da company (PRIMARY pra credenciais '
    'compartilhadas: API keys, app_secrets, tokens). agent_adapter_configs '
    'fica como OVERRIDE de exceção (debug/recovery). Resolver backend: '
    'lookup agent_adapter_configs → company_adapter_values → None.';

COMMENT ON COLUMN "vectraclip"."company_adapter_values"."field_values_json" IS
    'JSONB: text/url/select/boolean direto; secret como vault://<vault_secret_id> '
    '(ref pra company_secrets/vault.secrets). Mesma convenção W4.';

-- Verificação
DO $$
BEGIN
  RAISE NOTICE 'W5 company_adapter_values table created (verify via to_regclass)';
END $$;

NOTIFY pgrst, 'reload schema';
