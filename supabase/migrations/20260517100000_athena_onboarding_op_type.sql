-- Migration: adiciona operation_type 'athena-onboarding' ao CHECK constraint.
--
-- Contexto (PR 3 do flow Vectra Cargo dogfood):
--   Após signup self-service criar a company, dispatch automático de uma task
--   athena-onboarding que sintetiza um markdown estruturado do perfil
--   empresarial (CNPJ + bio + atividade) e ingere no RAG corpus do tenant
--   via Mnemos (rag-ingest). Quando o user chegar no primeiro Goal, a Athena
--   classify/charter já tem contexto.
--
-- Pré-existe:
--   * Athena daemon e _SPECIALTY_DISPATCH em src/agents/athena.py
--   * Bucket Storage `rag-documents` (criado 2026-05-09 VEC-370)
--   * Tabela vectraclip.rag_documents + Mnemos handler rag-ingest
--
-- Pattern (espelha migrations VEC-388/389/390 que adicionaram athena-classify..prioritize):
--   DROP CHECK existente, ADD CHECK com lista nova incluindo o novo op_type.
--   3 listas hardcoded a manter em sincronia:
--     1. CHECK constraint (este arquivo)
--     2. Pydantic Literal em src/models.py (Task.operation_type)
--     3. _SPECIALTY_DISPATCH em src/agents/athena.py

ALTER TABLE vectraclip.tasks DROP CONSTRAINT IF EXISTS tasks_operation_type_check;

ALTER TABLE vectraclip.tasks ADD CONSTRAINT tasks_operation_type_check
CHECK (operation_type = ANY (ARRAY[
  'orchestration'::text,
  'code_generation'::text,
  'code_review'::text,
  'research'::text,
  'document_generation'::text,
  'qa_testing'::text,
  'email_lead'::text,
  'freight-quotation'::text,
  'freight-quotation-approval'::text,
  'route-cost-calculation'::text,
  'crm-fill'::text,
  'crm-fill-precheck'::text,
  'crm-fill-finalize'::text,
  'oracle-research'::text,
  'oracle-extract'::text,
  'oracle-report'::text,
  'oracle-rag'::text,
  'oracle-vision'::text,
  'oracle-summarize'::text,
  'dispatch-research'::text,
  'financial-audit'::text,
  'financial-bookkeeping'::text,
  'conciliacao-backlog'::text,
  'planner-import-ofx'::text,
  'planner-categorize-pendings'::text,
  'kronos-audit-historico'::text,
  'rag-ingest'::text,
  'athena-classify'::text,
  'athena-charter'::text,
  'athena-stakeholder-map'::text,
  'athena-risk-register'::text,
  'athena-evm'::text,
  'athena-rag-ingest'::text,
  'athena-audit'::text,
  'athena-recommend'::text,
  'athena-prioritize'::text,
  'athena-onboarding'::text,
  'bpmn-generate'::text,
  'other'::text
]));

COMMENT ON CONSTRAINT tasks_operation_type_check ON vectraclip.tasks IS
  'Catálogo canônico de operation_types. Sincronizar com src/models.py (Pydantic Literal) e src/agents/athena.py (_SPECIALTY_DISPATCH).';
