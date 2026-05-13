-- PR-DA — Categorização por domínio canônico
--
-- Hoje `vectraclip.agent_specialties.domain` é texto livre. Resultado:
-- 21 specialties espalhadas em 12 valores diferentes, com sobreposição
-- conceitual (Data/Knowledge/Research/Intelligence/Analytics), linguagem
-- misturada (PT/EN), typos e 1 specialty órfã criada via UI.
--
-- Esta migration:
--   1. Cria tabela canônica `vectraclip.agent_domains` (7 domínios PT-BR)
--   2. Deleta specialty órfã `upload-ofx` (sp_1778676294, prompt vazio,
--      0 consumers, duplicata conceitual de `planner-import-ofx`)
--   3. UPDATE agent_specialties.domain mapeando os 12 textos livres → 7 slugs
--   4. Adiciona FK agent_specialties.domain → agent_domains(id)
--
-- Idempotente — UPSERT + WHERE clauses específicas.

set search_path to vectraclip, public;

-- ════════════════════════════════════════════════════════════════════════════
-- 1. Tabela agent_domains
-- ════════════════════════════════════════════════════════════════════════════
create table if not exists vectraclip.agent_domains (
  id            text        primary key,           -- slug: 'finance', 'logistics', ...
  name          text        not null,              -- 'Financeiro', 'Logística', ...
  description   text,
  icon          text,                              -- nome do ícone (lucide-react)
  color         text,                              -- tailwind class ou hex
  display_order int         not null default 100,
  is_active     boolean     not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

alter table vectraclip.agent_domains owner to postgres;
comment on table vectraclip.agent_domains is
  'Catálogo canônico de domínios de skills. Substitui o campo texto livre em agent_specialties.domain.';

-- ════════════════════════════════════════════════════════════════════════════
-- 2. Seed dos 7 domínios canônicos
-- ════════════════════════════════════════════════════════════════════════════
insert into vectraclip.agent_domains (id, name, description, icon, color, display_order) values
  ('finance',       'Financeiro',
   'Auditoria, conciliação OFX, categorização de lançamentos, despachos financeiros.',
   'wallet',           'text-emerald-600',  10),
  ('logistics',     'Logística',
   'Cotação de fretes, cálculo de rotas, validação de tabelas, integrações com transportadoras.',
   'truck',            'text-blue-600',     20),
  ('communication', 'Comunicação',
   'Monitoramento de inbox, disparo de e-mails, WhatsApp/Telegram, relatórios SMTP.',
   'message-circle',   'text-purple-600',   30),
  ('intelligence',  'Inteligência & Pesquisa',
   'Research web, sumarização, vision, scout em redes sociais, relatórios analíticos.',
   'search',           'text-amber-600',    40),
  ('knowledge',     'Dados & Conhecimento',
   'Extração estruturada, RAG, análise de dados, processamento de arquivos.',
   'database',         'text-cyan-600',     50),
  ('automation',    'Processos & Automação',
   'Workflow Builder, geração de fluxos a partir de SIPOC, orquestração de tasks.',
   'workflow',         'text-pink-600',     60),
  ('crm',           'CRM & Clientes',
   'Preenchimento de CRM, gerenciamento de oportunidades, follow-up comercial.',
   'users',            'text-indigo-600',   70)
on conflict (id) do update
  set name          = excluded.name,
      description   = excluded.description,
      icon          = excluded.icon,
      color         = excluded.color,
      display_order = excluded.display_order,
      is_active     = excluded.is_active,
      updated_at    = now();

-- ════════════════════════════════════════════════════════════════════════════
-- 3. Cleanup: deletar specialty órfã `upload-ofx` (sp_1778676294)
--    - prompt_template vazio
--    - 0 consumers (nenhum agent_specialty_configs)
--    - duplicata conceitual de `planner-import-ofx` (que tem 1735 chars
--      de prompt rico + 1 consumer + config_schema completo)
-- ════════════════════════════════════════════════════════════════════════════
delete from vectraclip.agent_specialty_configs
  where specialty_id = 'sp_1778676294';

delete from vectraclip.agent_specialties
  where id = 'sp_1778676294'
    and slug = 'upload-ofx'
    and coalesce(length(system_prompt_template), 0) = 0
    and not exists (
      select 1 from vectraclip.agent_specialty_configs c
      where c.specialty_id = 'sp_1778676294'
    );

-- ════════════════════════════════════════════════════════════════════════════
-- 4. UPDATE agent_specialties.domain — mapeamento texto livre → slug canônico
--
-- Mapping table (12 valores antigos → 7 slugs canônicos):
--
--   Analytics              → knowledge   (data-analysis)
--   Automação de Processos → automation  (workflow-builder)
--   Communication          → communication
--   CRM                    → crm
--   Data                   → knowledge   (oracle-extract)
--   Finance                → finance
--   Intelligence           → intelligence
--   Knowledge              → knowledge
--   Logistics              → logistics
--   Operations             → knowledge   (file-processing; upload-ofx será deletado)
--   Research               → intelligence (web-research)
--   Social Intelligence    → intelligence (scout-redes-sociais)
-- ════════════════════════════════════════════════════════════════════════════
update vectraclip.agent_specialties set domain = 'finance'      where domain in ('Finance');
update vectraclip.agent_specialties set domain = 'logistics'    where domain in ('Logistics');
update vectraclip.agent_specialties set domain = 'communication' where domain in ('Communication');
update vectraclip.agent_specialties set domain = 'crm'          where domain in ('CRM');
update vectraclip.agent_specialties set domain = 'intelligence' where domain in ('Intelligence', 'Research', 'Social Intelligence');
update vectraclip.agent_specialties set domain = 'knowledge'    where domain in ('Knowledge', 'Data', 'Analytics', 'Operations');
update vectraclip.agent_specialties set domain = 'automation'   where domain in ('Automação de Processos');

-- ════════════════════════════════════════════════════════════════════════════
-- 5. FOREIGN KEY agent_specialties.domain → agent_domains(id)
-- ════════════════════════════════════════════════════════════════════════════
-- Drop FK se existir (re-run safe), depois recria.
alter table vectraclip.agent_specialties
  drop constraint if exists fk_agent_specialties_domain;

alter table vectraclip.agent_specialties
  add constraint fk_agent_specialties_domain
  foreign key (domain) references vectraclip.agent_domains (id)
  on update cascade
  on delete restrict;

-- ════════════════════════════════════════════════════════════════════════════
-- 6. Verificação final (best-effort: log via raise notice)
-- ════════════════════════════════════════════════════════════════════════════
do $$
declare
  v_unmapped int;
begin
  -- Specialties sem domain canônico válido (não deve haver após este script)
  select count(*) into v_unmapped
  from vectraclip.agent_specialties s
  where s.domain is null
     or not exists (select 1 from vectraclip.agent_domains d where d.id = s.domain);

  if v_unmapped > 0 then
    raise warning 'PR-DA: % specialty(ies) com domain inválido após migration', v_unmapped;
  else
    raise notice 'PR-DA: todas as specialties mapeadas para 7 domínios canônicos';
  end if;
end $$;
