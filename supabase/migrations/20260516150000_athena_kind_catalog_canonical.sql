-- =============================================================================
-- Athena Recommendations — kind catalog canonical (resolve drift PR9/#139)
--
-- Contexto:
--   PR2 (#131) criou CHECK constraint com 4 valores incompletos (sobrava
--   diagnose_gap mas faltavam 4 executáveis). PR9 (#139) começou a inserir
--   `diagnose_gap` corretamente, MAS o frontend Zod esperava outros 5
--   valores (`hire_new_agent`, `add_specialty`, `rewrite_system_prompt`,
--   `create_specialty`, `consolidate_agents`), gerando drift triplo:
--
--     DB CHECK  (PR2 #131):  rewrite_system_prompt, diagnose_gap,
--                            suggest_automation, suggest_hire_agent
--     Frontend Zod:          hire_new_agent, add_specialty,
--                            rewrite_system_prompt, create_specialty,
--                            consolidate_agents
--     Backend _REC_VALID_KINDS: igual ao Frontend
--
--   Esta migration consolida em 8 valores canônicos (5 executáveis + 3
--   informativos), permitindo que Athena PMO continue executando o que sabe
--   executar e que diagnose/suggestions informativos coexistam.
--
-- Categorização dos 8 kinds:
--
--   EXECUTÁVEIS (Athena aplica via auto-action após aprovação humana):
--     - hire_new_agent          : criar agent novo (provisioning P2)
--     - add_specialty           : associar specialty a agent
--     - rewrite_system_prompt   : trocar prompt de agent (snapshot histórico)
--     - create_specialty        : criar specialty nova no catálogo
--     - consolidate_agents      : fundir agents redundantes
--
--   INFORMATIVOS (Athena gera, humano lê e decide — sem auto-execução):
--     - diagnose_gap            : output de POST /api/sipoc/diagnose (PR9)
--     - suggest_automation      : sugestão derivada do diagnose
--     - suggest_hire_agent      : sugestão que pode virar hire_new_agent depois
--
-- Compatibilidade preservada:
--   - 3 rows existentes (kind=diagnose_gap) continuam válidas
--   - 1 row existente (kind=rewrite_system_prompt) continua válida
--   - Frontend Zod precisa atualizar pra aceitar os 8 (PR separado)
--   - Backend _REC_VALID_KINDS atualizado no mesmo PR desta migration
-- =============================================================================

-- 1. Drop CHECK antigo (do PR2 #131)
ALTER TABLE vectraclip.athena_recommendations
    DROP CONSTRAINT IF EXISTS athena_recommendations_kind_check;

-- 2. Recriar com os 8 valores canônicos
ALTER TABLE vectraclip.athena_recommendations
    ADD CONSTRAINT athena_recommendations_kind_check
    CHECK (kind = ANY (ARRAY[
        -- Executáveis (Athena auto-aplica após aprovação humana)
        'hire_new_agent'::text,
        'add_specialty'::text,
        'rewrite_system_prompt'::text,
        'create_specialty'::text,
        'consolidate_agents'::text,
        -- Informativos (Athena gera, humano lê)
        'diagnose_gap'::text,
        'suggest_automation'::text,
        'suggest_hire_agent'::text
    ]));

-- 3. Documentar semântica no schema (sobrevive a re-introspect via db pull)
COMMENT ON COLUMN vectraclip.athena_recommendations.kind IS
    'Tipo da recomendação Athena. Catalog canônico em docs/ATHENA-RECOMMENDATIONS.md. '
    'EXECUTÁVEIS (Athena auto-aplica após aprovação humana): hire_new_agent, '
    'add_specialty, rewrite_system_prompt, create_specialty, consolidate_agents. '
    'INFORMATIVOS (relatório/insight sem auto-execução): diagnose_gap, '
    'suggest_automation, suggest_hire_agent.';

COMMENT ON TABLE vectraclip.athena_recommendations IS
    'Recomendações Athena (PMO/PMBOK). status=pending até humano aprovar; '
    'kind divide em 5 executáveis (Athena aplica via auto-action) e 3 '
    'informativos (apenas relatório). Ver docs/ATHENA-RECOMMENDATIONS.md.';
