-- M3 do plano Brain → Daedalus (autopilot 2026-05-19). Marcelo cravou:
-- usar fluxo de conciliação bancária Kronos como caso real, NÃO importação
-- marítima fictícia do Brain.
--
-- ESPELHEI ANTES (Regra de Ouro #1):
--   - vectraclip.workflow_steps: schema confirmado, ferramentas jsonb default []
--   - vectraclip.workflow_definitions: trigger_type DEFAULT 'manual' já existe
--   - vectraclip.operation_types_catalog: planner-import-ofx, planner-categorize-pendings,
--     kronos-audit-historico, planner-apply-corrections — TODOS existem como rows
--   - vectraclip.companies: VECTRA IA SERVICES = 01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2
--   - vectraclip.agents: Kronos = 9c8d7e6f-5a4b-4321-9876-543210fedcba (SSOT em src/agent_ids.py)
--   - tools_catalog: NÃO EXISTE — primeira aparição
--
-- Aplica:
--   1. CREATE tools_catalog (cross-tenant — Marcelo cravou)
--   2. Seed 8 tools (3 m3_tools + 5 Kronos pipeline)
--   3. INSERT workflow_definitions "Conciliação Bancária Mensal" (1 row Vectra)
--   4. INSERT 4 workflow_steps mapeando op_types reais do Kronos
--   5. Comment marcando endpoint GET /api/agent/workflow pra retornar DB (TODO M3 code part)
--
-- Workflow é catalog-driven (Regra Ouro #2): step.ferramentas[] aponta pra
-- tools_catalog.id como soft FK (validação no agente, não no DB — flexibilidade
-- pra runtime tools que ainda não estão no catalog).

-- ============================================================================
-- 1) tools_catalog cross-tenant (W14.1 + M3)
-- ============================================================================

CREATE TABLE IF NOT EXISTS vectraclip.tools_catalog (
  id              text         PRIMARY KEY,
  name            text         NOT NULL,
  description     text,
  category        text         NOT NULL,
  runtime_module  text,        -- ex: 'src.m3_tools.calculate_cbm' ou 'src.services.kronos_browser'
  display_order   integer      NOT NULL DEFAULT 0,
  is_active       boolean      NOT NULL DEFAULT true,
  created_at      timestamptz  NOT NULL DEFAULT now(),
  updated_at      timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE vectraclip.tools_catalog IS
  'Catalog cross-tenant das tools que workflow_steps.ferramentas[] referencia. Soft FK — validacao no agente, nao no DB. Categories: parser, browser, llm, db, http, render. Criado em M3 (autopilot 2026-05-19) substituindo hardcode em m3_tools.TOOLS_REGISTRY + brain/workflow_aduaneiro.py.';

ALTER TABLE vectraclip.tools_catalog ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tools_catalog_select_all ON vectraclip.tools_catalog;
CREATE POLICY tools_catalog_select_all
  ON vectraclip.tools_catalog
  FOR SELECT
  TO authenticated
  USING (true);

-- Writes só via service_role (sem policy).

-- ============================================================================
-- 2) Seed 8 tools (3 m3 + 5 Kronos)
-- ============================================================================

INSERT INTO vectraclip.tools_catalog (id, name, description, category, runtime_module, display_order) VALUES
  -- M3 tools (logística — uso atual em workflow aduaneiro futuro)
  ('calculate_cbm',
   'Calcular CBM',
   'Calcula Cubic Meter a partir de dimensoes de caixa/pallet (length, width, height, quantity)',
   'parser',
   'src.m3_tools.calculate_cbm',
   10),
  ('extract_bl_pl',
   'Extrair BL/PL',
   'OCR + parsing de Bill of Lading e Packing List (PDF). Cross-ref opcional.',
   'parser',
   'src.m3_tools.extract_bl_pl',
   20),
  ('infer_vehicle_capacity',
   'Inferir capacidade de veiculo',
   'Estima capacidade veicular (peso + volume) baseado em CBM e payload',
   'parser',
   'src.m3_tools.infer_vehicle_capacity',
   30),

  -- Kronos pipeline (conciliação bancária)
  ('playwright_planner_browser',
   'Playwright Browser Planner',
   'Sessao Playwright autenticada no webapp Meu Planner Financeiro pra import/edit',
   'browser',
   'src.agents.kronos_browser.KronosPlannerSession',
   40),
  ('ofx_parser',
   'OFX Parser',
   'Parse de arquivo OFX bancario em transacoes estruturadas',
   'parser',
   'src.agents.kronos_planner.parse_ofx',
   50),
  ('kronos_rules_engine',
   'Kronos Rules Engine',
   'Aplica 113 regras de classificacao (vectraclip.kronos_rules) sobre transacoes',
   'db',
   'src.agents.kronos.apply_rules',
   60),
  ('markdown_renderer',
   'Markdown Renderer',
   'Gera relatorio em markdown a partir de dict (usado por audit-historico)',
   'render',
   'src.agents.kronos_audit.render_report',
   70),
  ('smtp_sender',
   'SMTP Sender',
   'Envia email via HermesReporter SMTP (configurado por agent_adapter_configs)',
   'http',
   'src.services.hermes_smtp.send',
   80)
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- 3) workflow_definitions "Conciliação Bancária Mensal"
-- ============================================================================

