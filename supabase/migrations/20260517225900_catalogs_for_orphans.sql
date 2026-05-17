-- ESPELHEI ANTES:
--   Estado real (lido via SELECT antes de criar):
--   - companies_pkey = ("company_id") NÃO "id"
--   - agents UNIQUE (company_id, id) — ON CONFLICT bate com essa OU (id)
--   - agent_specialty_configs UNIQUE (agent_id, specialty_id) — NÃO inclui company_id
--   - operation_types_catalog cols reais: (id, name, category, primary_agent_id,
--     default_specialty_slug, is_active, routing_score) — NÃO (operation_type, label, default_agent_id)
--   - agent_specialty_configs coluna jsonb chama `values`, não `field_values_json`
-- PADRÃO ADOTADO:
--   Catálogos cross-tenant (sem company_id) — vocabulário do produto, não config per-empresa.
--   Mesmo shape de workflow_logic_patterns / agent_status_types (PK text slug, name, description,
--   display_order, is_active). Aplica Regra Ouro #2 NO HARDCODE — substitui 4 CHECKs hardcoded
--   que viriam nas próximas 3 migrations (connector_sessions, prospects) por FK pra estes catálogos.
--
-- W3 PRD Fundação Orchestration — pré-requisito pras 3 migrations órfãs.
-- Cria 4 catálogos referenciados como FK pelas tabelas connector_sessions + prospects.
-- Sem este arquivo, as 3 órfãs reintroduziriam o anti-pattern (CHECKs duplicando catalog).

