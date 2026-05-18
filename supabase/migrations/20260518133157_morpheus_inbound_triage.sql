-- ESPELHEI ANTES (Regra Ouro #1):
--   (1) agent_specialties shape: id text PK, slug text, name, domain text,
--       compatible_roles text[], system_prompt_template text, config_schema jsonb,
--       is_active bool. Slug `inbound-triage` NÃO existe.
--   (2) operation_types_catalog: já tem `orchestration` (Morpheus, score 0=harness).
--       NÃO tem inbound-triage, human-triage, cross-docking-quotation, gymsite-quotation.
--   (3) connector_channels: tem `default_inbound_operation_type` (W7 P0-9), NÃO tem
--       `fallback_operation_type`. Precisa ADD COLUMN.
--   (4) Tabela `kronos_rules` é o precedente direto pra `inbound_intent_rules`
--       (rules com priority + is_active + pattern). Auditor 2026-05-18 confirmou.
--   (5) Site vectracargo.com.br oferece 5 serviços; Marcelo cravou 3 op_types
--       prioritários: Cotação (existente), GymSite (previsão), Cross-Docking (novo).
--
-- PADRÃO ADOTADO:
--   - Tabela própria (não JSONB em specialty_configs) — auditor (i) confirmou
--   - human-triage como op_type (não status) — auditor (ii) confirmou
--   - fallback_operation_type catalog-driven em connector_channels (não literal em handler)
--   - Loop matching data-driven (rules ORDER BY priority, handler sem if/elif por tipo)
--
-- W9 — Opção A do ADR-VEC-INBOUND-INTENT-CLASSIFIER (Marcelo 2026-05-18):
-- Morpheus router. Webhook cria task inbound-triage; Morpheus classifica via
-- inbound_intent_rules + dispatcha task filha com op_type+agent corretos.
-- Resolve caso Fabio (mensagem ambígua → human-triage em vez de gambiarra freight-quotation).

-- ============================================================================
-- 1. Op_types novos no catálogo
-- ============================================================================
INSERT INTO vectraclip.operation_types_catalog
    (id, name, category, primary_agent_id, routing_score, is_active)
VALUES
    ('inbound-triage',          'Triage de Mensagens Inbound',
     'system',     '00000000-0000-0000-0000-000000000001',  -- Morpheus
     0,    true),  -- score 0 = harness (Morpheus daemon)
    ('human-triage',            'Atendimento Humano (fallback inbound)',
     'system',     NULL,                                     -- NULL = humano via UI
     60,   true),
    ('cross-docking-quotation', 'Cotação Cross-Docking',
     'commercial', 'c7de1b0f-7c74-42f1-9de4-7210349e668e',  -- Mercator
     80,   true),
    ('gymsite-quotation',       'Cotação GymSite (previsão futuro)',
     'commercial', 'c7de1b0f-7c74-42f1-9de4-7210349e668e',  -- Mercator (não GymSite agent — esse é prospect-scan)
     80,   true)
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- 2. Specialty `inbound-triage` (Morpheus skill catalog-driven)
-- ============================================================================
INSERT INTO vectraclip.agent_specialties
    (id, slug, name, domain, compatible_roles, system_prompt_template, config_schema, is_active)
VALUES (
    'inbound-triage',
    'inbound-triage',
    'Roteamento de Mensagens Inbound',
    'automation',
    ARRAY['orquestrador', 'router', 'classifier'],
    $$# Morpheus — Roteador de Mensagens Inbound

Você recebe mensagens de canais externos (WhatsApp Meta, etc) sem
classificação prévia. Sua função: identificar a intent do remetente e
dispatcha pra task filha com o op_type correto.

NÃO responda mensagens diretamente. NÃO execute cotação, suporte, ou
qualquer ação de negócio. Apenas classifica e roteia.

## Sinais de match (em ordem decrescente de confiança)

1. **button_id_hint** (Meta interactive button_reply.id) — match exato
2. **origin_pattern** (regex contra texto) — ex: `\\[VECTRA_WEB:freight\\]`
3. **keywords** (qualquer palavra-chave no texto lowercase)

## Output esperado

Cria task filha:
- op_type = rule.target_operation_type
- assigned_to_agent_id = rule.target_agent_id (NULL = humano)
- parent_task_id = sua_task_id
- input_json = mensagem original + sinais detectados

Se nenhuma rule bate: cai em fallback do connector_channels (geralmente
human-triage). Sem fallback hardcoded.
$$,
    '[]'::jsonb,  -- specialty sem fields configuráveis (rules vivem em tabela própria)
    true
) ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- 3. Tabela `inbound_intent_rules` (precedente kronos_rules + multi-tenant)
-- ============================================================================
CREATE TABLE IF NOT EXISTS vectraclip.inbound_intent_rules (
    id                         uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id                 uuid          NOT NULL REFERENCES vectraclip.companies(company_id) ON DELETE CASCADE,
    intent_slug                text          NOT NULL,           -- ex: 'web-freight', 'text-cross-docking'
    display_name               text          NOT NULL,           -- pra UI
    description                text,                              -- pra UI + LLM context futuro

    -- Sinais de match (auditor: matching data-driven, primeira rule por priority que matchar vence)
    keywords                   text[],                            -- ['cotação','frete'] lowercase match
    origin_pattern             text,                              -- regex pattern (compile no Python)
    button_id                  text,                              -- Meta interactive button_reply.id (match exato)

    -- Dispatch target
    target_operation_type      text          NOT NULL REFERENCES vectraclip.operation_types_catalog(id),
    target_agent_id            uuid          REFERENCES vectraclip.agents(id) ON DELETE SET NULL,  -- NULL = humano

    priority                   int           NOT NULL DEFAULT 100,  -- menor = mais prioritário
    is_active                  boolean       NOT NULL DEFAULT true,
    created_at                 timestamptz   NOT NULL DEFAULT now(),
    updated_at                 timestamptz   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_inbound_intent_rules_company_active
    ON vectraclip.inbound_intent_rules (company_id, is_active, priority);
CREATE UNIQUE INDEX IF NOT EXISTS uq_inbound_intent_rules_company_slug
    ON vectraclip.inbound_intent_rules (company_id, intent_slug);

-- Trigger updated_at
CREATE OR REPLACE FUNCTION vectraclip.fn_inbound_intent_rules_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = vectraclip AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;
DROP TRIGGER IF EXISTS trg_inbound_intent_rules_updated_at ON vectraclip.inbound_intent_rules;
CREATE TRIGGER trg_inbound_intent_rules_updated_at
    BEFORE UPDATE ON vectraclip.inbound_intent_rules
    FOR EACH ROW EXECUTE FUNCTION vectraclip.fn_inbound_intent_rules_updated_at();

-- RLS
ALTER TABLE vectraclip.inbound_intent_rules ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS inbound_intent_rules_service_role_all ON vectraclip.inbound_intent_rules;
CREATE POLICY inbound_intent_rules_service_role_all
    ON vectraclip.inbound_intent_rules FOR ALL TO service_role
    USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS inbound_intent_rules_authenticated_all ON vectraclip.inbound_intent_rules;
CREATE POLICY inbound_intent_rules_authenticated_all
    ON vectraclip.inbound_intent_rules FOR ALL TO authenticated
    USING (
        company_id IN (SELECT company_id FROM vectraclip.app_users WHERE id = auth.uid())
    )
    WITH CHECK (
        company_id IN (SELECT company_id FROM vectraclip.app_users WHERE id = auth.uid())
    );

COMMENT ON TABLE vectraclip.inbound_intent_rules IS
    'W9 — Regras catalog-driven pro Morpheus classificar mensagens inbound. '
    'Matching: ORDER BY priority ASC; primeira rule que bate (button_id OU '
    'origin_pattern regex OU keywords any-match) vence. target_agent_id NULL '
    '= humano via UI. Sem nenhuma rule = fallback do connector_channels.';

-- ============================================================================
-- 4. ADD COLUMN connector_channels.fallback_operation_type (auditor P1)
-- ============================================================================
ALTER TABLE vectraclip.connector_channels
    ADD COLUMN IF NOT EXISTS fallback_operation_type text
    REFERENCES vectraclip.operation_types_catalog(id) ON DELETE SET NULL;

COMMENT ON COLUMN vectraclip.connector_channels.fallback_operation_type IS
    'W9 — op_type criado quando nenhuma rule de inbound_intent_rules bate. '
    'Geralmente human-triage. NULL = handler levanta erro/log warning. '
    'Catalog-driven (Regra Ouro #2) — handler NÃO tem string literal.';

-- ============================================================================
-- 5. UPDATE connector_channels.whatsapp — default + fallback
-- ============================================================================
UPDATE vectraclip.connector_channels
   SET default_inbound_operation_type = 'inbound-triage',
       fallback_operation_type        = 'human-triage',
       updated_at                     = now()
 WHERE slug = 'whatsapp';

-- ============================================================================
-- 6. Seed inicial pra VECTRA IA SERVICES (7 rules)
--    Mapeados dos serviços reais do site vectracargo.com.br
-- ============================================================================
INSERT INTO vectraclip.inbound_intent_rules
    (company_id, intent_slug, display_name, description, keywords, origin_pattern, button_id,
     target_operation_type, target_agent_id, priority)
VALUES
    -- Origin patterns (priority 10 — mais fortes, match determinístico)
    ('01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2', 'web-freight',
     'Botão Cotação — site Vectra Cargo',
     'Form do site (Assunto=Cotação) gera link wa.me com prefix [VECTRA_WEB:freight]',
     NULL, '\[VECTRA_WEB:freight\]', NULL,
     'freight-quotation', 'c7de1b0f-7c74-42f1-9de4-7210349e668e', 10),

    ('01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2', 'web-cross-docking',
     'Botão Cross-Docking — site Vectra Cargo',
     'Form (Assunto=Cross-Docking ou Armazenagem) prefix [VECTRA_WEB:cross-docking]',
     NULL, '\[VECTRA_WEB:cross-docking\]', NULL,
     'cross-docking-quotation', 'c7de1b0f-7c74-42f1-9de4-7210349e668e', 10),

    ('01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2', 'web-gymsite',
     'Botão GymSite — site Vectra Cargo',
     'Previsão futuro: produto GymSite tem botão dedicado no site',
     NULL, '\[VECTRA_WEB:gymsite\]', NULL,
     'gymsite-quotation', 'c7de1b0f-7c74-42f1-9de4-7210349e668e', 10),

    -- Keywords (priority 50 — fallback texto livre, menos preciso)
    ('01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2', 'text-freight',
     'Texto sobre frete/transporte',
     'Mensagem WhatsApp livre com keywords de cotação de transporte',
     ARRAY['cotação','frete','transportar','transporte','cubagem','equipamento','academia'],
     NULL, NULL,
     'freight-quotation', 'c7de1b0f-7c74-42f1-9de4-7210349e668e', 50),

    ('01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2', 'text-cross-docking',
     'Texto sobre cross-docking/armazenagem',
     'Keywords de armazenagem, cross-docking, distribuição',
     ARRAY['cross-docking','cross docking','crossdocking','armazenagem','armazém','distribuição','warehouse','estoque'],
     NULL, NULL,
     'cross-docking-quotation', 'c7de1b0f-7c74-42f1-9de4-7210349e668e', 50),

    ('01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2', 'text-gymsite',
     'Texto sobre GymSite',
     'Keywords do produto GymSite (prospecção academias)',
     ARRAY['gymsite','prospect academia','prospectar academia','monitor academia'],
     NULL, NULL,
     'gymsite-quotation', 'c7de1b0f-7c74-42f1-9de4-7210349e668e', 50)
ON CONFLICT (company_id, intent_slug) DO NOTHING;

-- ============================================================================
-- Verificação shadow-replay-safe (hotfix 2026-05-18: assert condicional ao seed)
--
-- Versão anterior assumia presença de:
--   (a) row connector_channels.slug='whatsapp' (seed W3)
--   (b) companies.company_id='01b9b40e-...' (seed Vectra Cargo prod)
-- Em shadow DB do `supabase db pull`, (a) e (b) não existem → assert quebrava.
--
-- Fix: separa asserts auto-contidos (op_types + specialty inseridos POR esta
-- migration — devem sempre passar) dos asserts dependentes de seed externo
-- (condicionais à existência prévia).
-- ============================================================================
DO $$
DECLARE
    v_ops int; v_specs int; v_rules int; v_wa_default text; v_wa_fallback text;
    v_wa_exists int; v_vectra_exists int;
BEGIN
    -- Asserts auto-contidos (esta migration cria → sempre devem passar)
    SELECT count(*) INTO v_ops FROM vectraclip.operation_types_catalog
        WHERE id IN ('inbound-triage','human-triage','cross-docking-quotation','gymsite-quotation');
    SELECT count(*) INTO v_specs FROM vectraclip.agent_specialties WHERE slug='inbound-triage';

    -- Asserts dependentes de seed externo (condicionais)
    SELECT count(*) INTO v_wa_exists FROM vectraclip.connector_channels WHERE slug='whatsapp';
    SELECT count(*) INTO v_vectra_exists FROM vectraclip.companies
        WHERE company_id='01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2';
    SELECT count(*) INTO v_rules FROM vectraclip.inbound_intent_rules
        WHERE company_id='01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2';
    SELECT default_inbound_operation_type, fallback_operation_type
        INTO v_wa_default, v_wa_fallback
        FROM vectraclip.connector_channels WHERE slug='whatsapp';

    RAISE NOTICE 'W9: op_types=% (esp 4) | specialty=% (esp 1) | wa_existed=% rules_VECTRA=% (esp >=6 se vectra_existed) | vectra_existed=% | wa default=% fallback=%',
        v_ops, v_specs, v_wa_exists, v_rules, v_vectra_exists, v_wa_default, v_wa_fallback;

    -- Asserts incondicionais (own seed)
    IF v_ops < 4 THEN
        RAISE EXCEPTION 'W9: op_types_catalog seed falhou (esperado >=4, got %)', v_ops;
    END IF;
    IF v_specs < 1 THEN
        RAISE EXCEPTION 'W9: agent_specialties seed falhou (esperado >=1, got %)', v_specs;
    END IF;

    -- Asserts condicionais (só se seed externo existia)
    IF v_wa_exists > 0 AND (v_wa_default != 'inbound-triage' OR v_wa_fallback != 'human-triage') THEN
        RAISE EXCEPTION 'W9: connector_channels whatsapp UPDATE falhou (default=%, fallback=%)',
            v_wa_default, v_wa_fallback;
    END IF;
    IF v_vectra_exists > 0 AND v_rules < 6 THEN
        RAISE EXCEPTION 'W9: inbound_intent_rules seed Vectra falhou (esperado >=6, got %)', v_rules;
    END IF;
END $$;

NOTIFY pgrst, 'reload schema';
