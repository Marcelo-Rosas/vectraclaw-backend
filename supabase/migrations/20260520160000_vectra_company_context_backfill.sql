-- =============================================================================
-- Backfill companies.context_json (Vectra dev) — Oracle context catalog-driven
-- =============================================================================
-- Contexto (hardcode-auditor P1): oracle.py fixava _VECTRA_CONTEXT (descrição
-- "Vectra Cargo transportadora rodoviária") como FALLBACK universal de contexto
-- de empresa — aplicado a TODO tenant. Regra de Ouro #2: contexto da empresa
-- mora em companies.context_json, não em constante no .py.
--
-- O código passou a usar fallback NEUTRO (_GENERIC_COMPANY_CONTEXT). Para a
-- company dev não perder o guard "modal rodoviário" que vinha do hardcode,
-- gravamos o perfil em context_json.research_summary (lido por
-- oracle._get_company_context).
-- =============================================================================

UPDATE vectraclip.companies
SET context_json = jsonb_set(
      coalesce(context_json, '{}'::jsonb),
      '{research_summary}',
      to_jsonb(
        'Vectra Cargo é uma transportadora brasileira de modal EXCLUSIVAMENTE '
        'RODOVIÁRIO. Não opera aéreo, marítimo, ferroviário ou intermodal. Atua '
        'com frota própria e terceirizada no transporte de cargas em território '
        'nacional. Ao analisar processos, considere apenas o modal rodoviário e '
        'desconsidere referências a outros modais.'::text
      ),
      true
    ),
    updated_at = now()
WHERE company_id = '01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2'
  AND (context_json IS NULL OR NOT (context_json ? 'research_summary'));

NOTIFY pgrst, 'reload schema';
