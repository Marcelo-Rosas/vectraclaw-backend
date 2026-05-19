-- N3: Migra `password: "secret:GODDADY_SECRET"` legacy → `vault://<uuid>` W4 pattern
--
-- Plan §5 E5. Hermes IMAP password ainda usa convenção pré-W4 (`secret:NAME`)
-- enquanto W4 cravou `vault://<uuid>` como SSOT. Os dois resolvers convivem
-- em src/api.py (W4 vault:// + legacy secret: name lookup), mas há drift de
-- catalog vs implementação. Pós-W4 todo ref deve ser UUID.
--
-- ESPELHEI ANTES (Regra #1):
--   - 1 row em agent_adapter_configs (Hermes mcp-imap) com `password: secret:GODDADY_SECRET`
--   - 0 row em company_adapter_values com prefixo `secret:`
--   - vault.secrets já tem row name='co:01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2:GODDADY_SECRET'
--       id='8a6a3e9a-44a4-4a1c-b329-7737c59f0a01' (criado 2026-04-26)
--   - Resolver W4 em src/api.py:6275 aceita vault://<uuid>; legacy resolver
--     em api.py:7202 lê secret:NAME via vault.secrets.name — convive mas é
--     pattern velho.
--
-- Aplicação:
--   UPDATE field_values_json.password (literal) → vault://8a6a3e9a-44a4-4a1c-b329-7737c59f0a01
--
-- Verificação:
--   SELECT count(*) FROM vectraclip.agent_adapter_configs aac
--     JOIN vectraclip.adapter_catalog ac ON ac.id=aac.adapter_id
--     WHERE ac.slug='mcp-imap' AND aac.field_values_json->>'password' LIKE 'secret:%';
--   -- Expect 0 pós-migration

UPDATE vectraclip.agent_adapter_configs
SET field_values_json = jsonb_set(
  field_values_json,
  '{password}',
  '"vault://8a6a3e9a-44a4-4a1c-b329-7737c59f0a01"'::jsonb,
  false
)
WHERE adapter_id = (SELECT id FROM vectraclip.adapter_catalog WHERE slug = 'mcp-imap')
  AND company_id = '01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2'::uuid
  AND field_values_json->>'password' = 'secret:GODDADY_SECRET';
