-- Migration: gymsite_seed
-- Seed do agente GymSite no catálogo VectraClaw.
-- Provisiona: agent_domains + agent_specialties + agents (per-company) +
-- operation_types_catalog + agent_specialty_configs.
--
-- AGENT_ID GymSite: 917e51b3-9413-4000-8000-000000000006
-- UUID v4 válido, temático (gym), grepável. NUNCA alterar.
--
-- Schema: vectraclip (NUNCA public)
-- Idempotente: ON CONFLICT DO NOTHING em todos os inserts

-- =============================================================================
-- 1. Domain 'prospeccao' (novo)
-- =============================================================================

INSERT INTO vectraclip.agent_domains (id, name, description, icon, color, display_order, is_active)
VALUES (
      'prospeccao',
      'Prospecção & Mercado',
      'Monitoramento de abertura de CNPJs, análise de localização, due diligence de ponto comercial e ROI de expansão.',
      'target',
      'text-green-600',
      40,
      true
  )
ON CONFLICT (id) DO NOTHING;

-- =============================================================================
-- 2. Specialty 'gymsite-prospect'
-- =============================================================================

INSERT INTO vectraclip.agent_specialties (
      id, slug, name, domain, description, compatible_roles,
      system_prompt_template, config_schema, is_active
  )
VALUES (
      'gymsite-prospect',
      'gymsite-prospect',
      'GymSite Prospect Monitor',
      'prospeccao',
      'Monitora abertura de CNPJs com CNAE 9313-1/00 (academias), qualifica leads com score automático e aciona pipeline de contato via Navi/WhatsApp. Delega pesquisa de mercado ao Hermes/Nous via API Server.',
      ARRAY['executor'],
      $PROMPT$# GymSite — Agente de Prospecção de Academias

  Você é o GymSite, especialista em prospecção de academias recém-abertas.
  Mitologia: sem mitologia — nome técnico do produto.

  ## Responsabilidade principal

  Monitorar o dump mensal da Receita Federal, identificar CNPJs com
  CNAE 9313-1/00 abertos nos últimos N dias, qualificar cada lead com
  score 0-100 e acionar o pipeline de contato.

  ## Fontes de dados

  - Dump mensal RFB: `dados.rfb.gov.br/CNPJ/dados_abertos_cnpj/`
- BrasilAPI: `brasilapi.com.br/api/cnpj/v1/{cnpj}` (enriquecimento)
  - Hermes/Nous API Server (:8080): pesquisa web, Google Maps, IBGE

  ## Score de qualificação (0-100)

- Aberto há ≤30 dias: +25
  - Tem telefone E email: +20
  - Capital social ≥ R$30k: +15
  - Município na lista de targets: +15
  - É matriz (não filial): +7
  - Optante pelo Simples: +8
  - Tem nome fantasia: +10

## Status

  - HOT: score > 70 → aciona Navi WhatsApp imediatamente
  - WARM: 40-70 → entra na fila de contato semanal
  - COLD: < 40 → registra para análise futura
  $PROMPT$,
      '{
          "type": "object",
          "properties": {
              "estados_alvo": {
                  "type": "array",
                  "items": {"type": "string"},
                  "description": "UFs para monitorar, ex: [SP, RJ, MG]. Vazio = todos.",
                  "default": []
              },
              "janela_dias": {
                  "type": "integer",
                  "description": "Janela de abertura em dias",
                  "default": 30
              },
              "min_capital_social": {
                  "type": "number",
                  "description": "Capital social mínimo em R$ para incluir no resultado",
                  "default": 0
              },
              "municipios_alvo": {
                  "type": "array",
                  "items": {"type": "string"},
                  "description": "Lista de municípios prioritários",
                  "default": []
              }
          }
      }',
      true
  )
ON CONFLICT (id) DO NOTHING;

-- =============================================================================
-- 3. Operation types no catálogo
-- =============================================================================

INSERT INTO vectraclip.operation_types_catalog
    (operation_type, label, description, default_agent_id, routing_score, is_active)
VALUES
    (
          'gymsite-prospect-scan',
          'GymSite: Varredura de Prospecção',
          'Baixa dump mensal RFB, filtra CNAE 9313-1/00, qualifica leads e persiste em vectraclip.prospects.',
          '917e51b3-9413-4000-8000-000000000006',
          90,
          true
      ),
    (
          'gymsite-enrich-lead',
          'GymSite: Enriquecer Lead',
          'Enriquece um prospect com oracle-research (presença digital, avaliações, redes sociais).',
          '917e51b3-9413-4000-8000-000000000006',
          70,
          true
      ),
    (
          'gymsite-location-roi',
          'GymSite: ROI de Localização',
          'Análise de ROI de ponto comercial: aluguel m², densidade de concorrentes, dados demográficos IBGE.',
          '917e51b3-9413-4000-8000-000000000006',
          80,
          true
      )
ON CONFLICT (operation_type) DO NOTHING;

-- =============================================================================
-- 4. Agente GymSite (per-company via DO loop)
-- =============================================================================

DO $$
DECLARE rec RECORD;
BEGIN
    FOR rec IN SELECT id FROM vectraclip.companies LOOP
        INSERT INTO vectraclip.agents (
              id,
              company_id,
              name,
              role,
              description,
              specialty,
              is_active,
              is_daemon,
              adapter_type
          ) VALUES (
              '917e51b3-9413-4000-8000-000000000006',
              rec.id,
              'GymSite',
              'executor',
              'Agente de prospecção de academias. Monitora abertura de CNPJs CNAE 9313-1/00, qualifica leads e aciona pipeline de contato via Navi. Delega pesquisa ao Hermes/Nous.',
              'gymsite-prospect',
              true,
              false,  -- não é daemon contínuo: roda via cron Hermes/Nous
            'internal'
          )
        ON CONFLICT (id, company_id) DO NOTHING;
    END LOOP;
END $$;

-- =============================================================================
-- 5. agent_specialty_configs (vincula GymSite → gymsite-prospect)
-- =============================================================================

DO $$
DECLARE rec RECORD;
BEGIN
    FOR rec IN SELECT id FROM vectraclip.companies LOOP
        INSERT INTO vectraclip.agent_specialty_configs (
              agent_id,
              company_id,
              specialty_id,
              field_values_json,
              is_active
          ) VALUES (
              '917e51b3-9413-4000-8000-000000000006',
              rec.id,
              'gymsite-prospect',
              '{"estados_alvo": [], "janela_dias": 30, "min_capital_social": 0, "municipios_alvo": []}',
              true
          )
        ON CONFLICT (agent_id, company_id, specialty_id) DO NOTHING;
    END LOOP;
END $$;

-- =============================================================================
-- 6. Atualiza src/agent_ids.py (comentário de referência — fazer manualmente)
-- =============================================================================
-- GYMSITE_AGENT_ID = '917e51b3-9413-4000-8000-000000000006'
-- Adicionar em src/agent_ids.py após DAEDALUS_AGENT_ID
-- e incluir em ALL_AGENT_IDS
