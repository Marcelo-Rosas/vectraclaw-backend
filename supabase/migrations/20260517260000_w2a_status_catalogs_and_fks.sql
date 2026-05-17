-- ESPELHEI ANTES:
--   (1) SELECT slug FROM workflow_trigger_types WHERE is_active
--       → 4 slugs: manual, cron, webhook, event. Único valor em uso (1 wf_def)
--       é 'manual' — FK safe sem backfill.
--   (2) SELECT DISTINCT status FROM agents/heartbeats
--       → ambos só usam {idle, working, errored} — subset dos 5 valores
--       canonicais (working, idle, paused, errored, offline).
--   (3) approvals: 0 rows. goals.kind: 0 rows com valor. business_case_strength: idem.
--       routines: 0 rows. Tabelas vazias = sem backfill, só ALTER + INSERT seeds.
-- PADRÃO ADOTADO:
--   - Catalogs com PK text (slug). Mesmo shape de workflow_trigger_types e
--     workflow_logic_patterns (id text, name text, description text,
--     display_order int, is_active boolean, ...).
--   - FK lógica (não composta com company_id) — esses domínios são
--     CROSS-TENANT (status/kind/strength são vocabulário do framework, não
--     config per-company).
--   - Drop CHECK constraints que duplicavam o catalog (igual W1A fez com
--     workflow_steps_logic_pattern_check).
--
-- Wave 2A do GSD ampliado — PRD-CONTRATOS P1 (5 items consolidados).
-- Resolve: AUDIT-003 (trigger_type FK), AUDIT-004 (agent status catalog),
-- AUDIT-006 (approval request_type catalog), AUDIT-007 (goal_kinds +
-- business_case_strengths catalogs), AUDIT-016 (routines status padronizado).
--
-- Risco: BAIXO. Tabelas downstream vazias (approvals/routines) ou subset
-- coberto (agents/heartbeats/wf_def). Backfill = INSERT seeds via ON CONFLICT
-- DO NOTHING. Drop+Add CHECK idempotente.

-- ============================================================================
-- AUDIT-003 — workflow_definitions.trigger_type → workflow_trigger_types.slug
-- ============================================================================

ALTER TABLE vectraclip.workflow_definitions
  ADD CONSTRAINT workflow_definitions_trigger_type_fk
  FOREIGN KEY (trigger_type)
  REFERENCES vectraclip.workflow_trigger_types(slug)
  ON DELETE RESTRICT;

-- ============================================================================
-- AUDIT-004 — agent_status_types catalog (CROSS-TENANT, sem company_id)
-- Substitui CHECKs duplicados em agents.status e heartbeats.status.
-- ============================================================================

