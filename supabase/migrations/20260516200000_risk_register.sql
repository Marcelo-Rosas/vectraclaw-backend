-- G1 Fase A — Risk Register PMBOK (tabela formal de riscos)
--
-- Doc de planejamento: docs/EXECUCAO-G1-RISK-REGISTER-E-DAEDALUS.md §3
-- Cobre PMBOK Risk Management: identificar, analisar (prob × impact), responder
-- (avoid/transfer/mitigate/accept/escalate), monitorar.
--
-- Vínculos opcionais com niveis Schmidt LogFrame:
--   - linked_goal_id              → Goal (Pergunta 1 Schmidt: "o que queremos atingir?")
--   - linked_workflow_id          → Workflow (Pergunta 4: "como chegará lá?")
--   - linked_sipoc_process_id     → Process (operacional)
--   - linked_sipoc_component_id   → Component (atividade granular)
--
-- Athena pode popular automaticamente via handler `athena-risk-register` (PR C),
-- marcando detected_by_athena=true e linkando athena_recommendation_id.

-- =============================================================================
-- TABELA principal
-- =============================================================================

CREATE TABLE IF NOT EXISTS vectraclip.risks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES vectraclip.companies(company_id) ON DELETE CASCADE,

  -- Vínculos opcionais (LogFrame Schmidt — risco vive em algum nível objetivo)
  linked_goal_id            UUID REFERENCES vectraclip.goals(id) ON DELETE SET NULL,
  linked_workflow_id        UUID REFERENCES vectraclip.workflow_definitions(id) ON DELETE SET NULL,
  linked_sipoc_process_id   UUID REFERENCES vectraclip.sipoc_processes(id) ON DELETE SET NULL,
  linked_sipoc_component_id UUID REFERENCES vectraclip.sipoc_components(id) ON DELETE SET NULL,

  -- Identidade do risco (PMBOK 6th §11.1)
  name        TEXT NOT NULL,
  description TEXT,
  category    TEXT NOT NULL CHECK (category IN (
    'technical',      -- tecnologia, performance, qualidade, integração
    'external',       -- mercado, fornecedor, regulatório, clima
    'organizational', -- recursos, financiamento, prioridade, política
    'project_mgmt'    -- estimativa, planejamento, controle, comunicação
  )),

  -- Análise quantitativa (PMBOK 6th §11.4 Perform Quantitative Risk Analysis)
  probability NUMERIC NOT NULL CHECK (probability >= 0 AND probability <= 1),  -- 0.0 - 1.0
  impact      NUMERIC NOT NULL CHECK (impact >= 1 AND impact <= 10),           -- 1-10
  risk_score  NUMERIC GENERATED ALWAYS AS (probability * impact) STORED,

  -- Resposta planejada (PMBOK 6th §11.5 Plan Risk Responses)
  response_strategy TEXT CHECK (response_strategy IN (
    'avoid',     -- eliminar a causa
    'transfer',  -- terceirizar (seguro, contrato)
    'mitigate',  -- reduzir prob ou impacto
    'accept',    -- assumir consequências
    'escalate'   -- estourar pra nível acima
  )),
  mitigation_actions TEXT,
  contingency_plan   TEXT,

  -- Ownership (PMBOK risk owner)
  owner_position_id UUID REFERENCES vectraclip.sipoc_positions(id) ON DELETE SET NULL,

  -- Status lifecycle
  status TEXT NOT NULL DEFAULT 'identified' CHECK (status IN (
    'identified',  -- recém-cadastrado, sem análise
    'analyzing',   -- análise em curso
    'planned',     -- response_strategy + mitigation definidos
    'monitoring',  -- ativo, sendo vigiado
    'occurred',    -- materializou, contingência ativada
    'closed'       -- resolvido ou não-mais-aplicável
  )),

  -- Origem via Athena (rastreabilidade)
  detected_by_athena       BOOLEAN NOT NULL DEFAULT FALSE,
  athena_recommendation_id UUID REFERENCES vectraclip.athena_recommendations(id) ON DELETE SET NULL,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- ÍNDICES
-- =============================================================================

CREATE INDEX IF NOT EXISTS risks_company_status_idx
  ON vectraclip.risks(company_id, status);

CREATE INDEX IF NOT EXISTS risks_owner_idx
  ON vectraclip.risks(owner_position_id)
  WHERE owner_position_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS risks_score_desc_idx
  ON vectraclip.risks(risk_score DESC);

CREATE INDEX IF NOT EXISTS risks_linked_goal_idx
  ON vectraclip.risks(linked_goal_id)
  WHERE linked_goal_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS risks_linked_workflow_idx
  ON vectraclip.risks(linked_workflow_id)
  WHERE linked_workflow_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS risks_linked_sipoc_process_idx
  ON vectraclip.risks(linked_sipoc_process_id)
  WHERE linked_sipoc_process_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS risks_linked_sipoc_component_idx
  ON vectraclip.risks(linked_sipoc_component_id)
  WHERE linked_sipoc_component_id IS NOT NULL;

-- =============================================================================
-- TRIGGER updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION vectraclip.risks_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS risks_set_updated_at_trigger ON vectraclip.risks;
CREATE TRIGGER risks_set_updated_at_trigger
  BEFORE UPDATE ON vectraclip.risks
  FOR EACH ROW EXECUTE FUNCTION vectraclip.risks_set_updated_at();

-- =============================================================================
-- RLS — tenant-aware (mesmo padrão sipoc_raci PR #142)
-- =============================================================================

ALTER TABLE vectraclip.risks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS risks_select_own_tenant ON vectraclip.risks;
CREATE POLICY risks_select_own_tenant ON vectraclip.risks
  FOR SELECT
  USING (
    company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid)
  );

DROP POLICY IF EXISTS risks_write_admin_tenant ON vectraclip.risks;
CREATE POLICY risks_write_admin_tenant ON vectraclip.risks
  FOR ALL
  USING (
    company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid)
    AND ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = ANY (
      ARRAY['admin', 'platform_admin', 'consultant', 'company_admin']
    ))
  )
  WITH CHECK (
    company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid)
    AND ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'role')) = ANY (
      ARRAY['admin', 'platform_admin', 'consultant', 'company_admin']
    ))
  );

-- service_role (Athena handler) também precisa escrever
DROP POLICY IF EXISTS risks_service_role_all ON vectraclip.risks;
CREATE POLICY risks_service_role_all ON vectraclip.risks
  FOR ALL
  TO service_role
  USING (TRUE)
  WITH CHECK (TRUE);

-- =============================================================================
-- GRANTS
-- =============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON vectraclip.risks TO authenticated;
GRANT ALL ON vectraclip.risks TO service_role;

-- =============================================================================
-- NOTIFY pgrst — recarrega schema cache da REST API
-- =============================================================================

NOTIFY pgrst, 'reload schema';
