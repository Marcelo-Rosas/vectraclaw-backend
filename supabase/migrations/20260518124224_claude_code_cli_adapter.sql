-- ESPELHEI ANTES (Regra Ouro #1):
--   (1) adapter_catalog: cols (id uuid PK, company_id uuid FK, slug text,
--       display_name text, provider text, is_active bool, created/updated_at).
--       UNIQUE (company_id, slug). Sem CHECK em provider.
--   (2) adapter_field_definitions: cols (id, company_id, adapter_id, field_key,
--       field_label, field_type, is_required, options_json jsonb,
--       trigger_condition, sort_order, is_active, ...).
--   (3) Adapter `claude_code` (provider=anthropic, SDK paga) JÁ EXISTE pra
--       VECTRA IA SERVICES (id=fb4df519-...). Mercator atualmente aponta pra
--       ele em agent_adapter_configs.
--   (4) llm_models NÃO tem rows pros aliases CLI (sonnet/opus/haiku) — IDs
--       reais são claude-sonnet-4-5, claude-opus-4-5 etc. Aliases CLI são
--       específicos do binário `claude` e não vivem em llm_models. Por isso
--       `options_json` aqui é LISTA ESTÁTICA, não `{source:"llm_models"}`
--       (auditor 2026-05-18 confirmou: não é violação Regra #2 — não há
--       tabela espelho dos aliases).
--
-- PADRÃO ADOTADO:
--   Adapter novo com slug distinto de `claude_code` (que é Anthropic SDK
--   pay-per-token). Provider `claude_cli_subscription` discrimina o cliente
--   subprocess CLI (OAuth Max). PROVIDER_CLIENT_MAP em
--   src/managed_agents/agent_client_factory.py mapeia esse provider pra
--   ClaudeCodeCliAgentClient (W8 backend).
--
--   4 fields canônicos:
--     - model_id (select, required, options=sonnet/opus/haiku)
--     - system_prompt (textarea, optional)
--     - extended_thinking (boolean, optional)
--     - timeout_seconds (text, optional, default 180)
--
--   Credenciais: nenhuma. Auth é OAuth subscription do host
--   (~/.claude/.credentials.json), não vai pro Vault. Regra Ouro #2
--   respeitada — não há "API key escondida em env" porque o CLI usa
--   credentials file próprio (e o cliente Python faz env.pop("ANTHROPIC_API_KEY")
--   defensivo per memory `claude-cli-subscription-subprocess`).
--
-- W8 (2026-05-18) — Marcelo cravou 2x: `claude -p` deve virar adapter de
-- verdade. Default branch em agent_daemon.py:540-562 é gambiarra pré-MVP.
-- Esta migration + cliente W8 backend tornam Mercator (e qualquer outro
-- agente) capaz de usar Claude CLI subscription via UI W4 catalog-driven.

-- ============================================================================
-- 1. INSERT adapter_catalog row pra cada company que já tem claude_code (SDK)
-- ============================================================================
INSERT INTO vectraclip.adapter_catalog
    (company_id, slug, display_name, provider, is_active)
SELECT
    company_id,
    'claude_code_cli',
    'Claude Code CLI (Max subscription)',
    'claude_cli_subscription',
    true
FROM vectraclip.adapter_catalog
WHERE slug = 'claude_code'
  AND NOT EXISTS (
      SELECT 1 FROM vectraclip.adapter_catalog ac2
      WHERE ac2.company_id = adapter_catalog.company_id
        AND ac2.slug = 'claude_code_cli'
  );

-- ============================================================================
-- 2. INSERT 4 field definitions pro novo adapter (per company)
-- ============================================================================
INSERT INTO vectraclip.adapter_field_definitions
    (company_id, adapter_id, field_key, field_label, field_type, is_required, sort_order, options_json, is_active)
SELECT
    ac.company_id, ac.id,
    fk.field_key, fk.field_label, fk.field_type, fk.is_required, fk.sort_order,
    fk.options_json::jsonb, true
FROM vectraclip.adapter_catalog ac
CROSS JOIN (VALUES
    ('model_id',        'Modelo (alias CLI)',  'select',   true,  1, '["sonnet","haiku","opus"]'),
    ('system_prompt',   'System Prompt',       'textarea', false, 2, NULL),
    ('extended_thinking','Extended Thinking',  'boolean',  false, 3, NULL),
    ('timeout_seconds', 'Timeout (segundos)',  'text',     false, 4, NULL)
) AS fk(field_key, field_label, field_type, is_required, sort_order, options_json)
WHERE ac.slug = 'claude_code_cli'
  AND NOT EXISTS (
      SELECT 1 FROM vectraclip.adapter_field_definitions afd
      WHERE afd.adapter_id = ac.id AND afd.field_key = fk.field_key
  );

-- ============================================================================
-- Verificação shadow-replay-safe (hotfix 2026-05-18: assert condicional ao seed)
--
-- Versão anterior assumia que SEMPRE haveria pelo menos 1 row claude_code (seed
-- prod da Vectra IA Services). Mas em shadow DB do `supabase db pull` o
-- histórico é replayado sobre schema vazio (sem data seed) — INSERT cria 0 rows
-- e o assert quebrava com SQLSTATE P0001.
--
-- Fix: só falha SE havia source pra clonar (v_source_count > 0) E mesmo assim
-- nada foi criado. Em shadow vazio, v_source_count=0 → NOTICE info, sem erro.
-- ============================================================================
DO $$
DECLARE
  v_source_count int;
  v_adapters int;
  v_fields int;
BEGIN
  SELECT count(*) INTO v_source_count FROM vectraclip.adapter_catalog
    WHERE slug='claude_code';
  SELECT count(*) INTO v_adapters FROM vectraclip.adapter_catalog
    WHERE slug='claude_code_cli';
  SELECT count(*) INTO v_fields FROM vectraclip.adapter_field_definitions afd
    JOIN vectraclip.adapter_catalog ac ON ac.id=afd.adapter_id
    WHERE ac.slug='claude_code_cli';
  RAISE NOTICE 'W8: source claude_code=% | claude_code_cli adapters=% | fields=% (esp 4 por adapter)',
    v_source_count, v_adapters, v_fields;
  IF v_source_count > 0 AND v_adapters < 1 THEN
    RAISE EXCEPTION 'W8: claude_code existe (% rows) mas nenhum claude_code_cli foi criado — INSERT falhou silenciosamente', v_source_count;
  END IF;
END $$;

NOTIFY pgrst, 'reload schema';
