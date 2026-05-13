-- Task #49 — Tabela canônica vectraclip.workflow_logic_patterns
--
-- FlowLogic.tsx (VectraClip frontend, src/pages/FlowLogic.tsx) define 7 patterns
-- hardcoded em MOCK_PATTERNS. Coluna workflow_steps.logic_pattern é text livre
-- sem FK — não há fonte canônica que ligue catálogo educativo (frontend) ao
-- engine que vai consumir os patterns (backend).
--
-- Esta migration:
--   1. Cria tabela canônica workflow_logic_patterns (taxonomy + skeleton n8n +
--      heuristics + engine_handler).
--   2. Seed dos 8 patterns: os 7 do FlowLogic.tsx + SIMPLE (default linear
--      success/failure usado pelo engine v1 atual e pelos 4 Kronos steps que
--      acabamos de enriquecer no PR #99).
--   3. ALTER workflow_steps.logic_pattern → FK com ON UPDATE CASCADE +
--      ON DELETE RESTRICT.
--
-- O `engine_handler` documenta qual handler Python interpreta cada pattern.
-- Hoje só SIMPLE tem handler real (workflow_engine.advance success/failure).
-- Os demais ficam declarados mas com handler 'pending' — Engine v2 (task #42)
-- vai implementar.
--
-- Idempotente: CREATE IF NOT EXISTS + ON CONFLICT DO UPDATE.

set search_path to vectraclip, public;

-- ════════════════════════════════════════════════════════════════════════════
-- 1. Tabela canônica
-- ════════════════════════════════════════════════════════════════════════════
create table if not exists vectraclip.workflow_logic_patterns (
  id              text        primary key,             -- 'split-if', 'split-switch', ...
  category        text        not null,                -- 'splitting', 'merging', etc.
  taxonomy        text        not null unique,         -- 'SPLIT', 'MERGE', 'SIMPLE', etc.
  name            text        not null,                -- nome human-readable
  description     text,
  heuristics      text[]      not null default '{}',   -- array de regras heurísticas
  icon            text,                                -- lucide-react name (split, gitMerge, repeat...)
  color           text,                                -- tailwind class
  display_order   int         not null default 100,
  json_skeleton   jsonb,                               -- skeleton n8n parseado (referência)
  engine_handler  text        not null default 'pending', -- nome do módulo Python que interpreta
  is_active       boolean     not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

alter table vectraclip.workflow_logic_patterns owner to postgres;

comment on table vectraclip.workflow_logic_patterns is
  'Catálogo canônico de logic_patterns para workflow_steps. Espelha FlowLogic.tsx (VectraClip) + extras (SIMPLE). Endpoint GET /api/workflow-logic-patterns alimenta UI e documenta engine handlers.';

comment on column vectraclip.workflow_logic_patterns.engine_handler is
  'Nome do método Python que interpreta este pattern em runtime (ex: WorkflowEngine.advance_simple, advance_split_if, etc.). Use ''pending'' até Engine v2 implementar.';

-- ════════════════════════════════════════════════════════════════════════════
-- 2. Seed: 8 patterns canônicos
-- ════════════════════════════════════════════════════════════════════════════
insert into vectraclip.workflow_logic_patterns
  (id, category, taxonomy, name, description, heuristics, icon, color,
   display_order, json_skeleton, engine_handler)
values
  -- SIMPLE: default linear success/failure (engine v1 atual)
  ('simple', 'simple', 'SIMPLE',
   'Linear (Sucesso/Falha)',
   'Step linear sem condicionais; engine v1 segue on_success_step_id ou on_failure_step_id baseado no outcome.',
   ARRAY['Use quando não há decisão de roteamento.', 'Default para steps sem lógica especial.'],
   'arrow-right', 'text-slate-500', 10,
   null,  -- SIMPLE não tem skeleton n8n (é o default)
   'WorkflowEngine.advance'),

  -- SPLITTING (2 variantes — taxonomy SPLIT compartilhada mas id distinto)
  ('split-if', 'splitting', 'SPLIT-IF',
   'SPLIT com IF (binário)',
   'Transforma um workflow de ramo único em multi-ramo (true/false).',
   ARRAY['Se a tarefa envolve "se... então... senão" com 2 caminhos.'],
   'split', 'text-amber-600', 20,
   '{"nodes":[{"name":"IF","type":"n8n-nodes-base.if","parameters":{"conditions":{"number":[{"value1":"={{$json[\"score\"]}}","operation":"larger","value2":80}]}}}]}'::jsonb,
   'pending'),

  ('split-switch', 'splitting', 'SPLIT-SWITCH',
   'SPLIT com Switch',
   'Múltiplas rotas baseadas em regras ou expressões. Útil para roteamento complexo.',
   ARRAY['Se há 3+ caminhos por valor/regex/regra.'],
   'split', 'text-amber-600', 30,
   '{"name":"Switch","type":"n8n-nodes-base.switch","parameters":{"dataType":"string","value1":"={{$json[\"tipo\"]}}","rules":{"rules":[{"value2":"pedido","output":0},{"value2":"cancelamento","output":1},{"value2":"reembolso","output":2}]},"fallbackOutput":3}}'::jsonb,
   'pending'),

  -- MERGING
  ('merge-by-key', 'merging', 'MERGE',
   'Merge por Chave',
   'Consolidação de streams diferentes combinando posições ou chaves.',
   ARRAY['Se há ramos paralelos que devem convergir.', 'Se preciso unificar coleções de dados.'],
   'git-merge', 'text-cyan-600', 40,
   '{"name":"Merge","type":"n8n-nodes-base.merge","parameters":{"mode":"combine","combinationMode":"mergeByFields","mergeByFields":{"values":[{"field1":"email","field2":"email"}]}}}'::jsonb,
   'pending'),

  -- LOOPING
  ('loop-batch', 'looping', 'LOOP-BATCH',
   'Processar em Lotes (Rate Limit)',
   'Loop Over Items com Batch Size. Ideal para evitar rate limits em APIs.',
   ARRAY['Se a API tem rate limit ou paginação.'],
   'repeat', 'text-purple-600', 50,
   '{"nodes":[{"name":"Loop Over Items","type":"n8n-nodes-base.splitInBatches","parameters":{"batchSize":10}}]}'::jsonb,
   'pending'),

  -- WAITING
  ('wait-event', 'waiting', 'WAIT-EVENT',
   'Aguardar Webhook',
   'Pausa o workflow até um evento externo acontecer (ex: aprovação humana).',
   ARRAY['Se espera ação humana/externa (aprovação, pagamento).'],
   'clock', 'text-blue-600', 60,
   '{"name":"Wait for Approval","type":"n8n-nodes-base.wait","parameters":{"resume":"webhook","options":{"webhookSuffix":"approval"}}}'::jsonb,
   'pending'),

  -- SUB-WORKFLOWS
  ('subflow', 'subworkflows', 'SUBFLOW',
   'Execute Sub-workflow',
   'Modularidade. Chama um workflow filho passando dados de forma isolada.',
   ARRAY['Se o mesmo bloco se repete em ≥2 workflows.'],
   'layers', 'text-indigo-600', 70,
   '{"name":"Execute Sub-workflow","type":"n8n-nodes-base.executeWorkflow","parameters":{"source":"database","workflowId":"abc123XYZ"}}'::jsonb,
   'pending'),

  -- ERROR HANDLING
  ('error-handler', 'error-handling', 'ERROR-HANDLER',
   'Workflow de Erro',
   'Error Trigger que inicia um fluxo dedicado de notificação/recuperação.',
   ARRAY['Se qualquer passo crítico pode falhar (API externa, parse).'],
   'shield-alert', 'text-red-600', 80,
   '{"name":"Error Trigger","type":"n8n-nodes-base.errorTrigger","parameters":{}}'::jsonb,
   'pending')

on conflict (id) do update
  set category       = excluded.category,
      taxonomy       = excluded.taxonomy,
      name           = excluded.name,
      description    = excluded.description,
      heuristics     = excluded.heuristics,
      icon           = excluded.icon,
      color          = excluded.color,
      display_order  = excluded.display_order,
      json_skeleton  = excluded.json_skeleton,
      engine_handler = excluded.engine_handler,
      is_active      = true,
      updated_at     = now();

-- ════════════════════════════════════════════════════════════════════════════
-- 3. FK workflow_steps.logic_pattern → workflow_logic_patterns.taxonomy
--    (NULL ainda permitido — herda dos 14 steps NULL que existem hoje)
-- ════════════════════════════════════════════════════════════════════════════
alter table vectraclip.workflow_steps
  drop constraint if exists fk_workflow_steps_logic_pattern;

alter table vectraclip.workflow_steps
  add constraint fk_workflow_steps_logic_pattern
  foreign key (logic_pattern) references vectraclip.workflow_logic_patterns (taxonomy)
  on update cascade
  on delete restrict;

-- ════════════════════════════════════════════════════════════════════════════
-- 4. RLS — read autenticado, write service_role
-- ════════════════════════════════════════════════════════════════════════════
alter table vectraclip.workflow_logic_patterns enable row level security;

drop policy if exists "wlp_read_authenticated" on vectraclip.workflow_logic_patterns;
create policy "wlp_read_authenticated"
  on vectraclip.workflow_logic_patterns
  for select to authenticated using (true);

drop policy if exists "wlp_write_service_role" on vectraclip.workflow_logic_patterns;
create policy "wlp_write_service_role"
  on vectraclip.workflow_logic_patterns
  for all to service_role using (true) with check (true);

-- ════════════════════════════════════════════════════════════════════════════
-- 5. Verificação
-- ════════════════════════════════════════════════════════════════════════════
do $$
declare
  v_patterns int;
  v_invalid_refs int;
begin
  select count(*) into v_patterns
    from vectraclip.workflow_logic_patterns where is_active;

  -- Steps com logic_pattern que não bate com a taxonomy
  select count(*) into v_invalid_refs
    from vectraclip.workflow_steps s
    where s.logic_pattern is not null
      and not exists (
        select 1 from vectraclip.workflow_logic_patterns p
        where p.taxonomy = s.logic_pattern
      );

  if v_patterns = 8 and v_invalid_refs = 0 then
    raise notice 'Task #49 OK: 8 patterns ativos, 0 refs inválidos em workflow_steps';
  else
    raise warning 'Task #49: patterns=%, invalid_refs=%', v_patterns, v_invalid_refs;
  end if;
end $$;
