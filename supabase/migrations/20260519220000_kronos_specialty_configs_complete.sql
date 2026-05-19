-- Marcelo cravou 2026-05-19: apply-corrections + kronos-audit-historico
-- NÃO viraram agent_specialty_configs Kronos. Specialties existem em
-- vectraclip.agent_specialties (catalog cross-tenant) mas configs per-tenant
-- faltavam pro Kronos. Plus 3 configs existentes (financial-audit,
-- planner-categorize-pendings, planner-import-ofx) tinham values.operation_types=null
-- — Daedalus (M1) tem arrays populados, Kronos ficou inconsistente.
--
-- ESPELHEI ANTES (Regra #1):
--   - agent_specialties: 5 rows finance-domain existem (incluindo
--     planner-apply-corrections + kronos-audit-historico)
--   - agent_specialty_configs Kronos: 3 rows (faltam 2)
--   - operation_types_catalog: 5 rows finance Kronos (planner-import-ofx,
--     planner-categorize-pendings, planner-apply-corrections,
--     kronos-audit-historico, financial-audit, conciliacao-backlog)
--   - Kronos id = '9c8d7e6f-5a4b-4321-9876-543210fedcba' (SSOT agent_ids.py)
--   - Companies = '01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2' (Vectra IA Services)
--
-- Aplicação:
--   1. INSERT 2 agent_specialty_configs Kronos faltantes
--   2. UPDATE 3 configs existentes populando values.operation_types arrays
--      (1 op_type por config — relação 1:1 já existente)

-- ============================================================================
-- 1) INSERT 2 configs faltantes
-- ============================================================================

INSERT INTO vectraclip.agent_specialty_configs (
  company_id, agent_id, specialty_id, values
)
SELECT
  c.company_id,
  '9c8d7e6f-5a4b-4321-9876-543210fedcba'::uuid,
  s.specialty_id,
  s.values::jsonb
FROM vectraclip.companies c
CROSS JOIN (
  VALUES
    ('planner-apply-corrections',
     '{"operation_types":["planner-apply-corrections"],"requires_approval":true,"runtime":"playwright"}'),
    ('kronos-audit-historico',
     '{"operation_types":["kronos-audit-historico"],"output_format":"markdown","emit_oracle_report":true}')
) AS s(specialty_id, values)
ON CONFLICT (agent_id, specialty_id) DO NOTHING;

-- ============================================================================
-- 2) UPDATE 3 configs existentes — popular values.operation_types
-- ============================================================================

UPDATE vectraclip.agent_specialty_configs
SET values = COALESCE(values, '{}'::jsonb) || jsonb_build_object(
  'operation_types', jsonb_build_array('financial-audit', 'conciliacao-backlog')
)
WHERE agent_id = '9c8d7e6f-5a4b-4321-9876-543210fedcba'
  AND specialty_id = 'financial-audit';

UPDATE vectraclip.agent_specialty_configs
SET values = COALESCE(values, '{}'::jsonb) || jsonb_build_object(
  'operation_types', jsonb_build_array('planner-categorize-pendings')
)
WHERE agent_id = '9c8d7e6f-5a4b-4321-9876-543210fedcba'
  AND specialty_id = 'planner-categorize-pendings';

UPDATE vectraclip.agent_specialty_configs
SET values = COALESCE(values, '{}'::jsonb) || jsonb_build_object(
  'operation_types', jsonb_build_array('planner-import-ofx')
)
WHERE agent_id = '9c8d7e6f-5a4b-4321-9876-543210fedcba'
  AND specialty_id = 'planner-import-ofx';
