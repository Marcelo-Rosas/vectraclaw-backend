-- =============================================================================
-- companies.notification_email — SSOT do destinatário de relatórios por company
-- =============================================================================
-- Contexto (hardcode-auditor 2026-05-20, P1): o Kronos usava
-- DEFAULT_RECIPIENT = "marcelo.rosas@vectracargo.com.br" como fallback literal
-- no .py. Em multi-tenant, um cliente novo sem env receberia o relatório
-- financeiro no e-mail PESSOAL do Marcelo (vazamento de PII + dado de outro
-- tenant). Regra de Ouro #2: o destinatário mora em tabela, não em constante.
--
-- Cadeia de resolução no kronos.py (_resolve_recipient):
--   RECIPIENT explícito na task → companies.notification_email → erro (fail-loud)
-- =============================================================================

ALTER TABLE vectraclip.companies
  ADD COLUMN IF NOT EXISTS notification_email text;

COMMENT ON COLUMN vectraclip.companies.notification_email IS
  'E-mail operacional que recebe relatórios automáticos (Kronos audit, etc.) por padrão. Override por task via RECIPIENT.';

-- Backfill: Vectra Cargo (company dev) recebe o e-mail que ERA o default literal
-- — para a Vectra isso não é vazamento, é o destinatário legítimo.
UPDATE vectraclip.companies
SET notification_email = 'marcelo.rosas@vectracargo.com.br',
    updated_at = now()
WHERE company_id = '01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2'
  AND notification_email IS NULL;

NOTIFY pgrst, 'reload schema';
