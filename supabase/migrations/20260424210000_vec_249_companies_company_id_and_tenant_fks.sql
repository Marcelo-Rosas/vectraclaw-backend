-- VEC-249 (plano multi-tenant)
-- 1) Renomeia vectraclip.companies.id -> company_id (PK) e recria FKs filhos.
-- 2) UNIQUE (company_id, id) em tabelas núcleo + FKs compostas para impedir mistura de tenant
--    em caminhos críticos (agents, tasks, goals, incidents, heartbeats, adapters).
--
-- Idempotente: pode ser reaplicado em DBs já migrados (detecta coluna companies.id ausente).

set search_path to vectraclip, public;

-- ---------------------------------------------------------------------------
-- A) companies: dropar FKs que apontam para companies, renomear id, recriar FKs
-- ---------------------------------------------------------------------------
do $$
declare
  r record;
  d text;
  newdef text;
begin
  if to_regclass('vectraclip.companies') is null then
    raise notice 'vec_249: skip — tabela vectraclip.companies não existe';
    return;
  end if;

  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'vectraclip' and table_name = 'companies' and column_name = 'id'
  ) then
    raise notice 'vec_249: skip rename — companies.id já ausente (provavelmente migrado)';
    return;
  end if;

  create temporary table if not exists _vec249_company_fks (
    conname text not null,
    tbl regclass not null,
    def text not null
  ) on commit drop;

  truncate _vec249_company_fks;

  insert into _vec249_company_fks (conname, tbl, def)
  select c.conname, c.conrelid::regclass, pg_get_constraintdef(c.oid)
  from pg_constraint c
  where c.contype = 'f'
    and c.confrelid = 'vectraclip.companies'::regclass;

  for r in select * from _vec249_company_fks loop
    execute format('alter table %s drop constraint if exists %I', r.tbl, r.conname);
  end loop;

  alter table vectraclip.companies rename column id to company_id;

  for r in select * from _vec249_company_fks loop
    d := r.def;
    newdef := replace(d, 'vectraclip.companies(id)', 'vectraclip.companies(company_id)');
    newdef := replace(newdef, 'companies(id)', 'companies(company_id)');
    execute format('alter table %s add constraint %I %s', r.tbl, r.conname, newdef);
  end loop;
end;
$$;

-- ---------------------------------------------------------------------------
-- B) UNIQUE (company_id, entity_id) para permitir FKs compostas
-- ---------------------------------------------------------------------------
do $$
begin
  if to_regclass('vectraclip.agents') is not null then
    alter table vectraclip.agents drop constraint if exists agents_company_entity_key;
    alter table vectraclip.agents
      add constraint agents_company_entity_key unique (company_id, id);
  end if;

  if to_regclass('vectraclip.goals') is not null then
    alter table vectraclip.goals drop constraint if exists goals_company_entity_key;
    alter table vectraclip.goals
      add constraint goals_company_entity_key unique (company_id, id);
  end if;

  if to_regclass('vectraclip.tasks') is not null then
    alter table vectraclip.tasks drop constraint if exists tasks_company_entity_key;
    alter table vectraclip.tasks
      add constraint tasks_company_entity_key unique (company_id, id);
  end if;

  if to_regclass('vectraclip.adapter_catalog') is not null then
    alter table vectraclip.adapter_catalog drop constraint if exists adapter_catalog_company_entity_key;
    alter table vectraclip.adapter_catalog
      add constraint adapter_catalog_company_entity_key unique (company_id, id);
  end if;
end;
$$;

-- ---------------------------------------------------------------------------
-- C) FKs compostas (drop simples por nome conhecido + add composto)
--    Nomes padrão Postgres *_fkey; idempotente com IF EXISTS via catálogo.
-- ---------------------------------------------------------------------------

-- helpers: drop FK by referenced cols (child table, confrelid, array of referenced attnames)
create or replace function vectraclip._vec249_drop_fk_to(
  p_child regclass,
  p_parent regclass,
  p_parent_cols text[]
) returns void
language plpgsql
as $$
declare
  oid_ oid;
