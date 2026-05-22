-- Instagram inbound channel + meta-instagram adapter field definitions (W12 / NAVI)
-- Espelhar: SELECT slug FROM vectraclip.connector_channels;

INSERT INTO vectraclip.connector_channels (slug, name, description, display_order)
VALUES (
  'instagram',
  'Instagram (DM)',
  'Mensagens diretas via Meta Instagram Messaging API',
  15
)
ON CONFLICT (slug) DO NOTHING;

UPDATE vectraclip.connector_channels
   SET default_inbound_operation_type = 'inbound-triage',
       fallback_operation_type        = 'human-triage',
       updated_at                     = now()
 WHERE slug = 'instagram';

-- Field definitions para companies que já têm adapter meta-instagram no catalog
INSERT INTO vectraclip.adapter_field_definitions
    (company_id, adapter_id, field_key, field_label, field_type, is_required, sort_order, is_active)
SELECT ac.company_id, ac.id, v.field_key, v.field_label, v.field_type, v.is_required, v.sort_order, true
FROM vectraclip.adapter_catalog ac
CROSS JOIN (
  VALUES
    ('instagram_account_id', 'Instagram Account ID', 'text', true, 1),
    ('access_token',         'Access Token (Page/IG)', 'secret', true, 2),
    ('app_secret',           'App Secret (Meta App)', 'secret', true, 3),
    ('webhook_verify_token', 'Webhook Verify Token', 'secret', true, 4),
    ('api_version',          'Graph API Version', 'text', false, 5),
    ('page_id',              'Facebook Page ID', 'text', false, 6)
) AS v(field_key, field_label, field_type, is_required, sort_order)
WHERE ac.slug = 'meta-instagram'
  AND NOT EXISTS (
      SELECT 1 FROM vectraclip.adapter_field_definitions afd
      WHERE afd.adapter_id = ac.id AND afd.field_key = v.field_key
  );

NOTIFY pgrst, 'reload schema';
