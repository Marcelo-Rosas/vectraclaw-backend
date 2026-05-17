-- VEC-388 PR1 — Seed do agente Athena (9º daemon do VectraClaw)
-- ATHENA_AGENT_ID: ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d
--
-- Reconciliação retroativa (VEC-394): este DDL foi aplicado em prod em
-- 2026-05-10 20:22:20 UTC via mcp apply_migration durante a sessão do
-- VEC-388 PR1, antes deste arquivo existir. O timestamp do nome reflete
-- o momento da aplicação real (preservando ordem do histórico).
DO $$
DECLARE
  v_athena_id uuid := 'ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d';
  v_gemini_adapter_id uuid;
  v_athena_system_prompt text;
  rec RECORD;
BEGIN
  v_athena_system_prompt :=
'Você é Athena, 9º daemon do VectraClaw e PMOia (PMO virtual) da Vectra Cargo. Sua metodologia é o PMBOK descrito por Kim Heldman ("Gerência de Projetos: Guia para o Exame Oficial do PMI"). Opera em 2 mandatos: (1) Pipeline PMI VEC-388: classifica goals como projeto vs operação, gera Charter, Stakeholder Map, Risk Register e EVM. (2) Coverage Manager VEC-389: audita quadro de agentes e propõe melhorias (nunca aplica sozinha). Outputs seguem schema PMBOK Inputs/Tools/Outputs com vocabulário fixo de tools, escala oficial PMBOK 5ª no Risk Register (prob 0.1-0.9 × impacto 0.05-0.80), 5 elementos PMBOK na Charter, e ancoragem nas 5 citações canônicas de Heldman. Detalhes completos em .claude/skills/athena/athena_system_prompt.md.';

  FOR rec IN SELECT company_id, name FROM vectraclip.companies LOOP

    -- 1. INSERT em vectraclip.agents
    INSERT INTO vectraclip.agents (
      id, company_id, name, role, status, token_budget, current_burn_rate,
      adapter_type, system_prompt, requires_approval, is_system
    ) VALUES (
      v_athena_id, rec.company_id, 'Athena',
      'Project Management Coach (Heldman/PMBOK)',
      'idle', 100000, 0, 'gemini',
      v_athena_system_prompt, false, true
    )
    ON CONFLICT (id) DO NOTHING;

    -- 2. INSERT em vectraclip.agent_adapter_configs
    SELECT id INTO v_gemini_adapter_id
    FROM vectraclip.adapter_catalog
    WHERE company_id = rec.company_id
      AND slug = 'gemini'
      AND is_active = true
    LIMIT 1;

    IF v_gemini_adapter_id IS NULL THEN
      RAISE WARNING
        'Adapter gemini não encontrado para company % (%). Athena não terá adapter config — dashboard pode mostrar "sem adapter".',
        rec.name, rec.company_id;
    ELSE
      INSERT INTO vectraclip.agent_adapter_configs (
        company_id, agent_id, adapter_id, field_values_json, is_active
      ) VALUES (
        rec.company_id, v_athena_id, v_gemini_adapter_id,
        '{"model": "gemini-2.5-pro", "rag_k": 4, "max_chars_per_chunk": 1500}'::jsonb,
        true
      )
      ON CONFLICT DO NOTHING;
    END IF;

    -- 3. INSERT em vectraclip.agent_specialty_configs
    INSERT INTO vectraclip.agent_specialty_configs (
      company_id, agent_id, specialty_id, values
    ) VALUES (
      rec.company_id, v_athena_id, 'oracle-rag',
      jsonb_build_object(
        'domain', 'project_management',
        'operation_types', jsonb_build_array(
          'athena-classify', 'athena-charter', 'athena-stakeholder-map',
          'athena-risk-register', 'athena-evm', 'athena-audit',
          'athena-recommend', 'athena-rag-ingest'
        ),
        'rag_corpus', 'athena',
        'methodology', 'PMBOK 5e / Kim Heldman'
      )
    )
    ON CONFLICT DO NOTHING;

  END LOOP;

  -- Shadow DB do `db pull` não tem companies → skip verificação (remoto com tenants OK).
  IF (SELECT count(*) FROM vectraclip.companies) = 0 THEN
    RAISE NOTICE 'Seed Athena skipped: nenhuma company ainda (shadow/replay OK)';
  ELSE
    IF NOT EXISTS (SELECT 1 FROM vectraclip.agents WHERE id = v_athena_id) THEN
      RAISE EXCEPTION 'Seed Athena falhou: nenhuma linha em vectraclip.agents';
    END IF;

    IF (SELECT count(*) FROM vectraclip.agent_specialty_configs WHERE agent_id = v_athena_id) = 0 THEN
      RAISE EXCEPTION 'Seed Athena falhou: nenhuma linha em vectraclip.agent_specialty_configs';
    END IF;

    RAISE NOTICE 'Seed Athena OK: % company(ies) processed',
      (SELECT count(DISTINCT company_id) FROM vectraclip.agents WHERE id = v_athena_id);
  END IF;

END $$;

NOTIFY pgrst, 'reload schema';
