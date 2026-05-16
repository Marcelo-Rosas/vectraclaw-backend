-- Daedalus PR D — bpmn_diagrams + bpmn_diagram_versions
--
-- Doc de planejamento: docs/EXECUCAO-G1-RISK-REGISTER-E-DAEDALUS.md §2.4
-- Schema interno JSON (NÃO BPMN 2.0 XML — engine própria, sem Camunda).
-- Decisão registrada na memória: feedback_no_camunda_keep_custom_engine.
--
-- Tabelas:
--   - bpmn_diagrams (current state) + trigger snapshot
--   - bpmn_diagram_versions (histórico append-only)
--
-- Vínculos opcionais (LogFrame Schmidt — diagrama pode visualizar processo
-- SIPOC, workflow, ou estar standalone vinculado só a um goal):
--   - linked_sipoc_process_id
--   - linked_workflow_id
--   - linked_goal_id
--
-- Origem (rastreabilidade):
--   - generated_by: manual | athena | daedalus | imported
--   - generated_by_task_id: FK opcional pra task que gerou (Daedalus dispatch)
--
-- Versionamento: cada UPDATE em diagram_json automaticamente INSERT no
-- bpmn_diagram_versions com a versão anterior (snapshot). version é incrementado.

-- =============================================================================
-- TABELA principal: bpmn_diagrams
-- =============================================================================

CREATE TABLE IF NOT EXISTS vectraclip.bpmn_diagrams (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES vectraclip.companies(company_id) ON DELETE CASCADE,

  -- Vínculos opcionais (LogFrame Schmidt)
  linked_sipoc_process_id UUID REFERENCES vectraclip.sipoc_processes(id) ON DELETE SET NULL,
  linked_workflow_id      UUID REFERENCES vectraclip.workflow_definitions(id) ON DELETE SET NULL,
  linked_goal_id          UUID REFERENCES vectraclip.goals(id) ON DELETE SET NULL,

  -- Metadados
  name        TEXT NOT NULL,
  description TEXT,

  -- Diagrama (JSON nativo do canvas @xyflow/react)
  -- Shape esperado: {nodes: [...], edges: [...], viewport?: {...}}
  -- Validação rica fica no handler Daedalus (PR G); aqui só garantimos JSONB
  diagram_json JSONB NOT NULL,

  -- Versionamento (auto-incrementado por trigger em UPDATE)
  version INTEGER NOT NULL DEFAULT 1,

  -- Origem
  generated_by         TEXT NOT NULL CHECK (generated_by IN ('manual', 'athena', 'daedalus', 'imported')),
  generated_by_task_id UUID REFERENCES vectraclip.tasks(id) ON DELETE SET NULL,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- HISTÓRICO: bpmn_diagram_versions (append-only)
-- =============================================================================

CREATE TABLE IF NOT EXISTS vectraclip.bpmn_diagram_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  diagram_id UUID NOT NULL REFERENCES vectraclip.bpmn_diagrams(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  diagram_json JSONB NOT NULL,
  changed_by_user_id UUID,
  change_notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (diagram_id, version)
);

-- =============================================================================
-- ÍNDICES
-- =============================================================================

CREATE INDEX IF NOT EXISTS bpmn_diagrams_company_idx
  ON vectraclip.bpmn_diagrams(company_id);

CREATE INDEX IF NOT EXISTS bpmn_diagrams_linked_sipoc_idx
  ON vectraclip.bpmn_diagrams(linked_sipoc_process_id)
  WHERE linked_sipoc_process_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS bpmn_diagrams_linked_workflow_idx
  ON vectraclip.bpmn_diagrams(linked_workflow_id)
  WHERE linked_workflow_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS bpmn_diagrams_linked_goal_idx
  ON vectraclip.bpmn_diagrams(linked_goal_id)
  WHERE linked_goal_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS bpmn_diagram_versions_diagram_idx
  ON vectraclip.bpmn_diagram_versions(diagram_id, version DESC);

-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- 1) Snapshot da versão anterior em UPDATE de diagram_json
--    (NOTA: SECURITY DEFINER aplicado em hotfix subsequente
--     20260516210001_bpmn_trigger_security_definer.sql — necessário porque
--     authenticated tem só SELECT em bpmn_diagram_versions)
CREATE OR REPLACE FUNCTION vectraclip.bpmn_snapshot_version()
RETURNS TRIGGER AS $$
BEGIN
  -- Só snapshota se o JSON realmente mudou (evita ruído de PATCH só de name/description)
  IF TG_OP = 'UPDATE' AND OLD.diagram_json IS DISTINCT FROM NEW.diagram_json THEN
    INSERT INTO vectraclip.bpmn_diagram_versions (diagram_id, version, diagram_json)
    VALUES (OLD.id, OLD.version, OLD.diagram_json);
    NEW.version := OLD.version + 1;
  END IF;
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS bpmn_diagrams_version_trigger ON vectraclip.bpmn_diagrams;
CREATE TRIGGER bpmn_diagrams_version_trigger
  BEFORE UPDATE ON vectraclip.bpmn_diagrams
  FOR EACH ROW EXECUTE FUNCTION vectraclip.bpmn_snapshot_version();

