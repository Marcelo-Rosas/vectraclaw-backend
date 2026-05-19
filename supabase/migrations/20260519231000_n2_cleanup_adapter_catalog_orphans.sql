-- N2 Cleanup: 4 órfãos em adapter_catalog + 1 field def deprecated em meta-whatsapp
--
-- Plan §5 erros E2 (codex) + E3 (mcp-gmail/slack/github) + E4 (template_language deprecated)
--
-- ESPELHEI ANTES (Regra #1):
--   - 4 órfãos (codex, mcp-gmail, mcp-slack, mcp-github) tem:
--       0 adapter_field_definitions rows
--       0 agent_adapter_configs rows
--       0 company_adapter_values rows
--     → safe DELETE (sem FK cascade dependency).
--   - meta-whatsapp.template_language is_active=false (deprecated, mantido visivel pra forms);
--     pode ser HARD DELETE — UI já não renderiza is_active=false; toda data path resolve por
--     field_values_json.template_name + idioma na payload.
--
-- Refactor TRI-TABELA aproximando (N4+):
--   - codex: REMOVE (sem implementação)
--   - mcp-gmail/slack/github: serão recriados em mcp_server_catalog quando N4/N5 rodarem,
--     com schema correto + field_definitions. Esses rows em adapter_catalog estavam errados
--     conceitualmente (MCPs não são "LLM adapter").
--
-- Verificação pós-aplicação:
--   SELECT count(*) FROM vectraclip.adapter_catalog
--     WHERE slug IN ('codex','mcp-gmail','mcp-slack','mcp-github'); -- expect 0
--   SELECT count(*) FROM vectraclip.adapter_field_definitions afd
--     JOIN vectraclip.adapter_catalog ac ON ac.id = afd.adapter_id
--     WHERE ac.slug='meta-whatsapp' AND afd.is_active=false; -- expect 0

-- ============================================================================
-- 1) DELETE 4 órfãos sem dependências em adapter_catalog
-- ============================================================================

DELETE FROM vectraclip.adapter_catalog
WHERE slug IN ('codex', 'mcp-gmail', 'mcp-slack', 'mcp-github');

-- ============================================================================
-- 2) DELETE row deprecated meta-whatsapp.template_language
-- ============================================================================

DELETE FROM vectraclip.adapter_field_definitions
WHERE id = '6b885989-e795-4c02-b3bc-5cb8eaa1c2a2'
  AND field_key = 'template_language'
  AND is_active = false;