begin
  select c.oid into oid_
  from pg_constraint c
  join pg_class rel on rel.oid = c.conrelid
  join pg_namespace n on n.oid = rel.relnamespace
  where c.contype = 'f'
    and c.conrelid = p_child::oid
    and c.confrelid = p_parent::oid
    and (
      select coalesce(array_agg(a.attname::text order by u.ord), array[]::text[])
      from unnest(c.confkey) with ordinality as u(attnum, ord)
      join pg_attribute a on a.attrelid = c.confrelid and a.attnum = u.attnum
    ) = p_parent_cols;

  if oid_ is not null then
    execute format(
      'alter table %s drop constraint if exists %I',
      p_child,
      (select conname from pg_constraint where oid = oid_)
    );
  end if;
end;
$$;

-- goals: parent self-FK
do $$
begin
  if to_regclass('vectraclip.goals') is null then return; end if;
  perform vectraclip._vec249_drop_fk_to('vectraclip.goals'::regclass, 'vectraclip.goals'::regclass, array['id']);
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'vectraclip' and table_name = 'goals' and column_name = 'parent_goal_id'
  ) then
    alter table vectraclip.goals
      add constraint goals_parent_goal_company_fkey
      foreign key (company_id, parent_goal_id)
      references vectraclip.goals (company_id, id)
      on delete set null;
  end if;
exception
  when duplicate_object then null;
end;
$$;

-- tasks: assigned agent, parent task, goal
do $$
begin
  if to_regclass('vectraclip.tasks') is null then return; end if;

  perform vectraclip._vec249_drop_fk_to('vectraclip.tasks'::regclass, 'vectraclip.agents'::regclass, array['id']);
  if exists (select 1 from information_schema.columns where table_schema='vectraclip' and table_name='tasks' and column_name='assigned_to_agent_id') then
    alter table vectraclip.tasks
      add constraint tasks_assigned_agent_company_fkey
      foreign key (company_id, assigned_to_agent_id)
      references vectraclip.agents (company_id, id)
      on delete set null;
  end if;

  perform vectraclip._vec249_drop_fk_to('vectraclip.tasks'::regclass, 'vectraclip.tasks'::regclass, array['id']);
  if exists (select 1 from information_schema.columns where table_schema='vectraclip' and table_name='tasks' and column_name='parent_task_id') then
    alter table vectraclip.tasks
      add constraint tasks_parent_task_company_fkey
      foreign key (company_id, parent_task_id)
      references vectraclip.tasks (company_id, id)
      on delete set null;
  end if;

  if to_regclass('vectraclip.goals') is not null then
    perform vectraclip._vec249_drop_fk_to('vectraclip.tasks'::regclass, 'vectraclip.goals'::regclass, array['id']);
    if exists (select 1 from information_schema.columns where table_schema='vectraclip' and table_name='tasks' and column_name='goal_id') then
      alter table vectraclip.tasks
        add constraint tasks_goal_company_fkey
        foreign key (company_id, goal_id)
        references vectraclip.goals (company_id, id)
        on delete set null;
    end if;
  end if;
exception
  when duplicate_object then null;
end;
$$;

-- agents: reports_to self
do $$
begin
  if to_regclass('vectraclip.agents') is null then return; end if;
  perform vectraclip._vec249_drop_fk_to('vectraclip.agents'::regclass, 'vectraclip.agents'::regclass, array['id']);
  if exists (select 1 from information_schema.columns where table_schema='vectraclip' and table_name='agents' and column_name='reports_to_id') then
    alter table vectraclip.agents
      add constraint agents_reports_to_company_fkey
      foreign key (company_id, reports_to_id)
      references vectraclip.agents (company_id, id)
      on delete set null;
  end if;
exception
  when duplicate_object then null;
end;
$$;

-- incidents -> agents
do $$
begin
  if to_regclass('vectraclip.incidents') is null then return; end if;
  perform vectraclip._vec249_drop_fk_to('vectraclip.incidents'::regclass, 'vectraclip.agents'::regclass, array['id']);
  alter table vectraclip.incidents
    add constraint incidents_agent_company_fkey
    foreign key (company_id, agent_id)
    references vectraclip.agents (company_id, id)
    on delete cascade;
exception
  when duplicate_object then null;
end;
$$;

-- heartbeats -> agents (e task se existir coluna)
do $$
begin
  if to_regclass('vectraclip.heartbeats') is null then return; end if;
  perform vectraclip._vec249_drop_fk_to('vectraclip.heartbeats'::regclass, 'vectraclip.agents'::regclass, array['id']);
  alter table vectraclip.heartbeats
    add constraint heartbeats_agent_company_fkey
    foreign key (company_id, agent_id)
    references vectraclip.agents (company_id, id)
    on delete cascade;
