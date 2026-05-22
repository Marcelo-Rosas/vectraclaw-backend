-- Field defs para adapter slug meta_instagram (wizard _slugify_adapter_slug).
-- Migration 20260521120000 já cobre meta-instagram (kebab legado).

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
WHERE ac.slug = 'meta_instagram'
  AND NOT EXISTS (
      SELECT 1 FROM vectraclip.adapter_field_definitions afd
      WHERE afd.adapter_id = ac.id AND afd.field_key = v.field_key
  );

NOTIFY pgrst, 'reload schema';
