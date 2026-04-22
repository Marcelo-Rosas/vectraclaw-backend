-- =====================================================================
-- VEC-199: Tabelas de Incidentes e Auditoria do Heartbeat Doctor
-- =====================================================================

-- Tier da company. Usado pelo Doctor como dimensão D5 do severity score.
alter table vectraclip.companies
  add column if not exists tier text
    not null default 'trial'
    check (tier in ('trial', 'standard', 'enterprise'));

-- Tabela central de incidentes detectados pelo Doctor.
create table if not exists vectraclip.incidents (
  id           uuid primary key default gen_random_uuid(),
  company_id   uuid not null references vectraclip.companies(id) on delete cascade,
  agent_id     uuid not null references vectraclip.agents(id)    on delete cascade,
  symptom      text not null,
  fix_applied  text,
  severity     text not null check (severity in ('low','medium','high')),
  severity_score integer not null check (severity_score between 0 and 10),
  agent_snapshot jsonb not null,
  decision     text not null check (decision in (
    'auto_healed','pending_council','approved','rejected','undone','manual_fix_required'
  )),
  undo_expires_at timestamptz,
  created_at   timestamptz not null default now(),
  resolved_at  timestamptz
);

create index if not exists incidents_company_created_idx
  on vectraclip.incidents (company_id, created_at desc);
create index if not exists incidents_agent_created_idx
  on vectraclip.incidents (agent_id, created_at desc);
create index if not exists incidents_pending_idx
  on vectraclip.incidents (company_id) where decision = 'pending_council';

-- Log imutável de ações do Doctor.
create table if not exists vectraclip.incident_audit (
  id           uuid primary key default gen_random_uuid(),
  incident_id  uuid not null references vectraclip.incidents(id) on delete cascade,
  event        text not null,
  actor        text not null,
  payload      jsonb,
  created_at   timestamptz not null default now()
);

create index if not exists incident_audit_incident_idx
  on vectraclip.incident_audit (incident_id, created_at);

-- RLS
alter table vectraclip.incidents       enable row level security;
alter table vectraclip.incident_audit  enable row level security;

-- Membros da empresa podem ler os incidentes.
create policy incidents_select_own_company on vectraclip.incidents
  for select to authenticated
  using (company_id = (auth.jwt() -> 'app_metadata' -> 'vectraclip' ->> 'company_id')::uuid);

create policy incident_audit_select_own_company on vectraclip.incident_audit
  for select to authenticated
  using (exists (
    select 1 from vectraclip.incidents i
    where i.id = incident_audit.incident_id
      and i.company_id = (auth.jwt() -> 'app_metadata' -> 'vectraclip' ->> 'company_id')::uuid
  ));

-- Grants
grant select on vectraclip.incidents      to authenticated;
grant select on vectraclip.incident_audit to authenticated;
grant insert, update on vectraclip.incidents to authenticated;
grant insert on vectraclip.incident_audit to authenticated;
