-- N10: company_mcp_values — credenciais MCP ao nível COMPANY (não agente).
--
-- Decisão Marcelo 2026-05-19: "todas as credenciais exigidas devem morar em
-- /admin/mcp - não no agente". Espelha o padrão W5 adapter
-- (company_adapter_values PRIMARY + agent override exceção — memory
-- feedback_company_primary_agent_override).
--
-- Modelo resultante (4 camadas, igual adapter):
--   mcp_server_catalog        → schema cross-tenant (field_definitions, transport, auth)
--   company_mcp_values        → credenciais PRIMARY por (company, server) [NOVO]
--   agent_mcp_bindings        → referência + override de exceção (debug/recovery)
--   vault.secrets             → segredos via vault://<uuid>
--
-- Resolver (N11): handshake lê company_mcp_values[server] PRIMEIRO; só usa
-- agent_mcp_bindings.field_values_json quando há override explícito.
--
-- ESPELHEI ANTES (Regra #1): estrutura idêntica a company_adapter_values
-- (id, company_id, <catalog_fk>, field_values_json, is_active, created_at, updated_at)
-- trocando adapter_id (uuid) por mcp_server_id (text FK mcp_server_catalog).
--
-- Verificação:
--   SELECT count(*) FROM information_schema.tables
--     WHERE table_schema='vectraclip' AND table_name='company_mcp_values'; -- 1

CREATE TABLE IF NOT EXISTS vectraclip.company_mcp_values (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id        uuid NOT NULL,
  mcp_server_id     text NOT NULL,
  field_values_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  allowed_tools     text[],
  is_active         boolean NOT NULL DEFAULT true,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT fk_company_mcp_values_company
    FOREIGN KEY (company_id) REFERENCES vectraclip.companies(company_id) ON DELETE CASCADE,
  CONSTRAINT fk_company_mcp_values_server
    FOREIGN KEY (mcp_server_id) REFERENCES vectraclip.mcp_server_catalog(id) ON DELETE RESTRICT,
  CONSTRAINT uq_company_mcp_values_company_server
    UNIQUE (company_id, mcp_server_id)
);

CREATE INDEX IF NOT EXISTS idx_company_mcp_values_company
  ON vectraclip.company_mcp_values (company_id) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_company_mcp_values_server
  ON vectraclip.company_mcp_values (mcp_server_id);

COMMENT ON TABLE vectraclip.company_mcp_values IS
  'Credenciais MCP PRIMARY por (company, mcp_server). Configuradas em /admin/mcp. Secrets via vault://. Resolver lê isto antes de agent_mcp_bindings (override).';
COMMENT ON COLUMN vectraclip.company_mcp_values.allowed_tools IS
  'Whitelist default da company; agent binding pode estreitar. NULL = todos.';

-- updated_at trigger (reusa set_updated_at criada no N4)
DROP TRIGGER IF EXISTS trg_company_mcp_values_updated_at ON vectraclip.company_mcp_values;
CREATE TRIGGER trg_company_mcp_values_updated_at
  BEFORE UPDATE ON vectraclip.company_mcp_values
  FOR EACH ROW EXECUTE FUNCTION vectraclip.set_updated_at();

-- RLS — tenant isolation (pattern agent_mcp_bindings)
ALTER TABLE vectraclip.company_mcp_values ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS company_mcp_values_select_own ON vectraclip.company_mcp_values;
CREATE POLICY company_mcp_values_select_own ON vectraclip.company_mcp_values
  FOR SELECT TO authenticated
  USING (company_id::text = ((auth.jwt() -> 'app_metadata') -> 'vectraclip' ->> 'company_id'));

DROP POLICY IF EXISTS company_mcp_values_modify_own ON vectraclip.company_mcp_values;
CREATE POLICY company_mcp_values_modify_own ON vectraclip.company_mcp_values
  FOR ALL TO authenticated
  USING (company_id::text = ((auth.jwt() -> 'app_metadata') -> 'vectraclip' ->> 'company_id'))
  WITH CHECK (company_id::text = ((auth.jwt() -> 'app_metadata') -> 'vectraclip' ->> 'company_id'));

DROP POLICY IF EXISTS company_mcp_values_service_role_all ON vectraclip.company_mcp_values;
CREATE POLICY company_mcp_values_service_role_all ON vectraclip.company_mcp_values
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE, DELETE ON vectraclip.company_mcp_values TO authenticated;
GRANT ALL ON vectraclip.company_mcp_values TO service_role;
