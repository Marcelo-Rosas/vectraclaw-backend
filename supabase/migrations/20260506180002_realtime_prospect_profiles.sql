-- =============================================================================
-- VEC-XXX — Habilita Supabase Realtime em prospect_profiles
-- Frontend assina mudanças (research_status, research_progress) sem WS custom.
-- =============================================================================

DO $$
BEGIN
    -- Adiciona prospect_profiles à publication supabase_realtime (idempotente)
    IF NOT EXISTS (
        SELECT 1
        FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime'
          AND schemaname = 'vectraclip'
          AND tablename = 'prospect_profiles'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE vectraclip.prospect_profiles;
    END IF;

    -- Idem para research_templates (frontend lista atualiza em tempo real
    -- quando admin cria/edita templates em outra aba)
    IF NOT EXISTS (
        SELECT 1
        FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime'
          AND schemaname = 'vectraclip'
          AND tablename = 'research_templates'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE vectraclip.research_templates;
    END IF;
END $$;

-- REPLICA IDENTITY FULL é necessário se a UI quiser receber o "old" record
-- nas mensagens de UPDATE. Default é DEFAULT (só PK). Mantemos default para
-- economizar bandwidth — o frontend só precisa do "new".
