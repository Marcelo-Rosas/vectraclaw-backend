-- app_secret em meta_instagram estava is_active=false (soft-delete) → não aparece no wizard Valores.
UPDATE vectraclip.adapter_field_definitions afd
   SET is_active = true,
       updated_at = now()
  FROM vectraclip.adapter_catalog ac
 WHERE afd.adapter_id = ac.id
   AND ac.slug IN ('meta_instagram', 'meta-instagram')
   AND afd.field_key = 'app_secret'
   AND afd.is_active = false;

NOTIFY pgrst, 'reload schema';
