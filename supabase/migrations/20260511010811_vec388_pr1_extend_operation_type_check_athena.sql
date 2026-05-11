-- VEC-388 PR1: estende whitelist de operation_type para incluir os 9 athena-*
-- Gap descoberto no smoke 2026-05-10: tasks_operation_type_check é hardcoded
-- e rejeitava INSERT de athena-* antes do daemon poder pegar.
--
-- Reconciliação retroativa (VEC-394): este DDL foi aplicado em prod em
-- 2026-05-11 01:08:11 UTC via mcp apply_migration durante a sessão do
-- VEC-388 PR1, antes deste arquivo existir. O timestamp do nome reflete
-- o momento da aplicação real (preservando ordem do histórico).

ALTER TABLE vectraclip.tasks DROP CONSTRAINT IF EXISTS tasks_operation_type_check;

ALTER TABLE vectraclip.tasks ADD CONSTRAINT tasks_operation_type_check
CHECK (operation_type = ANY (ARRAY[
  -- 25 valores existentes (preservados intactos)
  'orchestration'::text, 'code_generation'::text, 'code_review'::text, 'research'::text,
  'document_generation'::text, 'qa_testing'::text, 'email_lead'::text,
  'freight-quotation'::text, 'freight-quotation-approval'::text, 'route-cost-calculation'::text,
  'crm-fill-precheck'::text, 'crm-fill-finalize'::text, 'crm-fill'::text,
  'oracle-research'::text, 'oracle-extract'::text, 'oracle-report'::text, 'oracle-rag'::text,
  'oracle-vision'::text, 'oracle-summarize'::text,
  'dispatch-research'::text, 'financial-audit'::text, 'financial-bookkeeping'::text,
  'conciliacao-backlog'::text, 'rag-ingest'::text, 'other'::text,
  -- VEC-388 PR1: 9 novos operation types da Athena
  'athena-classify'::text, 'athena-charter'::text, 'athena-stakeholder-map'::text,
  'athena-risk-register'::text, 'athena-evm'::text, 'athena-rag-ingest'::text,
  'athena-audit'::text, 'athena-recommend'::text, 'athena-prioritize'::text
]));

NOTIFY pgrst, 'reload schema';
