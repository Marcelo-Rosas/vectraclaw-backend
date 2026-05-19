-- Marcelo aprovou (autopilot 2026-05-19): nomes N8N pros logic_patterns + tooltip curto
-- descriptions. Plus fix icons workflow_trigger_types + populate Kronos steps.
--
-- ESPELHEI ANTES (Regra #1):
--   - workflow_logic_patterns: 8 rows; coluna 'icon' (text) e 'description' (text) existem
--   - workflow_trigger_types: 5 rows; coluna 'icon' (text) existe; realtime sem icon;
--     'lightning' não é nome canônico Lucide (correto: 'zap')
--   - workflow_steps Conciliação Bancária (4 rows): logic_pattern=null + trigger_type=null
--     em todos → fallback Box no StepNode pq patternIcon não casa nada
--
-- 4 mudanças:
--   1) Rename + description curta em workflow_logic_patterns (8 rows)
--   2) Fix workflow_trigger_types.icon: 'lightning'→'zap' + realtime.icon='play'
--   3) UPDATE workflow_steps Conciliação: trigger_type='manual' + logic_pattern='simple'
--   4) Step 4 (apply-corrections) extra: requires_approval=true (memory pivot Kronos
--      cravou "após aprovação humana")

-- ============================================================================
-- 1) workflow_logic_patterns rename N8N-style
-- ============================================================================

UPDATE vectraclip.workflow_logic_patterns SET
  name = 'Linear',
  description = 'Step sem decisão. Sucesso vai pro próximo, falha pro alternativo.',
  updated_at = now()
WHERE id = 'simple';

UPDATE vectraclip.workflow_logic_patterns SET
  name = 'IF',
  description = 'Bifurca em 2 caminhos: true / false.',
  updated_at = now()
WHERE id = 'split-if';

UPDATE vectraclip.workflow_logic_patterns SET
  name = 'Switch',
  description = '3+ caminhos por valor, regex ou regra.',
  updated_at = now()
WHERE id = 'split-switch';

UPDATE vectraclip.workflow_logic_patterns SET
  name = 'Merge',
  description = 'Junta ramos paralelos por chave comum.',
  updated_at = now()
WHERE id = 'merge-by-key';

UPDATE vectraclip.workflow_logic_patterns SET
  name = 'Loop Over Items',
  description = 'Itera em batches respeitando rate limit de APIs.',
  updated_at = now()
WHERE id = 'loop-batch';

UPDATE vectraclip.workflow_logic_patterns SET
  name = 'Wait',
  description = 'Pausa o workflow até evento externo (webhook, aprovação humana).',
  updated_at = now()
WHERE id = 'wait-event';

UPDATE vectraclip.workflow_logic_patterns SET
  name = 'Execute Workflow',
  description = 'Chama workflow filho passando dados de forma isolada.',
  updated_at = now()
WHERE id = 'subflow';

UPDATE vectraclip.workflow_logic_patterns SET
  name = 'Error Trigger',
  description = 'Captura erros e dispara workflow dedicado de recovery.',
  updated_at = now()
WHERE id = 'error-handler';

-- ============================================================================
-- 2) workflow_trigger_types: fix icons (lightning não é Lucide canônico)
-- ============================================================================

UPDATE vectraclip.workflow_trigger_types SET icon = 'zap', updated_at = now() WHERE slug = 'webhook';
UPDATE vectraclip.workflow_trigger_types SET icon = 'play', updated_at = now() WHERE slug = 'realtime';

-- ============================================================================
-- 2.5) Fix FK duplicada em workflow_steps.logic_pattern
-- Existem 2 FKs apontando pra colunas diferentes (id lowercase vs taxonomy UPPERCASE),
-- contraditórias entre si. Drop a redundante (aponta pra .id) e mantém só a
-- canônica (aponta pra .taxonomy CASCADE).
-- ============================================================================

ALTER TABLE vectraclip.workflow_steps
  DROP CONSTRAINT IF EXISTS workflow_steps_logic_pattern_fk;

-- ============================================================================
-- 3) UPDATE workflow_steps Conciliação Bancária: popular logic_pattern + trigger
--    (memory project_kronos_planner_pivot — Kronos manual via UI/scheduled)
-- ============================================================================

UPDATE vectraclip.workflow_steps SET
  logic_pattern = 'SIMPLE',
  trigger_type = 'manual',
  updated_at = now()
WHERE workflow_id = '00000000-0000-4000-8000-000000000001'
  AND slug IN ('import-ofx', 'categorize-pendings', 'audit-historico');

-- ============================================================================
-- 4) Step 4 apply-corrections: requires_approval=true (pivot Kronos memory)
-- ============================================================================

UPDATE vectraclip.workflow_steps SET
  logic_pattern = 'SIMPLE',
  trigger_type = 'manual',
  requires_approval = true,
  updated_at = now()
WHERE workflow_id = '00000000-0000-4000-8000-000000000001'
  AND slug = 'apply-corrections';