-- UUID fixo pra reuso em workflow_steps abaixo (idempotente — ON CONFLICT slug)
INSERT INTO vectraclip.workflow_definitions (
  id, company_id, name, slug, description, is_active, version, trigger_type, is_scheduled
)
VALUES (
  '00000000-0000-4000-8000-000000000001',  -- fixo, namespace separado de UUIDs aleatorios
  '01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2',  -- VECTRA IA SERVICES
  'Conciliação Bancária Mensal',
  'conciliacao-bancaria-mensal',
  'Pipeline Kronos: import OFX → categoriza pendings → audit histórico → aplica correções no Meu Planner Financeiro. Materializado em M3 (autopilot 2026-05-19) substituindo workflow_aduaneiro.py do Brain.',
  true,
  1,
  'manual',
  false
)
ON CONFLICT (company_id, slug) DO NOTHING;

-- ============================================================================
-- 4) workflow_steps — 4 steps mapeando op_types reais do Kronos
-- ============================================================================

INSERT INTO vectraclip.workflow_steps (
  workflow_id,
  step_order,
  name,
  slug,
  default_operation_type,
  responsavel,
  setor,
  ferramentas,
  proximo_step_codes,
  on_failure_action
)
VALUES
  -- W1: Import OFX
  (
    '00000000-0000-4000-8000-000000000001',
    1,
    'Import OFX no Meu Planner',
    'import-ofx',
    'planner-import-ofx',
    'agente',
    'Financeiro',
    '["playwright_planner_browser", "ofx_parser"]'::jsonb,
    ARRAY['categorize-pendings'],
    'block'
  ),
  -- W2: Categorize pendings
  (
    '00000000-0000-4000-8000-000000000001',
    2,
    'Categorizar transações pendentes',
    'categorize-pendings',
    'planner-categorize-pendings',
    'agente',
    'Financeiro',
    '["kronos_rules_engine"]'::jsonb,
    ARRAY['audit-historico'],
    'block'
  ),
  -- W3: Audit histórico
  (
    '00000000-0000-4000-8000-000000000001',
    3,
    'Audit histórico (relatório markdown)',
    'audit-historico',
    'kronos-audit-historico',
    'agente',
    'Financeiro',
    '["markdown_renderer", "smtp_sender"]'::jsonb,
    ARRAY['apply-corrections'],
    'block'
  ),
  -- W4: Apply corrections (opcional, requer approval)
  (
    '00000000-0000-4000-8000-000000000001',
    4,
    'Aplicar correções no Planner (após aprovação humana)',
    'apply-corrections',
    'planner-apply-corrections',
    'agente',
    'Financeiro',
    '["playwright_planner_browser"]'::jsonb,
    ARRAY[]::text[],  -- terminal
    'block'
  )
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 5) Coment endpoint (TODO code part separada)
-- ============================================================================
-- GET /api/agent/workflow será refactored em PR separado pra ler do DB
-- (workflow_definitions + workflow_steps) em vez de brain/workflow_aduaneiro.py.
-- Brain workflow_aduaneiro fica como deprecation_warning até M5.
