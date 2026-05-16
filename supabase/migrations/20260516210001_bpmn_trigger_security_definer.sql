-- Hotfix Daedalus PR E — trigger bpmn_snapshot_version precisa SECURITY DEFINER
--
-- Bug: smoke do PR E falhou no PATCH com erro:
--   {"detail":"permission denied for table bpmn_diagram_versions (42501)"}
--
-- Causa: o trigger BEFORE UPDATE em bpmn_diagrams faz INSERT em
-- bpmn_diagram_versions. Quando o UPDATE vem via REST de um user
-- `authenticated`, o trigger roda no mesmo contexto — mas authenticated tem
-- só GRANT SELECT em bpmn_diagram_versions (intencional: "INSERT só via trigger").
-- Sem privilégio elevado, o INSERT do trigger é rejeitado.
--
-- Fix: SECURITY DEFINER permite o trigger rodar com privilégios do owner
-- (postgres). search_path fixo (vectraclip, pg_catalog) previne search_path
-- hijack — recomendação Supabase.
--
-- Idempotente via CREATE OR REPLACE FUNCTION.

CREATE OR REPLACE FUNCTION vectraclip.bpmn_snapshot_version()
RETURNS TRIGGER
SECURITY DEFINER
SET search_path = vectraclip, pg_catalog
AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.diagram_json IS DISTINCT FROM NEW.diagram_json THEN
    INSERT INTO vectraclip.bpmn_diagram_versions (diagram_id, version, diagram_json)
    VALUES (OLD.id, OLD.version, OLD.diagram_json);
    NEW.version := OLD.version + 1;
  END IF;
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

NOTIFY pgrst, 'reload schema';
