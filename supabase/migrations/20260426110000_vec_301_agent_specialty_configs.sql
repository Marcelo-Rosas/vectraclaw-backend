-- VEC-301: Create vectraclip.agent_specialty_configs table
-- Stores per-agent specialty configuration (one row per agent).

set search_path to vectraclip, public;

create table if not exists vectraclip.agent_specialty_configs (
  id          uuid primary key default gen_random_uuid(),
  company_id  uuid not null references vectraclip.companies(company_id) on delete cascade,
  agent_id    uuid not null references vectraclip.agents(id) on delete cascade,
  specialty_id text not null references vectraclip.agent_specialties(id) on delete restrict,
  values      jsonb not null default '{}',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (agent_id)
);

create index if not exists agent_specialty_configs_company_id_idx
  on vectraclip.agent_specialty_configs(company_id);

alter table vectraclip.agent_specialty_configs enable row level security;

create policy agent_specialty_configs_select on vectraclip.agent_specialty_configs
  for select using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
  );

create policy agent_specialty_configs_insert on vectraclip.agent_specialty_configs
  for insert with check (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = any(array['admin','operator'])
  );

create policy agent_specialty_configs_update on vectraclip.agent_specialty_configs
  for update using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = any(array['admin','operator'])
  ) with check (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = any(array['admin','operator'])
  );

create policy agent_specialty_configs_delete on vectraclip.agent_specialty_configs
  for delete using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = 'admin'
  );
