-- =============================================================================
-- VEC-359 (Step 10) — Seed do agente Mnemos por company
-- =============================================================================
-- Mnemos é o agente curador da memória corporativa: orquestra a ingestão
-- assíncrona de documentos no RAG (extract → chunk → embed → insert).
--
-- Recebe tasks com operation_type='rag-ingest'. Não usa LLM de chat
-- (apenas embedding API), por isso adapter_type='internal' como Morpheus.
--
-- Pattern segue Morpheus + Oracle (is_system=true, UUID fixo na faixa
-- '00000000-0000-0000-0000-00000000000X'). UUID = ...0003.
--
-- Multi-tenancy: DO loop sobre companies + ON CONFLICT (id) DO NOTHING.
-- Limitação conhecida: PK é (id) — UUID global. Hoje só Vectra Cargo
-- tem agentes; quando 2ª company entrar, vai precisar UUID próprio
-- (Mnemos da company X != Mnemos da Y). Esta migration insere apenas
-- 1 row se PK colidir.
--
-- RLS: as 5 policies existentes em vectraclip.agents cobrem o contrato:
--   - agents_select_own_company        (SELECT da própria company)
--   - agents_insert_own_company_admin_op (INSERT admin/operator)
--   - agents_update_own_company_admin_op (UPDATE admin/operator)
--   - agents_delete_own_company_admin   (DELETE admin)
--   - agents_write_service_role         (ALL para service_role — usada aqui)
-- Sem novas policies necessárias.
-- =============================================================================

DO $$
DECLARE
  rec RECORD;
  v_mnemos_id uuid := '00000000-0000-0000-0000-000000000003';
BEGIN
  FOR rec IN SELECT company_id FROM vectraclip.companies LOOP
    INSERT INTO vectraclip.agents (
      id, company_id, name, role, status, adapter_type,
      is_system, token_budget, requires_approval,
      system_prompt
    ) VALUES (
      v_mnemos_id,
      rec.company_id,
      'Mnemos',
      'Knowledge Base Curator',
      'idle',
      'internal',
      true,
      0,
      false,
      'Sou o Mnemos: agente curador da memória corporativa. Recebo documentos (PDF/TXT/HTML/JSON/XLSX), extraio texto, divido em chunks e gero embeddings vetoriais para RAG. Não converso — só ingiro.'
    ) ON CONFLICT (id) DO NOTHING;
  END LOOP;
END $$;

-- Verificação: falha só se há companies mas Mnemos não foi inserido.
-- Shadow DB do `db pull` reaplica migrations sem seed de companies → skip OK.
DO $$
DECLARE v_count int;
DECLARE v_companies int;
BEGIN
  SELECT count(*) INTO v_companies FROM vectraclip.companies;
  SELECT count(*) INTO v_count FROM vectraclip.agents
  WHERE id = '00000000-0000-0000-0000-000000000003';
  IF v_companies > 0 AND v_count = 0 THEN
    RAISE EXCEPTION 'Mnemos seed falhou: 0 rows em vectraclip.agents com % companies cadastradas', v_companies;
  END IF;
  IF v_count > 0 THEN
    RAISE NOTICE 'Mnemos registrado em % company(ies)', v_count;
  ELSE
    RAISE NOTICE 'Mnemos seed skipped: nenhuma company ainda (shadow/replay OK)';
  END IF;
END $$;

NOTIFY pgrst, 'reload schema';
