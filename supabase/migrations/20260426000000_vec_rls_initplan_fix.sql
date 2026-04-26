-- VEC-300: Fix auth_rls_initplan warnings no schema vectraclip
-- Substitui auth.jwt() por (select auth.jwt()) em todas as políticas afetadas.
-- Isso faz o Postgres avaliar o JWT uma vez por query (init plan) em vez de por linha.
-- Também corrige incidents/incident_audit que usavam o caminho errado no JWT.

set search_path to vectraclip, public;

-- Helper expressions (comentário — não executado):
-- company_id_from_jwt : (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
-- role_from_jwt       : (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role'))

-- ---------------------------------------------------------------------------
-- companies
-- ---------------------------------------------------------------------------
drop policy if exists companies_select_own     on vectraclip.companies;
drop policy if exists companies_update_admin   on vectraclip.companies;

create policy companies_select_own on vectraclip.companies
  for select using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
  );

create policy companies_update_admin on vectraclip.companies
  for update using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = 'admin'
  ) with check (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = 'admin'
  );

-- ---------------------------------------------------------------------------
-- agents
-- ---------------------------------------------------------------------------
drop policy if exists agents_select_own_company            on vectraclip.agents;
drop policy if exists agents_insert_own_company_admin_op   on vectraclip.agents;
drop policy if exists agents_update_own_company_admin_op   on vectraclip.agents;
drop policy if exists agents_delete_own_company_admin      on vectraclip.agents;

create policy agents_select_own_company on vectraclip.agents
  for select using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
  );

create policy agents_insert_own_company_admin_op on vectraclip.agents
  for insert with check (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = any(array['admin','operator'])
  );

create policy agents_update_own_company_admin_op on vectraclip.agents
  for update using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = any(array['admin','operator'])
  ) with check (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = any(array['admin','operator'])
  );

create policy agents_delete_own_company_admin on vectraclip.agents
  for delete using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = 'admin'
  );

-- ---------------------------------------------------------------------------
-- app_users
-- ---------------------------------------------------------------------------
drop policy if exists app_users_select_own_company on vectraclip.app_users;
drop policy if exists app_users_insert_admin       on vectraclip.app_users;
drop policy if exists app_users_update_admin       on vectraclip.app_users;
drop policy if exists app_users_delete_admin       on vectraclip.app_users;

create policy app_users_select_own_company on vectraclip.app_users
  for select using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
  );

create policy app_users_insert_admin on vectraclip.app_users
  for insert with check (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = 'admin'
  );

create policy app_users_update_admin on vectraclip.app_users
  for update using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = 'admin'
  ) with check (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = 'admin'
  );

create policy app_users_delete_admin on vectraclip.app_users
  for delete using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = 'admin'
  );

-- ---------------------------------------------------------------------------
-- tasks
-- ---------------------------------------------------------------------------
drop policy if exists tasks_select_own_company          on vectraclip.tasks;
drop policy if exists tasks_insert_own_company_admin_op on vectraclip.tasks;
drop policy if exists tasks_update_own_company_admin_op on vectraclip.tasks;
drop policy if exists tasks_delete_own_company_admin    on vectraclip.tasks;

create policy tasks_select_own_company on vectraclip.tasks
  for select using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
  );

create policy tasks_insert_own_company_admin_op on vectraclip.tasks
  for insert with check (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = any(array['admin','operator'])
  );

create policy tasks_update_own_company_admin_op on vectraclip.tasks
  for update using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = any(array['admin','operator'])
  ) with check (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = any(array['admin','operator'])
  );

create policy tasks_delete_own_company_admin on vectraclip.tasks
  for delete using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = 'admin'
  );

-- ---------------------------------------------------------------------------
-- heartbeats
-- ---------------------------------------------------------------------------
drop policy if exists heartbeats_select_own_company        on vectraclip.heartbeats;
drop policy if exists heartbeats_insert_own_company        on vectraclip.heartbeats;
drop policy if exists heartbeats_update_own_company_admin  on vectraclip.heartbeats;
drop policy if exists heartbeats_delete_own_company_admin  on vectraclip.heartbeats;

create policy heartbeats_select_own_company on vectraclip.heartbeats
  for select using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
  );

create policy heartbeats_insert_own_company on vectraclip.heartbeats
  for insert with check (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = any(array['admin','operator'])
  );

create policy heartbeats_update_own_company_admin on vectraclip.heartbeats
  for update using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = 'admin'
  ) with check (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = 'admin'
  );

create policy heartbeats_delete_own_company_admin on vectraclip.heartbeats
  for delete using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = 'admin'
  );

-- ---------------------------------------------------------------------------
-- incidents (também corrige caminho errado: jwt->>'company_id' → app_metadata.vectraclip)
-- ---------------------------------------------------------------------------
drop policy if exists incidents_select_own_company on vectraclip.incidents;

create policy incidents_select_own_company on vectraclip.incidents
  for select using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
  );

-- ---------------------------------------------------------------------------
-- incident_audit (idem — corrige caminho errado)
-- ---------------------------------------------------------------------------
drop policy if exists incident_audit_select_own_company on vectraclip.incident_audit;

create policy incident_audit_select_own_company on vectraclip.incident_audit
  for select using (
    exists (
      select 1 from vectraclip.incidents i
      where i.id = incident_audit.incident_id
        and i.company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    )
  );

-- ---------------------------------------------------------------------------
-- goals (already uses select wrapper but recreate for consistency)
-- ---------------------------------------------------------------------------
drop policy if exists "company members can manage goals" on vectraclip.goals;

create policy "company members can manage goals" on vectraclip.goals
  for all using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
  );

-- ---------------------------------------------------------------------------
-- adapter_catalog
-- ---------------------------------------------------------------------------
drop policy if exists adapter_catalog_select_authenticated on vectraclip.adapter_catalog;

create policy adapter_catalog_select_authenticated on vectraclip.adapter_catalog
  for select using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
  );

-- ---------------------------------------------------------------------------
-- adapter_field_definitions
-- ---------------------------------------------------------------------------
drop policy if exists adapter_fields_select_authenticated on vectraclip.adapter_field_definitions;

create policy adapter_fields_select_authenticated on vectraclip.adapter_field_definitions
  for select using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
  );

-- ---------------------------------------------------------------------------
-- agent_adapter_configs
-- ---------------------------------------------------------------------------
drop policy if exists agent_adapter_configs_select_authenticated on vectraclip.agent_adapter_configs;

create policy agent_adapter_configs_select_authenticated on vectraclip.agent_adapter_configs
  for select using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
  );

-- ---------------------------------------------------------------------------
-- agent_execution_configs
-- ---------------------------------------------------------------------------
drop policy if exists agent_execution_configs_select_authenticated on vectraclip.agent_execution_configs;

create policy agent_execution_configs_select_authenticated on vectraclip.agent_execution_configs
  for select using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
  );
