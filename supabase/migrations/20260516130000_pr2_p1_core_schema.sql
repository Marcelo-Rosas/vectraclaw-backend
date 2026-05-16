-- =============================================================================
-- PR2 — Fase A / P1 core: schema pra discovery + diagnóstico + marketplace SIPOC
--
-- Referência: docs/ARCHITECTURE-TO-BE.md Seções 1.3 e 1.4 (Módulo P1 — Consultoria).
--
-- Mudanças (todas non-destructive, FKs nullable, IF NOT EXISTS):
--   1. vectraclip.sipoc_components: 5 colunas novas
--      - responsible_position_id     (FK pra sipoc_positions; quem responde)
--      - automation_status           (CHECK: undefined|manual|hybrid|automated)
--      - suggested_operation_type    (FK pra operation_types_catalog.id)
--      - diagnostic_metadata         (JSONB livre pra Athena)
--      - cloned_from_template_id     (FK pra sipoc_taxonomy_global, criada abaixo)
--
--   2. vectraclip.sipoc_taxonomy_global (NOVA): catálogo global de atividades
--      por vertical/setor (marketplace SIPOC, parte do P1 vendável)
--      + RLS authenticated read (catálogo público pros tenants)
--
--   3. vectraclip.athena_recommendations.kind: amplia CHECK constraint
--      Valor histórico 'rewrite_system_prompt' mantido + 3 novos
--      (diagnose_gap, suggest_automation, suggest_hire_agent)
--
--   4. vectraclip.app_users: assigned_position_id + amplia CHECK role
--      RBAC TO-BE Seção 3.6 (5 roles novos) + valor histórico 'admin' mantido
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. sipoc_components — atributos de RACI + automação + linkagem a template
-- -----------------------------------------------------------------------------

ALTER TABLE vectraclip.sipoc_components
  ADD COLUMN IF NOT EXISTS responsible_position_id UUID
    REFERENCES vectraclip.sipoc_positions(id),
  ADD COLUMN IF NOT EXISTS automation_status TEXT
    DEFAULT 'undefined',
  ADD COLUMN IF NOT EXISTS suggested_operation_type TEXT
    REFERENCES vectraclip.operation_types_catalog(id),
  ADD COLUMN IF NOT EXISTS diagnostic_metadata JSONB DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS cloned_from_template_id UUID;

-- CHECK constraint pra automation_status (separado pra ser idempotente)
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'sipoc_components_automation_status_check'
      AND table_schema = 'vectraclip'
  ) THEN
    ALTER TABLE vectraclip.sipoc_components
      ADD CONSTRAINT sipoc_components_automation_status_check
      CHECK (automation_status IN ('undefined','manual','hybrid','automated'));
  END IF;
END $$;

COMMENT ON COLUMN vectraclip.sipoc_components.responsible_position_id IS
  'Cargo/posição (RACI: Responsible) que executa esta atividade. NULL = não atribuído ainda.';
COMMENT ON COLUMN vectraclip.sipoc_components.automation_status IS
  'Athena classifica: undefined (não avaliado), manual (humano), hybrid (humano+agente), automated (agente puro).';
COMMENT ON COLUMN vectraclip.sipoc_components.suggested_operation_type IS
  'Athena sugere qual operation_type do catálogo se aplica a esta atividade. FK pra operation_types_catalog.id.';
COMMENT ON COLUMN vectraclip.sipoc_components.diagnostic_metadata IS
  'JSONB livre pra Athena: tempo gasto atual, custo atual, frequência, gargalos, etc.';
COMMENT ON COLUMN vectraclip.sipoc_components.cloned_from_template_id IS
  'Se foi importado do marketplace SIPOC, aponta pro template original (auditoria/diff).';


