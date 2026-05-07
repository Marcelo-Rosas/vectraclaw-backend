-- =============================================================================
-- VEC-XXX — research_templates
-- Tabela editável de templates de prompt para a specialty oracle-research.
-- company_id NULL = template global (default herdado por todos os tenants).
-- company_id = x  = template específico do tenant (override).
-- =============================================================================

CREATE TABLE IF NOT EXISTS vectraclip.research_templates (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      uuid REFERENCES vectraclip.companies(company_id) ON DELETE CASCADE,
    slug            text NOT NULL,
    name            text NOT NULL,
    description     text,
    prompt_template text NOT NULL,
    output_sections jsonb NOT NULL DEFAULT '[]'::jsonb,
    default_urls    jsonb NOT NULL DEFAULT '[]'::jsonb,
    require_review  boolean NOT NULL DEFAULT true,
    active          boolean NOT NULL DEFAULT true,
    created_at      timestamp with time zone NOT NULL DEFAULT now(),
    updated_at      timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT research_templates_slug_unique UNIQUE NULLS NOT DISTINCT (company_id, slug)
);

ALTER TABLE vectraclip.research_templates OWNER TO postgres;

COMMENT ON TABLE  vectraclip.research_templates IS 'Templates de prompt para a specialty oracle-research. company_id NULL = template global default.';
COMMENT ON COLUMN vectraclip.research_templates.slug            IS 'Identificador estável: transportadora, embarcador, concorrente, custom, ...';
COMMENT ON COLUMN vectraclip.research_templates.prompt_template IS 'Template Jinja-like com placeholders: {{empresa}} {{cnpj}} {{cnpj_data}} {{urls}} {{tipo}}';
COMMENT ON COLUMN vectraclip.research_templates.output_sections IS 'Array de seções esperadas no relatório, ex: ["perfil","decisores","sipoc","score_vectra","linkedin_ads","articles","sintese_abordagem"]';
COMMENT ON COLUMN vectraclip.research_templates.default_urls    IS 'Lista de placeholders de URL que o formulário deve pedir, ex: ["website","linkedin_company","instagram"]';

CREATE INDEX IF NOT EXISTS idx_research_templates_company
    ON vectraclip.research_templates (company_id)
    WHERE company_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_research_templates_global
    ON vectraclip.research_templates (slug)
    WHERE company_id IS NULL;

CREATE OR REPLACE TRIGGER set_updated_at_research_templates
    BEFORE UPDATE ON vectraclip.research_templates
    FOR EACH ROW EXECUTE FUNCTION vectraclip.handle_updated_at();

-- =============================================================================
-- Seed de templates GLOBAIS (company_id = NULL)
-- ON CONFLICT permite re-rodar a migration sem duplicar.
-- =============================================================================

INSERT INTO vectraclip.research_templates
    (company_id, slug, name, description, prompt_template, output_sections, default_urls, require_review, active)
