-- =====================================================================
-- VEC-197: liberar UPDATE e INSERT em vectraclip.agents para o usuário
-- autenticado da mesma company. SELECT já está coberto desde o piloto.
-- =====================================================================

-- UPDATE: pause / resume / kill / PATCH (VEC-196).
create policy "agents_update_own_company"
  on vectraclip.agents
  for update
  using (
    company_id = (
      auth.jwt() -> 'app_metadata' -> 'vectraclip' ->> 'company_id'
    )::uuid
  )
  with check (
    company_id = (
      auth.jwt() -> 'app_metadata' -> 'vectraclip' ->> 'company_id'
    )::uuid
  );

-- INSERT: hire agent (POST /companies/:id/agents).
create policy "agents_insert_own_company"
  on vectraclip.agents
  for insert
  with check (
    company_id = (
      auth.jwt() -> 'app_metadata' -> 'vectraclip' ->> 'company_id'
    )::uuid
  );

-- Grants: RLS só filtra linhas; quem NÃO tem grant da operação
-- nem chega a ser avaliado pelas policies.
grant select, insert, update on vectraclip.agents to authenticated;
