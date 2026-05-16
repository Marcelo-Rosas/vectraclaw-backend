-- G2.1 — Admin RLS hardening
--
-- Bug capturado em docs/AUDIT-HANDLERS-2026-05-16.md §Camada 2.2:
--   "app_users PATCH service_role bypass; RLS GRANT incompleto" (🔴 P0)
--
-- Diagnóstico real:
--   - 3 tabelas com mesmo gap: app_users, companies, llm_models
--   - GRANT só SELECT pra authenticated
--   - Policies WRITE existem mas com set de roles DESATUALIZADO
--     (só 'admin', enquanto convenção atual é {admin, platform_admin,
--      consultant, company_admin} — vide policies de risks PR #149)
--   - PR #137 hotfix usou service_role como workaround — ESTRUTURAL
--     fica aqui, código volta a usar authenticated client.
--
-- Esta migration:
--   A. app_users — GRANT INSERT/UPDATE/DELETE + policies com set ampliado
--   B. companies — GRANT UPDATE + policy ampliada
--      (DELETE company fica service_role: operação platform, risco maior)
--   C. llm_models — GRANT INSERT/UPDATE/DELETE + policy role='platform_admin'
--      (catalog cross-tenant; código mantém service_role por ora porque
--       UI tenant admin não consegue gerenciar — gerência futura via
--       admin console plataforma)

-- =============================================================================
-- A. app_users
-- =============================================================================

GRANT INSERT, UPDATE, DELETE ON vectraclip.app_users TO authenticated;

DROP POLICY IF EXISTS app_users_update_admin ON vectraclip.app_users;
CREATE POLICY app_users_update_admin ON vectraclip.app_users
  FOR UPDATE
  USING (
    company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid)
    AND ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = ANY (
      ARRAY['admin', 'platform_admin', 'consultant', 'company_admin']
    ))
  )
  WITH CHECK (
    company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid)
    AND ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = ANY (
      ARRAY['admin', 'platform_admin', 'consultant', 'company_admin']
    ))
  );

DROP POLICY IF EXISTS app_users_delete_admin ON vectraclip.app_users;
CREATE POLICY app_users_delete_admin ON vectraclip.app_users
  FOR DELETE
  USING (
    company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid)
    AND ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = ANY (
      ARRAY['admin', 'platform_admin', 'consultant', 'company_admin']
    ))
  );

DROP POLICY IF EXISTS app_users_insert_admin ON vectraclip.app_users;
CREATE POLICY app_users_insert_admin ON vectraclip.app_users
  FOR INSERT
  WITH CHECK (
    company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid)
    AND ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = ANY (
      ARRAY['admin', 'platform_admin', 'consultant', 'company_admin']
    ))
  );

-- =============================================================================
-- B. companies
-- =============================================================================

GRANT UPDATE ON vectraclip.companies TO authenticated;

DROP POLICY IF EXISTS companies_update_admin ON vectraclip.companies;
CREATE POLICY companies_update_admin ON vectraclip.companies
  FOR UPDATE
  USING (
    company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid)
    AND ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = ANY (
      ARRAY['admin', 'platform_admin', 'consultant', 'company_admin']
    ))
  )
  WITH CHECK (
    company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid)
    AND ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = ANY (
      ARRAY['admin', 'platform_admin', 'consultant', 'company_admin']
    ))
  );

-- =============================================================================
-- C. llm_models — catalog cross-tenant; só platform_admin
-- =============================================================================

GRANT INSERT, UPDATE, DELETE ON vectraclip.llm_models TO authenticated;

-- Policy WRITE platform_admin (catalog é global, não tenant-scoped — sem company_id check)
DROP POLICY IF EXISTS llm_models_write_platform_admin ON vectraclip.llm_models;
CREATE POLICY llm_models_write_platform_admin ON vectraclip.llm_models
  FOR ALL
  USING (
    ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = 'platform_admin')
  )
  WITH CHECK (
    ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = 'platform_admin')
  );

NOTIFY pgrst, 'reload schema';
