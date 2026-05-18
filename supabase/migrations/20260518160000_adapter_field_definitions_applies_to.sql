-- W11 PR1 (M1/3) — applies_to em adapter_field_definitions + ajuste meta-whatsapp template_*
--
-- Resolve: gap onde CompanyAdapterValuesDialog e AgentAdapterConfigDialog
-- mostram os MESMOS fields (sem separar company-level vs agent-level).
-- Fix: nova coluna scope `applies_to` ENUM-like ('company'|'agent'|'both').
-- Frontend (PR pareado) filtra:
--   - CompanyAdapterValuesDialog: applies_to IN ('company','both')
--   - AgentAdapterConfigDialog:   applies_to IN ('agent','both')
--
-- Default 'company' por segurança: nada vaza pra agent UI sem decisão explícita.
-- Auditor pré-impl 2026-05-18 (Regra Ouro #4): aprovado com este pattern.

ALTER TABLE vectraclip.adapter_field_definitions
  ADD COLUMN IF NOT EXISTS applies_to text NOT NULL DEFAULT 'company'
    CHECK (applies_to IN ('company','agent','both'));

COMMENT ON COLUMN vectraclip.adapter_field_definitions.applies_to IS
  'Escopo de exibição: company-level (default), agent-level (override per-agent), ou both. Filtro do dialog UI vem daqui.';

-- meta-whatsapp: template_id e template_language são per-agent (cada agente
-- escolhe seu template default — Mercator usa "respondi cotação", Hodos usa
-- "atualização frete", etc.). Todos os outros 6 fields ficam company.
UPDATE vectraclip.adapter_field_definitions afd
   SET applies_to = 'agent',
       updated_at = now()
  FROM vectraclip.adapter_catalog ac
 WHERE afd.adapter_id = ac.id
   AND ac.slug = 'meta-whatsapp'
   AND afd.field_key IN ('template_id','template_language');

-- template_language: redundante. Cada template Meta já carrega `language` na
-- API (pt_BR / en / en_US). Desativar e fim — template_id select catalog-driven
-- (próxima migration) resolve idioma na origem.
UPDATE vectraclip.adapter_field_definitions afd
   SET is_active = false,
       updated_at = now()
  FROM vectraclip.adapter_catalog ac
 WHERE afd.adapter_id = ac.id
   AND ac.slug = 'meta-whatsapp'
   AND afd.field_key = 'template_language';

-- Verificação inline (RAISE NOTICE só funciona em DO block)
DO $$
DECLARE
  total int;
  company_count int;
  agent_count int;
BEGIN
  SELECT count(*) INTO total FROM vectraclip.adapter_field_definitions;
  SELECT count(*) INTO company_count FROM vectraclip.adapter_field_definitions WHERE applies_to = 'company';
  SELECT count(*) INTO agent_count FROM vectraclip.adapter_field_definitions WHERE applies_to = 'agent';
  RAISE NOTICE '[W11 M1/3] adapter_field_definitions: total=%, company=%, agent=%', total, company_count, agent_count;
END $$;
