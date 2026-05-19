-- N4 DDL: separação tri-tabela arquitetural (Plan §4)
--   adapter_catalog       → APENAS LLM providers (já existente; cleanup feito N2)
--   mcp_server_catalog    → NOVA: MCP servers cross-tenant (tools externas)
--   agent_mcp_bindings    → NOVA: per-tenant N:N (agente ↔ MCP server)
--   connector_channels    → não tocado (mensageria já existe)
--
-- Memory refs:
--   - feedback_no_camunda_keep_custom_engine — Camunda só como cliente MCP, não engine
--   - vault_secrets_convention — credenciais via vault://<uuid>
--   - company_primary_agent_override — resolver hybrid pattern (company-level + agent override)
--   - feedback_metadata_driven_no_hardcode — catalog cross-tenant + field_definitions JSONB
--
-- ESPELHEI ANTES (Regra #1):
--   - 0 tabelas com prefixo mcp existentes em vectraclip
--   - adapter_field_definitions tem shape: field_key, field_label, field_type, is_required,
--     options_json, sort_order, trigger_condition, is_active (espelhei pra field_definitions JSONB)
--   - athena_documents recente é template RLS canônico (auth.jwt → app_metadata → vectraclip → company_id)
--   - companies.company_id é PK pra FK ON DELETE CASCADE
--   - agents.id é uuid PK
--
-- Contratos:
--   docs/CONTRACTS-MCP-BINDINGS.md (PR #247) define TS+Pydantic shape; este DDL espelha.

-- ============================================================================
-- 1) mcp_server_catalog — cross-tenant catalog de MCP servers disponíveis
-- ============================================================================

CREATE TABLE IF NOT EXISTS vectraclip.mcp_server_catalog (
  id                    text PRIMARY KEY,
  name                  text NOT NULL,
  description           text,
  transport             text NOT NULL,
  endpoint_url_template text,
  auth_type             text NOT NULL DEFAULT 'none',
  field_definitions     jsonb NOT NULL DEFAULT '[]'::jsonb,
  category              text NOT NULL DEFAULT 'other',
  icon                  text,
  color                 text,
  display_order         integer NOT NULL DEFAULT 100,
  is_active             boolean NOT NULL DEFAULT true,
  documentation_url     text,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT mcp_server_catalog_transport_check
    CHECK (transport IN ('stdio', 'http', 'sse')),
  CONSTRAINT mcp_server_catalog_auth_type_check
    CHECK (auth_type IN ('oauth2_client_credentials', 'api_key', 'bearer', 'none', 'env_vars')),
  CONSTRAINT mcp_server_catalog_category_check
    CHECK (category IN ('bpm', 'messaging', 'code', 'crm', 'storage', 'finance', 'other'))
);

CREATE INDEX IF NOT EXISTS idx_mcp_server_catalog_active_order
  ON vectraclip.mcp_server_catalog (is_active, display_order)
  WHERE is_active = true;

COMMENT ON TABLE vectraclip.mcp_server_catalog IS
  'Cross-tenant catalog de MCP servers (Camunda, Supabase MCP, mcp-imap, etc.). Writes só service_role.';
COMMENT ON COLUMN vectraclip.mcp_server_catalog.field_definitions IS
  'Array de definições de campo shape: [{key, label, type, required, default, placeholder, ...}]. Espelha adapter_field_definitions.';
COMMENT ON COLUMN vectraclip.mcp_server_catalog.transport IS
  'stdio|http|sse — protocolo MCP de transporte. stdio requer subprocess local.';
COMMENT ON COLUMN vectraclip.mcp_server_catalog.auth_type IS
  'oauth2_client_credentials|api_key|bearer|none|env_vars';

-- ============================================================================
-- 2) agent_mcp_bindings — per-tenant N:N (agent ↔ mcp_server)
-- ============================================================================

