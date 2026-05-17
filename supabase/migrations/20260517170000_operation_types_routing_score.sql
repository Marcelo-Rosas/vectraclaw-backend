-- A.4 do ADR Fase A (decisão P13 Opção 1 — 2026-05-17): aposenta
-- `_OPERATION_TYPE_SCORES` hardcoded em `src/managed_agents/decision_engine.py`
-- via coluna `routing_score` em `operation_types_catalog`.
--
-- ANTES: 10 entries hardcoded no Python (`_OPERATION_TYPE_SCORES`); 30 dos
-- 40 operation_types do catálogo caíam no default 60 sem visibilidade — bug
-- documentado no ADR §7.7 (varredura 2026-05-17).
--
-- DEPOIS: cada row do catálogo tem `routing_score` explícito (0-100).
-- `decision_engine.should_use_managed_agent()` lê do catálogo via
-- helper `_load_operation_type_routing_scores()` cacheado 60s.
-- Regra de Ouro #2 (NO HARDCODE).
--
-- Risco operacional: ZERO. ADD COLUMN aditivo com DEFAULT 60 (comportamento
-- atual preservado pra tipos não enumerados). Backfill explícito só nos 10
-- conhecidos.

ALTER TABLE vectraclip.operation_types_catalog
  ADD COLUMN IF NOT EXISTS routing_score smallint NOT NULL DEFAULT 60
  CHECK (routing_score BETWEEN 0 AND 100);

COMMENT ON COLUMN vectraclip.operation_types_catalog.routing_score IS
  'Score 0-100 do Decision Engine (CMA × Harness). 0=sempre harness, 100=sempre CMA. Threshold padrão CMA_THRESHOLD=50. Lido por src/managed_agents/decision_engine.py:_load_operation_type_routing_scores (cache TTL 60s). Substitui _OPERATION_TYPE_SCORES hardcoded desde A.4 do ADR Fase A (2026-05-17).';

-- Backfill: 10 valores conhecidos do _OPERATION_TYPE_SCORES histórico.
-- Demais operation_types (30+) herdam DEFAULT 60 — comportamento atual.
UPDATE vectraclip.operation_types_catalog SET routing_score = 0   WHERE id = 'orchestration';        -- coordenação multi-step → harness
UPDATE vectraclip.operation_types_catalog SET routing_score = 10  WHERE id = 'email_lead';            -- HermesReporter trata nativo
UPDATE vectraclip.operation_types_catalog SET routing_score = 15  WHERE id = 'code_generation';      -- precisa bash/file tools → harness
UPDATE vectraclip.operation_types_catalog SET routing_score = 35  WHERE id = 'qa_testing';            -- pode precisar execução → lean harness
UPDATE vectraclip.operation_types_catalog SET routing_score = 65  WHERE id = 'code_review';           -- análise pura → lean CMA
UPDATE vectraclip.operation_types_catalog SET routing_score = 75  WHERE id = 'document_generation';   -- síntese estruturada → CMA
UPDATE vectraclip.operation_types_catalog SET routing_score = 80  WHERE id = 'freight-quotation';     -- extração briefing + cotação → CMA
UPDATE vectraclip.operation_types_catalog SET routing_score = 85  WHERE id = 'research';              -- síntese de informação → CMA
UPDATE vectraclip.operation_types_catalog SET routing_score = 85  WHERE id = 'athena-onboarding';     -- síntese estruturada perfil → CMA
-- 'other' fica em 60 (default — bate com hardcoded antigo)

-- Verificação shadow-replay safe (NOTICE em vez de EXCEPTION)
DO $$
DECLARE n_explicit int; n_default int;
BEGIN
  SELECT count(*) INTO n_explicit FROM vectraclip.operation_types_catalog WHERE routing_score != 60;
  SELECT count(*) INTO n_default FROM vectraclip.operation_types_catalog WHERE routing_score = 60;
  RAISE NOTICE 'routing_score backfill: % com valor explícito, % no DEFAULT 60', n_explicit, n_default;
END $$;

NOTIFY pgrst, 'reload schema';
