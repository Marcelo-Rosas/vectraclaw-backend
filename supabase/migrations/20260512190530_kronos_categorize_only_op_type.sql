-- VEC-416 PR6: novo operation_type 'planner-categorize-pendings' para o
-- handler categorize-only do Kronos.
--
-- Permite rodar categorização sobre linhas existentes no Meu Planner
-- sem reimportar OFX. Caso de uso: smoke iterativo após adicionar regras
-- no YAML, atualizar categorias retroativamente, etc.

-- Tabela `tasks`
ALTER TABLE vectraclip.tasks DROP CONSTRAINT IF EXISTS tasks_operation_type_check;

ALTER TABLE vectraclip.tasks ADD CONSTRAINT tasks_operation_type_check
CHECK (operation_type = ANY (ARRAY[
  -- 25 originais
  'orchestration'::text, 'code_generation'::text, 'code_review'::text, 'research'::text,
  'document_generation'::text, 'qa_testing'::text, 'email_lead'::text,
  'freight-quotation'::text, 'freight-quotation-approval'::text, 'route-cost-calculation'::text,
  'crm-fill-precheck'::text, 'crm-fill-finalize'::text, 'crm-fill'::text,
  'oracle-research'::text, 'oracle-extract'::text, 'oracle-report'::text, 'oracle-rag'::text,
  'oracle-vision'::text, 'oracle-summarize'::text,
  'dispatch-research'::text, 'financial-audit'::text, 'financial-bookkeeping'::text,
  'conciliacao-backlog'::text, 'rag-ingest'::text, 'other'::text,
  -- VEC-388 PR1: Athena
  'athena-classify'::text, 'athena-charter'::text, 'athena-stakeholder-map'::text,
  'athena-risk-register'::text, 'athena-evm'::text, 'athena-rag-ingest'::text,
  'athena-audit'::text, 'athena-recommend'::text, 'athena-prioritize'::text,
  -- VEC-419: import OFX no Meu Planner via Playwright
  'planner-import-ofx'::text,
  -- VEC-416 PR6 (esta migration): categorize-only sem reimport
  'planner-categorize-pendings'::text
]));

-- Tabela `routines` (rotinas Kronos podem agendar este op_type também)
ALTER TABLE vectraclip.routines DROP CONSTRAINT IF EXISTS routines_operation_type_check;

ALTER TABLE vectraclip.routines ADD CONSTRAINT routines_operation_type_check
CHECK (operation_type = ANY (ARRAY[
  'email_lead'::text,
  'route-cost-calculation'::text,
  'freight-quotation'::text,
  'crm-fill'::text,
  'crm-fill-precheck'::text,
  'financial-audit'::text,
  'financial-bookkeeping'::text,
  'planner-import-ofx'::text,
  'planner-categorize-pendings'::text,
  'other'::text
]));

NOTIFY pgrst, 'reload schema';
