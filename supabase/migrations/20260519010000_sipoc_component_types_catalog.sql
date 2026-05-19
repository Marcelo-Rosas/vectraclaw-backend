-- PR2.1 do roadmap autopilot night (F-006).
-- Auditor a778cf6d57ef076a5 cravou GO COM AJUSTES: type sem CHECK + status sem CHECK
-- bloqueava o commit do Oracle session (PR2.3). Marcelo decidiu Opção B (catalog + FK)
-- pra component types e CHECK rígido pra process status (máquina de estados fechada PMI).
--
-- ESPELHEI ANTES (Regra de Ouro #1):
--   - SELECT count FROM vectraclip.sipoc_components → 0 rows (FK safe sem backfill)
--   - SELECT count FROM vectraclip.sipoc_processes → 0 rows (CHECK safe sem backfill)
--   - SELECT conname FROM pg_constraint WHERE conrelid='vectraclip.sipoc_components'::regclass
--     → só sipoc_components_automation_status_check; NÃO existe constraint em type
--   - SELECT conname FROM pg_constraint WHERE conrelid='vectraclip.sipoc_processes'::regclass
--     → zero CHECKs em status
--   - Valores válidos pra type vêm de src/agents/oracle.py:50-55 (_SIPOC_TYPE_LABELS):
--     activity | supplier | input | output | customer (5 valores PMBOK SIPOC clássicos)
--   - Valores válidos pra status vêm de src/services/sipoc_approvals.py:9-14
--     (transitions): rascunho | em_revisao | aprovado
--
-- PADRÃO ADOTADO (espelha goal_kinds, business_case_strengths, agent_status_types):
--   - Catalog com PK text (slug). Shape: slug | name | description | display_order |
--     is_active | created_at | updated_at.
--   - Cross-tenant (sem company_id) — vocabulário PMI canônico, não config per-company.
--   - FK lógica em sipoc_components.type → sipoc_component_types.slug (ON DELETE RESTRICT).
--   - RLS ENABLE com policy SELECT pra authenticated (vocabulário público dentro do app),
--     escrita só via service_role (DDL/admin). Mesmo padrão de agent_status_types
--     (mas Wave 2A esqueceu de habilitar RLS lá — registrar pra sweep futuro).
--
-- Risco: BAIXO. Tabelas downstream vazias (0 rows). FK + CHECK = no-op em backfill.

-- ============================================================================
-- 1) Catalog sipoc_component_types (cross-tenant, PMI canonical)
-- ============================================================================

CREATE TABLE IF NOT EXISTS vectraclip.sipoc_component_types (
  slug          text         PRIMARY KEY,
  name          text         NOT NULL,
  description   text,
  display_order integer      NOT NULL DEFAULT 0,
  is_active     boolean      NOT NULL DEFAULT true,
  created_at    timestamptz  NOT NULL DEFAULT now(),
  updated_at    timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE vectraclip.sipoc_component_types IS
  'Catalog cross-tenant pros 5 tipos de SIPOC component (Suppliers/Inputs/Process activity/Outputs/Customers). PMI canônico. Substitui hardcode em src/agents/oracle.py:50-55 (_SIPOC_TYPE_LABELS). FK em sipoc_components.type. Extensível via INSERT (ex: decision_point, event futuros) sem migration nova — Opção B do PR2.1 (autopilot night 2026-05-19).';

INSERT INTO vectraclip.sipoc_component_types (slug, name, description, display_order) VALUES
  ('supplier', 'Fornecedor',  'Quem fornece os Inputs do processo (área, sistema, parceiro)',         10),
  ('input',    'Entrada',     'Insumo material/informacional consumido pelas atividades',             20),
  ('activity', 'Atividade',   'Passo executável do Process (P do SIPOC). Recebe 5W2H + RACI.',        30),
  ('output',   'Saída',       'Produto/entregável gerado pelas atividades',                           40),
  ('customer', 'Cliente',     'Quem recebe os Outputs (interno ou externo)',                          50)
ON CONFLICT (slug) DO NOTHING;

ALTER TABLE vectraclip.sipoc_component_types ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sipoc_component_types_select_all ON vectraclip.sipoc_component_types;
CREATE POLICY sipoc_component_types_select_all
  ON vectraclip.sipoc_component_types
  FOR SELECT
  TO authenticated
  USING (true);

-- Writes só via service_role (sem policy = bloqueado pra authenticated).

-- ============================================================================
-- 2) FK sipoc_components.type → sipoc_component_types.slug
-- ============================================================================

-- Defensivo: drop CHECK se algum sweep futuro tiver criado entre o audit e este push.
ALTER TABLE vectraclip.sipoc_components
  DROP CONSTRAINT IF EXISTS sipoc_components_type_check;

ALTER TABLE vectraclip.sipoc_components
  ADD CONSTRAINT sipoc_components_type_fk
  FOREIGN KEY (type)
  REFERENCES vectraclip.sipoc_component_types(slug)
  ON DELETE RESTRICT;

-- ============================================================================
-- 3) CHECK sipoc_processes.status (máquina de estados fechada PMI)
-- ============================================================================
-- NOTA: optei por CHECK (não catalog) porque máquina de estados PMI/PMO tem
-- 3 estados estáveis (rascunho → em_revisao → aprovado) sem perspectiva de
-- crescer. Diferente de component_types onde futuro pode pedir decision_point,
-- event, gateway etc. Se status precisar crescer, refator pra catalog é trivial.

-- Defensivo: drop se já existir
ALTER TABLE vectraclip.sipoc_processes
  DROP CONSTRAINT IF EXISTS sipoc_processes_status_check;

ALTER TABLE vectraclip.sipoc_processes
  ADD CONSTRAINT sipoc_processes_status_check
  CHECK (status IS NULL OR status = ANY (ARRAY['rascunho'::text, 'em_revisao'::text, 'aprovado'::text]));

-- ============================================================================
-- 4) Backfill defensivo (idempotente)
-- ============================================================================
-- Se houver rows pré-existentes com status NULL ou type inválido, este UPDATE
-- normaliza pra valores aceitos antes do CHECK/FK aprovar. Hoje 0 rows — no-op.

UPDATE vectraclip.sipoc_processes
SET status = 'rascunho'
WHERE status IS NULL OR status NOT IN ('rascunho','em_revisao','aprovado');

-- Para sipoc_components, NÃO faço backfill blind — se houvesse type inválido
-- seria erro de dados que merece visibilidade humana, não normalização silenciosa.
-- Como 0 rows, este comentário é doc; INSERT futuro com type inválido vai bater
-- no FK e devolver erro 23503 (foreign_key_violation) — comportamento desejado.
