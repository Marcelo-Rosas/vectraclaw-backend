-- M4 do plano Brain → Daedalus. Adiciona 4 op_types pros novos handlers
-- orchestration de Daedalus. M1 (PR #240) cravou specialties em
-- agent_specialty_configs com status=stub_until_m4. Agora ativa.
--
-- ESPELHEI ANTES (Regra #1):
--   - tasks_operation_type_check foi DROPADO em A.2 (2026-05-17). Validação
--     agora vive em src/api.py:_validate_operation_type via lookup catalog.
--     Logo só preciso INSERT em operation_types_catalog (sem ALTER CHECK).
--   - agent_specialty_configs.values existente tem operation_types com naming
--     workflow-* (vide PR #240). Renomear pra daedalus-* pra alinhar com
--     prefix dispatch (agent_daemon.py:629 já cobre bpmn-, vai cobrir daedalus-).
--
-- Naming: prefix `daedalus-` (consistência owner agent + 1 branch dispatch).
--
-- 4 op_types:
--   - daedalus-orchestrate-step: avança workflow_definitions criando task filha
--   - daedalus-route-task: decide qual agente recebe (lookup agent_specialty_configs)
--   - daedalus-replan: retry/skip/abort em failure
--   - daedalus-compile-prompt: compila system_prompt dinâmico (substitui Brain)

-- ============================================================================
-- 1) INSERT 4 op_types em operation_types_catalog
-- ============================================================================

INSERT INTO vectraclip.operation_types_catalog (id, name, description, category, primary_agent_id, default_specialty_slug, display_order) VALUES
  (
    'daedalus-orchestrate-step',
    'Daedalus: Orquestrar Step',
    'Avanca workflow_definitions criando task filha pro proximo step, lendo workflow_steps + agent_specialty_configs',
    'orchestration',
    'd4ed4145-0000-4000-8000-000000000005',
    'workflow-orchestration',
    310
  ),
  (
    'daedalus-route-task',
    'Daedalus: Roteia Task',
    'Decide qual agente recebe a task baseado em step.agent_specialty_config_id (lookup agent_specialty_configs)',
    'orchestration',
    'd4ed4145-0000-4000-8000-000000000005',
    'workflow-orchestration',
    320
  ),
  (
    'daedalus-replan',
    'Daedalus: Replan',
    'Decide retry/skip/abort apos failure de step. M4 fase initial: retry simples ate 3x, depois abort.',
    'orchestration',
    'd4ed4145-0000-4000-8000-000000000005',
    'workflow-orchestration',
    330
  ),
  (
    'daedalus-compile-prompt',
    'Daedalus: Compila Prompt',
    'Compila system_prompt dinamico do orchestrator (substitui brain/system_prompt.py estatico) combinando persona + workflow + step + tools',
    'orchestration',
    'd4ed4145-0000-4000-8000-000000000005',
    'system-prompt-compilation',
    340
  )
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- 2) UPDATE agent_specialty_configs.values — renomear op_types pros 3 specialties M1
-- ============================================================================

-- workflow-orchestration: 3 op_types agora com prefix daedalus-
UPDATE vectraclip.agent_specialty_configs
SET values = jsonb_set(
  values,
  '{operation_types}',
  '["daedalus-orchestrate-step", "daedalus-route-task", "daedalus-replan"]'::jsonb,
  true
),
updated_at = now()
WHERE agent_id = 'd4ed4145-0000-4000-8000-000000000005'
  AND specialty_id = 'workflow-orchestration';

-- tool-binding: era bind-step-tools, vira parte de daedalus-orchestrate-step
-- (não precisa op_type próprio — orchestrate-step injeta tools antes dispatch)
UPDATE vectraclip.agent_specialty_configs
SET values = jsonb_set(
  values,
  '{operation_types}',
  '[]'::jsonb,  -- subsumido por orchestrate-step
  true
) || '{"status":"absorbed_by_orchestrate_step","absorbed_at":"2026-05-19"}'::jsonb,
updated_at = now()
WHERE agent_id = 'd4ed4145-0000-4000-8000-000000000005'
  AND specialty_id = 'tool-binding';

-- system-prompt-compilation: renomear compile-orchestrator-prompt → daedalus-compile-prompt
UPDATE vectraclip.agent_specialty_configs
SET values = jsonb_set(
  values,
  '{operation_types}',
  '["daedalus-compile-prompt"]'::jsonb,
  true
),
updated_at = now()
WHERE agent_id = 'd4ed4145-0000-4000-8000-000000000005'
  AND specialty_id = 'system-prompt-compilation';
