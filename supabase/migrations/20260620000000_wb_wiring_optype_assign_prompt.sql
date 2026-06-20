-- workflow-builder wiring (caminho B, 2026-06-20)
-- Liga a specialty 'workflow-builder' (catálogo vec_331) ao motor de execução:
--   1. operation_type 'workflow-builder' → agente Daedalus (mesmo padrão de bpmn-generate)
--   2. atribui a specialty ao Daedalus (agent_specialty_configs) com defaults do config_schema
--   3. estende o system_prompt_template pra emitir operationType/specialtySlug por step
--      (sem isso os steps saem sem roteamento executável → task.operation_type='other')
-- Idempotente. Execução real via src/agents/specialty_generic.py + workflow_builder.py.

-- 1. operation_type
INSERT INTO vectraclip.operation_types_catalog
  (id, name, description, category, icon, color, display_order,
   primary_agent_id, default_specialty_slug, is_active, routing_score,
   handler_is_async, handler_pass_supabase)
VALUES
  ('workflow-builder', 'Construção de Workflow',
   'Daedalus gera workflow_steps executáveis a partir do SIPOC 5W2H (motor genérico de specialty).',
   'automation', 'workflow', 'text-orange-600', 210,
   'd4ed4145-0000-4000-8000-000000000005', 'workflow-builder', true, 62, false, true)
ON CONFLICT (id) DO UPDATE SET
   primary_agent_id = EXCLUDED.primary_agent_id,
   default_specialty_slug = EXCLUDED.default_specialty_slug,
   is_active = true;

-- 2. atribuição ao Daedalus (company Vectra Cargo MVP)
INSERT INTO vectraclip.agent_specialty_configs (company_id, agent_id, specialty_id, values)
VALUES (
  '01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2',
  'd4ed4145-0000-4000-8000-000000000005',
  'workflow-builder',
  '{"max_steps":20,"default_sla_horas":24,"default_logic_pattern":"SIMPLE","responsavel_default":"agente","auto_validate_5w2h":true,"gemini_model":"gemini-2.0-flash"}'::jsonb
)
ON CONFLICT (agent_id, specialty_id) DO NOTHING;

-- 3. extensão do prompt: roteamento executável (operationType/specialtySlug)
UPDATE vectraclip.agent_specialties
SET system_prompt_template = system_prompt_template || E'\n\n## Roteamento executável (extensão 2026-06-20)\nAlém dos campos acima, inclua em CADA step:\n  "operationType": "<id exato de availableOperationTypes, ou null>",\n  "specialtySlug": "<specialtySlug correspondente, ou null>"\nEscolha de availableOperationTypes (fornecido no input) o op_type que melhor EXECUTA a atividade. Se nenhum couber, use null (marcado needs-handler). NUNCA invente operationType fora da lista.'
WHERE slug = 'workflow-builder'
  AND system_prompt_template NOT LIKE '%Roteamento executável%';
