-- PR-A (Modelo C) — Tabela agent_shared_config + seed Kronos + remove campos
-- compartilhados das 3 specialties de Kronos
--
-- Hoje 4 campos repetem-se entre as specialties do Kronos (ofx_path, recipient,
-- pdf_path, planner_instituicao). O usuário precisa preencher o mesmo path em
-- 2-3 cards diferentes — duplicação de UX que vira drift silencioso ao editar
-- só um lado.
--
-- Mudança: extrai os 4 campos para `vectraclip.agent_shared_config`, uma row
-- por (company_id, agent_id). Specialties ficam apenas com campos específicos
-- do fluxo. Resolver consome cadeia:
--   payload (task.input_json)
--      > specialty.values
--      > agent_shared_config.values  ← NOVO
--      > task.description KEY=VALUE
--      > env vars
--
-- Idempotente em todas as operações.

set search_path to vectraclip, public;

-- ════════════════════════════════════════════════════════════════════════════
-- 1. Tabela agent_shared_config
-- ════════════════════════════════════════════════════════════════════════════
create table if not exists vectraclip.agent_shared_config (
  id          uuid        primary key default gen_random_uuid(),
  company_id  uuid        not null,
  agent_id    uuid        not null,
  values      jsonb       not null default '{}'::jsonb,
  schema      jsonb       not null default '[]'::jsonb,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint agent_shared_config_company_agent_unique unique (company_id, agent_id)
);

alter table vectraclip.agent_shared_config owner to postgres;

comment on table vectraclip.agent_shared_config is
  'Campos compartilhados entre as specialties de um agente. Defaults globais por (company, agent). Resolver lê após specialty.values mas antes de description KEY=VALUE.';

comment on column vectraclip.agent_shared_config.schema is
  'Field descriptors igual a agent_specialties.config_schema (lista de {key, label, type, required, default, description}).';

comment on column vectraclip.agent_shared_config.values is
  'Valores concretos preenchidos pelo usuário via tab Skills da UI.';

-- Index extra (company_id, agent_id) já é coberto pelo UNIQUE constraint.
create index if not exists idx_agent_shared_config_agent
  on vectraclip.agent_shared_config (agent_id);

-- ════════════════════════════════════════════════════════════════════════════
-- 2. Seed Kronos × Vectra Cargo
--    schema dos 4 campos compartilhados; values={} (usuário preenche via UI)
-- ════════════════════════════════════════════════════════════════════════════
do $$
declare
  v_company_id uuid := '01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2';
  v_kronos_id  uuid := '9c8d7e6f-5a4b-4321-9876-543210fedcba';
  v_schema     jsonb := '[
    {
      "key": "ofx_path",
      "label": "Caminho do OFX (compartilhado)",
      "type": "text",
      "required": false,
      "description": "Diretório ou arquivo .ofx usado por todas as specialties do Kronos."
    },
    {
      "key": "planner_instituicao",
      "label": "Instituição financeira",
      "type": "text",
      "required": false,
      "description": "Nome no combobox partitionId do Meu Planner. Default: primeira opção real."
    },
    {
      "key": "pdf_path",
      "label": "PDF do extrato (opcional)",
      "type": "text",
      "required": false,
      "description": "PDF C6 para enrichment de descrições genéricas (PIX → nome do estabelecimento)."
    },
    {
      "key": "recipient",
      "label": "Email destinatário do relatório",
      "type": "text",
      "required": false,
      "default": "marcelo.rosas@vectracargo.com.br",
      "description": "Email para onde os relatórios do Kronos (audit + import) são enviados."
    }
  ]'::jsonb;
begin
  insert into vectraclip.agent_shared_config (company_id, agent_id, values, schema)
  values (v_company_id, v_kronos_id, '{}'::jsonb, v_schema)
  on conflict (company_id, agent_id) do update
    set schema     = excluded.schema,
        updated_at = now();
end $$;

-- ════════════════════════════════════════════════════════════════════════════
-- 3. UPDATE specialties — remover campos que foram pra agent_shared_config
-- ════════════════════════════════════════════════════════════════════════════

-- 3.1. financial-audit: tira ofx_path + recipient; mantém planner_path + período
update vectraclip.agent_specialties
set config_schema = '[
  {
    "key": "planner_path",
    "label": "Caminho do Planner (legacy)",
    "type": "text",
    "required": false,
    "description": "CSV/XLSX exportado do Meu Planner (modo audit-only)"
  },
  {
    "key": "periodo_inicio",
    "label": "Período início (YYYY-MM-DD)",
    "type": "text",
    "required": false,
    "description": "Data início no formato ISO YYYY-MM-DD"
  },
  {
    "key": "periodo_fim",
    "label": "Período fim (YYYY-MM-DD)",
    "type": "text",
    "required": false,
    "description": "Data fim no formato ISO YYYY-MM-DD"
  }
]'::jsonb
where id = 'financial-audit';

-- 3.2. planner-import-ofx: todos os 4 campos foram pra shared → schema vazio
update vectraclip.agent_specialties
set config_schema = '[]'::jsonb
where id = 'planner-import-ofx';

-- 3.3. planner-categorize-pendings: pdf_path foi pra shared → schema vazio
update vectraclip.agent_specialties
set config_schema = '[]'::jsonb
where id = 'planner-categorize-pendings';

-- ════════════════════════════════════════════════════════════════════════════
-- 4. Verificação
-- ════════════════════════════════════════════════════════════════════════════
do $$
declare
  v_shared_rows int;
  v_financial_fields int;
  v_import_fields int;
  v_categorize_fields int;
begin
  select count(*) into v_shared_rows
    from vectraclip.agent_shared_config
    where agent_id = '9c8d7e6f-5a4b-4321-9876-543210fedcba';

  select jsonb_array_length(config_schema) into v_financial_fields
    from vectraclip.agent_specialties where id = 'financial-audit';
  select jsonb_array_length(config_schema) into v_import_fields
    from vectraclip.agent_specialties where id = 'planner-import-ofx';
  select jsonb_array_length(config_schema) into v_categorize_fields
    from vectraclip.agent_specialties where id = 'planner-categorize-pendings';

  if v_shared_rows = 1
     and v_financial_fields = 3
     and v_import_fields = 0
     and v_categorize_fields = 0 then
    raise notice 'PR-A: migration OK (shared=1, financial=3, import=0, categorize=0)';
  else
    raise warning 'PR-A: verificação falhou — shared=%, financial=%, import=%, categorize=%',
      v_shared_rows, v_financial_fields, v_import_fields, v_categorize_fields;
  end if;
end $$;

-- ════════════════════════════════════════════════════════════════════════════
-- 5. RLS — agent_shared_config segue padrão das demais (autenticated read,
--    service_role write).
-- ════════════════════════════════════════════════════════════════════════════
alter table vectraclip.agent_shared_config enable row level security;

drop policy if exists "agent_shared_config_read_authenticated"
  on vectraclip.agent_shared_config;
create policy "agent_shared_config_read_authenticated"
  on vectraclip.agent_shared_config
  for select
  to authenticated
  using (true);

drop policy if exists "agent_shared_config_write_service_role"
  on vectraclip.agent_shared_config;
create policy "agent_shared_config_write_service_role"
  on vectraclip.agent_shared_config
  for all
  to service_role
  using (true)
  with check (true);
