-- W13 MVP — Mercator quotation handler (humano-in-loop)
--
-- Adiciona coluna `cubage_density_kg_m3` em companies pra resolver H3 do
-- hardcode-auditor (densidade tributária de cubagem hardcoded como 300 no
-- código). Cada empresa pode usar densidade diferente (IATA aéreo 167,
-- ANTT rodoviário 250-300, marítimo 1000 kg/m³).
--
-- Default 300 (NTC&L ABNT rodoviário pesado), que é o valor que o NAVI
-- `buscarCotacao` usa hoje. Operação cliente: ajustar via UI admin quando
-- houver tela /admin/freight-settings (W14+).

ALTER TABLE vectraclip.companies
    ADD COLUMN IF NOT EXISTS cubage_density_kg_m3 INTEGER NOT NULL DEFAULT 300
    CHECK (cubage_density_kg_m3 > 0 AND cubage_density_kg_m3 <= 2000);

COMMENT ON COLUMN vectraclip.companies.cubage_density_kg_m3 IS
    'Densidade tributária de cubagem em kg/m³. Default 300 (ANTT/NTC rodoviário). '
    'Aéreo IATA usa 167. Marítimo 1000. Cada empresa pode customizar conforme '
    'modal predominante. Consumido por src/services/freight/calculator.py:calculate_freight_cubage.';

-- Verificação shadow-replay-safe (pattern do PR #222 hotfix)
DO $$
DECLARE
    v_companies_with_density int;
BEGIN
    SELECT count(*) INTO v_companies_with_density
        FROM vectraclip.companies WHERE cubage_density_kg_m3 = 300;
    RAISE NOTICE 'W13 freight: companies com cubage_density_kg_m3=300 (default) = %',
        v_companies_with_density;
END $$;

NOTIFY pgrst, 'reload schema';
