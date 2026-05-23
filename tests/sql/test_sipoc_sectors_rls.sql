-- Testes de isolamento tenant — sipoc_sectors / sipoc_positions
-- Execução: supabase test db OU psql com role authenticated + JWT configurado.
--
-- Pré-requisitos:
--   SET request.jwt.claims = '{"app_metadata":{"vectraclip":{"company_id":"<UUID_A>"}}}';
--   SET ROLE authenticated;
--
-- Caso A (tenant correto): INSERT com company_id errado no payload → trigger corrige → RLS OK
-- Caso B (sem claim): sipoc_company_id() NULL → trigger 42501 tenant_claim_missing
-- Caso C (UPDATE mismatch): UPDATE company_id para outro tenant → 42501 tenant_company_id_mismatch

\echo '=== sipoc RLS — requer JWT de teste configurado no session ==='

-- Exemplo (substituir UUIDs reais do seed):
-- \set company_a '88aa2edc-6a9e-4048-9bd8-c588e0dcae4c'
-- SELECT set_config('request.jwt.claims', format('{"app_metadata":{"vectraclip":{"company_id":"%s"}}}', :'company_a'), true);

DO $$
BEGIN
  IF current_setting('request.jwt.claims', true) IS NULL THEN
    RAISE NOTICE 'SKIP: configure request.jwt.claims antes de rodar asserts';
    RETURN;
  END IF;
END $$;

-- INSERT: company_id no row deve ser ignorado e substituído pelo JWT
-- INSERT INTO vectraclip.sipoc_sectors (name, slug, company_id)
-- VALUES ('Setor Teste RLS', 'setor-teste-rls-' || gen_random_uuid()::text, '00000000-0000-0000-0000-000000000099');
-- Esperado: company_id = sipoc_company_id(), não o UUID fake do payload
