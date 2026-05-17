-- ESPELHEI ANTES:
--   SELECT field_key FROM vectraclip.adapter_field_definitions
--   WHERE adapter_id IN (SELECT id FROM vectraclip.adapter_catalog WHERE slug='meta-whatsapp')
--   ORDER BY sort_order
--   → 7 fields: access_token, phone_number_id, api_version, webhook_verify_token,
--     function_url, template_id, template_language. Falta app_secret pra HMAC.
--
-- PADRÃO ADOTADO:
--   adapter_field_definitions é per-company (company_id + adapter_id por row).
--   INSERT SELECT iterando rows do adapter_catalog WHERE slug='meta-whatsapp'
--   garante que TODA company que tem o adapter ganha o field (idempotente via
--   ON CONFLICT no índice único company_id+adapter_id+field_key se existir,
--   senão NOT EXISTS clause).
--
-- W3.1 hotfix — Meta WhatsApp Cloud API webhook precisa de App Secret pra
-- verificar X-Hub-Signature-256 (HMAC SHA-256 sobre o body). Sem este field,
-- o webhook ficaria env-driven (Regra Ouro #2 violation) ou aceito sem verify
-- (security violation). Adiciona como SECRET REQUIRED no adapter meta-whatsapp.

INSERT INTO vectraclip.adapter_field_definitions
    (company_id, adapter_id, field_key, field_label, field_type, is_required, sort_order, is_active)
SELECT
    ac.company_id,
    ac.id,
    'app_secret',
    'App Secret (META_WA_APP_SECRET)',
    'secret',
    true,
    8,
    true
FROM vectraclip.adapter_catalog ac
WHERE ac.slug = 'meta-whatsapp'
  AND NOT EXISTS (
      SELECT 1 FROM vectraclip.adapter_field_definitions afd
      WHERE afd.adapter_id = ac.id
        AND afd.field_key = 'app_secret'
  );

-- Verificação
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n
  FROM vectraclip.adapter_field_definitions afd
  JOIN vectraclip.adapter_catalog ac ON ac.id = afd.adapter_id
  WHERE ac.slug='meta-whatsapp' AND afd.field_key='app_secret';
  RAISE NOTICE 'W3.1 app_secret fields inseridas: % (esperado >= 1)', n;
END $$;

NOTIFY pgrst, 'reload schema';
