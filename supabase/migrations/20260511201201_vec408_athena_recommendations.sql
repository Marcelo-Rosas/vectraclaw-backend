-- =============================================================================
-- VEC-408 (slice 2/3 do VEC-389) — athena_recommendations + FK circular
-- =============================================================================
-- Tabela onde Athena registra recomendações pendentes de approval humano.
-- Handler `athena-recommend` insere com status='pending'. Aprovação é manual
-- (UI futura) — Athena NUNCA auto-aplica.
--
-- Sub-PR 1 do VEC-408 (este arquivo): tabela + RLS + grants + FK circular
-- com vectraclip.agent_prompt_history (criada no arquivo 20260511201200).
--
-- Decisão de contrato: reviewed_by_user_id usa auth.users(id) ON DELETE
-- SET NULL — Supabase Auth nativo. vectraclip.app_users NÃO existe.
-- =============================================================================

CREATE TABLE IF NOT EXISTS vectraclip.athena_recommendations (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id               uuid NOT NULL REFERENCES vectraclip.companies(company_id) ON DELETE CASCADE,
  triggered_by_goal_id     uuid REFERENCES vectraclip.goals(id) ON DELETE SET NULL,
  triggered_by_task_id     uuid REFERENCES vectraclip.tasks(id) ON DELETE SET NULL,

  -- Tipo da recomendação
  kind text NOT NULL CHECK (kind IN (
    'hire_new_agent',
    'add_specialty',
    'rewrite_system_prompt',
    'create_specialty',
    'consolidate_agents'
  )),

  -- Alvo (nullable quando kind=hire_new_agent — agent ainda não existe)
  target_agent_id     uuid REFERENCES vectraclip.agents(id) ON DELETE CASCADE,
  target_specialty_id text,  -- FK opcional (agent_specialties pode não ter PK uuid)

  -- Conteúdo
  title                text NOT NULL,
  rationale            text NOT NULL,
  proposed_changes_json jsonb NOT NULL,
  citations            jsonb NOT NULL DEFAULT '[]'::jsonb,

  -- Métricas de decisão
  confidence       numeric NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
  estimated_effort text NOT NULL CHECK (estimated_effort IN ('S','M','L','XL')),

  -- Workflow de approval
  status text NOT NULL DEFAULT 'pending' CHECK (status IN (
    'pending',     -- recém-criada pelo handler; aguarda revisão humana
    'approved',    -- humano aprovou; aguarda apply manual
    'applied',     -- aplicada em prod; applied_history_id linka history row
    'rejected',    -- humano rejeitou (review_notes obrigatório)
    'superseded'   -- substituída por recommendation mais nova
  )),
  reviewed_by_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  reviewed_at         timestamptz,
  review_notes        text,
  applied_history_id  uuid REFERENCES vectraclip.agent_prompt_history(id) ON DELETE SET NULL,

  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Index parcial: lookup rápido de pendentes (caminho quente do painel UI)
CREATE INDEX IF NOT EXISTS athena_recommendations_pending_idx
  ON vectraclip.athena_recommendations (company_id, target_agent_id, kind)
  WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS athena_recommendations_goal_idx
  ON vectraclip.athena_recommendations (triggered_by_goal_id)
  WHERE triggered_by_goal_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS athena_recommendations_target_idx
  ON vectraclip.athena_recommendations (target_agent_id)
  WHERE target_agent_id IS NOT NULL;

-- Constraint UNIQUE PARTIAL: impede 2 pending pro mesmo (target_agent_id, kind)
-- (idempotência hard-enforced no DB; handler também valida em Python)
CREATE UNIQUE INDEX IF NOT EXISTS athena_recommendations_unique_pending
  ON vectraclip.athena_recommendations (target_agent_id, kind)
  WHERE status = 'pending' AND target_agent_id IS NOT NULL;

COMMENT ON TABLE vectraclip.athena_recommendations IS
  'Recomendações Athena (mandato 2/VEC-389). status=pending até humano aprovar; nunca auto-aplica.';
COMMENT ON COLUMN vectraclip.athena_recommendations.reviewed_by_user_id IS
  'FK para auth.users (Supabase Auth nativo). ON DELETE SET NULL.';
COMMENT ON INDEX vectraclip.athena_recommendations_pending_idx IS
  'Hot path: SELECT WHERE status=pending no painel UI.';


-- ─────────────────────────────────────────────────────────────────────────────
-- FK CIRCULAR: agent_prompt_history.recommendation_id → athena_recommendations(id)
-- Coluna existe desde o arquivo 20260511201200 (nullable). Adiciona constraint agora.
-- ON DELETE SET NULL — se rec deletada, history fica órfã sem trava.
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'agent_prompt_history_recommendation_fk'
  ) THEN
    ALTER TABLE vectraclip.agent_prompt_history
      ADD CONSTRAINT agent_prompt_history_recommendation_fk
      FOREIGN KEY (recommendation_id)
      REFERENCES vectraclip.athena_recommendations(id)
      ON DELETE SET NULL;
  END IF;
END $$;


-- ─────────────────────────────────────────────────────────────────────────────
-- Trigger: updated_at automático
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION vectraclip.fn_set_athena_rec_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_athena_rec_updated_at ON vectraclip.athena_recommendations;
CREATE TRIGGER trg_athena_rec_updated_at
  BEFORE UPDATE ON vectraclip.athena_recommendations
  FOR EACH ROW
  EXECUTE FUNCTION vectraclip.fn_set_athena_rec_updated_at();


-- ─────────────────────────────────────────────────────────────────────────────
-- RLS — padrão rag_corpus
-- SELECT/UPDATE authenticated da mesma company (UI approve/reject)
-- ALL service_role (handler INSERT)
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE vectraclip.athena_recommendations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS athena_recommendations_select_own ON vectraclip.athena_recommendations;
CREATE POLICY athena_recommendations_select_own ON vectraclip.athena_recommendations
  FOR SELECT TO authenticated
  USING (
    company_id::text = (
      ((auth.jwt() -> 'app_metadata') -> 'vectraclip' ->> 'company_id')
    )
  );

-- Authenticated pode UPDATE (approve/reject/mark-applied) na própria company.
-- INSERT continua restrito a service_role (handler do daemon).
DROP POLICY IF EXISTS athena_recommendations_update_own ON vectraclip.athena_recommendations;
CREATE POLICY athena_recommendations_update_own ON vectraclip.athena_recommendations
  FOR UPDATE TO authenticated
  USING (
    company_id::text = (
      ((auth.jwt() -> 'app_metadata') -> 'vectraclip' ->> 'company_id')
    )
  )
  WITH CHECK (
    company_id::text = (
      ((auth.jwt() -> 'app_metadata') -> 'vectraclip' ->> 'company_id')
    )
  );

DROP POLICY IF EXISTS athena_recommendations_service_role_all ON vectraclip.athena_recommendations;
CREATE POLICY athena_recommendations_service_role_all ON vectraclip.athena_recommendations
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);


-- ─────────────────────────────────────────────────────────────────────────────
-- Grants
-- ─────────────────────────────────────────────────────────────────────────────
GRANT SELECT, UPDATE ON vectraclip.athena_recommendations TO authenticated;
GRANT ALL ON vectraclip.athena_recommendations TO service_role;


NOTIFY pgrst, 'reload schema';
