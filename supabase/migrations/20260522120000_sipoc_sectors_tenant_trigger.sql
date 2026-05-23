-- VEC — Multi-tenant hardening: sipoc_sectors (e sipoc_positions)
-- Nunca confiar em company_id vindo do cliente; derivar do JWT via sipoc_company_id().
-- RLS permanece como segunda linha de defesa (WITH CHECK em INSERT/UPDATE).

-- ---------------------------------------------------------------------------
-- Função genérica: popula company_id no INSERT; bloqueia mismatch no UPDATE
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION vectraclip.enforce_sipoc_tenant_company_id()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO vectraclip, public, pg_temp
AS $$
DECLARE
  jwt_company uuid;
BEGIN
  jwt_company := vectraclip.sipoc_company_id();

  IF jwt_company IS NULL THEN
    RAISE EXCEPTION 'tenant_claim_missing: app_metadata.vectraclip.company_id ausente no JWT'
      USING ERRCODE = '42501';
  END IF;

  IF TG_OP = 'INSERT' THEN
    -- Sempre sobrescreve: cliente/PostgREST não define o tenant.
    NEW.company_id := jwt_company;
  ELSIF TG_OP = 'UPDATE' THEN
    IF NEW.company_id IS DISTINCT FROM jwt_company THEN
      RAISE EXCEPTION 'tenant_company_id_mismatch: company_id não pertence ao tenant do JWT'
        USING ERRCODE = '42501';
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

COMMENT ON FUNCTION vectraclip.enforce_sipoc_tenant_company_id() IS
  'BEFORE INSERT/UPDATE: define company_id a partir do JWT; rejeita troca de tenant.';

-- sipoc_sectors
DROP TRIGGER IF EXISTS trg_sipoc_sectors_enforce_tenant ON vectraclip.sipoc_sectors;
CREATE TRIGGER trg_sipoc_sectors_enforce_tenant
  BEFORE INSERT OR UPDATE ON vectraclip.sipoc_sectors
  FOR EACH ROW
  EXECUTE FUNCTION vectraclip.enforce_sipoc_tenant_company_id();

-- sipoc_positions (mesmo padrão de tenant em company_id)
DROP TRIGGER IF EXISTS trg_sipoc_positions_enforce_tenant ON vectraclip.sipoc_positions;
CREATE TRIGGER trg_sipoc_positions_enforce_tenant
  BEFORE INSERT OR UPDATE ON vectraclip.sipoc_positions
  FOR EACH ROW
  EXECUTE FUNCTION vectraclip.enforce_sipoc_tenant_company_id();

-- ---------------------------------------------------------------------------
-- Testes SQL (rodar após migration em ambiente com JWT de teste)
-- Ver tests/sql/test_sipoc_sectors_rls.sql
-- ---------------------------------------------------------------------------
