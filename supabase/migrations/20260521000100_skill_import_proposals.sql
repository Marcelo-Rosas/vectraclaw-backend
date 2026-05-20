-- =============================================================================
-- Bloco A / Migration 2 — staging skill_import_proposals (aditiva, colateral 0)
-- =============================================================================
-- ESPELHEI ANTES (Regra #1 / P7):
--   information_schema.tables → skill_import_proposals NÃO existe (2026-05-20).
--   gymsite_seed.sql (idempotência + prefixo vectraclip.), pr1a (RLS catálogo
--   global USING(true)), contrato §3.2 (proposta → agent_specialties draft).
--
-- Cliente externo NÃO roda migration → catálogo de skills recebe via UI/API em
-- runtime. Decisão travada: NÃO adicionar company_id a agent_specialties (viola
-- §0 — catálogos GLOBAIS). Caminho = staging por company → curadoria → promove
-- pra agent_specialties status=draft. company_id aqui é só AUDIT (proponente).
--
-- RLS (decisão #1): isolamento por company é na API (service_role +
-- validate_jwt_company_id, igual create_task), NÃO via claim em RLS. Espelha
-- pr1a (catálogos usam USING(true) p/ authenticated). Default seguro do handoff.
-- =============================================================================

CREATE TABLE IF NOT EXISTS vectraclip.skill_import_proposals (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id             uuid NOT NULL,                 -- proponente (audit)
    source                 text NOT NULL CHECK (source IN ('import_csv', 'markdown_upload')),
    status                 text NOT NULL DEFAULT 'queued'
                             CHECK (status IN ('queued', 'curating', 'promoted', 'dismissed')),
    raw_input              text,
    name                   text,
    slug                   text,
    domain                 text,
    description            text,
    compatible_roles       text[] NOT NULL DEFAULT '{}',
    system_prompt_template text,
    config_schema          jsonb,                          -- inclui operation_types[]
    promoted_specialty_id  text REFERENCES vectraclip.agent_specialties(id),
    dismissed_reason       text,
    created_by             uuid,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_skill_import_proposals_company
  ON vectraclip.skill_import_proposals(company_id);
CREATE INDEX IF NOT EXISTS idx_skill_import_proposals_status
  ON vectraclip.skill_import_proposals(status);

ALTER TABLE vectraclip.skill_import_proposals ENABLE ROW LEVEL SECURITY;

-- RLS espelha pr1a (catálogo): leitura p/ authenticated; isolamento real na API.
CREATE POLICY "skill_import_proposals_select_authenticated"
  ON vectraclip.skill_import_proposals
  FOR SELECT TO authenticated USING (true);

GRANT SELECT ON vectraclip.skill_import_proposals TO authenticated;
GRANT ALL ON vectraclip.skill_import_proposals TO service_role;

DO $$ BEGIN RAISE NOTICE 'skill_import_proposals criada (staging import skills)'; END $$;

NOTIFY pgrst, 'reload schema';
