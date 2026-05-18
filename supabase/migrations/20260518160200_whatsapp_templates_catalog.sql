-- W11 PR1 (M3/3) — whatsapp_templates (espelho Meta Graph API) + sync_log + last_inbound_at
--
-- Auditor:
--   P0.2: service de sync REUTILIZA _META_GRAPH_BASE de connector_bus, não duplica URL.
--   P2.1: connector_sessions hoje só tem last_message_at (inclui outbound).
--         ADD last_inbound_at pra janela 24h check correto (só msgs do USER abrem janela).
--         Backfill = last_message_at é proxy razoável (na pior hipótese, janela "expira" antes — fail safe).
--
-- whatsapp_templates é espelho local do GET /<WABA>/message_templates.
-- Refresh via POST /api/connectors/whatsapp/templates/sync (admin).
-- Catalog opções pro DynamicFieldRenderer (options_json.source='whatsapp_templates').

CREATE TABLE IF NOT EXISTS vectraclip.whatsapp_templates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES vectraclip.companies(id) ON DELETE CASCADE,
  waba_id text NOT NULL,
  meta_template_id text NOT NULL,         -- ID na Meta (numérico string)
  name text NOT NULL,                     -- nome do template (slug)
  language text NOT NULL,                 -- pt_BR | en | en_US | und
  category text NOT NULL,                 -- MARKETING | UTILITY | AUTHENTICATION
  status text NOT NULL,                   -- APPROVED | PENDING | REJECTED | PAUSED | DISABLED | IN_APPEAL | LIMIT_EXCEEDED (enum Meta)
  components jsonb,                       -- payload Meta inteiro (body/header/footer params)
  quality_score jsonb,                    -- {score, date} se Meta retornar
  rejected_reason text,                   -- se status=REJECTED
  is_active boolean NOT NULL DEFAULT true, -- soft-disable local (não Meta)
  last_synced_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_whatsapp_template_unique UNIQUE (waba_id, name, language)
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_templates_company
  ON vectraclip.whatsapp_templates (company_id);
CREATE INDEX IF NOT EXISTS idx_whatsapp_templates_active_approved
  ON vectraclip.whatsapp_templates (company_id, status, is_active)
  WHERE status = 'APPROVED' AND is_active = true;

COMMENT ON TABLE vectraclip.whatsapp_templates IS
  'Espelho local dos templates WABA aprovados pela Meta. Source: Graph API GET /<WABA_ID>/message_templates. Refresh via /api/connectors/whatsapp/templates/sync.';
COMMENT ON COLUMN vectraclip.whatsapp_templates.status IS
  'Enum Meta (não slug local): APPROVED/PENDING/REJECTED/PAUSED/DISABLED/IN_APPEAL/LIMIT_EXCEEDED.';

-- RLS — leitura: usuários da company. Escrita: só service_role (sync via backend).
ALTER TABLE vectraclip.whatsapp_templates ENABLE ROW LEVEL SECURITY;

CREATE POLICY whatsapp_templates_read_own_company
  ON vectraclip.whatsapp_templates FOR SELECT
  TO authenticated
  USING (
    company_id IN (
      SELECT company_id FROM vectraclip.app_users WHERE id = auth.uid()
    )
  );

-- Audit log de cada sync (sucesso/falha, contagem, snapshot raw)
CREATE TABLE IF NOT EXISTS vectraclip.whatsapp_template_sync_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id uuid NOT NULL REFERENCES vectraclip.companies(id) ON DELETE CASCADE,
  adapter_id uuid REFERENCES vectraclip.adapter_catalog(id) ON DELETE SET NULL,
  triggered_by uuid REFERENCES vectraclip.app_users(id) ON DELETE SET NULL,
  status text NOT NULL CHECK (status IN ('success','error','partial')),
  templates_fetched int NOT NULL DEFAULT 0,
  templates_upserted int NOT NULL DEFAULT 0,
  error_message text,
  meta_response_snapshot jsonb,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_template_sync_log_company_recent
  ON vectraclip.whatsapp_template_sync_log (company_id, started_at DESC);

ALTER TABLE vectraclip.whatsapp_template_sync_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY template_sync_log_read_own_company
  ON vectraclip.whatsapp_template_sync_log FOR SELECT
  TO authenticated
  USING (
    company_id IN (
      SELECT company_id FROM vectraclip.app_users WHERE id = auth.uid()
    )
  );

-- last_inbound_at em connector_sessions — janela 24h precisa só msgs USER
ALTER TABLE vectraclip.connector_sessions
  ADD COLUMN IF NOT EXISTS last_inbound_at timestamptz;

-- Backfill: pra sessões existentes, last_message_at é proxy (fail-safe — janela
-- pode "expirar" um pouco antes se houve outbound recente; preferível a abrir
-- janela errada e mandar free text que a Meta vai rejeitar).
UPDATE vectraclip.connector_sessions
   SET last_inbound_at = last_message_at
 WHERE last_inbound_at IS NULL
   AND last_message_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_connector_sessions_last_inbound
  ON vectraclip.connector_sessions (last_inbound_at DESC)
  WHERE last_inbound_at IS NOT NULL;

COMMENT ON COLUMN vectraclip.connector_sessions.last_inbound_at IS
  'Última msg recebida do user externo (não inclui outbound do agente). Usado pra check de janela 24h da Meta WABA.';

DO $$
DECLARE
  sessions_total int;
  sessions_backfilled int;
BEGIN
  SELECT count(*) INTO sessions_total FROM vectraclip.connector_sessions;
  SELECT count(*) INTO sessions_backfilled FROM vectraclip.connector_sessions WHERE last_inbound_at IS NOT NULL;
  RAISE NOTICE '[W11 M3/3] connector_sessions total=%, last_inbound_at backfilled=%', sessions_total, sessions_backfilled;
END $$;
