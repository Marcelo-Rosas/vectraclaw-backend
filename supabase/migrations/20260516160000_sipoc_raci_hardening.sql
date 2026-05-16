-- =============================================================================
-- SIPOC RACI hardening — CHECK constraint em role + RLS tenant-aware
--
-- Contexto Schmidt (Strategic PM Made Simple):
--   RACI é peça central do "Engage Stakeholders" — define quem é
--   Responsible / Accountable / Consulted / Informed em cada atividade.
--   Hoje a tabela tem 0 rows, role aceita qualquer string (sem CHECK)
--   e RLS tem só policy "service_role full access" (true/true).
--
-- Mudanças:
--   1. CHECK constraint role IN ('R','A','C','I')
--   2. Policies tenant-aware via JOIN com sipoc_processes → sipoc_sectors
--      (sipoc_sectors.company_id é UUID que bate com companies.company_id
--      no JWT — confirmado no Vectra Cargo, único tenant em uso)
--   3. COMMENT explicando semântica RACI
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. CHECK constraint em role (R/A/C/I)
-- -----------------------------------------------------------------------------

ALTER TABLE vectraclip.sipoc_raci
    DROP CONSTRAINT IF EXISTS sipoc_raci_role_check;

ALTER TABLE vectraclip.sipoc_raci
    ADD CONSTRAINT sipoc_raci_role_check
    CHECK (role = ANY (ARRAY['R'::text, 'A'::text, 'C'::text, 'I'::text]));

COMMENT ON COLUMN vectraclip.sipoc_raci.role IS
    'Papel RACI da position na activity. R=Responsible (executa), A=Accountable (presta contas), C=Consulted (consultado antes), I=Informed (notificado depois). Schmidt LogFrame §Engage Stakeholders.';

COMMENT ON TABLE vectraclip.sipoc_raci IS
    'Matriz RACI por (process, component=activity, position). UNIQUE em (component_id, position_id) — cada cargo tem UM papel por atividade. Schmidt §"Envolva stakeholders".';


-- -----------------------------------------------------------------------------
-- 2. RLS policies tenant-aware
--
-- Chain real (descoberto na auditoria):
--   sipoc_raci.process_id → sipoc_processes.sector_id
--   → sipoc_sectors.company_id (UUID que bate com companies.company_id no JWT)
--
-- sipoc_companies é tabela órfã legada (não tem FK pra companies);
-- usamos sipoc_sectors.company_id direto, que casa com o JWT.
-- -----------------------------------------------------------------------------

-- Drop policies antigas (idempotente)
DROP POLICY IF EXISTS "service_role full access" ON vectraclip.sipoc_raci;
DROP POLICY IF EXISTS "sipoc_raci_select_own_tenant" ON vectraclip.sipoc_raci;
DROP POLICY IF EXISTS "sipoc_raci_insert_admin_tenant" ON vectraclip.sipoc_raci;
DROP POLICY IF EXISTS "sipoc_raci_update_admin_tenant" ON vectraclip.sipoc_raci;
DROP POLICY IF EXISTS "sipoc_raci_delete_admin_tenant" ON vectraclip.sipoc_raci;

-- SELECT: qualquer authenticated do tenant
CREATE POLICY "sipoc_raci_select_own_tenant"
    ON vectraclip.sipoc_raci
    FOR SELECT
    USING (
        process_id IN (
            SELECT p.id
            FROM vectraclip.sipoc_processes p
            JOIN vectraclip.sipoc_sectors s ON s.id = p.sector_id
            WHERE s.company_id = (
                ((SELECT (((auth.jwt() -> 'app_metadata'::text) -> 'vectraclip'::text) ->> 'company_id'::text)))::uuid
            )
        )
    );

-- INSERT/UPDATE/DELETE: só roles admin do tenant
CREATE POLICY "sipoc_raci_insert_admin_tenant"
    ON vectraclip.sipoc_raci
    FOR INSERT
    WITH CHECK (
        ((SELECT (((auth.jwt() -> 'app_metadata'::text) -> 'vectraclip'::text) ->> 'role'::text))
            = ANY (ARRAY['admin','platform_admin','consultant','company_admin']))
        AND process_id IN (
            SELECT p.id
            FROM vectraclip.sipoc_processes p
            JOIN vectraclip.sipoc_sectors s ON s.id = p.sector_id
            WHERE s.company_id = (
                ((SELECT (((auth.jwt() -> 'app_metadata'::text) -> 'vectraclip'::text) ->> 'company_id'::text)))::uuid
            )
        )
    );

CREATE POLICY "sipoc_raci_update_admin_tenant"
    ON vectraclip.sipoc_raci
    FOR UPDATE
    USING (
        ((SELECT (((auth.jwt() -> 'app_metadata'::text) -> 'vectraclip'::text) ->> 'role'::text))
            = ANY (ARRAY['admin','platform_admin','consultant','company_admin']))
        AND process_id IN (
            SELECT p.id
            FROM vectraclip.sipoc_processes p
            JOIN vectraclip.sipoc_sectors s ON s.id = p.sector_id
            WHERE s.company_id = (
                ((SELECT (((auth.jwt() -> 'app_metadata'::text) -> 'vectraclip'::text) ->> 'company_id'::text)))::uuid
            )
        )
    );

CREATE POLICY "sipoc_raci_delete_admin_tenant"
    ON vectraclip.sipoc_raci
    FOR DELETE
    USING (
        ((SELECT (((auth.jwt() -> 'app_metadata'::text) -> 'vectraclip'::text) ->> 'role'::text))
            = ANY (ARRAY['admin','platform_admin','consultant','company_admin']))
        AND process_id IN (
            SELECT p.id
            FROM vectraclip.sipoc_processes p
            JOIN vectraclip.sipoc_sectors s ON s.id = p.sector_id
            WHERE s.company_id = (
                ((SELECT (((auth.jwt() -> 'app_metadata'::text) -> 'vectraclip'::text) ->> 'company_id'::text)))::uuid
            )
        )
    );


-- -----------------------------------------------------------------------------
-- 3. GRANTs — RLS sozinho não basta: precisa GRANT base pra authenticated
--
-- Mesmo aprendizado do PR7 hotfix (#137): vectraclip.app_users tinha RLS OK
-- mas faltava GRANT INSERT/UPDATE/DELETE pra authenticated, então 'permission
-- denied for table' antes do RLS rodar. Aqui aplicamos preventivo.
-- -----------------------------------------------------------------------------

GRANT INSERT, UPDATE, DELETE ON vectraclip.sipoc_raci TO authenticated;
