-- VEC-326 Fix: field_type='url' nao e aceito pelo AdapterFieldDefinition
UPDATE vectraclip.adapter_field_definitions
SET field_type = 'text', updated_at = NOW()
WHERE adapter_id IN (
  SELECT id FROM vectraclip.adapter_catalog WHERE slug = 'ollama'
)
AND field_key = 'base_url'
AND field_type = 'url';
