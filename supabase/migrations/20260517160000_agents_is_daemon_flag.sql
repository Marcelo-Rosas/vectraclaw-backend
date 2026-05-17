-- Adiciona `agents.is_daemon` para aposentar 2 listas hardcoded de daemons.
--
-- Causa do PR: discrepância UI 2026-05-17 — Daedalus mostrava "Ocioso"
-- mesmo heartbeating normalmente (10 hb/5min). Diagnóstico:
-- `src/api_routes/system.py:_DAEMON_AGENTS` é lista de 10 hardcoded
-- (faltava Daedalus). Endpoint `/api/system/daemons` não retornava Daedalus,
-- `useDaemons()` no frontend dava `daemon=undefined`, AgentCard caía no
-- branch "Ocioso" do `displayStatusLabel`.
--
-- Fix completo (Regra de Ouro #2 — NO HARDCODE):
-- 1. Adicionar coluna `is_daemon` aqui (aditivo, default false)
-- 2. Backfill TRUE nos 11 daemons conhecidos (start_all_daemons.py:DAEMONS)
-- 3. `src/api_routes/system.py` e `start_all_daemons.py` aposentam listas
--    hardcoded → query Supabase WHERE is_daemon=true
--
-- NÃO usa `is_system` (semântica diferente — guardrail de mutation; ver
-- athena.py:2446 que rejeita modificação de agents is_system=true).
--
-- Risco operacional: zero. ADD COLUMN aditivo com DEFAULT false; backfill
-- explícito só dos 11 daemons conhecidos. Outros agents (qualquer agent que
-- venha a ser criado via UI/CMA) ficam com is_daemon=false (comportamento
-- atual preservado — não viram subprocess).

ALTER TABLE vectraclip.agents
  ADD COLUMN IF NOT EXISTS is_daemon BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN vectraclip.agents.is_daemon IS
  'Quando true, este agent tem daemon Python rodando como subprocess (lock em .daemon_locks/<id>.lock). Distinto de is_system (proteção contra mutation). Setado nos 11 daemons canônicos do VectraClaw. Consumido por src/api_routes/system.py e start_all_daemons.py — catalog-driven desde 2026-05-17.';

-- Backfill: 11 daemons canônicos (idempotente — pode rodar 2x sem efeito)
UPDATE vectraclip.agents SET is_daemon = TRUE WHERE id IN (
  '00000000-0000-0000-0000-000000000001',  -- Morpheus
  '00000000-0000-0000-0000-000000000002',  -- Oracle
  '00000000-0000-0000-0000-000000000003',  -- Mnemos
  '59b7a69e-cc53-4063-85f9-5dcc5619ac96',  -- Hermes
  'c7de1b0f-7c74-42f1-9de4-7210349e668e',  -- Mercator
  '80fd6d0e-53ab-4638-b6e9-05cbbd121092',  -- Plutus
  '0d6e56cc-28b6-4382-96cd-1952b890d412',  -- Hodos
  '360a96cb-b1c3-4b65-b9fa-2b9cbb59dac1',  -- Hermes Reporter
  '9c8d7e6f-5a4b-4321-9876-543210fedcba',  -- Kronos
  'ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d',  -- Athena
  'd4ed4145-0000-4000-8000-000000000005'   -- Daedalus
);

-- Verificação (não falha — só loga). RAISE NOTICE em vez de EXCEPTION
-- pra shadow DB do `db pull` não quebrar quando agents não está seed.
DO $$
DECLARE n_daemons int;
BEGIN
  SELECT count(*) INTO n_daemons FROM vectraclip.agents WHERE is_daemon = TRUE;
  RAISE NOTICE 'is_daemon backfill: % daemons marcados (esperado: 11 no remoto, 0 no shadow)', n_daemons;
END $$;

NOTIFY pgrst, 'reload schema';
