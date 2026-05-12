-- VEC-419 PR2: estende whitelist de operation_type para incluir 'planner-import-ofx'.
--
-- Handler novo entrypoint_planner_import (src/agents/kronos_planner.py) faz upload
-- de OFX no webapp Meu Planner Financeiro via Playwright. Sem essa migration, INSERT
-- de task com operation_type='planner-import-ofx' falha em tasks_operation_type_check.
--
-- Preserva os 34 valores existentes (incluindo os 9 athena-* do VEC-388 PR1).

ALTER TABLE vectraclip.tasks DROP CONSTRAINT IF EXISTS tasks_operation_type_check;

ALTER TABLE vectraclip.tasks ADD CONSTRAINT tasks_operation_type_check
CHECK (operation_type = ANY (ARRAY[
  -- 25 valores originais
  'orchestration'::text, 'code_generation'::text, 'code_review'::text, 'research'::text,
  'document_generation'::text, 'qa_testing'::text, 'email_lead'::text,
  'freight-quotation'::text, 'freight-quotation-approval'::text, 'route-cost-calculation'::text,
  'crm-fill-precheck'::text, 'crm-fill-finalize'::text, 'crm-fill'::text,
  'oracle-research'::text, 'oracle-extract'::text, 'oracle-report'::text, 'oracle-rag'::text,
  'oracle-vision'::text, 'oracle-summarize'::text,
  'dispatch-research'::text, 'financial-audit'::text, 'financial-bookkeeping'::text,
  'conciliacao-backlog'::text, 'rag-ingest'::text, 'other'::text,
  -- VEC-388 PR1: 9 operation types da Athena
  'athena-classify'::text, 'athena-charter'::text, 'athena-stakeholder-map'::text,
  'athena-risk-register'::text, 'athena-evm'::text, 'athena-rag-ingest'::text,
  'athena-audit'::text, 'athena-recommend'::text, 'athena-prioritize'::text,
  -- VEC-419 PR2: novo pipeline Kronos (import OFX via Playwright no Meu Planner)
  'planner-import-ofx'::text
]));

NOTIFY pgrst, 'reload schema';
