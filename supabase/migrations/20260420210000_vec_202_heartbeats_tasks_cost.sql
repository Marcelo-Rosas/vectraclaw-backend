-- VEC-202
-- Enriquecimento de heartbeats e tasks para custo real (USD) e tipo de operação.

alter table vectraclip.heartbeats
  add column if not exists input_tokens integer default 0,
  add column if not exists output_tokens integer default 0,
  add column if not exists cache_read_tokens integer default 0,
  add column if not exists model_id text,
  add column if not exists cost_usd numeric(12,8);

alter table vectraclip.heartbeats
  alter column input_tokens set default 0,
  alter column output_tokens set default 0,
  alter column cache_read_tokens set default 0;

update vectraclip.heartbeats
set
  input_tokens = coalesce(input_tokens, 0),
  output_tokens = coalesce(output_tokens, 0),
  cache_read_tokens = coalesce(cache_read_tokens, 0)
where input_tokens is null
   or output_tokens is null
   or cache_read_tokens is null;

alter table vectraclip.heartbeats
  alter column input_tokens set not null,
  alter column output_tokens set not null,
  alter column cache_read_tokens set not null;

alter table vectraclip.heartbeats
  drop constraint if exists heartbeats_input_tokens_nonnegative,
  drop constraint if exists heartbeats_output_tokens_nonnegative,
  drop constraint if exists heartbeats_cache_read_tokens_nonnegative,
  add constraint heartbeats_input_tokens_nonnegative check (input_tokens >= 0),
  add constraint heartbeats_output_tokens_nonnegative check (output_tokens >= 0),
  add constraint heartbeats_cache_read_tokens_nonnegative check (cache_read_tokens >= 0),
  add constraint heartbeats_cost_usd_nonnegative check (cost_usd is null or cost_usd >= 0);

alter table vectraclip.tasks
  add column if not exists operation_type text default 'other',
  add column if not exists cost_usd numeric(12,8) default 0;

update vectraclip.tasks
set
  operation_type = coalesce(operation_type, 'other'),
  cost_usd = coalesce(cost_usd, 0)
where operation_type is null
   or cost_usd is null;

alter table vectraclip.tasks
  alter column operation_type set default 'other',
  alter column operation_type set not null,
  alter column cost_usd set default 0,
  alter column cost_usd set not null;

alter table vectraclip.tasks
  drop constraint if exists tasks_operation_type_check,
  add constraint tasks_operation_type_check
    check (operation_type in (
      'orchestration',
      'code_generation',
      'code_review',
      'research',
      'document_generation',
      'qa_testing',
      'other'
    )),
  add constraint tasks_cost_usd_nonnegative check (cost_usd >= 0);

create index if not exists heartbeats_model_id_idx
  on vectraclip.heartbeats (model_id);

create index if not exists tasks_operation_type_idx
  on vectraclip.tasks (operation_type);

-- Nota: como `vectraclip.llm_models` usa histórico por `(id, effective_from)`,
-- uma FK nativa apenas por `id` impediria múltiplas versões no tempo.
-- Este trigger mantém integridade referencial de `heartbeats.model_id` por `id`.
create or replace function vectraclip.validate_heartbeat_model_id()
returns trigger
language plpgsql
as $$
begin
  if new.model_id is null then
    return new;
  end if;

  if exists (
    select 1
    from vectraclip.llm_models m
    where m.id = new.model_id
  ) then
    return new;
  end if;

  raise exception 'model_id % not found in vectraclip.llm_models', new.model_id;
end;
$$;

drop trigger if exists trg_heartbeats_validate_model_id on vectraclip.heartbeats;
create trigger trg_heartbeats_validate_model_id
before insert or update of model_id
on vectraclip.heartbeats
for each row
execute function vectraclip.validate_heartbeat_model_id();
