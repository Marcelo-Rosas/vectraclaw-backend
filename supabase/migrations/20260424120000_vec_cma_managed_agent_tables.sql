-- VEC: Claude Managed Agents (CMA) — session tracking tables
-- managed_agent_sessions: rastreia cada execução CMA
-- managed_agent_turn_logs: log detalhado de cada turn

set search_path to vectraclip;

-- =====================================================================
-- managed_agent_sessions
-- =====================================================================
create table if not exists managed_agent_sessions (
    session_id   uuid primary key default gen_random_uuid(),
    task_id      uuid not null references tasks(id) on delete cascade,
    agent_id     uuid references agents(id) on delete set null,
    model        text not null default 'claude-haiku-4-5-20251001',
    status       text not null default 'in_progress'
                 check (status in ('in_progress', 'completed', 'failed')),
    executor_type text not null default 'managed_agent',
    created_at   timestamptz not null default now(),
    started_at   timestamptz not null default now(),
    completed_at timestamptz,
    final_output text,
    error_message text,
    tokens_input  integer not null default 0,
    tokens_output integer not null default 0,
    metadata     jsonb not null default '{}'::jsonb
);

create index if not exists managed_agent_sessions_task_id_idx
    on managed_agent_sessions (task_id);

create index if not exists managed_agent_sessions_status_idx
    on managed_agent_sessions (status);

-- =====================================================================
-- managed_agent_turn_logs
-- =====================================================================
create table if not exists managed_agent_turn_logs (
    id           bigserial primary key,
    session_id   uuid not null references managed_agent_sessions(session_id) on delete cascade,
    turn_number  integer not null,
    input_text   text not null default '',
    tool_used    text,
    tool_input   jsonb,
    output_text  text not null default '',
    stop_reason  text not null default 'end_turn',
    created_at   timestamptz not null default now()
);

create index if not exists managed_agent_turn_logs_session_idx
    on managed_agent_turn_logs (session_id, turn_number);

-- =====================================================================
-- Adiciona colunas CMA à tabela tasks (se não existirem)
-- =====================================================================
do $$
begin
    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'vectraclip'
          and table_name   = 'tasks'
          and column_name  = 'executor_type'
    ) then
        alter table tasks add column executor_type text default 'auto'
            check (executor_type in ('harness', 'managed_agent', 'auto'));
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'vectraclip'
          and table_name   = 'tasks'
          and column_name  = 'managed_agent_session_id'
    ) then
        alter table tasks add column managed_agent_session_id uuid
            references managed_agent_sessions(session_id) on delete set null;
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'vectraclip'
          and table_name   = 'tasks'
          and column_name  = 'executor_selected_at'
    ) then
        alter table tasks add column executor_selected_at timestamptz;
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'vectraclip'
          and table_name   = 'tasks'
          and column_name  = 'executor_rationale'
    ) then
        alter table tasks add column executor_rationale text;
    end if;
end;
$$;

-- =====================================================================
-- RLS: permite service_role ler/escrever; anon sem acesso
-- =====================================================================
alter table managed_agent_sessions enable row level security;
alter table managed_agent_turn_logs enable row level security;

create policy "service_role full access on managed_agent_sessions"
    on managed_agent_sessions for all
    to service_role
    using (true)
    with check (true);

create policy "service_role full access on managed_agent_turn_logs"
    on managed_agent_turn_logs for all
    to service_role
    using (true)
    with check (true);
