-- Migration: connector_sessions
-- Fundação da camada de conectores externos do VectraClaw.
-- Persiste sessões de conversação de canais externos (Navi/WhatsApp, Hermes/email,
-- futuros canais) com estado, histórico e FK para tasks geradas.
--
-- Schema: vectraclip (NUNCA public)
-- Idempotente: CREATE TABLE IF NOT EXISTS + ON CONFLICT DO NOTHING

-- =============================================================================
-- 1. Tabela principal: vectraclip.connector_sessions
-- =============================================================================

CREATE TABLE IF NOT EXISTS "vectraclip"."connector_sessions" (
      "id"              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
      -- W3 fix: companies_pkey = company_id (NÃO id). FK corrigida.
      "company_id"      UUID        NOT NULL REFERENCES "vectraclip"."companies"("company_id") ON DELETE CASCADE,

    -- Canal de origem. W3: CHECK hardcoded removido — FK pra connector_channels catalog
    -- (Regra Ouro #2 NO HARDCODE). Catalog criado em 20260517225900.
    "channel"         TEXT        NOT NULL REFERENCES "vectraclip"."connector_channels"("slug") ON DELETE RESTRICT,
      "connector_id"    TEXT        NOT NULL,  -- ex: '5547933851351' (Navi), 'inbox@vectracargo.com.br' (Hermes)

    -- Identificação do contato externo
    "external_id"     TEXT        NOT NULL,  -- número WhatsApp, email remetente, etc.
    "external_name"   TEXT,                  -- nome resolvido do contato (opcional)
    "external_meta"   JSONB       DEFAULT '{}',  -- dados extras do canal (profile_pic, etc.)

    -- Estado da sessão. W3: CHECK hardcoded removido — FK pra connector_session_statuses.
    "status"          TEXT        NOT NULL DEFAULT 'open'
                                    REFERENCES "vectraclip"."connector_session_statuses"("slug") ON DELETE RESTRICT,

    -- Última mensagem recebida
    "last_message"    TEXT,
      "last_message_at" TIMESTAMPTZ,

    -- Task VectraClaw gerada por esta sessão (última task ativa)
    "active_task_id"  UUID        REFERENCES "vectraclip"."tasks"("id") ON DELETE SET NULL,

    -- Histórico compacto de mensagens (ring buffer — últimas 50 trocas)
    "history"         JSONB       NOT NULL DEFAULT '[]',

    -- Metadados de roteamento
    "routed_to_agent" UUID        REFERENCES "vectraclip"."agents"("id") ON DELETE SET NULL,
      "routing_score"   SMALLINT    CHECK (routing_score BETWEEN 0 AND 100),

    -- Timestamps
    "opened_at"       TIMESTAMPTZ NOT NULL DEFAULT now(),
      "closed_at"       TIMESTAMPTZ,
      "created_at"      TIMESTAMPTZ NOT NULL DEFAULT now(),
      "updated_at"      TIMESTAMPTZ NOT NULL DEFAULT now()
  );

-- =============================================================================
-- 2. Índices de performance
-- =============================================================================

CREATE INDEX IF NOT EXISTS "idx_connector_sessions_company_id"
    ON "vectraclip"."connector_sessions" ("company_id");

CREATE INDEX IF NOT EXISTS "idx_connector_sessions_channel_external"
    ON "vectraclip"."connector_sessions" ("channel", "external_id");

CREATE INDEX IF NOT EXISTS "idx_connector_sessions_status"
    ON "vectraclip"."connector_sessions" ("status")
    WHERE status IN ('open', 'waiting_agent', 'processing');

CREATE INDEX IF NOT EXISTS "idx_connector_sessions_updated_at"
    ON "vectraclip"."connector_sessions" ("updated_at" DESC);

-- Constraint única: por company + canal + contato externo, só 1 sessão aberta por vez
CREATE UNIQUE INDEX IF NOT EXISTS "uq_connector_sessions_open_per_contact"
    ON "vectraclip"."connector_sessions" ("company_id", "channel", "external_id")
    WHERE status IN ('open', 'waiting_agent', 'processing');

-- =============================================================================
-- 3. Trigger: atualiza updated_at automaticamente
-- =============================================================================

CREATE OR REPLACE FUNCTION vectraclip.fn_connector_sessions_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = vectraclip
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_connector_sessions_updated_at ON "vectraclip"."connector_sessions";
CREATE TRIGGER trg_connector_sessions_updated_at
    BEFORE UPDATE ON "vectraclip"."connector_sessions"
    FOR EACH ROW EXECUTE FUNCTION vectraclip.fn_connector_sessions_updated_at();

-- =============================================================================
-- 4. RLS — Row Level Security
-- =============================================================================

ALTER TABLE "vectraclip"."connector_sessions" ENABLE ROW LEVEL SECURITY;

-- service_role: acesso total (daemon, API interna)
DROP POLICY IF EXISTS "connector_sessions_service_role_all" ON "vectraclip"."connector_sessions";
CREATE POLICY "connector_sessions_service_role_all"
    ON "vectraclip"."connector_sessions"
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- authenticated: lê apenas sessões da sua company
DROP POLICY IF EXISTS "connector_sessions_authenticated_select" ON "vectraclip"."connector_sessions";
CREATE POLICY "connector_sessions_authenticated_select"
    ON "vectraclip"."connector_sessions"
    FOR SELECT
    TO authenticated
    -- W3 fix: tabela real é vectraclip.app_users (id = auth.uid()), NÃO company_users.
    USING (
          company_id IN (
              SELECT company_id FROM vectraclip.app_users
              WHERE id = auth.uid()
          )
      );

-- =============================================================================
-- 5. Comentários
-- =============================================================================

COMMENT ON TABLE  "vectraclip"."connector_sessions" IS
    'Sessões de conversação de canais externos (WhatsApp via Navi, email via Hermes, etc.). '
    'Uma sessão representa um fio de conversa entre um contato externo e o VectraClaw. '
    'Múltiplos canais, um único modelo de dados.';

COMMENT ON COLUMN "vectraclip"."connector_sessions"."channel"      IS 'Canal de origem: whatsapp | email | telegram | api | other';
COMMENT ON COLUMN "vectraclip"."connector_sessions"."connector_id" IS 'Identificador do conector no canal (ex: número WhatsApp da Navi, endereço email do Hermes)';
COMMENT ON COLUMN "vectraclip"."connector_sessions"."external_id"  IS 'Identificador do contato externo no canal (número do usuário, email remetente)';
COMMENT ON COLUMN "vectraclip"."connector_sessions"."history"      IS 'Ring buffer JSONB com últimas 50 trocas: [{role, content, ts}]. Truncado pelo connector_bus ao inserir.';
COMMENT ON COLUMN "vectraclip"."connector_sessions"."active_task_id" IS 'FK para a última task VectraClaw gerada por esta sessão. NULL quando idle.';
