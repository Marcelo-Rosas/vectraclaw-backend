-- N5.2: adiciona campo 'audience' ao field_definitions do camunda-mcp.
--
-- Camunda 8 SaaS OAuth client_credentials EXIGE param audience=zeebe.camunda.io
-- no token request (https://login.cloud.camunda.io/oauth/token). Sem ele o token
-- exchange falha. resolve_mcp_auth (mcp_client.py) só envia audience se o campo
-- existir em field_values → admin precisa de um field pra preencher.
--
-- Confirmado via doc oficial + env vars do cluster do Marcelo:
--   ZEEBE_TOKEN_AUDIENCE='zeebe.camunda.io' / CAMUNDA_TOKEN_AUDIENCE='zeebe.camunda.io'
--   REST address = https://{region}.api.camunda.io/{clusterId}
--   MCP endpoint = {cluster_url}/mcp/cluster (cluster_url = REST address; template N5.1 OK)
--
-- ESPELHEI ANTES (Regra #1): camunda-mcp field_definitions atual =
--   [cluster_url, client_id, client_secret, oauth_token_url]. Rebuild incluindo audience.
--   Catálogo = schema não-segredo → migration é o caminho sancionado (não é hardcode de secret).
--
-- Verificação:
--   SELECT jsonb_path_query_array(field_definitions,'$[*].key') FROM vectraclip.mcp_server_catalog WHERE id='camunda-mcp';
--   -- Expect inclui "audience"

UPDATE vectraclip.mcp_server_catalog
SET field_definitions = '[
  {"key":"cluster_url","label":"Cluster REST Address","type":"text","required":true,"placeholder":"https://jfk-1.api.camunda.io/<clusterId>"},
  {"key":"client_id","label":"Client ID","type":"text","required":true},
  {"key":"client_secret","label":"Client Secret","type":"secret","required":true},
  {"key":"oauth_token_url","label":"OAuth Token URL","type":"text","required":true,"default":"https://login.cloud.camunda.io/oauth/token"},
  {"key":"audience","label":"OAuth Audience","type":"text","required":true,"default":"zeebe.camunda.io"}
]'::jsonb
WHERE id = 'camunda-mcp';
