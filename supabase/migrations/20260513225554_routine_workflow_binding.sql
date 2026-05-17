-- Task #44 — Routine vincula workflow_id à task
--
-- Hoje routines criam tasks sem workflow_step_id (api.py:run_routine_now).
-- Consequências:
--   • TaskFactory.promote_successors_after_completion não tem por onde
--     avançar o DAG quando task pai termina.
--   • /workflow tree não mostra execuções de rotinas.
--   • Engine v2 (advance_v2 #102) não consegue ser invocado pelos handlers
--     porque task.workflow_step_id é sempre NULL.
--
-- Esta migration:
--   1. ALTER vectraclip.routines ADD COLUMN workflow_definition_id uuid NULL
--      FK references workflow_definitions(id) ON DELETE SET NULL.
--   2. Cria workflow definition `kronos-planner-flow` com 2 steps encadeados:
--        Step 1 (planner-import-ofx)  → on_success → Step 2
--        Step 2 (planner-categorize-pendings) → terminal
--      Ambos SIMPLE/agente, com current_operation_type populado.
--   3. UPDATE routine 'Lançamentos - Meu Planner' SET workflow_definition_id.
--   4. UPDATE workflow_logic_patterns.engine_handler para refletir #102
--      (SIMPLE e SPLIT-IF agora têm handler real: workflow_engine.advance_v2).
--
-- Code change companion em src/api.py:run_routine_now propaga
-- workflow_step_id no task_payload.
--
-- Idempotente.

set search_path to vectraclip, public;

-- ════════════════════════════════════════════════════════════════════════════
-- 1. ALTER routines ADD COLUMN workflow_definition_id
-- ════════════════════════════════════════════════════════════════════════════
alter table vectraclip.routines
  add column if not exists workflow_definition_id uuid null;

-- FK pode falhar em re-run se já existir — drop antes de add
alter table vectraclip.routines
  drop constraint if exists fk_routines_workflow_definition;

alter table vectraclip.routines
  add constraint fk_routines_workflow_definition
  foreign key (workflow_definition_id)
  references vectraclip.workflow_definitions (id)
  on delete set null;

comment on column vectraclip.routines.workflow_definition_id is
  'FK opcional para vectraclip.workflow_definitions. Quando preenchido, run_routine_now busca o primeiro step (step_order=1) e propaga seu id como task.workflow_step_id. Vazio = task standalone (sem grafo).';

-- ════════════════════════════════════════════════════════════════════════════
-- 2. INSERT workflow_definition kronos-planner-flow + 2 steps
-- ════════════════════════════════════════════════════════════════════════════
do $$
declare
  v_wf_id    uuid := 'd1e2f3a4-5b6c-4d7e-8f90-123456789012';
  v_step1_id uuid := 'd1e2f3a4-5b6c-4d7e-8f90-000000000001';
  v_step2_id uuid := 'd1e2f3a4-5b6c-4d7e-8f90-000000000002';
begin
  -- Workflow
  insert into vectraclip.workflow_definitions
    (id, slug, name, description, is_active, company_id)
  values
    (v_wf_id, 'kronos-planner-flow',
     'Kronos — Pipeline Meu Planner (Import + Categorize)',
     'Disparado pela rotina agendada. Step 1: planner-import-ofx (upload Playwright). Step 2: planner-categorize-pendings (regras YAML). Handoff oracle-report fica no handler até task #43.',
     true, null)  -- global (templates podem ser company_id NULL)
  on conflict (id) do update
    set name = excluded.name,
        description = excluded.description,
        is_active = true;

  -- Step 2 primeiro (FK on_success_step_id do step 1 aponta para step 2)
  insert into vectraclip.workflow_steps
    (id, workflow_id, step_order, name, slug, specialty_slug,
     logic_pattern, responsavel,
     current_operation_type, next_operation_type, default_operation_type,
     on_success_step_id, on_failure_action,
     requires_approval, active)
  values
    (v_step2_id, v_wf_id, 2,
     'Categorize Pendings', 'categorize-pendings', 'planner-categorize-pendings',
     'SIMPLE', 'agente',
     'planner-categorize-pendings', null, 'planner-categorize-pendings',
     null,  -- terminal (handoff oracle-report fica no handler até #43)
     'block',
     false, true)
  on conflict (id) do update
    set logic_pattern = excluded.logic_pattern,
        responsavel = excluded.responsavel,
        current_operation_type = excluded.current_operation_type,
        next_operation_type = excluded.next_operation_type,
        default_operation_type = excluded.default_operation_type;

  -- Step 1: Import OFX (após step 2 existir para satisfazer FK)
  insert into vectraclip.workflow_steps
    (id, workflow_id, step_order, name, slug, specialty_slug,
     logic_pattern, responsavel,
     current_operation_type, next_operation_type, default_operation_type,
     on_success_step_id, on_failure_action,
     requires_approval, active)
  values
    (v_step1_id, v_wf_id, 1,
     'Import OFX', 'import-ofx', 'planner-import-ofx',
     'SIMPLE', 'agente',
     'planner-import-ofx', 'planner-categorize-pendings', 'planner-import-ofx',
     v_step2_id, 'block',
     false, true)
  on conflict (id) do update
    set logic_pattern = excluded.logic_pattern,
        responsavel = excluded.responsavel,
        current_operation_type = excluded.current_operation_type,
        next_operation_type = excluded.next_operation_type,
        default_operation_type = excluded.default_operation_type,
        on_success_step_id = excluded.on_success_step_id;
end $$;

-- ════════════════════════════════════════════════════════════════════════════
-- 3. UPDATE routine 'Lançamentos - Meu Planner' → workflow_definition_id
-- ════════════════════════════════════════════════════════════════════════════
update vectraclip.routines
   set workflow_definition_id = 'd1e2f3a4-5b6c-4d7e-8f90-123456789012'
 where agent_id = '9c8d7e6f-5a4b-4321-9876-543210fedcba'
   and operation_type = 'planner-import-ofx'
   and workflow_definition_id is null;

-- ════════════════════════════════════════════════════════════════════════════
-- 4. UPDATE workflow_logic_patterns.engine_handler refletindo PR #102
-- ════════════════════════════════════════════════════════════════════════════
update vectraclip.workflow_logic_patterns
   set engine_handler = 'workflow_engine.advance_v2',
       updated_at = now()
 where taxonomy in ('SIMPLE', 'SPLIT-IF')
   and engine_handler in ('WorkflowEngine.advance', 'pending');

-- ════════════════════════════════════════════════════════════════════════════
-- 5. Verificação
-- ════════════════════════════════════════════════════════════════════════════
do $$
declare
  v_routine_linked int;
  v_wf_steps int;
  v_handlers_real int;
begin
  select count(*) into v_routine_linked
    from vectraclip.routines
    where agent_id = '9c8d7e6f-5a4b-4321-9876-543210fedcba'
      and workflow_definition_id is not null;

  select count(*) into v_wf_steps
    from vectraclip.workflow_steps
    where workflow_id = 'd1e2f3a4-5b6c-4d7e-8f90-123456789012';

  select count(*) into v_handlers_real
    from vectraclip.workflow_logic_patterns
    where engine_handler = 'workflow_engine.advance_v2';

  if v_routine_linked >= 1 and v_wf_steps = 2 and v_handlers_real = 2 then
    raise notice 'Task #44 OK: routine vinculada, workflow com 2 steps, 2 handlers reais (SIMPLE + SPLIT-IF)';
  else
    raise warning 'Task #44: routine_linked=%, wf_steps=%, handlers_real=%',
      v_routine_linked, v_wf_steps, v_handlers_real;
  end if;
end $$;
