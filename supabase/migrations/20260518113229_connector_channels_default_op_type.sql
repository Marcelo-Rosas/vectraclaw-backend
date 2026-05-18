-- ESPELHEI ANTES (Regra Ouro #1):
--   (1) SELECT FROM information_schema.columns WHERE table_schema='vectraclip'
--       AND table_name='connector_channels'
--       → 7 cols: slug, name, description, display_order, is_active, created_at, updated_at
--       → default_inbound_operation_type NÃO EXISTE — OK criar.
--   (2) operation_types_catalog.id é text (PK text slug), nullable=NO.
--       FK como REFERENCES vectraclip.operation_types_catalog(id) é válida.
--   (3) connector_channels já tem rows: whatsapp/email/telegram/api/other (W3).
--   (4) operation_types_catalog tem rows freight-quotation (primary=MERCATOR
--       c7de1b0f-) e oracle-research (primary=ORACLE 00000000-...0002).
--
-- PADRÃO ADOTADO (Regra Ouro #2):
--   Catalog-driven puro. Nenhuma const Python + nenhum dispatch hardcoded.
--   Adiciona campo `default_inbound_operation_type` em connector_channels.
--   FK pra operation_types_catalog garante integridade — sem CHECK constraint
--   redundante. Backend faz lookup em runtime no _dispatch_inbound_task.
--
-- W7 P0-9 — Caminho A do Miro board: Meta → VectraClaw direto. Toda mensagem
-- WhatsApp inbound (canal 'whatsapp') deve criar task freight-quotation pro
-- Mercator (resolvido via operation_types_catalog.primary_agent_id). Per Miro
-- backlog "P0-9 Webhook inbound: ramo cotação (não oracle-research)".
--
-- F2 deploy anterior (b9b483a) usava 'oracle-research' por default hardcoded.
-- Esta migration + W7 P0-9 backend remove o hardcode E corrige o roteamento.

ALTER TABLE vectraclip.connector_channels
  ADD COLUMN IF NOT EXISTS default_inbound_operation_type text
    REFERENCES vectraclip.operation_types_catalog(id) ON DELETE SET NULL;

COMMENT ON COLUMN vectraclip.connector_channels.default_inbound_operation_type IS
  'W7 P0-9 — operation_type default criado por _dispatch_inbound_task quando '
  'uma mensagem inbound deste canal é recebida sem intent classifier (NAVI '
  'edge fica pra fase posterior). NULL = canal não dispatcha task default '
  '(log + skip). FK garante slug válido em operation_types_catalog.';

-- Decisão de negócio (Marcelo via Miro board, Caminho A):
--   whatsapp → freight-quotation (Mercator é primary)
UPDATE vectraclip.connector_channels
   SET default_inbound_operation_type = 'freight-quotation',
       updated_at = now()
 WHERE slug = 'whatsapp';

-- Outros canais (email, telegram, api, other) ficam NULL por ora — sem
-- decisão de negócio cravada. Quando houver, basta UPDATE (não precisa nova
-- migration nem deploy).

-- Verificação shadow-replay-safe (hotfix 2026-05-18: assert condicional ao seed)
--
-- Versão anterior falhava em shadow DB do `supabase db pull` quando
-- connector_channels não tinha row 'whatsapp' (seed de W3 não está em shadow
-- vazio). Fix: só falha SE a row 'whatsapp' existia ANTES do UPDATE.
DO $$
DECLARE
  v_whatsapp_exists int;
  v_whatsapp_op text;
  v_total_canais int;
  v_canais_com_default int;
BEGIN
  SELECT count(*) INTO v_whatsapp_exists FROM vectraclip.connector_channels
    WHERE slug='whatsapp';
  SELECT default_inbound_operation_type INTO v_whatsapp_op
    FROM vectraclip.connector_channels WHERE slug='whatsapp';
  SELECT count(*) INTO v_total_canais FROM vectraclip.connector_channels;
  SELECT count(*) INTO v_canais_com_default FROM vectraclip.connector_channels
    WHERE default_inbound_operation_type IS NOT NULL;
  RAISE NOTICE 'W7 P0-9: whatsapp existia=% | default_op=% | canais total=% | com default=%',
    v_whatsapp_exists, v_whatsapp_op, v_total_canais, v_canais_com_default;
  IF v_whatsapp_exists > 0 AND (v_whatsapp_op IS NULL OR v_whatsapp_op != 'freight-quotation') THEN
    RAISE EXCEPTION 'W7 P0-9: setup whatsapp falhou (esperado freight-quotation, got %)', v_whatsapp_op;
  END IF;
END $$;

NOTIFY pgrst, 'reload schema';
