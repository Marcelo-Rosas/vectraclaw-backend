-- ESPELHEI ANTES:
--   PostgREST não expõe schema `vault` (PGRST106 Invalid schema). Só
--   public/graphql_public/vectraclip são exposed via api.exposed-schemas.
--   Confirmado via smoke W5 backend: resolve_secret_ref falhou ao tentar
--   SELECT direto em vault.decrypted_secrets.
--
-- PADRÃO ADOTADO:
--   RPC SECURITY DEFINER em vectraclip que valida ownership via
--   company_secrets antes de ler vault.decrypted_secrets. Backend chama via
--   supabase.rpc('get_vault_secret', {...}) — caminho exposed.
--
--   Defense in depth dupla:
--   1. SELECT em company_secrets WHERE vault_secret_id=X AND company_id=Y
--      (cross-company protection — mesmo que UUID vaze, sem ownership=acesso negado)
--   2. SELECT em vault.decrypted_secrets WHERE id=X
--      (Vault descriptografa só pra service_role; RPC SECURITY DEFINER roda como
--      owner da função, geralmente postgres/admin → tem acesso)
--
-- W5.1 — hotfix do W5 backend (#208). resolve_secret_ref atual tenta acessar
-- schema vault diretamente via PostgREST → 403 silent + None returned →
-- todos os refs vault:// retornam None → webhook Meta rejeita por falta de
-- app_secret. Esta RPC corrige a fonte: backend lê secret via RPC exposed.

CREATE OR REPLACE FUNCTION vectraclip.get_vault_secret(
    p_vault_secret_id uuid,
    p_company_id      uuid
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = vectraclip, vault, public
AS $$
DECLARE
    v_owner_exists boolean;
    v_decrypted    text;
BEGIN
    -- Cross-company protection: confirma que vault_secret_id pertence à company.
    SELECT EXISTS (
        SELECT 1
        FROM vectraclip.company_secrets cs
        WHERE cs.vault_secret_id = p_vault_secret_id
          AND cs.company_id = p_company_id
    ) INTO v_owner_exists;

    IF NOT v_owner_exists THEN
        -- Não vaza informação: 'not found' vs 'wrong company' tratados igual.
        RETURN NULL;
    END IF;

    -- Leitura do Vault. RPC roda como owner (admin) → tem acesso à
    -- decrypted_secrets. service_role do PostgREST chama esta RPC normalmente.
    SELECT decrypted_secret
      INTO v_decrypted
      FROM vault.decrypted_secrets
     WHERE id = p_vault_secret_id;

    RETURN v_decrypted;
END;
$$;

COMMENT ON FUNCTION vectraclip.get_vault_secret(uuid, uuid) IS
    'W5.1 — Lê texto claro de vault.secrets validando ownership em '
    'company_secrets. Backend usa via supabase.rpc(). SECURITY DEFINER porque '
    'schema vault não é exposto pelo PostgREST. Retorna NULL se ref órfã ou '
    'cross-company (não vaza diferenciação).';

-- Permissões: service_role precisa poder chamar via PostgREST.
GRANT EXECUTE ON FUNCTION vectraclip.get_vault_secret(uuid, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION vectraclip.get_vault_secret(uuid, uuid) TO authenticated;

-- Smoke do owner do RPC (precisa rodar como superuser/admin) — só DDL.
DO $$
BEGIN
  RAISE NOTICE 'W5.1 RPC vectraclip.get_vault_secret(uuid, uuid) created';
END $$;

NOTIFY pgrst, 'reload schema';
