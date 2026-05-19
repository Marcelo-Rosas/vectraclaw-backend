-- N5.1 Hotfix: camunda-mcp endpoint_url_template usava placeholder {cluster}
-- mas o field_definitions define a chave 'cluster_url' (URL completa). O resolver
-- (resolve_mcp_auth._fill_template) só substitui placeholders presentes em
-- field_values → {cluster} ficava intacto → McpAuthError endpoint_template_unresolved
-- → handshake 502.
--
-- Sintoma reportado por Marcelo no smoke 2026-05-19:
--   handshake_auth_failed:endpoint_template_unresolved:https://{cluster}.camunda.io/mcp/cluster
--
-- ESPELHEI ANTES (Regra #1):
--   SELECT mostrou camunda-mcp template '{cluster}' vs field_keys [cluster_url,...]
--   mcp-imap ({host}/{port}) e supabase-mcp ({project_ref}) já batem — não tocar.
--
-- Fix: template usa {cluster_url} (admin cola URL completa tipo
-- https://abc123.cl.camunda.io). Endpoint resolvido vira
-- https://abc123.cl.camunda.io/mcp/cluster.
--
-- Verificação:
--   SELECT endpoint_url_template FROM vectraclip.mcp_server_catalog WHERE id='camunda-mcp';
--   -- Expect: {cluster_url}/mcp/cluster

UPDATE vectraclip.mcp_server_catalog
SET endpoint_url_template = '{cluster_url}/mcp/cluster'
WHERE id = 'camunda-mcp'
  AND endpoint_url_template = 'https://{cluster}.camunda.io/mcp/cluster';
