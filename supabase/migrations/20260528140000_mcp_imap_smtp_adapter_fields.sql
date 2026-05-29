-- mcp-imap: campos SMTP no catálogo (metadata) + backfill company_adapter_values (W5).
--
-- Hermes Reporter envia via SMTP usando os mesmos metadados do adapter de e-mail.
-- Valores default GoDaddy Workspace ficam no SEED SQL (não no Python).
--
-- ESPELHEI ANTES:
--   adapter_field_definitions mcp-imap: imap_host, imap_port, email, password
--   agent_adapter_configs Hermes: email + vault password + imap_*
--   company_adapter_values mcp-imap: vazio

set search_path to vectraclip, public;

-- ════════════════════════════════════════════════════════════════════════════
-- 1. Field definitions (UI Connectors + validação de shape)
-- ════════════════════════════════════════════════════════════════════════════
INSERT INTO vectraclip.adapter_field_definitions (
  company_id, adapter_id, field_key, field_label, field_type,
  is_required, options_json, sort_order, is_active
)
SELECT
  ac.company_id,
  ac.id,
  v.field_key,
  v.field_label,
  v.field_type,
  v.is_required,
  v.options_json::jsonb,
  v.sort_order,
  true
FROM vectraclip.adapter_catalog ac
CROSS JOIN (
  VALUES
    (
      'smtp_host',
      'Servidor SMTP (envio)',
      'text',
      true,
      '{"default":"smtpout.secureserver.net","hint":"GoDaddy Workspace: smtpout.secureserver.net"}',
      50
    ),
    (
      'smtp_port',
      'Porta SMTP (SSL)',
      'number',
      true,
      '{"default":"465"}',
      60
    )
) AS v(field_key, field_label, field_type, is_required, options_json, sort_order)
WHERE ac.slug = 'mcp-imap'
  AND NOT EXISTS (
    SELECT 1
    FROM vectraclip.adapter_field_definitions afd
    WHERE afd.adapter_id = ac.id
      AND afd.field_key = v.field_key
  );

-- ════════════════════════════════════════════════════════════════════════════
-- 2. company_adapter_values (PRIMARY W5) — copia agent + smtp defaults
-- ════════════════════════════════════════════════════════════════════════════
INSERT INTO vectraclip.company_adapter_values (company_id, adapter_id, field_values_json)
SELECT
  aac.company_id,
  aac.adapter_id,
  aac.field_values_json
    || jsonb_build_object(
      'smtp_host',
      COALESCE(NULLIF(TRIM(aac.field_values_json->>'smtp_host'), ''), 'smtpout.secureserver.net'),
      'smtp_port',
      COALESCE(NULLIF(TRIM(aac.field_values_json->>'smtp_port'), ''), '465')
    )
FROM vectraclip.agent_adapter_configs aac
JOIN vectraclip.adapter_catalog ac ON ac.id = aac.adapter_id
WHERE ac.slug = 'mcp-imap'
ON CONFLICT (company_id, adapter_id) DO UPDATE
  SET field_values_json = vectraclip.company_adapter_values.field_values_json
    || jsonb_build_object(
      'smtp_host',
      COALESCE(
        NULLIF(TRIM(vectraclip.company_adapter_values.field_values_json->>'smtp_host'), ''),
        EXCLUDED.field_values_json->>'smtp_host',
        'smtpout.secureserver.net'
      ),
      'smtp_port',
      COALESCE(
        NULLIF(TRIM(vectraclip.company_adapter_values.field_values_json->>'smtp_port'), ''),
        EXCLUDED.field_values_json->>'smtp_port',
        '465'
      )
    ),
    updated_at = now();

-- ════════════════════════════════════════════════════════════════════════════
-- 3. agent_adapter_configs — override layer com smtp (se ainda vazio)
-- ════════════════════════════════════════════════════════════════════════════
UPDATE vectraclip.agent_adapter_configs aac
   SET field_values_json = aac.field_values_json
     || jsonb_build_object(
       'smtp_host',
       COALESCE(NULLIF(TRIM(aac.field_values_json->>'smtp_host'), ''), 'smtpout.secureserver.net'),
       'smtp_port',
       COALESCE(NULLIF(TRIM(aac.field_values_json->>'smtp_port'), ''), '465')
     ),
       updated_at = now()
  FROM vectraclip.adapter_catalog ac
 WHERE aac.adapter_id = ac.id
   AND ac.slug = 'mcp-imap';