-- -----------------------------------------------------------------------------
-- 2. sipoc_taxonomy_global — marketplace de atividades universais por vertical
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS vectraclip.sipoc_taxonomy_global (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  vertical TEXT NOT NULL,
  category TEXT NOT NULL,
  activity_name TEXT NOT NULL,
  default_5w2h JSONB,
  suggested_operation_type TEXT REFERENCES vectraclip.operation_types_catalog(id),
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sipoc_taxonomy_global_vertical_idx
  ON vectraclip.sipoc_taxonomy_global(vertical);
CREATE INDEX IF NOT EXISTS sipoc_taxonomy_global_category_idx
  ON vectraclip.sipoc_taxonomy_global(category);

COMMENT ON TABLE vectraclip.sipoc_taxonomy_global IS
  'Marketplace SIPOC — catálogo global de atividades por vertical/setor. Sem company_id (global). Cliente importa via clone-to-tenant. Parte do P1 vendável.';

-- FK do sipoc_components.cloned_from_template_id (depois do CREATE TABLE)
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'sipoc_components_cloned_from_template_id_fkey'
      AND table_schema = 'vectraclip'
  ) THEN
    ALTER TABLE vectraclip.sipoc_components
      ADD CONSTRAINT sipoc_components_cloned_from_template_id_fkey
      FOREIGN KEY (cloned_from_template_id)
      REFERENCES vectraclip.sipoc_taxonomy_global(id);
  END IF;
END $$;

-- RLS: catálogo global → leitura authenticated, escrita só service_role
ALTER TABLE vectraclip.sipoc_taxonomy_global ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "sipoc_taxonomy_global_select_authenticated"
  ON vectraclip.sipoc_taxonomy_global;

CREATE POLICY "sipoc_taxonomy_global_select_authenticated"
  ON vectraclip.sipoc_taxonomy_global
  FOR SELECT TO authenticated USING (true);

COMMENT ON POLICY "sipoc_taxonomy_global_select_authenticated"
  ON vectraclip.sipoc_taxonomy_global IS
  'Catálogo global de templates SIPOC — leitura aberta a authenticated. Escrita só service_role (sem policy explícita).';


-- -----------------------------------------------------------------------------
-- 3. athena_recommendations.kind — amplia CHECK constraint
--    Mantém valor histórico 'rewrite_system_prompt' + 3 novos.
-- -----------------------------------------------------------------------------

ALTER TABLE vectraclip.athena_recommendations
  DROP CONSTRAINT IF EXISTS athena_recommendations_kind_check;

ALTER TABLE vectraclip.athena_recommendations
  ADD CONSTRAINT athena_recommendations_kind_check
  CHECK (kind IN (
    'rewrite_system_prompt',  -- histórico (já presente em 1 row); ajuste de prompt do agent
    'diagnose_gap',           -- gap identificado no diagnóstico do P1
    'suggest_automation',     -- sugestão de automação por activity (CTA do P1 → P2)
    'suggest_hire_agent'      -- sugestão de contratar agent (vira athena_hire_suggestions na Fase B)
  ));

COMMENT ON COLUMN vectraclip.athena_recommendations.kind IS
  'Tipo da recomendação Athena. Valores: rewrite_system_prompt (ajusta prompt do agent), diagnose_gap (identifica gargalo no SIPOC), suggest_automation (CTA de automação), suggest_hire_agent (sugestão de contratar agent).';


-- -----------------------------------------------------------------------------
-- 4. app_users — assigned_position_id + amplia role
--    Mantém valor histórico 'admin' + 5 roles do RBAC TO-BE Seção 3.6.
-- -----------------------------------------------------------------------------

ALTER TABLE vectraclip.app_users
  ADD COLUMN IF NOT EXISTS assigned_position_id UUID
    REFERENCES vectraclip.sipoc_positions(id);

COMMENT ON COLUMN vectraclip.app_users.assigned_position_id IS
  'Cargo do user no organograma SIPOC. Usado pra escopar visibilidade quando role=sector_responsible.';

ALTER TABLE vectraclip.app_users
  DROP CONSTRAINT IF EXISTS app_users_role_check;

ALTER TABLE vectraclip.app_users
  ADD CONSTRAINT app_users_role_check
  CHECK (role IN (
    'admin',              -- histórico, mantido (sinônimo de platform_admin)
    'platform_admin',     -- dono da plataforma
    'consultant',         -- consultor multi-tenant (acesso a vários clientes)
    'company_admin',      -- decisor do cliente (CRUD do próprio tenant)
    'sector_responsible', -- responsável de setor/cargo (Oracle chat das próprias activities)
    'viewer'              -- read-only
  ));

-- Default pra novos cadastros: 'company_admin' (decisor do tenant)
ALTER TABLE vectraclip.app_users ALTER COLUMN role SET DEFAULT 'company_admin';

COMMENT ON COLUMN vectraclip.app_users.role IS
  'RBAC. admin/platform_admin = dono. consultant = multi-tenant. company_admin = decisor do tenant. sector_responsible = escopo do cargo (assigned_position_id). viewer = read-only.';
