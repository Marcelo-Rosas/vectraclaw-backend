-- M1 do plano Brain → Daedalus (autopilot 2026-05-19, doc M1 perfil em
-- docs/AGENTS/daedalus.md). Marcelo aprovou retrofit explicitly.
--
-- ESPELHEI ANTES (Regra de Ouro #1):
--   - SELECT agents WHERE id='d4ed4145-...' → name=Daedalus, system_prompt=NULL,
--     role='BPMN Process Modeler'
--   - SELECT agent_specialty_configs WHERE agent_id=Daedalus → 1 row (bpmn-modeling)
--   - SELECT agent_specialties → bpmn-modeling existe; workflow-orchestration,
--     tool-binding, system-prompt-compilation NÃO existem
--
-- Aplica:
--   1. UPDATE agents.role (Process Architect & Workflow Orchestrator)
--   2. INSERT 3 specialties novas em agent_specialties (cross-tenant catalog)
--   3. INSERT 3 agent_specialty_configs Daedalus (per-tenant config)
--
-- system_prompt fica null por enquanto — vai ser compilado dinamicamente em M4
-- via daedalus.compile_orchestrator_prompt(workflow_step_id). Template estático
-- pra M4 vive em src/agents/daedalus.py:_BASE_SYSTEM_PROMPT.
--
-- Comportamento atual (handler bpmn-generate) NÃO muda. Novas specialties
-- ficam stubs até M4 (orchestration loop) implementar handlers.

-- ============================================================================
-- 1) UPDATE agents.role
-- ============================================================================

UPDATE vectraclip.agents
SET role = 'Process Architect & Workflow Orchestrator',
    updated_at = now()
WHERE id = 'd4ed4145-0000-4000-8000-000000000005';

-- ============================================================================
-- 2) INSERT 3 specialties novas em agent_specialties (cross-tenant)
-- ============================================================================

INSERT INTO vectraclip.agent_specialties (id, slug, name, domain, description, compatible_roles, system_prompt_template, is_active)
VALUES
  (
    'workflow-orchestration',
    'workflow-orchestration',
    'Workflow Orchestration',
    'automation',
    'Avanca execucao de workflow_definitions criando workflow_steps filhas em ordem topologica, despachando tasks pros agentes executores apropriados, monitorando completion/failure e disparando replan quando necessario. M4 (autopilot Brain to Daedalus migration).',
    ARRAY['Process Architect & Workflow Orchestrator'],
    '',
    true
  ),
  (
    'tool-binding',
    'tool-binding',
    'Tool Binding',
    'automation',
    'Enriquece task.input_json.allowed_tools antes do dispatch baseado em workflow_steps.ferramentas[] do step parent. Valida cada tool contra tools_catalog. Depende de W14.1 (tools_catalog seed). M4.',
    ARRAY['Process Architect & Workflow Orchestrator'],
    '',
    true
  ),
  (
    'system-prompt-compilation',
    'system-prompt-compilation',
    'System Prompt Compilation',
    'intelligence',
    'Compila prompt dinamico do orchestrator combinando: persona base do agente delegado + workflow_definition context + workflow_steps context + tools bound + business rules. Substitui src/services/brain/system_prompt.py (estatico) por versao dinamica. Output: string. M4.',
    ARRAY['Process Architect & Workflow Orchestrator'],
    '',
    true
  )
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- 3) INSERT 3 agent_specialty_configs Daedalus (uma por specialty nova)
-- ============================================================================

INSERT INTO vectraclip.agent_specialty_configs (
  company_id, agent_id, specialty_id, values
)
SELECT
  c.company_id,
  'd4ed4145-0000-4000-8000-000000000005'::uuid,
  s.specialty_id,
  s.values::jsonb
FROM vectraclip.companies c
CROSS JOIN (
  VALUES
    ('workflow-orchestration', '{"operation_types":["workflow-orchestrate-step","workflow-route-task","workflow-replan"],"status":"stub_until_m4","engine_mode":"placeholder"}'),
    ('tool-binding', '{"operation_types":["bind-step-tools"],"status":"stub_until_m4","depends_on":"w14.1_tools_catalog"}'),
    ('system-prompt-compilation', '{"operation_types":["compile-orchestrator-prompt"],"status":"stub_until_m4","replaces":"src/services/brain/system_prompt.py"}')
) AS s(specialty_id, values)
ON CONFLICT (agent_id, specialty_id) DO NOTHING;
