-- =============================================================================
-- VEC-359 — Normaliza configuração do agente Mnemos para paridade com outros 8
-- =============================================================================
-- Após PR #20 (seed Mnemos), o card no dashboard ficava incompleto:
--   • token_budget=0 → Budget aparece zerado
--   • sem agent_adapter_configs → ausência de Pausar/Editar/Kill
--   • sem agent_specialty_configs → ausência da tag de domínio (ex: Knowledge)
--
-- Esta migration faz:
--   1. UPDATE agents.token_budget = 50000 (parity com Hodos/HermesReporter)
--   2. INSERT agent_adapter_configs para Mnemos usando adapter_id 'claude_code'
--      (universal, mesmo dos outros). field_values_json vazio porque Mnemos
--      não usa LLM de chat (apenas OpenAI embedding API).
--   3. INSERT agent_specialty_configs vinculando Mnemos à specialty
--      existente 'oracle-rag' (domain=Knowledge). Não cria specialty nova
--      para evitar proliferação; o domain "Knowledge" já cabe perfeitamente.
--
-- Idempotente: ON CONFLICT DO NOTHING em ambos INSERTs.
-- =============================================================================

DO $$
DECLARE
  v_mnemos_id  uuid := '00000000-0000-0000-0000-000000000003';
  v_company_id uuid;
  v_adapter_id uuid;
BEGIN
  -- 1. Token budget parity
  UPDATE vectraclip.agents
     SET token_budget = 50000,
         updated_at = now()
   WHERE id = v_mnemos_id
     AND token_budget = 0;

  -- 2. Adapter config + specialty — loop por company que já tem Mnemos seedado
  FOR v_company_id IN
    SELECT company_id FROM vectraclip.agents WHERE id = v_mnemos_id
  LOOP
    -- Resolve adapter_id 'claude_code' da company
    SELECT id INTO v_adapter_id
    FROM vectraclip.adapter_catalog
    WHERE company_id = v_company_id AND slug = 'claude_code'
    LIMIT 1;

    IF v_adapter_id IS NOT NULL THEN
      INSERT INTO vectraclip.agent_adapter_configs (
        company_id, agent_id, adapter_id, field_values_json, is_active
      ) VALUES (
        v_company_id,
        v_mnemos_id,
        v_adapter_id,
        '{}'::jsonb,
        true
      ) ON CONFLICT (agent_id) DO NOTHING;
    ELSE
      RAISE WARNING 'adapter_catalog claude_code não encontrado para company %', v_company_id;
    END IF;

    -- Specialty link → Oracle RAG (domain=Knowledge). Reaproveita ao invés
    -- de criar 'rag-curator' novo. Cabe semanticamente.
    INSERT INTO vectraclip.agent_specialty_configs (
      company_id, agent_id, specialty_id, values
    ) VALUES (
      v_company_id,
      v_mnemos_id,
      'oracle-rag',
      '{"role": "curator"}'::jsonb
    ) ON CONFLICT (agent_id, specialty_id) DO NOTHING;
  END LOOP;

  -- Verificação
  IF NOT EXISTS (
    SELECT 1 FROM vectraclip.agent_adapter_configs
    WHERE agent_id = v_mnemos_id AND is_active = true
  ) THEN
    RAISE WARNING 'Mnemos config parity: agent_adapter_configs não foi inserido';
  END IF;

  RAISE NOTICE 'Mnemos config parity aplicado';
END $$;

NOTIFY pgrst, 'reload schema';
