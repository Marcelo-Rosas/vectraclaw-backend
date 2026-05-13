-- PR-EA — Catálogo canônico de execution modes + FK em agent_execution_configs
--
-- Hoje `agent_execution_configs.execution_mode` é text com CHECK
-- ('REALTIME','CRON','TRIGGER') hardcoded e sem schema declarado dos campos
-- filhos. UI hardcoda labels e fica sem como renderizar form condicional.
--
-- Coerência com PR-DA (agent_domains): cria tabela canon com config_schema
-- por modo, no mesmo padrão de field descriptors usado em agent_specialties.
--
-- Esta migration é ADDITIVA — mantém colunas legadas function_url,
-- auth_secret_ref, auth_header_name. O cleanup delas (move pro
-- trigger_config jsonb) vira PR-EF futuro, após auditoria completa dos 5+
-- consumers em src/api.py.

set search_path to vectraclip, public;

-- ════════════════════════════════════════════════════════════════════════════
-- 1. Tabela agent_execution_modes (catálogo canon)
-- ════════════════════════════════════════════════════════════════════════════
create table if not exists vectraclip.agent_execution_modes (
  id            text        primary key,
  name          text        not null,
  description   text,
  icon          text,
  color         text,
  display_order int         not null default 100,
  config_schema jsonb       not null default '[]'::jsonb,
  is_active     boolean     not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

alter table vectraclip.agent_execution_modes owner to postgres;

comment on table vectraclip.agent_execution_modes is
  'Catálogo canônico de modos de execução de agentes (REALTIME/CRON/TRIGGER) com config_schema declarado por modo. Substitui CHECK hardcoded + UI sem schema.';

comment on column vectraclip.agent_execution_modes.config_schema is
  'Field descriptors dos campos filhos do modo (lista de {key, label, type, required, default, description}). Mesmo formato de agent_specialties.config_schema.';

-- ════════════════════════════════════════════════════════════════════════════
-- 2. Seed dos 3 modos canônicos
-- ════════════════════════════════════════════════════════════════════════════
insert into vectraclip.agent_execution_modes (id, name, description, icon, color, display_order, config_schema) values
  ('REALTIME', 'Tempo Real',
   'Daemon faz polling contínuo na fila de tasks. Latência mínima, custo de polling constante.',
   'zap', 'text-emerald-600', 10,
   '[
     {
       "key": "polling_interval_seconds",
       "label": "Intervalo de polling (segundos)",
       "type": "number",
       "required": false,
       "default": 5,
       "description": "Frequência com que o daemon consulta tasks queued na fila."
     },
     {
       "key": "idle_heartbeat_seconds",
       "label": "Heartbeat idle (segundos)",
       "type": "number",
       "required": false,
       "default": 30,
       "description": "Intervalo do heartbeat de presença (Live no dashboard) quando sem tasks."
     }
   ]'::jsonb),
  ('CRON', 'Agendado',
   'Execução em horário fixo via cron expression. Útil para rotinas diárias/semanais.',
   'clock', 'text-blue-600', 20,
   '[
     {
       "key": "cron_expression",
       "label": "Expressão cron",
       "type": "text",
       "required": true,
       "description": "Padrão cron (ex.: 0 8 * * * = todo dia às 08:00)."
     },
     {
       "key": "timezone",
       "label": "Fuso horário",
       "type": "text",
       "required": false,
       "default": "America/Sao_Paulo",
       "description": "Timezone IANA aplicado ao agendamento."
     }
   ]'::jsonb),
  ('TRIGGER', 'Gatilho HTTP',
   'Execução via webhook HTTP externo. Dispatchada por sistemas externos via POST.',
   'webhook', 'text-purple-600', 30,
   '[
     {
       "key": "function_url",
       "label": "Endpoint HTTP",
       "type": "text",
       "required": true,
       "description": "URL HTTPS pública que recebe o payload da task. Validação: https + host na allowlist."
     },
     {
       "key": "auth_header_name",
       "label": "Header de autenticação",
       "type": "text",
       "required": false,
       "default": "Authorization",
       "description": "Nome do header HTTP onde o segredo é injetado."
     },
     {
       "key": "auth_secret_ref",
       "label": "Referência do segredo",
       "type": "secret",
       "required": false,
       "description": "Nome da chave em Supabase Secrets / env (não o segredo bruto)."
     },
     {
       "key": "payload_template",
       "label": "Template do payload",
       "type": "text",
       "required": false,
       "default": "{}",
       "description": "JSON template enviado ao webhook. Suporta placeholders {{ task.input_json.* }}."
     },
     {
       "key": "timeout_seconds",
       "label": "Timeout (segundos)",
       "type": "number",
       "required": false,
       "default": 30,
       "description": "Tempo máximo de espera da resposta do webhook."
     }
   ]'::jsonb)
on conflict (id) do update
  set name          = excluded.name,
      description   = excluded.description,
      icon          = excluded.icon,
      color         = excluded.color,
      display_order = excluded.display_order,
      config_schema = excluded.config_schema,
      is_active     = true,
      updated_at    = now();

-- ════════════════════════════════════════════════════════════════════════════
-- 3. FK agent_execution_configs.execution_mode → agent_execution_modes(id)
--    Drop CHECK constraint legado primeiro (CHECK era hardcoded com os 3
--    valores; FK passa a garantir referencial via tabela canon).
-- ════════════════════════════════════════════════════════════════════════════
alter table vectraclip.agent_execution_configs
  drop constraint if exists agent_execution_configs_execution_mode_check;

alter table vectraclip.agent_execution_configs
  drop constraint if exists fk_agent_execution_configs_mode;

alter table vectraclip.agent_execution_configs
  add constraint fk_agent_execution_configs_mode
  foreign key (execution_mode) references vectraclip.agent_execution_modes (id)
  on update cascade
  on delete restrict;

-- ════════════════════════════════════════════════════════════════════════════
-- 4. RLS — segue padrão dos demais catálogos
-- ════════════════════════════════════════════════════════════════════════════
alter table vectraclip.agent_execution_modes enable row level security;

drop policy if exists "agent_execution_modes_read_authenticated"
  on vectraclip.agent_execution_modes;
create policy "agent_execution_modes_read_authenticated"
  on vectraclip.agent_execution_modes
  for select
  to authenticated
  using (true);

drop policy if exists "agent_execution_modes_write_service_role"
  on vectraclip.agent_execution_modes;
create policy "agent_execution_modes_write_service_role"
  on vectraclip.agent_execution_modes
  for all
  to service_role
  using (true)
  with check (true);

-- ════════════════════════════════════════════════════════════════════════════
-- 5. Verificação
-- ════════════════════════════════════════════════════════════════════════════
do $$
declare
  v_modes int;
  v_invalid_refs int;
begin
  select count(*) into v_modes from vectraclip.agent_execution_modes where is_active;

  select count(*) into v_invalid_refs
    from vectraclip.agent_execution_configs e
    where not exists (
      select 1 from vectraclip.agent_execution_modes m where m.id = e.execution_mode
    );

  if v_modes = 3 and v_invalid_refs = 0 then
    raise notice 'PR-EA: migration OK (modes=3, invalid_refs=0)';
  else
    raise warning 'PR-EA: verificação falhou — modes=%, invalid_refs=%', v_modes, v_invalid_refs;
  end if;
end $$;