-- =============================================================================
-- RLS — tenant-aware (mesmo padrão sipoc_raci PR #142 e risks PR #149)
-- =============================================================================

ALTER TABLE vectraclip.bpmn_diagrams ENABLE ROW LEVEL SECURITY;
ALTER TABLE vectraclip.bpmn_diagram_versions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bpmn_diagrams_select_own_tenant ON vectraclip.bpmn_diagrams;
CREATE POLICY bpmn_diagrams_select_own_tenant ON vectraclip.bpmn_diagrams
  FOR SELECT
  USING (
    company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid)
  );

DROP POLICY IF EXISTS bpmn_diagrams_write_admin_tenant ON vectraclip.bpmn_diagrams;
CREATE POLICY bpmn_diagrams_write_admin_tenant ON vectraclip.bpmn_diagrams
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

DROP POLICY IF EXISTS bpmn_diagrams_service_role_all ON vectraclip.bpmn_diagrams;
CREATE POLICY bpmn_diagrams_service_role_all ON vectraclip.bpmn_diagrams
  FOR ALL
  TO service_role
  USING (TRUE) WITH CHECK (TRUE);

-- Versões herdam mesma visibilidade do diagrama pai (via JOIN no SELECT)
DROP POLICY IF EXISTS bpmn_diagram_versions_select_via_diagram ON vectraclip.bpmn_diagram_versions;
CREATE POLICY bpmn_diagram_versions_select_via_diagram ON vectraclip.bpmn_diagram_versions
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM vectraclip.bpmn_diagrams d
       WHERE d.id = bpmn_diagram_versions.diagram_id
         AND d.company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid)
    )
  );

-- INSERT em versions: só via trigger (service_role bypass garante o trigger funcionar)
DROP POLICY IF EXISTS bpmn_diagram_versions_service_role_all ON vectraclip.bpmn_diagram_versions;
CREATE POLICY bpmn_diagram_versions_service_role_all ON vectraclip.bpmn_diagram_versions
  FOR ALL
  TO service_role
  USING (TRUE) WITH CHECK (TRUE);

-- =============================================================================
-- GRANTS
-- =============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON vectraclip.bpmn_diagrams TO authenticated;
GRANT SELECT ON vectraclip.bpmn_diagram_versions TO authenticated;
GRANT ALL ON vectraclip.bpmn_diagrams TO service_role;
GRANT ALL ON vectraclip.bpmn_diagram_versions TO service_role;

-- =============================================================================
-- NOTIFY pgrst — recarrega schema cache da REST API
-- =============================================================================

NOTIFY pgrst, 'reload schema';
