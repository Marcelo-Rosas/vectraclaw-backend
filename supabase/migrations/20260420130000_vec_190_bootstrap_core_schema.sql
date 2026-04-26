-- VEC-190 bootstrap core schema
-- Objetivo: permitir `supabase db reset` em clone limpo sem depender
-- de estado pré-existente criado manualmente.

create schema if not exists vectraclip;
set search_path to vectraclip, public;

create extension if not exists pgcrypto;
create extension if not exists moddatetime;

-- ---------------------------------------------------------------------
-- Core: companies
-- (pré-vec249: PK em `id`; vec249 renomeia para `company_id`)
-- ---------------------------------------------------------------------
create table if not exists vectraclip.companies (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- Core: agents (necessária antes de 20260420135225_agents_write_rls.sql)
-- ---------------------------------------------------------------------
create table if not exists vectraclip.agents (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references vectraclip.companies(id) on delete cascade,
  name text not null,
  role text not null default ''::text,
  reports_to_id uuid references vectraclip.agents(id) on delete set null,
  status text not null check (status in ('working', 'idle', 'paused', 'errored', 'offline')),
  token_budget integer not null default 0 check (token_budget >= 0),
  current_burn_rate numeric not null default 0 check (current_burn_rate >= 0),
  adapter_type text not null check (adapter_type in ('claude_code', 'cursor', 'bot')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists agents_company_id_idx
  on vectraclip.agents (company_id);

-- ---------------------------------------------------------------------
-- Core: goals
-- ---------------------------------------------------------------------
create table if not exists vectraclip.goals (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references vectraclip.companies(id) on delete cascade,
  parent_goal_id uuid references vectraclip.goals(id) on delete set null,
  title text not null,
  metric text not null default ''::text,
  target numeric not null default 100,
  current numeric not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists goals_company_id_idx
  on vectraclip.goals (company_id);

-- ---------------------------------------------------------------------
-- Core: tasks (colunas baseline; migrations seguintes enriquecem)
-- ---------------------------------------------------------------------
create table if not exists vectraclip.tasks (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references vectraclip.companies(id) on delete cascade,
  assigned_to_agent_id uuid references vectraclip.agents(id) on delete set null,
  parent_task_id uuid references vectraclip.tasks(id) on delete set null,
  goal_id uuid references vectraclip.goals(id) on delete set null,
  title text not null,
  description text not null default ''::text,
  status text not null default 'backlog'::text check (status in ('backlog', 'queued', 'in_progress', 'review', 'done')),
  budget_limit integer not null default 0 check (budget_limit >= 0),
  spent numeric not null default 0 check (spent >= 0),
  claimed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists tasks_company_id_idx
  on vectraclip.tasks (company_id);

-- ---------------------------------------------------------------------
-- Core: heartbeats (baseline; 20260420210000 adiciona colunas de custo)
-- ---------------------------------------------------------------------
create table if not exists vectraclip.heartbeats (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references vectraclip.companies(id) on delete cascade,
  agent_id uuid not null references vectraclip.agents(id) on delete cascade,
  task_id uuid references vectraclip.tasks(id) on delete set null,
  status text not null check (status in ('working', 'idle', 'paused', 'errored', 'offline')),
  tokens_used integer not null default 0 check (tokens_used >= 0),
  log_excerpt text not null default ''::text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists heartbeats_company_created_idx
  on vectraclip.heartbeats (company_id, created_at desc);

-- ---------------------------------------------------------------------
-- Core: utilitários usados por API/testes
-- ---------------------------------------------------------------------
create table if not exists vectraclip.app_users (
  id uuid primary key default gen_random_uuid(),
  email text unique not null,
  name text not null,
  role text not null check (role in ('admin', 'operator', 'viewer')),
  company_id uuid not null references vectraclip.companies(id) on delete cascade,
  avatar_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists vectraclip.routines (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references vectraclip.companies(id) on delete cascade,
  name text not null,
  status text not null default 'active'::text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists vectraclip.audit_log (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references vectraclip.companies(id) on delete cascade,
  actor_type text not null default 'system'::text,
  actor_id text not null default 'system'::text,
  action text not null default ''::text,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists vectraclip.approvals (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references vectraclip.companies(id) on delete cascade,
  request_type text not null default ''::text,
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'pending'::text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