VALUES
-- ---------------------------------------------------------------------------
-- 1) transportadora — pesquisa completa multi-fonte (7 seções)
-- ---------------------------------------------------------------------------
(
    NULL,
    'transportadora',
    'Pesquisa completa de transportadora',
    'Mapeamento profundo de transportadora: perfil, decisores, SIPOC, score de automação Vectra, biblioteca LinkedIn Ads, articles publicados e síntese para abordagem comercial.',
    $template$Pesquise {{empresa}} (transportadora{{#cnpj}}, CNPJ {{cnpj}}{{/cnpj}}{{#cidade}}, {{cidade}}{{/cidade}}{{#uf}} {{uf}}{{/uf}}). Use as URLs primárias informadas em `documents` como fontes preferenciais.

Entregue relatório COMPLETO em PT-BR com as seções abaixo.

SEÇÃO 1 — Perfil da Empresa: nome legal, CNPJ, fundação, sede, filiais, frota, modalidades, certificações, faturamento estimado.

SEÇÃO 2 — Decisores: mapeie nome, cargo, LinkedIn, sinais de autoridade sobre contratação de frete. Priorize Diretor Comercial, Gerente de Logística, Gerente de Frotas, CEO/Sócio. Inclua FONTE de cada informação.

SEÇÃO 3 — Estrutura Operacional para SIPOC: processos identificados (coleta, transporte, entrega, gerenciamento de risco, roteirização, faturamento). Para cada processo: fornecedores prováveis, insumos, outputs, clientes internos e externos.

SEÇÃO 4 — Score de Automação Vectra para vagas publicadas recentemente. Para cada vaga: calcule score 0–100 usando rubrica Vectra v1: Repetitividade +40, Volume de dados +15, Criticidade tolerante a erro +15, Ambiguidade -20, Aprovação Física obrigatória -10. Retorne: score, breakdown por critério, justificativa, potencial_vectra alto/médio/baixo.

SEÇÃO 5 — Biblioteca de Anúncios LinkedIn: o que está sendo anunciado, público-alvo, mensagem principal, frequência, sinais de investimento em captação.

SEÇÃO 6 — Articles e Publicações: temas dos artigos publicados, quem assina, o que revela sobre cultura e prioridades estratégicas.

SEÇÃO 7 — Síntese para Abordagem Vectra: (a) dor logística mais provável que a Vectra pode resolver (b) melhor decisor para abordar e canal preferencial (c) gancho de abertura recomendado.
$template$,
    '["perfil","decisores","sipoc","score_vectra","linkedin_ads","articles","sintese_abordagem"]'::jsonb,
    '["website","linkedin_company","linkedin_posts","linkedin_ads","linkedin_articles","instagram"]'::jsonb,
    true,
    true
),
-- ---------------------------------------------------------------------------
-- 2) embarcador — perfil de embarcador potencial
-- ---------------------------------------------------------------------------
(
    NULL,
    'embarcador',
    'Perfil de embarcador potencial',
    'Mapeamento de embarcador: volume de carga, modais, fornecedores atuais, decisores de logística e gancho de abordagem para a Vectra Cargo.',
    $template$Pesquise {{empresa}} (embarcador potencial{{#cnpj}}, CNPJ {{cnpj}}{{/cnpj}}{{#cidade}}, {{cidade}}{{/cidade}}{{#uf}} {{uf}}{{/uf}}). Use as URLs primárias informadas em `documents` como fontes preferenciais.

Entregue relatório em PT-BR com as seções:

SEÇÃO 1 — Perfil: nome legal, CNPJ, setor, fundação, sede, faturamento estimado, volume de produção/distribuição.

SEÇÃO 2 — Volume e Frequência de Cargas: tipos de carga (geral, refrigerada, perigosa, especial), volume mensal estimado, frequência (diário, semanal, sazonal), origens e destinos principais.

SEÇÃO 3 — Modais Utilizados: rodoviário, marítimo, aéreo, multimodal. Sinais de operação própria vs terceirizada.

SEÇÃO 4 — Fornecedores de Frete Atuais: transportadoras parceiras conhecidas (sites institucionais, releases, redes). Sinais de descontentamento ou troca recente.

SEÇÃO 5 — Decisores de Logística: nome, cargo, LinkedIn. Priorize Diretor de Operações, Gerente de Logística, Supply Chain, Compras. Inclua FONTE.

SEÇÃO 6 — Gancho de Abordagem Vectra: (a) dor logística provável (b) decisor a abordar e canal (c) abertura recomendada.
$template$,
    '["perfil","volume_carga","modais","fornecedores_atuais","decisores","gancho_abordagem"]'::jsonb,
    '["website","linkedin_company","linkedin_posts","instagram"]'::jsonb,
    true,
    true
),
-- ---------------------------------------------------------------------------
-- 3) concorrente — análise de concorrente
-- ---------------------------------------------------------------------------
(
    NULL,
    'concorrente',
    'Análise de concorrente',
    'Mapeamento de concorrente direto: posicionamento, preços públicos, parcerias, gaps e nível de ameaça competitiva.',
    $template$Pesquise {{empresa}} como CONCORRENTE direto da Vectra Cargo{{#cnpj}} (CNPJ {{cnpj}}){{/cnpj}}. Use as URLs primárias informadas em `documents` como fontes preferenciais.

Entregue análise em PT-BR com as seções:

SEÇÃO 1 — Perfil: nome legal, sede, anos de operação, frota, modalidades, certificações, faturamento estimado, número de funcionários.

SEÇÃO 2 — Posicionamento de Mercado: proposta de valor, segmentos atendidos, tipos de cliente, regiões de atuação, diferenciais comunicados.

SEÇÃO 3 — Preços Públicos: tabelas, simuladores, propostas vazadas em redes sociais ou releases. Pricing implícito por vaga, faixa salarial.

SEÇÃO 4 — Parcerias e Clientes Visíveis: clientes citados em cases, releases, LinkedIn (logos), parcerias estratégicas (seguradoras, GR, tecnologia).

SEÇÃO 5 — Gaps e Vulnerabilidades: queixas de cliente em redes/Reclame Aqui, processos trabalhistas relevantes, alta rotatividade, sinais de problemas operacionais.

SEÇÃO 6 — Nível de Ameaça: classifique como BAIXA / MÉDIA / ALTA. Justifique com base em sobreposição de ICP, capacidade de execução e sinais de crescimento.
$template$,
    '["perfil","posicionamento","precos_publicos","parcerias","gaps","ameaca"]'::jsonb,
    '["website","linkedin_company","linkedin_posts","linkedin_articles","instagram","reclame_aqui"]'::jsonb,
    true,
    true
),
-- ---------------------------------------------------------------------------
-- 4) custom — template em branco
-- ---------------------------------------------------------------------------
(
    NULL,
    'custom',
    'Pesquisa customizada',
    'Template vazio — escreva seu próprio prompt de pesquisa.',
    $template$Pesquise {{empresa}}{{#cnpj}} (CNPJ {{cnpj}}){{/cnpj}} usando as URLs primárias em `documents` como fontes preferenciais.

(Substitua este texto pelo seu prompt customizado.)
$template$,
    '[]'::jsonb,
    '["website"]'::jsonb,
    true,
    true
)
ON CONFLICT (company_id, slug) DO NOTHING;