CREATE TABLE IF NOT EXISTS vectraclip.agent_mcp_bindings (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id        uuid NOT NULL,
  agent_id          uuid NOT NULL,
  mcp_server_id     text NOT NULL,
  field_values_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  allowed_tools     text[],
  tools_cache       jsonb,
  last_health_at    timestamptz,
  last_error        text,
  is_active         boolean NOT NULL DEFAULT true,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT fk_agent_mcp_bindings_company
    FOREIGN KEY (company_id) REFERENCES vectraclip.companies(company_id) ON DELETE CASCADE,
  CONSTRAINT fk_agent_mcp_bindings_agent
    FOREIGN KEY (agent_id) REFERENCES vectraclip.agents(id) ON DELETE CASCADE,
  CONSTRAINT fk_agent_mcp_bindings_mcp_server
    FOREIGN KEY (mcp_server_id) REFERENCES vectraclip.mcp_server_catalog(id) ON DELETE RESTRICT,
  CONSTRAINT uq_agent_mcp_bindings_agent_server
    UNIQUE (agent_id, mcp_server_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_mcp_bindings_agent
  ON vectraclip.agent_mcp_bindings (agent_id) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_agent_mcp_bindings_company
  ON vectraclip.agent_mcp_bindings (company_id);
CREATE INDEX IF NOT EXISTS idx_agent_mcp_bindings_server
  ON vectraclip.agent_mcp_bindings (mcp_server_id);

COMMENT ON TABLE vectraclip.agent_mcp_bindings IS
  'Per-tenant N:N (agent × mcp_server). Secrets em field_values_json como vault://<uuid> refs.';
COMMENT ON COLUMN vectraclip.agent_mcp_bindings.allowed_tools IS
  'Whitelist de tool names; NULL = todos os tools do server permitidos.';
COMMENT ON COLUMN vectraclip.agent_mcp_bindings.tools_cache IS
  'Array McpTool[] cached em handshake. Refresh via POST /tools/refresh.';

-- ============================================================================
-- 3) Trigger updated_at em ambas
-- ============================================================================

CREATE OR REPLACE FUNCTION vectraclip.set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_mcp_server_catalog_updated_at ON vectraclip.mcp_server_catalog;
CREATE TRIGGER trg_mcp_server_catalog_updated_at
  BEFORE UPDATE ON vectraclip.mcp_server_catalog
  FOR EACH ROW EXECUTE FUNCTION vectraclip.set_updated_at();

DROP TRIGGER IF EXISTS trg_agent_mcp_bindings_updated_at ON vectraclip.agent_mcp_bindings;
CREATE TRIGGER trg_agent_mcp_bindings_updated_at
  BEFORE UPDATE ON vectraclip.agent_mcp_bindings
  FOR EACH ROW EXECUTE FUNCTION vectraclip.set_updated_at();

-- ============================================================================
-- 4) RLS — pattern athena_documents (auth.jwt app_metadata vectraclip company_id)
-- ============================================================================

ALTER TABLE vectraclip.mcp_server_catalog ENABLE ROW LEVEL SECURITY;
ALTER TABLE vectraclip.agent_mcp_bindings  ENABLE ROW LEVEL SECURITY;

-- mcp_server_catalog: SELECT autenticado livre (cross-tenant catalog); writes só service_role
DROP POLICY IF EXISTS mcp_server_catalog_select_all ON vectraclip.mcp_server_catalog;
CREATE POLICY mcp_server_catalog_select_all ON vectraclip.mcp_server_catalog
  FOR SELECT TO authenticated
  USING (is_active = true);

DROP POLICY IF EXISTS mcp_server_catalog_service_role_all ON vectraclip.mcp_server_catalog;
CREATE POLICY mcp_server_catalog_service_role_all ON vectraclip.mcp_server_catalog
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- agent_mcp_bindings: tenant isolation via JWT company_id
DROP POLICY IF EXISTS agent_mcp_bindings_select_own ON vectraclip.agent_mcp_bindings;
CREATE POLICY agent_mcp_bindings_select_own ON vectraclip.agent_mcp_bindings
  FOR SELECT TO authenticated
  USING (
    company_id::text = (
      ((auth.jwt() -> 'app_metadata') -> 'vectraclip' ->> 'company_id')
    )
  );

DROP POLICY IF EXISTS agent_mcp_bindings_modify_own ON vectraclip.agent_mcp_bindings;
CREATE POLICY agent_mcp_bindings_modify_own ON vectraclip.agent_mcp_bindings
  FOR ALL TO authenticated
  USING (
    company_id::text = (
      ((auth.jwt() -> 'app_metadata') -> 'vectraclip' ->> 'company_id')
    )
  )
  WITH CHECK (
    company_id::text = (
      ((auth.jwt() -> 'app_metadata') -> 'vectraclip' ->> 'company_id')
    )
  );

DROP POLICY IF EXISTS agent_mcp_bindings_service_role_all ON vectraclip.agent_mcp_bindings;
CREATE POLICY agent_mcp_bindings_service_role_all ON vectraclip.agent_mcp_bindings
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- ============================================================================
-- 5) Grants para PostgREST
-- ============================================================================

GRANT SELECT ON vectraclip.mcp_server_catalog TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON vectraclip.agent_mcp_bindings TO authenticated;

GRANT ALL ON vectraclip.mcp_server_catalog TO service_role;
GRANT ALL ON vectraclip.agent_mcp_bindings  TO service_role;
