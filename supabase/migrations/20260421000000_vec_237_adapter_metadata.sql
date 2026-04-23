-- VEC-237
-- Metadata-driven adapters: catálogo, definição de campos e config por agente.

create table if not exists vectraclip.adapter_catalog (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references vectraclip.companies(id) on delete cascade,
  slug text not null,
  display_name text not null,
  provider text not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (company_id, slug)
);

create table if not exists vectraclip.adapter_field_definitions (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references vectraclip.companies(id) on delete cascade,
  adapter_id uuid not null references vectraclip.adapter_catalog(id) on delete cascade,
  field_key text not null,
  field_label text not null,
  field_type text not null check (
    field_type in (
      'text',
      'textarea',
      'number',
      'boolean',
      'select',
      'multiselect',
      'file_upload',
      'secret'
    )
  ),
  is_required boolean not null default false,
  options_json jsonb,
  trigger_condition jsonb,
  sort_order integer not null default 100,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (company_id, adapter_id, field_key)
);

create table if not exists vectraclip.agent_adapter_configs (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references vectraclip.companies(id) on delete cascade,
  agent_id uuid not null references vectraclip.agents(id) on delete cascade,
  adapter_id uuid not null references vectraclip.adapter_catalog(id) on delete restrict,
  field_values_json jsonb not null default '{}'::jsonb,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (agent_id),
  unique (company_id, agent_id)
);

create index if not exists adapter_catalog_company_active_idx
  on vectraclip.adapter_catalog(company_id, is_active);

create index if not exists adapter_field_definitions_adapter_active_idx
  on vectraclip.adapter_field_definitions(adapter_id, is_active, sort_order);

create index if not exists adapter_field_definitions_company_adapter_idx
  on vectraclip.adapter_field_definitions(company_id, adapter_id);

create index if not exists agent_adapter_configs_company_agent_idx
  on vectraclip.agent_adapter_configs(company_id, agent_id);

create index if not exists agent_adapter_configs_adapter_idx
  on vectraclip.agent_adapter_configs(adapter_id);

alter table vectraclip.adapter_catalog enable row level security;
alter table vectraclip.adapter_field_definitions enable row level security;
alter table vectraclip.agent_adapter_configs enable row level security;

revoke all on table vectraclip.adapter_catalog from anon, authenticated, service_role;
revoke all on table vectraclip.adapter_field_definitions from anon, authenticated, service_role;
revoke all on table vectraclip.agent_adapter_configs from anon, authenticated, service_role;

grant select on table vectraclip.adapter_catalog to authenticated;
grant select on table vectraclip.adapter_field_definitions to authenticated;
grant select on table vectraclip.agent_adapter_configs to authenticated;

grant select, insert, update, delete on table vectraclip.adapter_catalog to service_role;
grant select, insert, update, delete on table vectraclip.adapter_field_definitions to service_role;
grant select, insert, update, delete on table vectraclip.agent_adapter_configs to service_role;

drop policy if exists adapter_catalog_select_authenticated on vectraclip.adapter_catalog;
create policy adapter_catalog_select_authenticated
  on vectraclip.adapter_catalog
  for select
  to authenticated
  using (((auth.jwt() -> 'app_metadata' -> 'vectraclip' ->> 'company_id')::uuid = company_id));

drop policy if exists adapter_fields_select_authenticated on vectraclip.adapter_field_definitions;
create policy adapter_fields_select_authenticated
  on vectraclip.adapter_field_definitions
  for select
  to authenticated
  using (((auth.jwt() -> 'app_metadata' -> 'vectraclip' ->> 'company_id')::uuid = company_id));

drop policy if exists agent_adapter_configs_select_authenticated on vectraclip.agent_adapter_configs;
create policy agent_adapter_configs_select_authenticated
  on vectraclip.agent_adapter_configs
  for select
  to authenticated
  using (((auth.jwt() -> 'app_metadata' -> 'vectraclip' ->> 'company_id')::uuid = company_id));

