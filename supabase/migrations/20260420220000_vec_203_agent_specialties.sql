-- VEC-203: tabela agent_specialties — catálogo de especialidades de agentes
-- Aplicar em: https://epgedaiukjippepujuzc.supabase.co
-- Ordem: VEC-201 ANTES de VEC-203 (dependência: nenhuma, mas convenção)

create table if not exists vectraclip.agent_specialties (
  id                      text        primary key,
  name                    text        not null,
  slug                    text        not null unique,
  domain                  text        not null,
  description             text,
  compatible_roles        text[]      not null default '{}',
  system_prompt_template  text        not null default '',
  is_active               boolean     not null default true,
  created_at              timestamptz not null default now()
);

create index if not exists agent_specialties_is_active_idx
  on vectraclip.agent_specialties (is_active);

alter table vectraclip.agent_specialties enable row level security;

revoke all on table vectraclip.agent_specialties from anon, authenticated, service_role;
grant select on table vectraclip.agent_specialties to authenticated;
grant select, insert, update on table vectraclip.agent_specialties to service_role;

drop policy if exists agent_specialties_select_authenticated on vectraclip.agent_specialties;
create policy agent_specialties_select_authenticated
  on vectraclip.agent_specialties for select
  to authenticated using (true);

drop policy if exists agent_specialties_write_service_role on vectraclip.agent_specialties;
create policy agent_specialties_write_service_role
  on vectraclip.agent_specialties for all
  to service_role using (true) with check (true);

-- Seed inicial — 4 especialidades (fiel ao seed MSW)
insert into vectraclip.agent_specialties
  (id, name, slug, domain, description, compatible_roles, system_prompt_template)
values
  ('email-monitoring', 'Email Monitoring', 'email-monitoring', 'Communication',
   'Monitora inbox via IMAP, categoriza e resume e-mails.',
   array['Email Intelligence', 'Inbox Assistant', 'Communication'],
   E'# Skill: Agente de Email\n\n## Identidade\nVocê é especialista em monitoramento e triagem de e-mails.'),

  ('web-research', 'Web Research', 'web-research', 'Research',
   'Pesquisa web, extração e síntese de informação.',
   array['Researcher', 'Analyst', 'Scout'],
   E'# Skill: Agente de Pesquisa Web\n\n## Identidade\nVocê é especialista em pesquisa e síntese de informações da web.'),

  ('data-analysis', 'Data Analysis', 'data-analysis', 'Analytics',
   'Análise de dados tabulares e geração de insights.',
   array['Data Analyst', 'BI', 'Analytics'],
   E'# Skill: Agente de Análise de Dados\n\n## Identidade\nVocê é especialista em análise de dados tabulares.'),

  ('file-processing', 'File Processing', 'file-processing', 'Operations',
   'Processamento de arquivos, ETL e transformação de documentos.',
   array['Processor', 'ETL', 'Document Handler'],
   E'# Skill: Agente de Processamento de Arquivos\n\n## Identidade\nVocê é especialista em transformação e processamento de arquivos.')

on conflict (id) do update
set name                   = excluded.name,
    slug                   = excluded.slug,
    domain                 = excluded.domain,
    description            = excluded.description,
    compatible_roles       = excluded.compatible_roles,
    system_prompt_template = excluded.system_prompt_template;
