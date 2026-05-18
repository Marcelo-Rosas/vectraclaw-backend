-- W11 PR1 (M2/3) — meta-whatsapp: waba_id + session_window_hours + template_id catalog-driven
--
-- Auditor 2026-05-18:
--   P0.1: WABA_ID precisa de storage no adapter (não constante Python no service).
--   P1.1: 24h window deve ser config no adapter (Meta pode mudar pra 72h, varia
--         por categoria de conversa). Default 24, faixa 1..168.
--   Item 3 do plano: template_id text → select catalog-driven (source=whatsapp_templates),
--                    filtro APPROVED+pt_BR/pt/und. Documenta que APPROVED é enum Meta.

-- 1. waba_id — company-level (1 WABA por company)
INSERT INTO vectraclip.adapter_field_definitions
  (company_id, adapter_id, field_key, field_label, field_type, is_required, applies_to, sort_order)
SELECT company_id, id, 'waba_id', 'WhatsApp Business Account ID (Meta)',
       'text', true, 'company', 25
  FROM vectraclip.adapter_catalog
 WHERE slug = 'meta-whatsapp'
ON CONFLICT DO NOTHING;

-- 2. session_window_hours — company-level (regra Meta vigente)
INSERT INTO vectraclip.adapter_field_definitions
  (company_id, adapter_id, field_key, field_label, field_type, is_required, applies_to,
   options_json, sort_order)
SELECT company_id, id, 'session_window_hours', 'Janela conversacional (h)',
       'number', false, 'company',
       jsonb_build_object(
         'default', 24,
         'min', 1,
         'max', 168,
         'description',
           'Regra Meta vigente: dentro dessa janela após última inbound do user, free text é permitido. Fora dela, só TEMPLATE WABA aprovado. Meta já mudou (24h/72h) — manter configurável.'
       ),
       30
  FROM vectraclip.adapter_catalog
 WHERE slug = 'meta-whatsapp'
ON CONFLICT DO NOTHING;

-- 3. template_id: text → select catalog-driven via whatsapp_templates
UPDATE vectraclip.adapter_field_definitions afd
   SET field_type = 'select',
       field_label = 'Template padrão (Meta WABA aprovado)',
       options_json = jsonb_build_object(
         'source', 'whatsapp_templates',
         'filter', jsonb_build_object(
           'status', 'APPROVED',
           'is_active', true,
           'language_in', jsonb_build_array('pt_BR','pt','und')
         ),
         'value_field', 'name',
         'label_field', 'name',
         'note', 'status=APPROVED é enum Meta (não slug local). DynamicFieldRenderer resolve options via GET /api/connectors/whatsapp/templates?adapter_id=<id>.'
       ),
       updated_at = now()
  FROM vectraclip.adapter_catalog ac
 WHERE afd.adapter_id = ac.id
   AND ac.slug = 'meta-whatsapp'
   AND afd.field_key = 'template_id';

-- 4. Backfill company_adapter_values Vectra Cargo
--    WABA_ID confirmado 2026-05-18 pelo Marcelo via Business Manager UI:
--      Account: Vectra Cargo  |  WABA ID: 1749567302601773
--    Outras companies preencherão via UI quando onboardarem.
UPDATE vectraclip.company_adapter_values cav
   SET field_values_json = COALESCE(field_values_json, '{}'::jsonb)
                        || jsonb_build_object(
                             'waba_id', '1749567302601773',
                             'session_window_hours', 24
                           ),
       updated_at = now()
  FROM vectraclip.adapter_catalog ac
 WHERE cav.adapter_id = ac.id
   AND ac.slug = 'meta-whatsapp'
   AND cav.company_id = '01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2'; -- Vectra Cargo

DO $$
DECLARE
  fields_meta int;
  values_meta jsonb;
BEGIN
  SELECT count(*) INTO fields_meta
    FROM vectraclip.adapter_field_definitions afd
    JOIN vectraclip.adapter_catalog ac ON ac.id = afd.adapter_id
   WHERE ac.slug = 'meta-whatsapp' AND afd.is_active = true;

  SELECT cav.field_values_json INTO values_meta
    FROM vectraclip.company_adapter_values cav
    JOIN vectraclip.adapter_catalog ac ON ac.id = cav.adapter_id
   WHERE ac.slug = 'meta-whatsapp'
     AND cav.company_id = '01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2';

  RAISE NOTICE '[W11 M2/3] meta-whatsapp active fields=%, vectra waba_id=%, window=%',
    fields_meta,
    values_meta->>'waba_id',
    values_meta->>'session_window_hours';
END $$;
