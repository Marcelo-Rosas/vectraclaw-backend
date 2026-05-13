-- Task #41 — Enriquecer os 4 steps Kronos com campos que estavam NULL
--
-- Auditoria expôs que workflow_steps tem 33 colunas (incluindo logic_pattern,
-- responsavel, current_operation_type, next_operation_type, etc.) mas os 4
-- steps dos workflows do Kronos (kronos-audit + kronos-hermes-handoff) tinham
-- quase tudo NULL — herdadas de migrations VEC-330 antes do Workflow Builder
-- rich existir.
--
-- Sem esses campos preenchidos:
--   - /workflow frontend renderiza com placeholders genéricos
--   - morpheus_dispatcher não consegue rotear por current/next_operation_type
--   - Visualização de "responsável" e "logic_pattern" fica vazia
--
-- Fix: UPDATE em 4 rows específicas com valores semanticamente corretos.
-- Idempotente: WHERE filtra por id + atual NULL (re-run não muda nada).

set search_path to vectraclip, public;

-- ════════════════════════════════════════════════════════════════════════════
-- Workflow kronos-audit (3 steps, todos no fluxo financial-audit)
-- ════════════════════════════════════════════════════════════════════════════

-- Step 1: Parse Inputs → continua em financial-audit (próximo é Reconcile)
update vectraclip.workflow_steps
   set logic_pattern = 'SIMPLE',
       responsavel = 'agente',
       current_operation_type = 'financial-audit',
       next_operation_type = 'financial-audit',
       default_operation_type = 'financial-audit'
 where id = 'c0de0001-0000-0000-0000-000000000330'
   and (logic_pattern is null or responsavel is null);

-- Step 2: Reconcile → continua em financial-audit (próximo é Report)
update vectraclip.workflow_steps
   set logic_pattern = 'SIMPLE',
       responsavel = 'agente',
       current_operation_type = 'financial-audit',
       next_operation_type = 'financial-audit',
       default_operation_type = 'financial-audit'
 where id = 'c0de0002-0000-0000-0000-000000000330'
   and (logic_pattern is null or responsavel is null);

-- Step 3: Report & Dispatch → next=oracle-report (handoff HermesReporter)
update vectraclip.workflow_steps
   set logic_pattern = 'SIMPLE',
       responsavel = 'agente',
       current_operation_type = 'financial-audit',
       next_operation_type = 'oracle-report',
       default_operation_type = 'financial-audit'
 where id = 'c0de0003-0000-0000-0000-000000000330'
   and (logic_pattern is null or responsavel is null);

-- ════════════════════════════════════════════════════════════════════════════
-- Workflow kronos-hermes-handoff (1 step, terminal)
-- ════════════════════════════════════════════════════════════════════════════

-- Step 1: Hermes Reporter → current=oracle-report (já era SIMPLE), next=NULL (terminal)
update vectraclip.workflow_steps
   set responsavel = 'agente',
       current_operation_type = 'oracle-report',
       default_operation_type = 'oracle-report'
       -- logic_pattern já era 'SIMPLE', next_operation_type fica NULL (terminal)
 where workflow_id = '1b9e21d9-b277-4204-a7a9-1877d00f19eb'
   and step_order = 1
   and responsavel is null;

-- ════════════════════════════════════════════════════════════════════════════
-- Verificação
-- ════════════════════════════════════════════════════════════════════════════
do $$
declare
  v_null_logic int;
  v_null_resp int;
  v_null_curr_op int;
begin
  select count(*) into v_null_logic
    from vectraclip.workflow_steps
    where workflow_id in (
      'c0de0000-0000-0000-0000-000000000330',
      '1b9e21d9-b277-4204-a7a9-1877d00f19eb'
    )
    and logic_pattern is null;

  select count(*) into v_null_resp
    from vectraclip.workflow_steps
    where workflow_id in (
      'c0de0000-0000-0000-0000-000000000330',
      '1b9e21d9-b277-4204-a7a9-1877d00f19eb'
    )
    and responsavel is null;

  select count(*) into v_null_curr_op
    from vectraclip.workflow_steps
    where workflow_id in (
      'c0de0000-0000-0000-0000-000000000330',
      '1b9e21d9-b277-4204-a7a9-1877d00f19eb'
    )
    and current_operation_type is null;

  if v_null_logic = 0 and v_null_resp = 0 and v_null_curr_op = 0 then
    raise notice 'Task #41 OK: 4 Kronos steps enriquecidos (logic_pattern/responsavel/current_op preenchidos)';
  else
    raise warning 'Task #41: nulls remanescentes — logic=% resp=% curr_op=%',
      v_null_logic, v_null_resp, v_null_curr_op;
  end if;
end $$;
