-- =============================================================================
-- PR7 Fase 1 — dispatch de operation_type catalog-driven (handler refs)
-- =============================================================================
-- Contexto: agent_daemon.execute_task roteia por operation_type numa cadeia
-- `if op_type == "...":` (~20 ramos) — a 3ª das "3 listas hardcoded"
-- (Pydantic models.py + CHECK no DB + este dispatch). Regra de Ouro #2: a
-- ligação op_type→handler deve ser metadata, não constante no .py.
--
-- Esta migration adiciona a referência declarativa do handler ao catálogo.
-- O daemon ganha um fast-path: se a row do op_type tiver handler_module +
-- handler_function, ele carrega via importlib e chama conforme as flags. Se
-- NÃO tiver (handler_module IS NULL), cai na cadeia if-elif legada (intacta =
-- safety net). Toda row nova SEM handler_module é válida e usa o fallback.
--
-- Fase 1 = só exact-match sem side-effect e sem prefixo (11 op_types). Famílias
-- por prefixo (athena-*/bpmn-*/oracle-*), side-effects (oracle-research email),
-- audit-review (inline), dispatch-research (método de instância) e skillforge
-- ficam na if-chain (Fase 2).
-- =============================================================================

ALTER TABLE vectraclip.operation_types_catalog
  ADD COLUMN IF NOT EXISTS handler_module     text,
  ADD COLUMN IF NOT EXISTS handler_function   text,
  ADD COLUMN IF NOT EXISTS handler_is_async   boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS handler_pass_supabase boolean NOT NULL DEFAULT true;

COMMENT ON COLUMN vectraclip.operation_types_catalog.handler_module IS
  'Módulo Python do handler (ex: src.agents.kronos). NULL = usa fallback if-chain no agent_daemon.';
COMMENT ON COLUMN vectraclip.operation_types_catalog.handler_function IS
  'Função do handler dentro do módulo (ex: entrypoint). Assinatura: (task) ou (task, supabase) conforme handler_pass_supabase.';
COMMENT ON COLUMN vectraclip.operation_types_catalog.handler_is_async IS
  'true → dispatcher chama via asyncio.run(fn(...)).';
COMMENT ON COLUMN vectraclip.operation_types_catalog.handler_pass_supabase IS
  'true → fn(task, supabase); false → fn(task).';

-- ── Backfill: 10 handlers com assinatura canônica (task, supabase), sync ──────
UPDATE vectraclip.operation_types_catalog SET handler_module='src.agents.morpheus_inbound_triage', handler_function='entrypoint',           handler_is_async=false, handler_pass_supabase=true  WHERE id='inbound-triage';
UPDATE vectraclip.operation_types_catalog SET handler_module='src.agents.mercator',                handler_function='handle_freight_quotation', handler_is_async=false, handler_pass_supabase=true WHERE id='freight-quotation';
UPDATE vectraclip.operation_types_catalog SET handler_module='src.agents.kronos',                  handler_function='entrypoint',               handler_is_async=false, handler_pass_supabase=true WHERE id='financial-audit';
UPDATE vectraclip.operation_types_catalog SET handler_module='src.agents.kronos',                  handler_function='entrypoint_backlog',       handler_is_async=false, handler_pass_supabase=true WHERE id IN ('conciliacao-backlog','financial-bookkeeping');
UPDATE vectraclip.operation_types_catalog SET handler_module='src.agents.kronos_planner',          handler_function='entrypoint_planner_import',handler_is_async=false, handler_pass_supabase=true WHERE id='planner-import-ofx';
UPDATE vectraclip.operation_types_catalog SET handler_module='src.agents.kronos_planner',          handler_function='entrypoint_categorize_pendings', handler_is_async=false, handler_pass_supabase=true WHERE id='planner-categorize-pendings';
UPDATE vectraclip.operation_types_catalog SET handler_module='src.agents.kronos_audit',            handler_function='entrypoint_kronos_audit',  handler_is_async=false, handler_pass_supabase=true WHERE id='kronos-audit-historico';
UPDATE vectraclip.operation_types_catalog SET handler_module='src.agents.kronos_apply_corrections',handler_function='entrypoint_apply_corrections', handler_is_async=false, handler_pass_supabase=true WHERE id='planner-apply-corrections';
UPDATE vectraclip.operation_types_catalog SET handler_module='src.agents.mnemos',                  handler_function='entrypoint',               handler_is_async=false, handler_pass_supabase=true WHERE id='rag-ingest';

-- ── Caso especial: oracle-report tem assinatura (task) — SÓ task (Correção B) ─
UPDATE vectraclip.operation_types_catalog SET handler_module='src.agents.hermes_reporter',         handler_function='entrypoint',               handler_is_async=false, handler_pass_supabase=false WHERE id='oracle-report';

NOTIFY pgrst, 'reload schema';
