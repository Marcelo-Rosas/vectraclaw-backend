-- Add coluna mission em vectraclip.companies
--
-- Hoje POST /api/companies retorna `mission` echoed do payload mas nunca
-- persiste (api.py:3833 — "mission: payload.mission" só copia, não vai pro DB).
-- Resposta mente. Esta migration corrige: cria a coluna pra persistência real.
--
-- Trigger: PR self-service signup Vectra Cargo (2026-05-17).

ALTER TABLE vectraclip.companies
  ADD COLUMN IF NOT EXISTS mission TEXT;

NOTIFY pgrst, 'reload schema';