-- ============================================================================
-- 1. prospect_statuses (consumido por prospects.status)
-- ============================================================================
CREATE TABLE IF NOT EXISTS vectraclip.prospect_statuses (
  slug          text         PRIMARY KEY,
  name          text         NOT NULL,
  description   text,
  display_order integer      NOT NULL DEFAULT 0,
  is_active     boolean      NOT NULL DEFAULT true,
  created_at    timestamptz  NOT NULL DEFAULT now(),
  updated_at    timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE vectraclip.prospect_statuses IS
  'Catalog cross-tenant pra prospects.status (W3 PRD Fundação). Substitui CHECK hardcoded (HOT/WARM/COLD/CONTACTED/CONVERTED/DISQUALIFIED). Score-driven workflow: HOT > 70 aciona Navi imediato; WARM 40-70 fila semanal; COLD < 40 análise futura.';

INSERT INTO vectraclip.prospect_statuses (slug, name, description, display_order) VALUES
  ('HOT',          'Quente',       'Score > 70 — aciona pipeline Navi/WhatsApp imediato',    10),
  ('WARM',         'Morno',        'Score 40-70 — entra fila de contato semanal',            20),
  ('COLD',         'Frio',         'Score < 40 — registra pra análise futura, sem ação',     30),
  ('CONTACTED',    'Contatado',    'Já entrou em contato; aguarda resposta',                 40),
  ('CONVERTED',    'Convertido',   'Virou cliente Vectra Cargo',                             50),
  ('DISQUALIFIED', 'Desqualificado','Não fit (porte errado, inativo, fora do target)',       60)
ON CONFLICT (slug) DO NOTHING;

-- ============================================================================
-- 2. contact_channels (consumido por prospects.contacted_via)
-- ============================================================================
CREATE TABLE IF NOT EXISTS vectraclip.contact_channels (
  slug          text         PRIMARY KEY,
  name          text         NOT NULL,
  description   text,
  display_order integer      NOT NULL DEFAULT 0,
  is_active     boolean      NOT NULL DEFAULT true,
  created_at    timestamptz  NOT NULL DEFAULT now(),
  updated_at    timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE vectraclip.contact_channels IS
  'Catalog cross-tenant pra registrar canal de contato comercial (W3 PRD Fundação). prospects.contacted_via é FK pra cá. Distinto de connector_channels: estes são canais de SAÍDA ATIVA (CRM ação), não inbound de mensagem.';

INSERT INTO vectraclip.contact_channels (slug, name, description, display_order) VALUES
  ('whatsapp', 'WhatsApp',         'Contato via WhatsApp (manual ou Navi)',           10),
  ('email',    'E-mail',           'Envio direto via Hermes/SMTP ou manual',          20),
  ('phone',    'Telefone',         'Ligação registrada (operador humano)',            30),
  ('other',    'Outro',            'Canal não-padrão; ver contact_notes pro detalhe', 90)
ON CONFLICT (slug) DO NOTHING;

-- ============================================================================
-- 3. connector_channels (consumido por connector_sessions.channel)
-- ============================================================================
CREATE TABLE IF NOT EXISTS vectraclip.connector_channels (
  slug          text         PRIMARY KEY,
  name          text         NOT NULL,
  description   text,
  display_order integer      NOT NULL DEFAULT 0,
  is_active     boolean      NOT NULL DEFAULT true,
  created_at    timestamptz  NOT NULL DEFAULT now(),
  updated_at    timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE vectraclip.connector_channels IS
  'Catalog cross-tenant pra connector_sessions.channel (W3 PRD Fundação). Distinto de contact_channels: estes são canais de INBOUND (sessões de conversa entrando no VectraClaw via webhook/poller). Whatsapp aparece em ambos com semântica diferente (inbound aqui, outbound em contact_channels).';

INSERT INTO vectraclip.connector_channels (slug, name, description, display_order) VALUES
  ('whatsapp', 'WhatsApp (Navi)',  'Mensagens via Evolution API/Navi WhatsApp',       10),
  ('email',    'E-mail (Hermes)',  'IMAP polling Hermes',                              20),
  ('telegram', 'Telegram',         'Reserva pra Telegram bot (não implementado)',     30),
  ('api',      'API direta',       'Outros sistemas chamando webhook próprio',        40),
  ('other',    'Outro',            'Canal não-categorizado',                          90)
ON CONFLICT (slug) DO NOTHING;

-- ============================================================================
-- 4. connector_session_statuses (consumido por connector_sessions.status)
-- ============================================================================
CREATE TABLE IF NOT EXISTS vectraclip.connector_session_statuses (
  slug          text         PRIMARY KEY,
  name          text         NOT NULL,
  description   text,
  display_order integer      NOT NULL DEFAULT 0,
  is_active     boolean      NOT NULL DEFAULT true,
  created_at    timestamptz  NOT NULL DEFAULT now(),
  updated_at    timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE vectraclip.connector_session_statuses IS
  'Catalog cross-tenant pra connector_sessions.status (W3 PRD Fundação). Máquina de estados da sessão de conversa.';

INSERT INTO vectraclip.connector_session_statuses (slug, name, description, display_order) VALUES
  ('open',           'Aberta',         'Sessão recém-criada, sem agente roteado ainda',           10),
  ('waiting_agent',  'Aguardando',     'Sessão aguardando resposta do agente roteado',            20),
  ('processing',     'Processando',    'Agente executando task derivada desta sessão',            30),
  ('closed',         'Fechada',        'Conversa concluída (manualmente ou por timeout)',         40),
  ('errored',        'Erro',           'Agente falhou; humano precisa intervir',                  50)
ON CONFLICT (slug) DO NOTHING;

-- ============================================================================
-- Verificação shadow-replay safe
-- ============================================================================
DO $$
DECLARE
  n_ps int; n_cc int; n_cn int; n_css int;
BEGIN
  SELECT count(*) INTO n_ps  FROM vectraclip.prospect_statuses;
  SELECT count(*) INTO n_cc  FROM vectraclip.contact_channels;
  SELECT count(*) INTO n_cn  FROM vectraclip.connector_channels;
  SELECT count(*) INTO n_css FROM vectraclip.connector_session_statuses;
  RAISE NOTICE 'W3 catalogs: prospect_statuses=% (esp 6) | contact_channels=% (esp 4) | connector_channels=% (esp 5) | connector_session_statuses=% (esp 5)',
    n_ps, n_cc, n_cn, n_css;
END $$;

NOTIFY pgrst, 'reload schema';
