-- =============================================================================
-- VEC-XXX — Policies RLS para vectraclip.research_templates
-- Padrão alinhado a `companies_select_own` (jwt → app_metadata → vectraclip).
--
-- SELECT: globais (company_id IS NULL) + do próprio tenant
-- INSERT/UPDATE/DELETE: apenas role=admin do próprio tenant
-- (templates globais permanecem read-only via API; mutations só via migration)
-- =============================================================================

-- Limpa policies pré-existentes (idempotente)
DROP POLICY IF EXISTS "research_templates_select_visible"      ON vectraclip.research_templates;
DROP POLICY IF EXISTS "research_templates_insert_admin_tenant" ON vectraclip.research_templates;
DROP POLICY IF EXISTS "research_templates_update_admin_tenant" ON vectraclip.research_templates;
DROP POLICY IF EXISTS "research_templates_delete_admin_tenant" ON vectraclip.research_templates;

CREATE POLICY "research_templates_select_visible"
    ON vectraclip.research_templates
    FOR SELECT
    USING (
        company_id IS NULL
        OR company_id = ((SELECT (((auth.jwt() -> 'app_metadata'::text) -> 'vectraclip'::text) ->> 'company_id'::text))::uuid)
    );

CREATE POLICY "research_templates_insert_admin_tenant"
    ON vectraclip.research_templates
    FOR INSERT
    WITH CHECK (
        company_id = ((SELECT (((auth.jwt() -> 'app_metadata'::text) -> 'vectraclip'::text) ->> 'company_id'::text))::uuid)
        AND ((SELECT (((auth.jwt() -> 'app_metadata'::text) -> 'vectraclip'::text) ->> 'role'::text)) = 'admin')
    );

CREATE POLICY "research_templates_update_admin_tenant"
    ON vectraclip.research_templates
    FOR UPDATE
    USING (
        company_id = ((SELECT (((auth.jwt() -> 'app_metadata'::text) -> 'vectraclip'::text) ->> 'company_id'::text))::uuid)
        AND ((SELECT (((auth.jwt() -> 'app_metadata'::text) -> 'vectraclip'::text) ->> 'role'::text)) = 'admin')
    );

CREATE POLICY "research_templates_delete_admin_tenant"
    ON vectraclip.research_templates
    FOR DELETE
    USING (
        company_id = ((SELECT (((auth.jwt() -> 'app_metadata'::text) -> 'vectraclip'::text) ->> 'company_id'::text))::uuid)
        AND ((SELECT (((auth.jwt() -> 'app_metadata'::text) -> 'vectraclip'::text) ->> 'role'::text)) = 'admin')
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE vectraclip.research_templates TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE vectraclip.research_templates TO service_role;
