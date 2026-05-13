-- Task #43 — Handoff Kronos → Hermes Reporter totalmente relacional
--
-- Acordo arquitetural fixado: "NADA HARDCODADO. Tudo relacional via tabelas."
--
-- Hoje:
--   • kronos_planner.py:68 hardcoda _HERMESREPORTER_AGENT_ID = '360a96cb-...'
--   • kronos_planner.py:269+ chama _create_hermesreporter_task (UUID
--     hardcoded) ao final de _run_planner_import_async
--   • workflow `kronos-planner-flow` (PR #103) tem só 2 steps (Import + Categorize);
--     handoff Reporter fica fora do grafo, escondido em código
--
-- Esta migration + code companion no api.py:run_routine_now + remoção do
-- hardcoded em kronos_planner.py:
--   1. Re-atribui specialty `oracle-report` (Oracle → Hermes Reporter) —
--      drift histórico: specialty estava no Oracle mas o EXECUTOR real é
--      o Hermes Reporter (handler em agents/hermes_reporter.py).
--   2. ADD Step 3 'Hermes Report' ao workflow `kronos-planner-flow`:
--      specialty_slug='oracle-report' → TaskFactory.materialize_workflow
--      resolve responsible agent = Hermes Reporter via _find_agent(spec).
--   3. UPDATE successor/dependency_step_codes (slug-based) nos 3 steps
--      para alinhar com TaskFactory.promote_successors.
--
-- Code companion (separado, no api.py + kronos_planner.py):
--   - run_routine_now chama TaskFactory.materialize_workflow quando
--     routine.workflow_definition_id está preenchido (substitui o
--     INSERT single de 1 task).
--   - REMOVE _HERMESREPORTER_AGENT_ID + _create_hermesreporter_task +
--     chamada em _run_planner_import_async.
--
-- Idempotente.

set search_path to vectraclip, public;

-- ════════════════════════════════════════════════════════════════════════════
-- 1. Re-atribui specialty 'oracle-report' para Hermes Reporter
--    (estava atrelada ao Oracle por drift histórico)
-- ════════════════════════════════════════════════════════════════════════════
-- Remove atribuição antiga (Oracle)
delete from vectraclip.agent_specialty_configs
 where specialty_id = 'oracle-report'
   and agent_id = '00000000-0000-0000-0000-000000000002';  -- Oracle UUID

-- Adiciona atribuição correta (Hermes Reporter — executor real)
insert into vectraclip.agent_specialty_configs
  (company_id, agent_id, specialty_id, values)
values
  ('01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2',
   '360a96cb-b1c3-4b65-b9fa-2b9cbb59dac1',
   'oracle-report',
   '{}'::jsonb)
on conflict (agent_id, specialty_id) do update
  set values = excluded.values,
      updated_at = now();

-- ════════════════════════════════════════════════════════════════════════════
-- 2. Workflow `kronos-planner-flow` ganha Step 3 (Hermes Report)
-- ════════════════════════════════════════════════════════════════════════════
do $$
declare
  v_wf_id    uuid := 'd1e2f3a4-5b6c-4d7e-8f90-123456789012';
  v_step1_id uuid := 'd1e2f3a4-5b6c-4d7e-8f90-000000000001';
  v_step2_id uuid := 'd1e2f3a4-5b6c-4d7e-8f90-000000000002';
  v_step3_id uuid := 'd1e2f3a4-5b6c-4d7e-8f90-000000000003';
begin
  -- Step 3: Hermes Report (specialty=oracle-report → resolve Hermes Reporter)
  insert into vectraclip.workflow_steps
    (id, workflow_id, step_order, name, slug, specialty_slug,
     logic_pattern, responsavel,
     current_operation_type, next_operation_type, default_operation_type,
     dependency_step_codes, proximo_step_codes,
     on_failure_action,
     requires_approval, active)
  values
    (v_step3_id, v_wf_id, 3,
     'Hermes Report', 'hermes-report', 'oracle-report',
     'SIMPLE', 'agente',
     'oracle-report', null, 'oracle-report',
     ARRAY['categorize-pendings']::text[],
     ARRAY[]::text[],
     'block',
     false, true)
  on conflict (id) do update
    set logic_pattern = excluded.logic_pattern,
        responsavel = excluded.responsavel,
        specialty_slug = excluded.specialty_slug,
        current_operation_type = excluded.current_operation_type,
        default_operation_type = excluded.default_operation_type,
        dependency_step_codes = excluded.dependency_step_codes,
        proximo_step_codes = excluded.proximo_step_codes;

  -- Step 1: agora aponta succ → categorize-pendings (slug-based, alinha TaskFactory)
  update vectraclip.workflow_steps
     set proximo_step_codes = ARRAY['categorize-pendings']::text[],
         dependency_step_codes = ARRAY[]::text[]
   where id = v_step1_id;

  -- Step 2: agora tem succ → hermes-report + dep ← import-ofx
  update vectraclip.workflow_steps
     set proximo_step_codes = ARRAY['hermes-report']::text[],
         dependency_step_codes = ARRAY['import-ofx']::text[],
         next_operation_type = 'oracle-report'
   where id = v_step2_id;
end $$;

-- ════════════════════════════════════════════════════════════════════════════
-- 3. Verificação
-- ════════════════════════════════════════════════════════════════════════════
do $$
declare
  v_steps int;
  v_oracle_report_owner uuid;
  v_step3_specialty text;
begin
  select count(*) into v_steps
    from vectraclip.workflow_steps
    where workflow_id = 'd1e2f3a4-5b6c-4d7e-8f90-123456789012'
      and active = true;

  select agent_id into v_oracle_report_owner
    from vectraclip.agent_specialty_configs
    where specialty_id = 'oracle-report'
    limit 1;

  select specialty_slug into v_step3_specialty
    from vectraclip.workflow_steps
    where id = 'd1e2f3a4-5b6c-4d7e-8f90-000000000003';

  if v_steps = 3
     and v_oracle_report_owner = '360a96cb-b1c3-4b65-b9fa-2b9cbb59dac1'
     and v_step3_specialty = 'oracle-report' then
    raise notice 'Task #43 OK: 3 steps no workflow, oracle-report no Hermes Reporter, Step 3 vinculado';
  else
    raise warning 'Task #43: steps=%, oracle_report_owner=%, step3_specialty=%',
      v_steps, v_oracle_report_owner, v_step3_specialty;
  end if;
end $$;
