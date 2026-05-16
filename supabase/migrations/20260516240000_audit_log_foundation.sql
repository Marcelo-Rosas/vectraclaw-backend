-- G1.1 — Audit log foundation
--
-- Bug capturado em docs/AUDIT-HANDLERS-2026-05-16.md §Camada 1:
--   "Audit log nunca alimentado" (🔴 ALTA). Helper generate_audit_log() em
--   src/services/sipoc_approvals.py só monta dict — nunca persiste. Endpoint
--   GET /api/audit-log lê de vectraclip.audit_log mas a tabela NÃO EXISTE
--   (fallback silencioso pra MOCK_AUDIT em api.py:3886).
--
-- Esta migration:
--   1. Cria vectraclip.audit_log (schema espelhando Pydantic AuditLogEntry)
--   2. Indexes pra query padrão (company_id + created_at DESC)
--   3. RLS tenant-aware (SELECT por company); INSERT só service_role
--      (audit é write-once: sem UPDATE/DELETE pra authenticated)
--   4. GRANTs alinhados
--
-- Helper Python `src/services/audit.py` consome esta tabela no mesmo PR.

CREATE TABLE IF NOT EXISTS vectraclip.audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id UUID NOT NULL REFERENCES vectraclip.companies(company_id) ON DELETE CASCADE,

  -- Quem fez (PMBOK auditoria — actor pode ser humano, agente IA, ou system)
  actor_type TEXT NOT NULL CHECK (actor_type IN ('human', 'agent', 'system')),
  actor_id   TEXT NOT NULL,  -- user_id (UUID stringificado) | agent_id | "system-<componente>"

  -- O que fez
  action TEXT NOT NULL,  -- ex: "approval.approve", "risk.create", "user.role_change"
  target TEXT NOT NULL,  -- ex: "approval:<uuid>", "user:<uuid>", "risk:<uuid>", "agent:<uuid>"

  -- Detalhes (livre — JSONB pra acomodar contexto específico por action)
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes pra queries comuns
CREATE INDEX IF NOT EXISTS audit_log_company_created_idx
  ON vectraclip.audit_log(company_id, created_at DESC);

CREATE INDEX IF NOT EXISTS audit_log_actor_idx
  ON vectraclip.audit_log(actor_type, actor_id);

CREATE INDEX IF NOT EXISTS audit_log_action_idx
  ON vectraclip.audit_log(action);

-- RLS — audit é write-once: tenant lê próprio company; só service_role escreve
ALTER TABLE vectraclip.audit_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS audit_log_select_own_tenant ON vectraclip.audit_log;
CREATE POLICY audit_log_select_own_tenant ON vectraclip.audit_log
  FOR SELECT
  USING (
    company_id = ((SELECT (((auth.jwt() -> 'app_metadata') -> 'vectraclip') ->> 'company_id'))::uuid)
  );

DROP POLICY IF EXISTS audit_log_service_role_all ON vectraclip.audit_log;
CREATE POLICY audit_log_service_role_all ON vectraclip.audit_log
  FOR ALL
  TO service_role
  USING (TRUE) WITH CHECK (TRUE);

-- GRANTs — authenticated SÓ lê; service_role insere (helper backend usa)
GRANT SELECT ON vectraclip.audit_log TO authenticated;
GRANT ALL ON vectraclip.audit_log TO service_role;

NOTIFY pgrst, 'reload schema';
