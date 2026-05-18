-- W15.1 (1/2) — ADD slug 'realtime' em workflow_trigger_types
--
-- Refator Step (Marcelo 2026-05-18): trigger sai do AGENTE pro STEP.
-- workflow_trigger_types hoje cobre 4 slugs (manual/cron/webhook/event)
-- pensados pro nível workflow inteiro. Adicionar 'realtime' pra cobrir
-- o caminho mais comum no nível STEP: "executa imediato após anterior".
--
-- 'realtime' é o DEFAULT da nova coluna workflow_steps.trigger_type
-- (próxima migration). PRECISA estar inserido antes pra FK aceitar.
--
-- Auditor pré-impl 2026-05-18: APROVADO COM AJUSTES.

INSERT INTO vectraclip.workflow_trigger_types
  (slug, name, description, display_order, is_active)
VALUES
  ('realtime', 'Tempo Real',
   'Executa imediato após o step anterior (DAG advance). Padrão de fluxo síncrono — não requer config adicional.',
   5, true)
ON CONFLICT (slug) DO NOTHING;

DO $$
DECLARE
  total int;
BEGIN
  SELECT count(*) INTO total FROM vectraclip.workflow_trigger_types WHERE is_active;
  RAISE NOTICE '[W15.1 M1/2] workflow_trigger_types active rows: %', total;
END $$;
