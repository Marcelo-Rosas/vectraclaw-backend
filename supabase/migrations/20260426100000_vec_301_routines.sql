-- VEC-301: Create vectraclip.routines table
-- Stores scheduled agent routines per company.

set search_path to vectraclip, public;

create table if not exists vectraclip.routines (
  id          uuid primary key default gen_random_uuid(),
  company_id  uuid not null references vectraclip.companies(company_id) on delete cascade,
  name        text not null,
  status      text not null default 'active' check (status in ('active', 'paused', 'error')),
  schedule    jsonb not null,
  agent_id    uuid references vectraclip.agents(id) on delete set null,
  metadata    jsonb,
  next_run_at timestamptz,
  last_run_at timestamptz,
  created_at  timestamptz not null default now()
);

create index if not exists routines_company_id_idx on vectraclip.routines(company_id);

alter table vectraclip.routines enable row level security;

-- RLS policies (init-plan pattern)
create policy routines_select_own_company on vectraclip.routines
  for select using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
  );

create policy routines_insert_own_company_admin_op on vectraclip.routines
  for insert with check (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = any(array['admin','operator'])
  );

create policy routines_update_own_company_admin_op on vectraclip.routines
  for update using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = any(array['admin','operator'])
  ) with check (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = any(array['admin','operator'])
  );

create policy routines_delete_own_company_admin on vectraclip.routines
  for delete using (
    company_id = (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid
    and (select (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = 'admin'
  );
