-- Folhas executáveis da prospecção (PR3, 2026-06-20) — effect-only (sem LLM).
-- enrich-phone (GymSite): reconcilia mobile via contacts NAVI → prospect.
-- outbound-wa  (Plutus/CRM): enfileira template no send_queue do NAVI (gated por
--   confirm_send). Execução real em src/agents/prospect_leaves.py.
-- Idempotente.

-- 1. specialties no catálogo (system_prompt_template vazio: effect-only não usa LLM)
INSERT INTO vectraclip.agent_specialties (id, name, slug, domain, description, system_prompt_template, is_active, config_schema, status, source)
VALUES
  ('enrich-phone', 'Enriquecimento de Telefone', 'enrich-phone', 'automation',
   'Reconcilia o mobile do decisor a partir dos contacts do NAVI (pipeline GymSite/Instagram) e grava no prospect. Effect-only.',
   '', true, '[]'::jsonb, 'active', 'seed'),
  ('outbound-wa', 'Disparo WhatsApp', 'outbound-wa', 'automation',
   'Enfileira template aprovado no send_queue do NAVI (número GREEN). Outward-facing: gated por confirm_send (dry-run default). Effect-only.',
   '', true,
   '[{"key":"default_template","type":"text","label":"Template padrão","required":false,"defaultValue":"vectra_prospeccao_academia"},{"key":"default_lang","type":"text","label":"Idioma","required":false,"defaultValue":"pt_BR"}]'::jsonb,
   'active', 'seed')
ON CONFLICT (id) DO UPDATE SET is_active=true, description=EXCLUDED.description, config_schema=EXCLUDED.config_schema;

-- 2. operation_types → agentes (GymSite=enrich, Plutus=outbound)
INSERT INTO vectraclip.operation_types_catalog
  (id, name, description, category, icon, color, display_order,
   primary_agent_id, default_specialty_slug, is_active, routing_score, handler_is_async, handler_pass_supabase)
VALUES
  ('enrich-phone', 'Enriquecimento de Telefone',
   'Reconcilia mobile do decisor via NAVI contacts (effect-only).', 'automation', 'phone',
   'text-emerald-600', 220, '917e51b3-9413-4000-8000-000000000006', 'enrich-phone', true, 55, false, true),
  ('outbound-wa', 'Disparo WhatsApp',
   'Enfileira template no send_queue do NAVI (gated por confirm_send).', 'automation', 'message-circle',
   'text-emerald-600', 221, '80fd6d0e-53ab-4638-b6e9-05cbbd121092', 'outbound-wa', true, 55, false, true)
ON CONFLICT (id) DO UPDATE SET
   primary_agent_id=EXCLUDED.primary_agent_id, default_specialty_slug=EXCLUDED.default_specialty_slug, is_active=true;

-- 3. atribui specialties aos agentes (company Vectra Cargo)
INSERT INTO vectraclip.agent_specialty_configs (company_id, agent_id, specialty_id, values)
VALUES
  ('01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2', '917e51b3-9413-4000-8000-000000000006', 'enrich-phone', '{}'::jsonb),
  ('01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2', '80fd6d0e-53ab-4638-b6e9-05cbbd121092', 'outbound-wa',
   '{"default_template":"vectra_prospeccao_academia","default_lang":"pt_BR"}'::jsonb)
ON CONFLICT (agent_id, specialty_id) DO NOTHING;