exception
  when duplicate_object then null;
end;
$$;

do $$
begin
  if to_regclass('vectraclip.heartbeats') is null then return; end if;
  if not exists (select 1 from information_schema.columns where table_schema='vectraclip' and table_name='heartbeats' and column_name='task_id') then
    return;
  end if;
  if not exists (select 1 from information_schema.columns where table_schema='vectraclip' and table_name='heartbeats' and column_name='company_id') then
    return;
  end if;
  perform vectraclip._vec249_drop_fk_to('vectraclip.heartbeats'::regclass, 'vectraclip.tasks'::regclass, array['id']);
  alter table vectraclip.heartbeats
    add constraint heartbeats_task_company_fkey
    foreign key (company_id, task_id)
    references vectraclip.tasks (company_id, id)
    on delete set null;
exception
  when duplicate_object then null;
end;
$$;

-- adapter_field_definitions -> adapter_catalog
do $$
begin
  if to_regclass('vectraclip.adapter_field_definitions') is null then return; end if;
  perform vectraclip._vec249_drop_fk_to(
    'vectraclip.adapter_field_definitions'::regclass,
    'vectraclip.adapter_catalog'::regclass,
    array['id']
  );
  alter table vectraclip.adapter_field_definitions
    add constraint adapter_field_definitions_adapter_company_fkey
    foreign key (company_id, adapter_id)
    references vectraclip.adapter_catalog (company_id, id)
    on delete cascade;
exception
  when duplicate_object then null;
end;
$$;

-- agent_adapter_configs -> agents, adapter_catalog
do $$
begin
  if to_regclass('vectraclip.agent_adapter_configs') is null then return; end if;
  perform vectraclip._vec249_drop_fk_to(
    'vectraclip.agent_adapter_configs'::regclass,
    'vectraclip.agents'::regclass,
    array['id']
  );
  perform vectraclip._vec249_drop_fk_to(
    'vectraclip.agent_adapter_configs'::regclass,
    'vectraclip.adapter_catalog'::regclass,
    array['id']
  );
  alter table vectraclip.agent_adapter_configs
    add constraint agent_adapter_configs_agent_company_fkey
    foreign key (company_id, agent_id)
    references vectraclip.agents (company_id, id)
    on delete cascade;
  alter table vectraclip.agent_adapter_configs
    add constraint agent_adapter_configs_adapter_company_fkey
    foreign key (company_id, adapter_id)
    references vectraclip.adapter_catalog (company_id, id)
    on delete restrict;
exception
  when duplicate_object then null;
end;
$$;

-- agent_execution_configs -> agents
do $$
begin
  if to_regclass('vectraclip.agent_execution_configs') is null then return; end if;
  perform vectraclip._vec249_drop_fk_to(
    'vectraclip.agent_execution_configs'::regclass,
    'vectraclip.agents'::regclass,
    array['id']
  );
  alter table vectraclip.agent_execution_configs
    add constraint agent_execution_configs_agent_company_fkey
    foreign key (company_id, agent_id)
    references vectraclip.agents (company_id, id)
    on delete cascade;
exception
  when duplicate_object then null;
end;
$$;

-- managed_agent_sessions: manter FK simples task_id -> tasks(id) (sem company_id na sessão).
do $$
begin
  if to_regclass('vectraclip.managed_agent_sessions') is null or to_regclass('vectraclip.tasks') is null then
    return;
  end if;
  if not exists (
    select 1 from pg_constraint c
    join pg_class rel on rel.oid = c.conrelid
    join pg_namespace n on n.oid = rel.relnamespace
    where n.nspname = 'vectraclip' and rel.relname = 'managed_agent_sessions'
      and c.contype = 'f' and pg_get_constraintdef(c.oid) like '%REFERENCES vectraclip.tasks%'
  ) then
    alter table vectraclip.managed_agent_sessions
      add constraint managed_agent_sessions_task_id_fkey
      foreign key (task_id) references vectraclip.tasks (id) on delete cascade;
  end if;
exception
  when duplicate_object then null;
end;
$$;

drop function if exists vectraclip._vec249_drop_fk_to(regclass, regclass, text[]);
