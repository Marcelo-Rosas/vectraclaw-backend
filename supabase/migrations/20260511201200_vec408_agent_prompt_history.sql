-- =============================================================================
-- VEC-408 (slice 2/3 do VEC-389) — agent_prompt_history + trigger
-- =============================================================================
-- Tabela append-only de versionamento de agents.system_prompt. Trigger
-- BEFORE UPDATE OF system_prompt grava OLD em history antes da escrita.
--
-- ⚠️ ANÁLISE DE RISCO DE CONSUMIDORES (registrada no VEC-408):
-- - Trigger `OF system_prompt` é cirúrgico — só dispara nesse campo.
-- - UPDATEs de runtime (current_burn_rate em agent_daemon.py:678, status,
--   etc) NÃO afetam.
-- - Tocam o campo: api.py:5019 (PATCH genérico) e api.py:5094. Comportamento
--   desejado nesses casos (UI Save → history row).
-- - Trigger usa IS DISTINCT FROM: 3 submits idênticos = 1 row em history.
--
-- ⚠️ FK circular para athena_recommendations será adicionada no arquivo
-- 20260511201201_*. Coluna recommendation_id é nullable inicialmente
-- pra não bloquear a migration na ordem correta.
-- =============================================================================

CREATE TABLE IF NOT EXISTS vectraclip.agent_prompt_history (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id        uuid NOT NULL REFERENCES vectraclip.agents(id) ON DELETE CASCADE,
  company_id      uuid REFERENCES vectraclip.companies(company_id) ON DELETE SET NULL,
  version         integer NOT NULL,
  system_prompt   text NOT NULL,
  prompt_length   integer GENERATED ALWAYS AS (length(system_prompt)) STORED,
  source          text NOT NULL CHECK (source IN ('manual','athena_recommendation','migration','seed')),
  -- FK circular adicionada em arquivo posterior (recommendation_id → athena_recommendations(id))
  recommendation_id uuid,
  changed_by_user_id  uuid,
  changed_by_agent_id uuid REFERENCES vectraclip.agents(id) ON DELETE SET NULL,
  change_reason   text,
  created_at      timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT agent_prompt_history_agent_version_unique UNIQUE (agent_id, version)
);

CREATE INDEX IF NOT EXISTS agent_prompt_history_agent_version_idx
  ON vectraclip.agent_prompt_history (agent_id, version DESC);

COMMENT ON TABLE vectraclip.agent_prompt_history IS
  'Versionamento append-only de agents.system_prompt. Snapshot via trigger BEFORE UPDATE.';
COMMENT ON COLUMN vectraclip.agent_prompt_history.recommendation_id IS
  'FK opcional pra athena_recommendations — linkada via ALTER em arquivo posterior.';
COMMENT ON COLUMN vectraclip.agent_prompt_history.changed_by_user_id IS
  'UUID de auth.users (não FK para evitar dependência hard com schema auth — Supabase Auth).';


-- ─────────────────────────────────────────────────────────────────────────────
-- Trigger: snapshot ao UPDATE em agents.system_prompt
-- - IS DISTINCT FROM: só grava se valor mudou (Postgres NULL-safe compare)
-- - version: max(version)+1 por agent_id; começa em 1
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION vectraclip.fn_snapshot_agent_prompt()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  next_version integer;
BEGIN
  IF OLD.system_prompt IS DISTINCT FROM NEW.system_prompt THEN
    SELECT COALESCE(MAX(version), 0) + 1 INTO next_version
    FROM vectraclip.agent_prompt_history
    WHERE agent_id = NEW.id;

    INSERT INTO vectraclip.agent_prompt_history
      (agent_id, company_id, version, system_prompt, source, change_reason)
    VALUES
      (NEW.id, NEW.company_id, next_version, OLD.system_prompt,
       'manual', 'Auto-snapshot before UPDATE in vectraclip.agents');
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_prompt_history ON vectraclip.agents;
CREATE TRIGGER trg_agent_prompt_history
  BEFORE UPDATE OF system_prompt ON vectraclip.agents
  FOR EACH ROW
  EXECUTE FUNCTION vectraclip.fn_snapshot_agent_prompt();


-- ─────────────────────────────────────────────────────────────────────────────
-- RLS — padrão rag_corpus (VEC-360)
-- SELECT: authenticated da mesma company OU service_role
-- INSERT/UPDATE/DELETE: service_role apenas (trigger e backend)
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE vectraclip.agent_prompt_history ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS agent_prompt_history_select_own ON vectraclip.agent_prompt_history;
CREATE POLICY agent_prompt_history_select_own ON vectraclip.agent_prompt_history
  FOR SELECT TO authenticated
  USING (
    company_id::text = (
      ((auth.jwt() -> 'app_metadata') -> 'vectraclip' ->> 'company_id')
    )
  );

DROP POLICY IF EXISTS agent_prompt_history_service_role_all ON vectraclip.agent_prompt_history;
CREATE POLICY agent_prompt_history_service_role_all ON vectraclip.agent_prompt_history
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);


-- ─────────────────────────────────────────────────────────────────────────────
-- Grants explícitos para PostgREST
-- ─────────────────────────────────────────────────────────────────────────────
GRANT SELECT ON vectraclip.agent_prompt_history TO authenticated;
GRANT ALL    ON vectraclip.agent_prompt_history TO service_role;


NOTIFY pgrst, 'reload schema';
