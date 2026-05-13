-- Task #52 — Catálogo canônico operation_types_catalog
--
-- Hoje task.operation_type é text com CHECK constraint enumerando 36 valores,
-- e Pydantic Task model (src/models.py:98-137) duplica como Literal[...].
-- Frontend VectraClip tem TERCEIRA cópia hardcoded em Zod schema.
--
-- Bug detectado: form Edit Task mostra "Selecionar..." vazio para
-- planner-import-ofx porque frontend não conhece o valor (introduzido em
-- VEC-416). Pattern sistêmico — mesmo enum em 3 lugares dessincronizados.
--
-- Solução: tabela canônica espelhando os 36 valores com metadata rica
-- (nome humano, descrição, categoria, ícone, cor, agente primário,
-- specialty default). Frontend consome GET /api/operation-types e popula
-- dropdown dinamicamente. Backend mantém Literal[...] no Pydantic por
-- validação estática + CHECK constraint por integridade — mas catálogo
-- vira fonte de verdade pra UI.
--
-- Idempotente: CREATE IF NOT EXISTS + ON CONFLICT DO UPDATE.

set search_path to vectraclip, public;

-- ════════════════════════════════════════════════════════════════════════════
-- 1. Tabela canônica
-- ════════════════════════════════════════════════════════════════════════════
create table if not exists vectraclip.operation_types_catalog (
  id                      text        primary key,            -- 'planner-import-ofx'
  name                    text        not null,                -- 'Upload OFX (Meu Planner)'
  description             text,
  category                text        not null,                -- 'kronos', 'oracle', 'athena', 'commercial', etc.
  icon                    text,                                -- lucide-react name
  color                   text,                                -- tailwind class
  display_order           int         not null default 100,
  primary_agent_id        uuid        null,                    -- dono primário (FK soft)
  default_specialty_slug  text        null,                    -- specialty default associada
  is_active               boolean     not null default true,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

alter table vectraclip.operation_types_catalog owner to postgres;

comment on table vectraclip.operation_types_catalog is
  'Catálogo canônico dos operation_types aceitos em tasks. Espelha o Literal[...] do Pydantic Task em src/models.py. Endpoint GET /api/operation-types alimenta dropdown do Edit Task no VectraClip.';

create index if not exists idx_operation_types_category
  on vectraclip.operation_types_catalog (category, display_order);

-- ════════════════════════════════════════════════════════════════════════════
-- 2. Seed dos 36 operation_types (alinhado com src/models.py:98-137)
-- ════════════════════════════════════════════════════════════════════════════
insert into vectraclip.operation_types_catalog
  (id, name, description, category, icon, color, display_order, primary_agent_id, default_specialty_slug)
values
  -- ── Sistema / Genérico ────────────────────────────────────────────────────
  ('orchestration',       'Orquestração',                'Coordenação de tasks entre agentes.',
   'system', 'workflow', 'text-slate-600', 10, '00000000-0000-0000-0000-000000000001', null),
  ('code_generation',     'Geração de Código',           'Gera código com agente LLM.',
   'system', 'code', 'text-slate-600', 20, null, null),
  ('code_review',         'Revisão de Código',           'Revisa PRs/diffs.',
   'system', 'git-pull-request', 'text-slate-600', 30, null, null),
  ('research',            'Pesquisa Genérica',           'Pesquisa de propósito geral.',
   'system', 'search', 'text-slate-600', 40, null, null),
  ('document_generation', 'Geração de Documento',        'Cria documento estruturado.',
   'system', 'file-text', 'text-slate-600', 50, null, null),
  ('qa_testing',          'QA / Testing',                'Validação automatizada.',
   'system', 'check-circle', 'text-slate-600', 60, null, null),

  -- ── Comercial / Logística ─────────────────────────────────────────────────
  ('email_lead',                  'Email Lead',                       'Lead recebido via IMAP.',
   'commercial', 'mail', 'text-violet-600', 100, '59b7a69e-cc53-4063-85f9-5dcc5619ac96', 'email-monitoring'),
  ('freight-quotation',           'Cotação de Frete',                 'Cotação solicitada por embarcador.',
   'commercial', 'truck', 'text-blue-600', 110, 'c7de1b0f-7c74-42f1-9de4-7210349e668e', 'freight-quotation'),
  ('freight-quotation-approval',  'Aprovação Cotação',                'Aprovação humana antes do envio.',
   'commercial', 'check', 'text-blue-600', 120, null, null),
  ('route-cost-calculation',      'Cálculo Rota/Custo',               'Hodos calcula rota e custo via QUALP.',
   'commercial', 'map', 'text-blue-600', 130, '0d6e56cc-28b6-4382-96cd-1952b890d412', 'route-cost-calculation'),

  -- ── CRM ───────────────────────────────────────────────────────────────────
  ('crm-fill-precheck',  'CRM Fill Pré-check',  'Validação prévia antes de preencher CRM.',
   'crm', 'check-square', 'text-indigo-600', 200, '80fd6d0e-53ab-4638-b6e9-05cbbd121092', 'crm-fill'),
  ('crm-fill-finalize',  'CRM Fill Finalizar',  'Finaliza preenchimento do CRM.',
   'crm', 'check-circle', 'text-indigo-600', 210, '80fd6d0e-53ab-4638-b6e9-05cbbd121092', 'crm-fill'),
  ('crm-fill',           'CRM Fill',            'Preenchimento de cotação no CRM (Plutus).',
   'crm', 'edit', 'text-indigo-600', 220, '80fd6d0e-53ab-4638-b6e9-05cbbd121092', 'crm-fill'),

  -- ── Oracle (Intelligence) ─────────────────────────────────────────────────
  ('oracle-research',  'Oracle Research',   'Pesquisa web profunda + síntese.',
   'oracle', 'search', 'text-amber-600', 300, '00000000-0000-0000-0000-000000000002', 'oracle-research'),
  ('oracle-extract',   'Oracle Extract',    'Extração estruturada de documento.',
   'oracle', 'file-search', 'text-amber-600', 310, '00000000-0000-0000-0000-000000000002', 'oracle-extract'),
  ('oracle-report',    'Oracle Report',     'Envio SMTP de relatório (HermesReporter).',
   'oracle', 'send', 'text-amber-600', 320, '360a96cb-b1c3-4b65-b9fa-2b9cbb59dac1', 'oracle-report'),
  ('oracle-rag',       'Oracle RAG Query',  'Consulta semântica no corpus RAG.',
   'oracle', 'database', 'text-amber-600', 330, '00000000-0000-0000-0000-000000000002', 'oracle-rag'),
  ('oracle-vision',    'Oracle Vision',     'Análise visual (multimodal).',
   'oracle', 'eye', 'text-amber-600', 340, '00000000-0000-0000-0000-000000000002', 'oracle-vision'),
  ('oracle-summarize', 'Oracle Summary',    'Sumarização de documento longo.',
   'oracle', 'file-text', 'text-amber-600', 350, '00000000-0000-0000-0000-000000000002', 'oracle-summarize'),
  ('dispatch-research','Dispatch Research', 'Dispatcher de research entre agentes.',
   'oracle', 'arrow-right-circle', 'text-amber-600', 360, '00000000-0000-0000-0000-000000000001', null),

  -- ── Kronos (Financeiro) ──────────────────────────────────────────────────
  ('financial-audit',                'Financial Audit',              'Auditoria OFX vs Planner (modo legacy).',
   'kronos', 'shield-check', 'text-emerald-600', 400, '9c8d7e6f-5a4b-4321-9876-543210fedcba', 'financial-audit'),
  ('financial-bookkeeping',          'Financial Bookkeeping',        'Registro contábil.',
   'kronos', 'book-open', 'text-emerald-600', 410, '9c8d7e6f-5a4b-4321-9876-543210fedcba', null),
  ('conciliacao-backlog',            'Conciliação Backlog',          'Conciliação OFX × planner local.',
   'kronos', 'list-checks', 'text-emerald-600', 420, '9c8d7e6f-5a4b-4321-9876-543210fedcba', 'financial-audit'),
  ('planner-import-ofx',             'Upload OFX (Meu Planner)',     'Pivot VEC-416: upload OFX via Playwright.',
   'kronos-planner', 'upload', 'text-emerald-600', 430, '9c8d7e6f-5a4b-4321-9876-543210fedcba', 'planner-import-ofx'),
  ('planner-categorize-pendings',    'Categorização Pós-Import',     'Categoriza linhas pendentes via regras YAML.',
   'kronos-planner', 'tag', 'text-emerald-600', 440, '9c8d7e6f-5a4b-4321-9876-543210fedcba', 'planner-categorize-pendings'),

  -- ── Mnemos (RAG) ─────────────────────────────────────────────────────────
  ('rag-ingest', 'RAG Ingest', 'Ingere documento no corpus geral.',
   'mnemos', 'database', 'text-cyan-600', 500, '00000000-0000-0000-0000-000000000003', null),

  -- ── Athena (PMBOK) — VEC-388 ─────────────────────────────────────────────
  ('athena-classify',         'Athena Classify',          'Classifica goal/problema em domínio PMBOK.',
   'athena', 'layers', 'text-rose-600', 600, 'ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d', 'athena-classify'),
  ('athena-charter',          'Athena Project Charter',   'Gera Project Charter.',
   'athena', 'scroll', 'text-rose-600', 610, 'ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d', 'athena-charter'),
  ('athena-stakeholder-map',  'Athena Stakeholder Map',   'Mapa de stakeholders.',
   'athena', 'users', 'text-rose-600', 620, 'ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d', 'athena-stakeholder-map'),
  ('athena-risk-register',    'Athena Risk Register',     'Registro de riscos.',
   'athena', 'alert-triangle', 'text-rose-600', 630, 'ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d', 'athena-risk-register'),
  ('athena-evm',              'Athena EVM',               'Earned Value Management.',
   'athena', 'trending-up', 'text-rose-600', 640, 'ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d', 'athena-evm'),
  ('athena-rag-ingest',       'Athena RAG Ingest',        'Ingere documento no corpus Athena (PMBOK).',
   'athena', 'database', 'text-rose-600', 650, 'ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d', 'athena-rag-ingest'),
  ('athena-audit',            'Athena Audit',             'Auditoria de cobertura/qualidade do projeto.',
   'athena', 'shield-check', 'text-rose-600', 660, 'ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d', 'athena-audit'),
  ('athena-recommend',        'Athena Recommend',         'Recomendações de melhoria.',
   'athena', 'lightbulb', 'text-rose-600', 670, 'ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d', 'athena-recommend'),
  ('athena-prioritize',       'Athena Prioritize',        'Priorização de backlog.',
   'athena', 'list-ordered', 'text-rose-600', 680, 'ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d', 'athena-prioritize'),

  -- ── Fallback genérico ────────────────────────────────────────────────────
  ('other', 'Outro', 'Operation type não classificado.',
   'system', 'help-circle', 'text-slate-400', 9999, null, null)
on conflict (id) do update
  set name                   = excluded.name,
      description            = excluded.description,
      category               = excluded.category,
      icon                   = excluded.icon,
      color                  = excluded.color,
      display_order          = excluded.display_order,
      primary_agent_id       = excluded.primary_agent_id,
      default_specialty_slug = excluded.default_specialty_slug,
      is_active              = true,
      updated_at             = now();

-- ════════════════════════════════════════════════════════════════════════════
-- 3. RLS — leitura pública (catálogo), escrita só service_role
-- ════════════════════════════════════════════════════════════════════════════
alter table vectraclip.operation_types_catalog enable row level security;

drop policy if exists "otc_read_authenticated" on vectraclip.operation_types_catalog;
create policy "otc_read_authenticated"
  on vectraclip.operation_types_catalog
  for select to authenticated using (true);

drop policy if exists "otc_write_service_role" on vectraclip.operation_types_catalog;
create policy "otc_write_service_role"
  on vectraclip.operation_types_catalog
  for all to service_role using (true) with check (true);

-- ════════════════════════════════════════════════════════════════════════════
-- 4. Verificação
-- ════════════════════════════════════════════════════════════════════════════
do $$
declare
  v_count int;
  v_orphan_in_check int;
begin
  select count(*) into v_count from vectraclip.operation_types_catalog where is_active;

  -- Garantia: todos op_types usados em tasks.operation_type devem existir no catálogo.
  select count(distinct t.operation_type) into v_orphan_in_check
    from vectraclip.tasks t
    where t.operation_type is not null
      and not exists (
        select 1 from vectraclip.operation_types_catalog c
        where c.id = t.operation_type
      );

  if v_count >= 36 and v_orphan_in_check = 0 then
    raise notice 'Task #52 OK: % op_types ativos no catalogo, 0 orfaos em tasks.', v_count;
  else
    raise warning 'Task #52: count=%, orphans=%', v_count, v_orphan_in_check;
  end if;
end $$;
