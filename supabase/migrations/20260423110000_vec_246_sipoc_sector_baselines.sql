-- Migration: SIPOC Sector Baselines
-- Issue: VEC-246
-- Schema: vectraclip

CREATE TABLE IF NOT EXISTS vectraclip.sipoc_sector_baselines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sector_slug TEXT NOT NULL UNIQUE,
    sector_display_name TEXT NOT NULL,
    baseline JSONB NOT NULL,
    source TEXT NOT NULL DEFAULT 'seed',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER set_updated_at_sipoc_sector_baselines
    BEFORE UPDATE ON vectraclip.sipoc_sector_baselines
    FOR EACH ROW EXECUTE FUNCTION vectraclip.handle_updated_at();

ALTER TABLE vectraclip.sipoc_sector_baselines ENABLE ROW LEVEL SECURITY;

CREATE POLICY "sipoc_sector_baselines_select_all"
    ON vectraclip.sipoc_sector_baselines FOR SELECT
    USING (true);

-- Seed: Logística
INSERT INTO vectraclip.sipoc_sector_baselines (sector_slug, sector_display_name, baseline, source)
VALUES (
    'logistica',
    'Logística',
    '{
        "processosSugeridos": [
            {
                "nome": "Coleta de Mercadoria",
                "descricao": "Agendamento e execução da coleta no fornecedor ou porto.",
                "sipocBase": {
                    "suppliers": ["Armadores", "Transportadoras", "Agentes de Carga"],
                    "inputs": ["Packing List", "Invoice", "Booking Confirmation"],
                    "outputs": ["Mercadoria Coletada", "DRAFT do BL"],
                    "customers": ["Importador", "Despachante"]
                },
                "automacaoScoreEstimado": 85
            },
            {
                "nome": "Desembaraço Aduaneiro",
                "descricao": "Trâmites legais e fiscais para liberação da carga.",
                "sipocBase": {
                    "suppliers": ["Receita Federal", "Portos", "Aeroportos"],
                    "inputs": ["DI (Declaração de Importação)", "LI (Licença de Importação)"],
                    "outputs": ["CI (Comprovante de Importação)", "Carga Liberada"],
                    "customers": ["Importador", "Transportadora"]
                },
                "automacaoScoreEstimado": 70
            }
        ],
        "riscosComuns": ["Atrasos por burocracia", "Erros de classificação NCM"],
        "oportunidadesIa": ["Parser automático de documentos aduaneiros", "Predição de tempo de liberação"]
    }'::jsonb,
    'seed'
),
(
    'financeiro',
    'Financeiro',
    '{
        "processosSugeridos": [
            {
                "nome": "Contas a Pagar",
                "descricao": "Gestão de obrigações financeiras e pagamentos a fornecedores.",
                "sipocBase": {
                    "suppliers": ["Fornecedores de Serviço", "Utilidades", "Governo"],
                    "inputs": ["Notas Fiscais", "Boletos", "Contratos"],
                    "outputs": ["Comprovantes de Pagamento", "Fluxo de Caixa Atualizado"],
                    "customers": ["Diretoria", "Contabilidade"]
                },
                "automacaoScoreEstimado": 95
            }
        ],
        "riscosComuns": ["Pagamentos em duplicidade", "Fraudes em boletos"],
        "oportunidadesIa": ["OCR para extração de dados de boletos", "Detecção de anomalias em pagamentos"]
    }'::jsonb,
    'seed'
)
ON CONFLICT (sector_slug) DO UPDATE SET
    sector_display_name = EXCLUDED.sector_display_name,
    baseline = EXCLUDED.baseline;
