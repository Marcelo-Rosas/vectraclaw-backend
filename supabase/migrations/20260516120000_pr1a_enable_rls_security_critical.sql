-- =============================================================================
-- PR1A — Habilita RLS nas 3 tabelas críticas identificadas pelo Supabase Advisor
--
-- Alertado em docs/ARCHITECTURE-AS-IS.md (seção 7) e refletido como PR1 da
-- Fase A do docs/ARCHITECTURE-TO-BE.md (Seção 4).
--
-- Tabelas afetadas:
--   1. vectraclip.kronos_rules     — catálogo global de regras (113 rows)
--   2. vectraclip.agent_domains    — catálogo global de domínios (7 rows)
--   3. vectraclip.tasks_block_log  — log interno (0 rows, possível legado)
--
-- Nenhuma das três tem coluna `company_id` — são todas globais ou internas.
-- Padrão: leitura authenticated quando faz sentido pra UI; escrita só
-- service_role (sem policy explícita = só service_role bypassa por design).
--
-- IMPORTANTE: daemons usam SUPABASE_SERVICE_ROLE_KEY → bypassam RLS → não
-- são afetados. Só impede acesso via anon key (anon = não autenticado).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. vectraclip.kronos_rules
--    Catálogo de regras de classificação OFX/Planner usado pelo agente Kronos.
--    SELECT: authenticated (UI admin de regras precisa listar)
--    Escrita: só service_role (mantido via ausência de policy)
-- -----------------------------------------------------------------------------

ALTER TABLE vectraclip.kronos_rules ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "kronos_rules_select_authenticated" ON vectraclip.kronos_rules;

CREATE POLICY "kronos_rules_select_authenticated"
    ON vectraclip.kronos_rules
    FOR SELECT
    TO authenticated
    USING (true);

COMMENT ON POLICY "kronos_rules_select_authenticated" ON vectraclip.kronos_rules IS
    'Catálogo global de regras Kronos — leitura aberta a qualquer authenticated. Escrita só via service_role (sem policy explícita).';


-- -----------------------------------------------------------------------------
-- 2. vectraclip.agent_domains
--    Catálogo global de domínios de skills (finance, logistics, communication,
--    etc.). Alimenta dropdown no /admin/specialties e em agent_specialties.domain.
--    SELECT: authenticated
--    Escrita: só service_role
-- -----------------------------------------------------------------------------

ALTER TABLE vectraclip.agent_domains ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "agent_domains_select_authenticated" ON vectraclip.agent_domains;

CREATE POLICY "agent_domains_select_authenticated"
    ON vectraclip.agent_domains
    FOR SELECT
    TO authenticated
    USING (true);

COMMENT ON POLICY "agent_domains_select_authenticated" ON vectraclip.agent_domains IS
    'Catálogo global de domínios — leitura aberta a qualquer authenticated. Escrita só via service_role.';


-- -----------------------------------------------------------------------------
-- 3. vectraclip.tasks_block_log
--    Log interno de tasks bloqueadas (provável legado — 0 rows hoje).
--    Sem policy = só service_role acessa. Se algum lugar do código tentar
--    ler com client authenticated, vai falhar visivelmente e poderemos
--    decidir: adicionar policy específica ou deprecar a tabela inteira.
-- -----------------------------------------------------------------------------

ALTER TABLE vectraclip.tasks_block_log ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE vectraclip.tasks_block_log IS
    'Log interno de tasks bloqueadas. RLS habilitado sem policies = só service_role acessa. Candidato a deprecar (0 rows há tempo).';
