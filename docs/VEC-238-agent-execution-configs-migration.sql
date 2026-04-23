-- VEC-238
-- Execução por agente: modo (REALTIME/CRON/TRIGGER), trigger JSON, URL de function e refs de auth.
-- Tabela dedicada 1:1 com agents; company-scoped com RLS alinhado ao padrão VEC-237.

create table if not exists vectraclip.agent_execution_configs (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references vectraclip.companies(id) on delete cascade,
  agent_id uuid not null references vectraclip.agents(id) on delete cascade,
  execution_mode text not null check (execution_mode in ('REALTIME', 'CRON', 'TRIGGER')),
  trigger_config jsonb not null default '{}'::jsonb,
  function_url text,
  auth_secret_ref text,
  auth_header_name text,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (agent_id),
  unique (company_id, agent_id)
);

create index if not exists agent_execution_configs_company_active_idx
  on vectraclip.agent_execution_configs(company_id, is_active);

create index if not exists agent_execution_configs_agent_idx
  on vectraclip.agent_execution_configs(agent_id);

create or replace function vectraclip.agent_execution_configs_sync_company_agent()
returns trigger
language plpgsql
as $$
declare
  agent_company uuid;
begin
  select a.company_id
    into agent_company
  from vectraclip.agents a
  where a.id = new.agent_id;

  if agent_company is null then
    raise exception 'agent_id % not found in vectraclip.agents', new.agent_id;
  end if;

  if new.company_id is distinct from agent_company then
    raise exception 'company_id mismatch for agent_id % (expected %, got %)',
      new.agent_id, agent_company, new.company_id;
  end if;

  return new;
end;
$$;

drop trigger if exists trg_agent_execution_configs_sync_company_agent
  on vectraclip.agent_execution_configs;
create trigger trg_agent_execution_configs_sync_company_agent
before insert or update of company_id, agent_id
on vectraclip.agent_execution_configs
for each row
execute function vectraclip.agent_execution_configs_sync_company_agent();

alter table vectraclip.agent_execution_configs enable row level security;

revoke all on table vectraclip.agent_execution_configs from anon, authenticated, service_role;

grant select on table vectraclip.agent_execution_configs to authenticated;

grant select, insert, update, delete on table vectraclip.agent_execution_configs to service_role;

drop policy if exists agent_execution_configs_select_authenticated
  on vectraclip.agent_execution_configs;
create policy agent_execution_configs_select_authenticated
  on vectraclip.agent_execution_configs
  for select
  to authenticated
  using (((auth.jwt() -> 'app_metadata' -> 'vectraclip' ->> 'company_id')::uuid = company_id));

drop policy if exists agent_execution_configs_write_service_role
  on vectraclip.agent_execution_configs;
create policy agent_execution_configs_write_service_role
  on vectraclip.agent_execution_configs
  as permissive
  for all
  to service_role
  using (true)
  with check (true);