drop policy if exists adapter_catalog_write_service_role on vectraclip.adapter_catalog;
create policy adapter_catalog_write_service_role
  on vectraclip.adapter_catalog
  as permissive
  for all
  to service_role
  using (true)
  with check (true);

drop policy if exists adapter_fields_write_service_role on vectraclip.adapter_field_definitions;
create policy adapter_fields_write_service_role
  on vectraclip.adapter_field_definitions
  as permissive
  for all
  to service_role
  using (true)
  with check (true);

drop policy if exists agent_adapter_configs_write_service_role on vectraclip.agent_adapter_configs;
create policy agent_adapter_configs_write_service_role
  on vectraclip.agent_adapter_configs
  as permissive
  for all
  to service_role
  using (true)
  with check (true);

-- Seed adapter catálogo por company.
insert into vectraclip.adapter_catalog (company_id, slug, display_name, provider, is_active)
select c.id, v.slug, v.display_name, v.provider, true
from vectraclip.companies c
cross join (
  values
    ('claude_code', 'Claude Code', 'anthropic'),
    ('codex', 'Codex', 'openai'),
    ('shell', 'Shell Runner', 'internal'),
    ('webhook', 'Webhook Bridge', 'internal')
) as v(slug, display_name, provider)
on conflict (company_id, slug) do update
set display_name = excluded.display_name,
    provider = excluded.provider,
    is_active = excluded.is_active,
    updated_at = now();

-- Seed fields dinâmicos de exemplo por adapter.
insert into vectraclip.adapter_field_definitions (
  company_id, adapter_id, field_key, field_label, field_type, is_required, options_json, sort_order, is_active
)
select ac.company_id, ac.id, fd.field_key, fd.field_label, fd.field_type, fd.is_required, fd.options_json, fd.sort_order, true
from vectraclip.adapter_catalog ac
join (
  values
    ('claude_code','model_id','Modelo LLM','select',true,'{"source":"llm_models","provider":"anthropic"}'::jsonb,10),
    ('claude_code','temperature','Temperature','number',false,null::jsonb,20),
    ('claude_code','max_tokens','Max tokens','number',false,null::jsonb,30),
    ('claude_code','rag_storage_url','Storage (RAG)','file_upload',false,null::jsonb,40),
    ('codex','model_id','Modelo LLM','text',true,null::jsonb,10),
    ('codex','temperature','Temperature','number',false,null::jsonb,20),
    ('shell','command_allowlist','Command allowlist','textarea',false,null::jsonb,10),
    ('webhook','endpoint_url','Endpoint URL','text',true,null::jsonb,10),
    ('webhook','auth_header','Auth Header','secret',false,null::jsonb,20)
) as fd(adapter_slug, field_key, field_label, field_type, is_required, options_json, sort_order)
  on ac.slug = fd.adapter_slug
on conflict (company_id, adapter_id, field_key) do update
set field_label = excluded.field_label,
    field_type = excluded.field_type,
    is_required = excluded.is_required,
    options_json = excluded.options_json,
    sort_order = excluded.sort_order,
    is_active = true,
    updated_at = now();

-- Seed config inicial por agente existente.
insert into vectraclip.agent_adapter_configs (company_id, agent_id, adapter_id, field_values_json, is_active)
select
  a.company_id,
  a.id,
  ac.id as adapter_id,
  case
    when ac.slug = 'claude_code' then jsonb_build_object('model_id','claude-opus-4-7-thinking-high','temperature',0.2,'max_tokens',8192)
    when ac.slug = 'codex' then jsonb_build_object('model_id','gpt-5.2-codex','temperature',0.2)
    else '{}'::jsonb
  end as field_values_json,
  true
from vectraclip.agents a
join vectraclip.adapter_catalog ac
  on ac.company_id = a.company_id
 and ac.slug = a.adapter_type
on conflict (agent_id) do update
set adapter_id = excluded.adapter_id,
    company_id = excluded.company_id,
    field_values_json = excluded.field_values_json,
    is_active = true,
    updated_at = now();
