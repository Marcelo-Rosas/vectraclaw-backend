-- VEC-XXX (Task #18 sessão 2026-05-14): Workflow kronos-audit-historico
--
-- Adiciona 3 novos operation_types pro pipeline de auditoria histórica
-- (Jan-Abr 2026):
--   - kronos-audit-historico:      handler novo (kronos_audit.py) que cruza
--                                  CSV export do Planner × PDF C6 × OFX para
--                                  detectar anomalias de categorização e
--                                  duplicatas (mesma data + valor).
--   - audit-review:                step de aprovação humana (requires_approval=true).
--                                  Nenhum daemon executa — task fica em backlog
--                                  até user aprovar via POST /api/tasks/{id}/approve.
--   - planner-apply-corrections:   handler novo (kronos_apply_corrections.py)
--                                  que aplica correções aprovadas no Excel local
--                                  e no Planner via Playwright.

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
  -- VEC-419
  'planner-import-ofx'::text,
  -- VEC-416 PR6
  'planner-categorize-pendings'::text,
  -- Task #18 sessão 2026-05-14: workflow kronos-audit-historico
  'kronos-audit-historico'::text,
  'audit-review'::text,
  'planner-apply-corrections'::text
]));

-- routines também pode agendar os 3 novos (cron diario)
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
  'kronos-audit-historico'::text,
  'planner-apply-corrections'::text,
  'other'::text
]));

-- ---------------------------------------------------------------------------
-- Specialties: 3 novas em agent_specialties (sem system_prompt_template
-- porque handlers são determinísticos Python — não usam LLM no dispatch).
-- config_schema reflete inputs esperados pelos handlers.
-- ---------------------------------------------------------------------------

INSERT INTO vectraclip.agent_specialties (id, name, slug, domain, description, is_active, config_schema)
VALUES
  (
    'kronos-audit-historico',
    'Auditoria Histórica de Lançamentos',
    'kronos-audit-historico',
    'financeiro',
    'Cruza CSV export do Planner × PDF C6 × OFX para detectar anomalias de categorização e duplicatas (mesma data + valor + descrição enriquecida). Gera relatório de sugestões para aprovação humana.',
    true,
    '[
      {"key":"mes_alvo","type":"text","label":"Mês alvo (YYYY-MM)","required":true,"description":"Ex: 2026-01. Cron escolhe próximo mês pendente do goal."},
      {"key":"csv_dir","type":"text","label":"Pasta CSV export Planner","required":false,"description":"User exporta manualmente. Padrão de arquivo: lancamentos-YYYY-MM.csv","default":"C:\\Users\\marce\\OFX-C6\\Planner-CSV"},
      {"key":"ofx_dir","type":"text","label":"Pasta OFX C6","required":false,"default":"C:\\Users\\marce\\OFX-C6"},
      {"key":"pdf_dir","type":"text","label":"Pasta PDF extratos","required":false,"default":"C:\\Users\\marce\\OFX-C6"}
    ]'::jsonb
  ),
  (
    'audit-review',
    'Revisão Humana de Auditoria',
    'audit-review',
    'governanca',
    'Step de aprovação. Não executa lógica — task fica em backlog até aprovação humana via POST /api/tasks/{id}/approve. Output do step anterior fica visível pra revisão.',
    true,
    '[]'::jsonb
  ),
  (
    'planner-apply-corrections',
    'Aplicar Correções no Planner',
    'planner-apply-corrections',
    'financeiro',
    'Aplica sugestões aprovadas (vindas do parent_task.output_json) editando o Excel local e re-categorizando lançamentos no Meu Planner via Playwright. Remove duplicatas detectadas.',
    true,
    '[]'::jsonb
  )
ON CONFLICT (slug) DO UPDATE SET
  name = excluded.name,
  description = excluded.description,
  config_schema = excluded.config_schema,
  is_active = excluded.is_active;

NOTIFY pgrst, 'reload schema';
