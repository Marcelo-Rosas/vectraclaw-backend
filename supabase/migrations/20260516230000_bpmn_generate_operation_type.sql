-- Daedalus PR G+H — operation_type 'bpmn-generate' (catalog + CHECK)
--
-- Pré-requisito para o handler em src/agents/daedalus.py poder receber
-- tasks. tasks.operation_type tem CHECK constraint enumerado (3 lugares
-- hardcoded — A5 do AUDIT-CONSOLIDADO: backlog futuro consolidar
-- via FK em operation_types_catalog). Por ora, padrão da casa é
-- DROP + recreate o CHECK ampliado.

-- =============================================================================
-- 1. Catálogo: registra bpmn-generate apontando pra Daedalus
-- =============================================================================

INSERT INTO vectraclip.operation_types_catalog (
  id, name, description, category, icon, color, display_order,
  primary_agent_id, default_specialty_slug, is_active
)
VALUES (
  'bpmn-generate',
  'Geração de Diagrama BPMN',
  'Daedalus gera diagrama BPMN visual a partir de SIPOC process, Charter ou descrição freeform.',
  'modeling',
  'workflow',
  'text-orange-600',
  200,
  'd4ed4145-0000-4000-8000-000000000005',  -- Daedalus AGENT_ID
  'bpmn-modeling',
  true
)
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  category = EXCLUDED.category,
  primary_agent_id = EXCLUDED.primary_agent_id,
  default_specialty_slug = EXCLUDED.default_specialty_slug,
  is_active = EXCLUDED.is_active;

-- =============================================================================
-- 2. CHECK constraint em tasks.operation_type — ampliar com bpmn-generate
--    Padrão da casa: DROP IF EXISTS + recreate enumerado completo.
-- =============================================================================

ALTER TABLE vectraclip.tasks DROP CONSTRAINT IF EXISTS tasks_operation_type_check;

ALTER TABLE vectraclip.tasks ADD CONSTRAINT tasks_operation_type_check
CHECK (operation_type = ANY (ARRAY[
  -- Core
  'orchestration', 'code_generation', 'code_review',
  'research', 'document_generation', 'qa_testing',
  -- Hermes/Mercator/Plutus/Hodos
  'email_lead',
  'freight-quotation', 'freight-quotation-approval',
  'route-cost-calculation',
  'crm-fill', 'crm-fill-precheck', 'crm-fill-finalize',
  -- Oracle
  'oracle-research', 'oracle-extract', 'oracle-report',
  'oracle-rag', 'oracle-vision', 'oracle-summarize',
  'dispatch-research',
  -- Kronos
  'financial-audit', 'financial-bookkeeping', 'conciliacao-backlog',
  'planner-import-ofx', 'planner-categorize-pendings',
  'kronos-audit-historico',
  -- Mnemos
  'rag-ingest',
  -- Athena (9 specialty handlers)
  'athena-classify', 'athena-charter', 'athena-stakeholder-map',
  'athena-risk-register', 'athena-evm', 'athena-rag-ingest',
  'athena-audit', 'athena-recommend', 'athena-prioritize',
  -- Daedalus (PR G+H — novo)
  'bpmn-generate',
  -- catch-all
  'other'
]));

NOTIFY pgrst, 'reload schema';