CREATE TABLE IF NOT EXISTS vectraclip.agent_status_types (
  slug          text         PRIMARY KEY,
  name          text         NOT NULL,
  description   text,
  icon          text,
  display_order integer      NOT NULL DEFAULT 0,
  is_active     boolean      NOT NULL DEFAULT true,
  created_at    timestamptz  NOT NULL DEFAULT now(),
  updated_at    timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE vectraclip.agent_status_types IS
  'Catalog cross-tenant para agents.status e heartbeats.status (W2A AUDIT-004). Substitui CHECKs duplicados que divergiam ao adicionar novo valor.';

INSERT INTO vectraclip.agent_status_types (slug, name, description, display_order) VALUES
  ('idle',    'Ocioso',       'Daemon vivo aguardando task',                10),
  ('working', 'Em execução',  'Daemon processando task no momento',         20),
  ('paused',  'Pausado',      'Daemon vivo mas não pega novas tasks',       30),
  ('errored', 'Erro',         'Daemon vivo mas última task falhou',         40),
  ('offline', 'Offline',      'Daemon morto ou sem heartbeat há > N min',   50)
ON CONFLICT (slug) DO NOTHING;

-- Drop CHECKs duplicados
ALTER TABLE vectraclip.agents
  DROP CONSTRAINT IF EXISTS agents_status_check;
ALTER TABLE vectraclip.heartbeats
  DROP CONSTRAINT IF EXISTS heartbeats_status_check;

-- Add FKs cross-tenant (sem ON DELETE — status_types não devem ser removidos)
ALTER TABLE vectraclip.agents
  ADD CONSTRAINT agents_status_fk
  FOREIGN KEY (status) REFERENCES vectraclip.agent_status_types(slug)
  ON DELETE RESTRICT;
ALTER TABLE vectraclip.heartbeats
  ADD CONSTRAINT heartbeats_status_fk
  FOREIGN KEY (status) REFERENCES vectraclip.agent_status_types(slug)
  ON DELETE RESTRICT;

-- ============================================================================
-- AUDIT-006 — approval_request_types catalog
-- ============================================================================

CREATE TABLE IF NOT EXISTS vectraclip.approval_request_types (
  slug          text         PRIMARY KEY,
  name          text         NOT NULL,
  description   text,
  icon          text,
  display_order integer      NOT NULL DEFAULT 0,
  is_active     boolean      NOT NULL DEFAULT true,
  created_at    timestamptz  NOT NULL DEFAULT now(),
  updated_at    timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE vectraclip.approval_request_types IS
  'Catalog cross-tenant pra approvals.request_type (W2A AUDIT-006). Substitui CHECK hardcoded.';

INSERT INTO vectraclip.approval_request_types (slug, name, description, display_order) VALUES
  ('hire_agent',      'Contratar Agente',     'Adicionar novo agente ao roster',                10),
  ('strategy',        'Decisão Estratégica',  'Aprovar mudança de direção/prioridade',          20),
  ('budget_increase', 'Aumento de Orçamento', 'Aprovar aumento de budget_limit em task/agent',  30),
  ('task_done',       'Conclusão de Task',    'Aprovar marcação de task como done',             40)
ON CONFLICT (slug) DO NOTHING;

ALTER TABLE vectraclip.approvals
  DROP CONSTRAINT IF EXISTS approvals_request_type_check;
ALTER TABLE vectraclip.approvals
  ADD CONSTRAINT approvals_request_type_fk
  FOREIGN KEY (request_type) REFERENCES vectraclip.approval_request_types(slug)
  ON DELETE RESTRICT;

-- ============================================================================
-- AUDIT-007 — goal_kinds + business_case_strengths catalogs (PMBOK canonical)
-- ============================================================================

CREATE TABLE IF NOT EXISTS vectraclip.goal_kinds (
  slug          text         PRIMARY KEY,
  name          text         NOT NULL,
  description   text,
  display_order integer      NOT NULL DEFAULT 0,
  is_active     boolean      NOT NULL DEFAULT true,
  created_at    timestamptz  NOT NULL DEFAULT now(),
  updated_at    timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE vectraclip.goal_kinds IS
  'Catalog cross-tenant PMBOK canonical pra goals.kind (W2A AUDIT-007). Vocabulário fixo do framework Heldman.';

INSERT INTO vectraclip.goal_kinds (slug, name, description, display_order) VALUES
  ('objective_outcome',     'Objetivo (Outcome)',        'Resultado de negócio mensurável (ex: aumentar conversão 20%)',  10),
  ('output',                'Output',                    'Entregável concreto (ex: novo módulo de cotação)',              20),
  ('deliverable',           'Entregável',                'Artefato físico/digital específico (ex: relatório SIPOC)',      30),
  ('key_result',            'Key Result (OKR)',          'Métrica que mede progresso de um Objective',                    40),
  ('operational_target',    'Meta Operacional',          'Target contínuo do dia-a-dia (ex: SLA de 24h)',                 50),
  ('compliance_obligation', 'Obrigação de Compliance',   'Requisito regulatório/legal (LGPD, ANTT, etc.)',                60)
ON CONFLICT (slug) DO NOTHING;

CREATE TABLE IF NOT EXISTS vectraclip.business_case_strengths (
  slug          text         PRIMARY KEY,
  name          text         NOT NULL,
  description   text,
  display_order integer      NOT NULL DEFAULT 0,
  is_active     boolean      NOT NULL DEFAULT true,
  created_at    timestamptz  NOT NULL DEFAULT now(),
  updated_at    timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE vectraclip.business_case_strengths IS
  'Catalog cross-tenant PMBOK canonical pra goals.business_case_strength (W2A AUDIT-007). Avalia força do case que justifica o goal.';

INSERT INTO vectraclip.business_case_strengths (slug, name, description, display_order) VALUES
  ('strong',         'Forte',           'Case com evidência quantitativa robusta + endorsement de stakeholder',  10),
  ('moderate',       'Moderado',        'Case com evidência parcial; assumptions a validar',                      20),
  ('weak',           'Fraco',           'Case especulativo; mais hipótese que dado',                              30),
  ('none',           'Sem case',        'Nenhuma justificativa formal registrada',                                40),
  ('not_applicable', 'Não se aplica',   'Tipo de goal (ex: compliance obrigatório) dispensa case',                50)
ON CONFLICT (slug) DO NOTHING;

ALTER TABLE vectraclip.goals
  ADD CONSTRAINT goals_kind_fk
  FOREIGN KEY (kind) REFERENCES vectraclip.goal_kinds(slug)
  ON DELETE RESTRICT;
ALTER TABLE vectraclip.goals
  ADD CONSTRAINT goals_business_case_strength_fk
  FOREIGN KEY (business_case_strength) REFERENCES vectraclip.business_case_strengths(slug)
  ON DELETE RESTRICT;

-- ============================================================================
-- AUDIT-016 — routines.status padronizar 'error' → 'errored'
-- (Consistência com agents/tasks/heartbeats. Decisão Marcelo 2026-05-17.)
-- Tabela vazia (0 rows), só ALTER CHECK.
-- ============================================================================

ALTER TABLE vectraclip.routines
  DROP CONSTRAINT IF EXISTS routines_status_check;
ALTER TABLE vectraclip.routines
  ADD CONSTRAINT routines_status_check
  CHECK (status IS NULL OR status = ANY (ARRAY['active'::text, 'paused'::text, 'errored'::text]));

-- ============================================================================
-- Verificação shadow-replay safe
-- ============================================================================

DO $$
DECLARE
  n_trigger_fk      int;
  n_agent_status    int;
  n_approval_types  int;
  n_goal_kinds      int;
  n_bcs             int;
  n_routine_check   int;
BEGIN
  SELECT COUNT(*) INTO n_trigger_fk
  FROM pg_constraint
  WHERE conname = 'workflow_definitions_trigger_type_fk';

  SELECT COUNT(*) INTO n_agent_status FROM vectraclip.agent_status_types;
  SELECT COUNT(*) INTO n_approval_types FROM vectraclip.approval_request_types;
  SELECT COUNT(*) INTO n_goal_kinds FROM vectraclip.goal_kinds;
  SELECT COUNT(*) INTO n_bcs FROM vectraclip.business_case_strengths;

  SELECT COUNT(*) INTO n_routine_check
  FROM pg_constraint
  WHERE conname = 'routines_status_check';

  RAISE NOTICE 'W2A status: trigger_type FK created (1 esperado): % | agent_status_types seeds (5): % | approval_request_types seeds (4): % | goal_kinds seeds (6): % | business_case_strengths seeds (5): % | routines CHECK errored (1): %',
    n_trigger_fk, n_agent_status, n_approval_types, n_goal_kinds, n_bcs, n_routine_check;
END $$;

NOTIFY pgrst, 'reload schema';
