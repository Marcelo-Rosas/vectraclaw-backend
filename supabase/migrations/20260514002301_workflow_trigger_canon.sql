-- PR-T1 — Workflow Trigger Canon
--
-- Contexto:
--   Hoje routine é entidade primária (CRUD em /routines + botão "Nova Rotina"),
--   workflow é só editor visual de DAG. O usuário pivotou pra n8n-style:
--   "fonte única de criação passa a ser /workflow; cada workflow decide via
--    toggle se é agendado (cron) ou disparo manual".
--
-- Esta migration:
--   1. Cria catálogo canônico `vectraclip.workflow_trigger_types` (4 slugs:
--      manual, cron, webhook, event). Frontend lê via GET /api/workflow-trigger-types
--      pra renderizar dropdown/chips.
--   2. ALTER `vectraclip.workflow_definitions` adiciona 3 colunas:
--        - trigger_type     text NOT NULL DEFAULT 'manual' (FK pro catálogo)
--        - cron_expression  text NULL
--        - is_scheduled     boolean NOT NULL DEFAULT false (liga/desliga sem
--          perder cron_expression)
--   3. Backfill: pra cada routine com workflow_definition_id apontando pra
--      workflow trigger_type='manual', propaga schedule.cron (jsonb) →
--      workflow.cron_expression + define trigger_type='cron'. Mantém routines
--      vivas (compat com daemon cron existente — PR-T3 futuro irá deprecá-las).
--
-- Schema real (snapshot 20260506025418):
--   routines.schedule       jsonb NOT NULL → ex {"cron":"30 9 * * 1-5","timezone":"..."}
--   routines.status         text ENUM('active','paused','error')
--   (NÃO existem colunas cron_expression nem is_active em routines)
--
-- Idempotente.

set search_path to vectraclip, public;

-- ════════════════════════════════════════════════════════════════════════════
-- 1. Catálogo canônico workflow_trigger_types
-- ════════════════════════════════════════════════════════════════════════════
create table if not exists vectraclip.workflow_trigger_types (
  slug          text primary key,
  name          text not null,
  description   text not null,
  icon          text,                          -- chip do frontend (clock, hand, etc.)
  display_order int not null default 100,
  is_active     boolean not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

insert into vectraclip.workflow_trigger_types
  (slug, name, description, icon, display_order)
values
  ('manual',  'Manual',
   'Disparado por ação humana via UI ou API (POST /tasks/from-workflow). Sem agendamento.',
   'hand', 100),
  ('cron',    'Agendado',
   'Disparado por cron expression em janelas fixas. Daemon cron faz dispatch.',
   'clock', 200),
  ('webhook', 'Webhook',
   'Disparado por POST externo em URL única gerada pelo workflow. Não implementado ainda.',
   'lightning', 300),
  ('event',   'Evento',
   'Disparado por evento interno do sistema (heartbeat, task done, incident). Não implementado ainda.',
   'bell', 400)
on conflict (slug) do update
  set name = excluded.name,
      description = excluded.description,
      icon = excluded.icon,
      display_order = excluded.display_order,
      updated_at = now();

alter table vectraclip.workflow_trigger_types enable row level security;

drop policy if exists workflow_trigger_types_read
  on vectraclip.workflow_trigger_types;
create policy workflow_trigger_types_read
  on vectraclip.workflow_trigger_types
  for select to authenticated
  using (true);

drop policy if exists workflow_trigger_types_write
  on vectraclip.workflow_trigger_types;
create policy workflow_trigger_types_write
  on vectraclip.workflow_trigger_types
  to service_role
  using (true) with check (true);

grant select on vectraclip.workflow_trigger_types to authenticated;
grant select, insert, update, delete on vectraclip.workflow_trigger_types to service_role;

-- ════════════════════════════════════════════════════════════════════════════
-- 2. ALTER workflow_definitions: trigger_type + cron_expression + is_scheduled
-- ════════════════════════════════════════════════════════════════════════════
alter table vectraclip.workflow_definitions
  add column if not exists trigger_type text not null default 'manual';

alter table vectraclip.workflow_definitions
  add column if not exists cron_expression text;

alter table vectraclip.workflow_definitions
  add column if not exists is_scheduled boolean not null default false;

-- FK pro catálogo (idempotente)
alter table vectraclip.workflow_definitions
  drop constraint if exists fk_workflow_definitions_trigger_type;

alter table vectraclip.workflow_definitions
  add constraint fk_workflow_definitions_trigger_type
  foreign key (trigger_type)
  references vectraclip.workflow_trigger_types (slug)
  on delete restrict;

comment on column vectraclip.workflow_definitions.trigger_type is
  'FK para workflow_trigger_types.slug. Define COMO o workflow é disparado (manual, cron, webhook, event).';
comment on column vectraclip.workflow_definitions.cron_expression is
  'Cron expression quando trigger_type=cron. NULL pra outros triggers. Ex: "0 9 * * 1" (segundas 09:00).';
comment on column vectraclip.workflow_definitions.is_scheduled is
  'Liga/desliga agendamento sem perder cron_expression. Útil pra pausar sem reconfigurar.';

-- ════════════════════════════════════════════════════════════════════════════
-- 3. Backfill: routines existentes → workflow.trigger_type='cron'
-- ════════════════════════════════════════════════════════════════════════════
update vectraclip.workflow_definitions wd
   set trigger_type    = 'cron',
       cron_expression = (r.schedule ->> 'cron'),
       is_scheduled    = (coalesce(r.status, 'paused') = 'active'),
       updated_at      = now()
  from vectraclip.routines r
 where r.workflow_definition_id = wd.id
   and (r.schedule ->> 'cron') is not null
   and (r.schedule ->> 'cron') <> ''
   and wd.trigger_type = 'manual';

-- ════════════════════════════════════════════════════════════════════════════
-- 4. Verificação
-- ════════════════════════════════════════════════════════════════════════════
do $$
declare
  v_types     int;
  v_cols      int;
  v_backfilled int;
begin
  select count(*) into v_types
    from vectraclip.workflow_trigger_types
    where is_active = true;

  select count(*) into v_cols
    from information_schema.columns
    where table_schema = 'vectraclip'
      and table_name   = 'workflow_definitions'
      and column_name in ('trigger_type', 'cron_expression', 'is_scheduled');

  select count(*) into v_backfilled
    from vectraclip.workflow_definitions
    where trigger_type = 'cron'
      and cron_expression is not null;

  if v_types >= 4 and v_cols = 3 then
    raise notice 'PR-T1 OK: workflow_trigger_types seed=% workflows cron-backfilled=%',
      v_types, v_backfilled;
  else
    raise warning 'PR-T1: types=% cols=% backfilled=%',
      v_types, v_cols, v_backfilled;
  end if;
end $$;
