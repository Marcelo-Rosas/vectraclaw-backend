-- VEC-325: 5W2H V2 Sprint 2 prep — contract versioning and validation tracking
-- Adds contract_version, validation_status and validation_errors to workflow_steps.
-- validation_status follows the existing 'verde/amarelo/vermelho' convention
-- already used in sipoc_components (VEC-246).

set search_path to vectraclip, public;

alter table vectraclip.workflow_steps
  add column if not exists contract_version  text    not null default 'v1',
  add column if not exists validation_status text    not null default 'verde',
  add column if not exists validation_errors jsonb   not null default '[]'::jsonb;

-- Backfill: steps that already have sipoc_meta with fiveW2H are v2
update vectraclip.workflow_steps
set contract_version = 'v2'
where sipoc_meta ? 'fiveW2H'
  and contract_version = 'v1';

-- Constraint: only known status values allowed
alter table vectraclip.workflow_steps
  drop constraint if exists workflow_steps_validation_status_check;

alter table vectraclip.workflow_steps
  add constraint workflow_steps_validation_status_check
  check (validation_status in ('verde', 'amarelo', 'vermelho'));
