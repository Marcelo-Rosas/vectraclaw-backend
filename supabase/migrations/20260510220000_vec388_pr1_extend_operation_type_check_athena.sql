-- =============================================================================
-- 20260510220000_vec388_pr1_extend_operation_type_check_athena
-- =============================================================================
--
-- Estende o CHECK constraint `tasks_operation_type_check` em
-- vectraclip.tasks para aceitar os 9 novos `operation_type` da Athena
-- (9º daemon, PMOia Heldman/PMBOK — VEC-388 PR1).
--
-- Sem esta migration, INSERT INTO vectraclip.tasks (operation_type='athena-*')
-- é rejeitado pelo banco com:
--   ERROR: new row for relation "tasks" violates check constraint
--          "tasks_operation_type_check"
-- O daemon Athena nunca pega nenhuma tarefa porque ela nem chega a existir
-- como `queued` — o INSERT falha antes.
--
-- Aplicada VIA MCP no Supabase durante o smoke em 2026-05-10 22:00 UTC,
-- antes de existir como arquivo no repo. Este arquivo apenas versiona
-- o que já está em produção (paridade local/remoto).
--
-- Estratégia: DROP + ADD do constraint com a lista COMPLETA (25 antigos +
-- 9 athena-* = 34 valores). Idempotente desde que a pré-checagem abaixo
-- volte 0 rows.
--
-- PRÉ-FLIGHT obrigatório antes de re-aplicar:
--   SELECT DISTINCT operation_type FROM vectraclip.tasks
--   WHERE operation_type NOT IN (
--     'orchestration', 'code_generation', 'code_review', 'research',
--     'document_generation', 'qa_testing', 'email_lead',
--     'freight-quotation', 'freight-quotation-approval', 'route-cost-calculation',
--     'crm-fill-precheck', 'crm-fill-finalize', 'crm-fill',
--     'oracle-research', 'oracle-extract', 'oracle-report', 'oracle-rag',
--     'oracle-vision', 'oracle-summarize',
--     'dispatch-research', 'financial-audit', 'financial-bookkeeping',
--     'conciliacao-backlog', 'rag-ingest', 'other',
--     'athena-classify', 'athena-charter', 'athena-stakeholder-map',
--     'athena-risk-register', 'athena-evm', 'athena-rag-ingest',
--     'athena-audit', 'athena-recommend', 'athena-prioritize'
--   );
--   -- Esperado: 0 rows. Se >0, o ADD CONSTRAINT vai falhar.
-- =============================================================================

ALTER TABLE vectraclip.tasks DROP CONSTRAINT IF EXISTS tasks_operation_type_check;

ALTER TABLE vectraclip.tasks ADD CONSTRAINT tasks_operation_type_check
CHECK (operation_type = ANY (ARRAY[
  -- 25 valores existentes (preservados intactos)
  'orchestration',
  'code_generation',
  'code_review',
  'research',
  'document_generation',
  'qa_testing',
  'email_lead',
  'freight-quotation',
  'freight-quotation-approval',
  'route-cost-calculation',
  'crm-fill-precheck',
  'crm-fill-finalize',
  'crm-fill',
  'oracle-research',
  'oracle-extract',
  'oracle-report',
  'oracle-rag',
  'oracle-vision',
  'oracle-summarize',
  'dispatch-research',
  'financial-audit',
  'financial-bookkeeping',
  'conciliacao-backlog',
  'rag-ingest',
  'other',
  -- VEC-388 PR1: 9 novos operation types da Athena (PMOia Heldman/PMBOK)
  'athena-classify',
  'athena-charter',
  'athena-stakeholder-map',
  'athena-risk-register',
  'athena-evm',
  'athena-rag-ingest',
  'athena-audit',
  'athena-recommend',
  'athena-prioritize'
]::text[]));
