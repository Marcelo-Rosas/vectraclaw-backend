-- N5 Seed: 3 MCP servers no mcp_server_catalog (Plan §5 / CONTRACTS §5)
--
-- ADITIVO PURO. NÃO toca adapter_catalog.mcp-imap (Hermes ainda lê creds IMAP
-- de agent_adapter_configs hoje; cutover pra agent_mcp_bindings só no N7 quando
-- MCPClient souber consumir binding). NÃO cria agent_mcp_bindings (precisa de
-- N6 endpoints + N7 runtime). Zero disrupção em produção.
--
-- ESPELHEI ANTES (Regra #1):
--   - mcp_server_catalog vazio (0 rows) — seguro INSERT
--   - adapter_catalog.mcp-imap presente (1) + agent_adapter_configs Hermes (1) — NÃO mexer
--   - field_definitions JSONB segue shape adapter_field_definitions: {key,label,type,required,...}
--   - 3 servers da CONTRACTS-MCP-BINDINGS.md §5 (mcp-imap canonical + camunda-mcp + supabase-mcp)
--
-- Memory: feedback_no_camunda_keep_custom_engine (Camunda só referência BPMN, não engine).
--
-- Verificação:
--   SELECT id, category, transport, auth_type FROM vectraclip.mcp_server_catalog ORDER BY display_order;
--   -- Expect 3 rows

INSERT INTO vectraclip.mcp_server_catalog
  (id, name, description, transport, endpoint_url_template, auth_type, field_definitions, category, icon, display_order, documentation_url)
VALUES
  (
    'mcp-imap',
    'IMAP Inbox',
    'Polling de inbox IMAP pra agente Hermes (leitura email_lead). Definição canônica MCP; cutover do adapter_catalog legacy ocorre no N7.',
    'http',
    'imap://{host}:{port}',
    'api_key',
    '[
      {"key":"host","label":"IMAP Host","type":"text","required":true},
      {"key":"port","label":"Port","type":"number","default":993},
      {"key":"username","label":"Username","type":"text","required":true},
      {"key":"password","label":"Password","type":"secret","required":true}
    ]'::jsonb,
    'messaging',
    'mail',
    10,
    'https://www.rfc-editor.org/rfc/rfc3501'
  ),
  (
    'camunda-mcp',
    'Camunda Orchestration Cluster',
    'Referência BPMN canônica pra Daedalus modelagem (NÃO execução). HTTP streamable Camunda 8.9+. Engine final é Vectra própria.',
    'http',
    'https://{cluster}.camunda.io/mcp/cluster',
    'oauth2_client_credentials',
    '[
      {"key":"cluster_url","label":"Cluster URL","type":"text","required":true,"placeholder":"https://abc123.cl.camunda.io"},
      {"key":"client_id","label":"Client ID","type":"text","required":true},
      {"key":"client_secret","label":"Client Secret","type":"secret","required":true},
      {"key":"oauth_token_url","label":"OAuth Token URL","type":"text","required":true,"placeholder":"https://login.cloud.camunda.io/oauth/token"}
    ]'::jsonb,
    'bpm',
    'git-branch',
    20,
    'https://docs.camunda.io/docs/apis-tools/orchestration-cluster-api-mcp/orchestration-cluster-api-mcp-overview/'
  ),
  (
    'supabase-mcp',
    'Supabase Vectraclip Schema',
    'Read schema interno workflow_definitions/sipoc_components pra agente consultar metadados próprios.',
    'http',
    'https://{project_ref}.supabase.co/mcp',
    'bearer',
    '[
      {"key":"project_ref","label":"Project Ref","type":"text","default":"epgedaiukjippepujuzc","readonly":true},
      {"key":"access_token","label":"Access Token","type":"secret","required":true}
    ]'::jsonb,
    'storage',
    'database',
    30,
    'https://supabase.com/docs'
  )
ON CONFLICT (id) DO NOTHING;
