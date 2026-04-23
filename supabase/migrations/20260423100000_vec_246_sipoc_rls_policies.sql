-- Migration: SIPOC RLS Policies
-- Issue: VEC-246
-- Schema: vectraclip
-- Nota: sipoc_company_id() fica em vectraclip (não em auth) para evitar
--   restrições de permissão do Supabase no schema auth.

CREATE OR REPLACE FUNCTION vectraclip.sipoc_company_id() RETURNS UUID AS $$
    SELECT ((auth.jwt() -> 'app_metadata' -> 'vectraclip') ->> 'company_id')::UUID;
$$ LANGUAGE SQL STABLE SECURITY DEFINER;

-- =====================================================================
-- sipoc_companies
-- INSERT: via service_role (endpoint usa supabase client, não authenticated)
--         RLS de insert não é necessária — service_role bypassa RLS.
-- SELECT/UPDATE/DELETE: restritos ao company_id do JWT
-- =====================================================================
CREATE POLICY "sipoc_companies_tenant_select"
    ON vectraclip.sipoc_companies FOR SELECT
    USING (id = vectraclip.sipoc_company_id());

CREATE POLICY "sipoc_companies_tenant_update"
    ON vectraclip.sipoc_companies FOR UPDATE
    USING (id = vectraclip.sipoc_company_id())
    WITH CHECK (id = vectraclip.sipoc_company_id());

CREATE POLICY "sipoc_companies_tenant_delete"
    ON vectraclip.sipoc_companies FOR DELETE
    USING (id = vectraclip.sipoc_company_id());

-- =====================================================================
-- sipoc_sectors
-- =====================================================================
CREATE POLICY "sipoc_sectors_tenant_select"
    ON vectraclip.sipoc_sectors FOR SELECT
    USING (company_id = vectraclip.sipoc_company_id());

CREATE POLICY "sipoc_sectors_tenant_insert"
    ON vectraclip.sipoc_sectors FOR INSERT
    WITH CHECK (company_id = vectraclip.sipoc_company_id());

CREATE POLICY "sipoc_sectors_tenant_update"
    ON vectraclip.sipoc_sectors FOR UPDATE
    USING (company_id = vectraclip.sipoc_company_id())
    WITH CHECK (company_id = vectraclip.sipoc_company_id());

CREATE POLICY "sipoc_sectors_tenant_delete"
    ON vectraclip.sipoc_sectors FOR DELETE
    USING (company_id = vectraclip.sipoc_company_id());

-- =====================================================================
-- sipoc_positions
-- =====================================================================
DROP POLICY IF EXISTS "Enable all for now" ON vectraclip.sipoc_positions;

CREATE POLICY "sipoc_positions_tenant_select"
    ON vectraclip.sipoc_positions FOR SELECT
    USING (company_id = vectraclip.sipoc_company_id());

CREATE POLICY "sipoc_positions_tenant_insert"
    ON vectraclip.sipoc_positions FOR INSERT
    WITH CHECK (company_id = vectraclip.sipoc_company_id());

CREATE POLICY "sipoc_positions_tenant_update"
    ON vectraclip.sipoc_positions FOR UPDATE
    USING (company_id = vectraclip.sipoc_company_id())
    WITH CHECK (company_id = vectraclip.sipoc_company_id());

CREATE POLICY "sipoc_positions_tenant_delete"
    ON vectraclip.sipoc_positions FOR DELETE
    USING (company_id = vectraclip.sipoc_company_id());

-- =====================================================================
-- sipoc_processes — isolamento via setor → empresa
-- =====================================================================
CREATE POLICY "sipoc_processes_tenant_select"
    ON vectraclip.sipoc_processes FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM vectraclip.sipoc_sectors s
            WHERE s.id = sector_id AND s.company_id = vectraclip.sipoc_company_id()
        )
    );

CREATE POLICY "sipoc_processes_tenant_insert"
    ON vectraclip.sipoc_processes FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM vectraclip.sipoc_sectors s
            WHERE s.id = sector_id AND s.company_id = vectraclip.sipoc_company_id()
        )
    );

CREATE POLICY "sipoc_processes_tenant_update"
    ON vectraclip.sipoc_processes FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM vectraclip.sipoc_sectors s
            WHERE s.id = sector_id AND s.company_id = vectraclip.sipoc_company_id()
        )
    );

CREATE POLICY "sipoc_processes_tenant_delete"
    ON vectraclip.sipoc_processes FOR DELETE
    USING (
        EXISTS (
            SELECT 1 FROM vectraclip.sipoc_sectors s
            WHERE s.id = sector_id AND s.company_id = vectraclip.sipoc_company_id()
        )
    );

-- =====================================================================
-- sipoc_components — isolamento via processo → setor → empresa
-- =====================================================================
CREATE POLICY "sipoc_components_tenant_select"
    ON vectraclip.sipoc_components FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM vectraclip.sipoc_processes p
            JOIN vectraclip.sipoc_sectors s ON s.id = p.sector_id
            WHERE p.id = process_id AND s.company_id = vectraclip.sipoc_company_id()
        )
    );

CREATE POLICY "sipoc_components_tenant_insert"
    ON vectraclip.sipoc_components FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM vectraclip.sipoc_processes p
            JOIN vectraclip.sipoc_sectors s ON s.id = p.sector_id
            WHERE p.id = process_id AND s.company_id = vectraclip.sipoc_company_id()
        )
    );

CREATE POLICY "sipoc_components_tenant_update"
    ON vectraclip.sipoc_components FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM vectraclip.sipoc_processes p
            JOIN vectraclip.sipoc_sectors s ON s.id = p.sector_id
            WHERE p.id = process_id AND s.company_id = vectraclip.sipoc_company_id()
        )
    );

CREATE POLICY "sipoc_components_tenant_delete"
    ON vectraclip.sipoc_components FOR DELETE
    USING (
        EXISTS (
            SELECT 1 FROM vectraclip.sipoc_processes p
            JOIN vectraclip.sipoc_sectors s ON s.id = p.sector_id
            WHERE p.id = process_id AND s.company_id = vectraclip.sipoc_company_id()
        )
    );
