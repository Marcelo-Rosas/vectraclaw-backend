-- =============================================================================
-- Migration: update_valid_operation_types_check_constraint
-- Data: 2026-05-09
-- Contexto:
--   VEC-359 (Step 10 — RAG migration) introduziu o operation_type 'rag-ingest'
--   usado pelo backend em src/api_routes/rag.py:325 (POST /rag/upload cria
--   task que o daemon Mnemos polla). A migration original do RAG
--   (20260507191500_vec_rag_corpus.sql) documentou o uso mas NÃO estendeu o
--   CHECK constraint `tasks_operation_type_check`.
--
--   Resultado em runtime: qualquer upload via /rag/upload falhava com 500
--   "new row for relation 'tasks' violates check constraint
--    tasks_operation_type_check".
--
-- Esta migration:
--   1. DROP idempotente do constraint atual
--   2. ADD com a lista completa atualizada (24 valores existentes + 'rag-ingest')
--
-- Aplicada manualmente no remoto via Supabase SQL Editor antes deste arquivo
-- ser criado (snippet 272a8a5c-d06b-48ee-9c0c-3c002640980a). Esta migration
-- versiona retroativamente para manter `db pull`/CI consistentes.
--
-- Safe: apenas ESTENDE a lista — nenhum operation_type existente é removido.
-- =============================================================================

ALTER TABLE "vectraclip"."tasks"
  DROP CONSTRAINT IF EXISTS "tasks_operation_type_check";

ALTER TABLE "vectraclip"."tasks"
  ADD CONSTRAINT "tasks_operation_type_check" CHECK (
    "operation_type" = ANY (ARRAY[
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
      'crm-fill-precheck'::text,
      'crm-fill-finalize'::text,
      'crm-fill'::text,
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
      'rag-ingest'::text,
      'other'::text
    ])
  );

COMMENT ON CONSTRAINT "tasks_operation_type_check" ON "vectraclip"."tasks" IS
  'Lista exaustiva de operation_types válidos. Estender via nova migration sempre que adicionar novo handler em src/agents/. Última atualização: 2026-05-09 (rag-ingest, VEC-359).';
