-- VEC-201
-- Tabela de preços de modelos LLM (Anthropic MVP) para o schema vectraclip.
-- Observação: tabela desenhada para histórico de preços via (id, effective_from).

create table if not exists vectraclip.llm_models (
  id text not null,
  provider text not null,
  display_name text not null,
  input_cost_per_1m numeric(12,4) not null check (input_cost_per_1m >= 0),
  output_cost_per_1m numeric(12,4) not null check (output_cost_per_1m >= 0),
  cache_read_cost_per_1m numeric(12,4) not null check (cache_read_cost_per_1m >= 0),
  context_window_k integer not null check (context_window_k > 0),
  is_active boolean not null default true,
  effective_from date not null,
  created_at timestamptz not null default now(),
  primary key (id, effective_from)
);

create index if not exists llm_models_provider_is_active_idx
  on vectraclip.llm_models (provider, is_active);

alter table vectraclip.llm_models enable row level security;

revoke all on table vectraclip.llm_models from anon;
revoke all on table vectraclip.llm_models from authenticated;
revoke all on table vectraclip.llm_models from service_role;

grant select on table vectraclip.llm_models to authenticated;
grant select, insert, update on table vectraclip.llm_models to service_role;

drop policy if exists llm_models_select_authenticated on vectraclip.llm_models;
create policy llm_models_select_authenticated
  on vectraclip.llm_models
  for select
  to authenticated
  using (true);

drop policy if exists llm_models_insert_service_role on vectraclip.llm_models;
create policy llm_models_insert_service_role
  on vectraclip.llm_models
  for insert
  to service_role
  with check (true);

drop policy if exists llm_models_update_service_role on vectraclip.llm_models;
create policy llm_models_update_service_role
  on vectraclip.llm_models
  for update
  to service_role
  using (true)
  with check (true);

insert into vectraclip.llm_models (
  id,
  provider,
  display_name,
  input_cost_per_1m,
  output_cost_per_1m,
  cache_read_cost_per_1m,
  context_window_k,
  is_active,
  effective_from
)
values
  ('claude-opus-4-5', 'anthropic', 'Claude Opus 4.5', 15.00, 75.00, 1.50, 200, true, '2026-01-01'),
  ('claude-sonnet-4-5', 'anthropic', 'Claude Sonnet 4.5', 3.00, 15.00, 0.30, 200, true, '2026-01-01'),
  ('claude-3-7-sonnet-20250219', 'anthropic', 'Claude 3.7 Sonnet', 3.00, 15.00, 0.30, 200, true, '2025-02-01'),
  ('claude-3-5-sonnet-20241022', 'anthropic', 'Claude 3.5 Sonnet', 3.00, 15.00, 0.30, 200, false, '2024-10-01'),
  ('claude-3-5-haiku-20241022', 'anthropic', 'Claude 3.5 Haiku', 0.80, 4.00, 0.08, 200, false, '2024-10-01'),
  ('claude-opus-4-7-thinking-high', 'anthropic', 'Claude Opus 4.7 (Extended Thinking)', 15.00, 75.00, 1.50, 200, true, '2026-01-01'),
  ('claude-4.6-sonnet-medium-thinking', 'anthropic', 'Claude Sonnet 4.6 (Medium Thinking)', 3.00, 15.00, 0.30, 200, true, '2026-01-01'),
  ('claude-4.5-sonnet', 'anthropic', 'Claude Sonnet 4.5', 3.00, 15.00, 0.30, 200, true, '2025-10-01')
on conflict on constraint llm_models_pkey do update
set
  provider = excluded.provider,
  display_name = excluded.display_name,
  input_cost_per_1m = excluded.input_cost_per_1m,
  output_cost_per_1m = excluded.output_cost_per_1m,
  cache_read_cost_per_1m = excluded.cache_read_cost_per_1m,
  context_window_k = excluded.context_window_k,
  is_active = excluded.is_active;
