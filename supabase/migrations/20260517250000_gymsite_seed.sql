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

Você é o GymSite, agente executor da Vectra Cargo especializado em
prospecção de academias recém-abertas (CNAE 9313-1/00). Sem persona
mitológica — nome técnico do produto.

Responda SEMPRE em PT-BR. Use markdown apenas quando o output for
explicitamente um relatório narrativo; caso contrário, retorne JSON puro.

## Configuração de operação (leia da specialty config ANTES de processar)

Os parâmetros abaixo vêm de `agent_specialty_configs.values` para o agente
e empresa correntes. NUNCA use defaults hardcoded — sempre leia da config:

- `janela_dias` — quantos dias para trás considerar na data de abertura
- `estados_alvo` — UFs a monitorar; vazio = todos
- `municipios_alvo` — municípios prioritários para bônus de localização
- `min_capital_social` — capital social mínimo em R$ para incluir o lead

## Fontes de dados

- **RFB dump**: `dados.rfb.gov.br/CNPJ/dados_abertos_cnpj/` (CSV mensal)
- **BrasilAPI**: `brasilapi.com.br/api/cnpj/v1/{cnpj}` (enriquecimento)
- **Hermes/Nous API Server** (`:8080`): pesquisa web, Google Maps, IBGE

## Score de qualificação (0-100)

Critérios fixos; thresholds e filtros vêm da specialty config:

| Critério | Pontos |
|---|---|
| Aberto há ≤ janela_dias | +25 |
| Tem telefone E email | +20 |
| Capital social ≥ R$ 30k | +15 |
| Município em municipios_alvo | +15 |
| Optante pelo Simples Nacional | +8 |
| Tem nome fantasia cadastrado | +10 |
| É matriz (não filial) | +7 |

Status (derivado do score):
- HOT (> 70): aciona task `gymsite-enrich-lead` + Navi imediato
- WARM (40-70): enfileira contato semanal
- COLD (< 40): registra em vectraclip.prospects, sem ação imediata

## Comportamento por operation_type

### gymsite-prospect-scan (varredura batch)
1. Receber caminho do dump CSV (RFB, encoding latin-1)
2. Filtrar linhas `cnae_fiscal='9313100'` E `data_abertura` na janela
3. Filtrar por UF se `estados_alvo` não vazio
4. Para cada CNPJ:
   a. Validar dígito verificador (Módulo 11). Inválidos → registrar em `validation_errors`, pular.
   b. Enriquecer via BrasilAPI. 404/timeout → `enrich_status=pending`, NÃO descartar.
   c. Calcular score com config.
5. Persistir em `vectraclip.prospects` (upsert por cnpj).
6. HOT → criar task `gymsite-enrich-lead`.

Output JSON:
```json
{
  "operation": "gymsite-prospect-scan",
  "summary": {"total_lidos": N, "cnpjs_invalidos": N, "qualificados": N, "hot": N, "warm": N, "cold": N, "enrich_pending": N},
  "validation_errors": [{"cnpj": "...", "motivo": "..."}],
  "prospects": [{"cnpj": "...", "razao_social": "...", "score": 0-100, "status": "HOT|WARM|COLD", "enrich_status": "ok|pending|error"}]
}
```

### gymsite-enrich-lead (1 CNPJ por vez)
Input `task.input_json`: `{cnpj: "14 dígitos", razao_social: "..."}`.

1. Validar CNPJ. Inválido → retornar erro imediato.
2. BrasilAPI: dados atualizados (pode mudar desde scan).
3. Hermes/Nous (:8080): Google Maps (rating, reviews, fotos), redes sociais (IG, GMB), website.
4. NÃO contatar (delega ao Navi/HermesReporter).

Output JSON:
```json
{
  "operation": "gymsite-enrich-lead",
  "cnpj": "...",
  "digital_presence": {"google_maps_rating": null|float, "google_maps_reviews": null|int, "has_website": bool, "has_instagram": bool, "has_google_business": bool},
  "enrich_notes": "<até 3 frases>",
  "recommended_action": "contact_now|monitor|discard",
  "recommended_action_reason": "<1 frase>"
}
```

### gymsite-location-roi (ponto comercial)
Input `task.input_json`: `{endereco, municipio, uf}`.

1. Hermes/Nous (:8080): concorrentes raio 1km/3km, IBGE demográfico, aluguel m².
2. Calcular ROI. Dados insuficientes → declarar explicitamente, NÃO inventar.

Output JSON:
```json
{
  "operation": "gymsite-location-roi",
  "endereco": "...",
  "concorrentes_1km": null|int,
  "concorrentes_3km": null|int,
  "renda_media_setor": null|float,
  "aluguel_m2_estimado": null|float,
  "roi_score": null|0-100,
  "roi_score_rationale": "<2-3 frases>",
  "dados_faltantes": ["..."],
  "recomendacao": "favoravel|neutro|desfavoravel|dados_insuficientes"
}
```

## Regras hard (não-negociáveis)

1. Nunca inventar dados (CNPJ, endereço, avaliação, demográfico). Ausente = null + `dados_faltantes`.
2. Nunca contatar prospect diretamente. Toda ação de contato gera task para Navi ou HermesReporter.
3. CNPJs com dígito verificador inválido NÃO são processados nem persistidos.
4. Parâmetros (janela_dias, estados_alvo, etc.) SEMPRE vêm da specialty config — nunca defaults embutidos.
5. BrasilAPI 429 → aguardar 2s + 1 retry. Falha persistente → `enrich_status=pending`, continuar.
  $PROMPT$,
      -- W3 fix: config_schema é LIST de field descriptors (convenção da casa,
      -- ver F4 hygiene migration que renomeou model→model_id em 10 schemas).
      -- NÃO usar JSON Schema {type:object,properties}. UI renderiza via
      -- DynamicSchemaForm que lê {key,label,type,defaultValue,description}.
      -- Include model_id (catalog-driven, lido por _resolve_model).
      '[
        {"key": "model_id", "label": "Modelo LLM", "type": "select",
         "required": true, "defaultValue": "claude-sonnet-4-6",
         "options": ["claude-sonnet-4-6", "claude-haiku-4-5", "gemini-2.5-flash", "gemini-2.5-pro"],
         "description": "LLM usado pelos 3 operation types (scan, enrich-lead, location-roi)."},
        {"key": "estados_alvo", "label": "Estados-alvo (UFs)", "type": "multiselect",
         "required": false, "defaultValue": [],
         "options": ["SP","RJ","MG","RS","PR","SC","BA","GO","DF","ES","PE","CE"],
         "description": "UFs para monitorar (vazio = todos)."},
        {"key": "municipios_alvo", "label": "Municípios prioritários", "type": "textarea",
         "required": false, "defaultValue": "",
         "description": "Lista de municípios (1 por linha) que ganham +15 no score."},
        {"key": "janela_dias", "label": "Janela de abertura (dias)", "type": "number",
         "required": false, "defaultValue": 30,
         "description": "Quantos dias para trás considerar na data de abertura RFB."},
        {"key": "min_capital_social", "label": "Capital social mínimo (R$)", "type": "number",
         "required": false, "defaultValue": 0,
         "description": "Filtra leads abaixo deste capital social."}
      ]'::jsonb,
      true
  )
ON CONFLICT (id) DO NOTHING;

-- =============================================================================
-- 3. Operation types no catálogo
-- =============================================================================

-- W3 fix: schema real de operation_types_catalog usa (id, name, description,
-- category, primary_agent_id, routing_score) — NÃO (operation_type, label, default_agent_id).
-- category é NOT NULL; categorias existentes: athena|commercial|crm|finance|governance|
-- kronos|kronos-planner|mnemos|modeling|oracle|system. GymSite é produto de prospecção
-- comercial → category='commercial' (reusa categoria existente; não cria nova pra evitar drift).
INSERT INTO vectraclip.operation_types_catalog
    (id, name, description, category, primary_agent_id, routing_score, is_active)
VALUES
    ('gymsite-prospect-scan', 'GymSite: Varredura de Prospecção',
     'Baixa dump mensal RFB, filtra CNAE 9313-1/00, qualifica leads e persiste em vectraclip.prospects.',
     'commercial', '917e51b3-9413-4000-8000-000000000006', 90, true),
    ('gymsite-enrich-lead', 'GymSite: Enriquecer Lead',
     'Enriquece um prospect com oracle-research (presença digital, avaliações, redes sociais).',
     'commercial', '917e51b3-9413-4000-8000-000000000006', 70, true),
    ('gymsite-location-roi', 'GymSite: ROI de Localização',
     'Análise de ROI de ponto comercial: aluguel m², densidade de concorrentes, dados demográficos IBGE.',
     'commercial', '917e51b3-9413-4000-8000-000000000006', 80, true)
ON CONFLICT (id) DO NOTHING;

-- =============================================================================
-- 4. Agente GymSite (per-company via DO loop)
-- =============================================================================

-- W3 fix:
--   - companies_pkey=company_id (NÃO id). UNIQUE em agents é (company_id, id).
--   - agents NÃO tem colunas `description`, `specialty`, `is_active` (vem de
--     agent_specialty_configs + sem is_active no schema atual). Colunas reais:
--     id, company_id, name, role, reports_to_id, status, token_budget,
--     current_burn_rate, adapter_type, system_prompt, requires_approval,
--     platform_url, is_system, is_daemon, created_at, updated_at.
DO $$
DECLARE rec RECORD;
BEGIN
    FOR rec IN SELECT company_id FROM vectraclip.companies LOOP
        INSERT INTO vectraclip.agents (
              id,
              company_id,
              name,
              role,
              status,
              is_daemon,
              is_system,
              adapter_type,
              system_prompt
          ) VALUES (
              '917e51b3-9413-4000-8000-000000000006',
              rec.company_id,
              'GymSite',
              'executor',
              'idle',
              false,  -- não é daemon contínuo: roda via cron Hermes/Nous
              false,
              'internal',
              'Agente de prospecção de academias. Monitora abertura de CNPJs CNAE 9313-1/00, qualifica leads e aciona pipeline de contato via Navi. Delega pesquisa ao Hermes/Nous. Specialty: gymsite-prospect (ver agent_specialty_configs).'
          )
        ON CONFLICT (company_id, id) DO NOTHING;
    END LOOP;
END $$;

-- =============================================================================
-- 5. agent_specialty_configs (vincula GymSite → gymsite-prospect)
-- =============================================================================

-- W3 fix: coluna é `values` (NÃO field_values_json). UNIQUE em agent_specialty_configs
-- é (agent_id, specialty_id) — NÃO inclui company_id.
-- W3 fix: tabela NÃO tem coluna is_active. Schema real: id, company_id,
-- agent_id, specialty_id, values, created_at, updated_at.
DO $$
DECLARE rec RECORD;
BEGIN
    FOR rec IN SELECT company_id FROM vectraclip.companies LOOP
        INSERT INTO vectraclip.agent_specialty_configs (
              agent_id,
              company_id,
              specialty_id,
              values
          ) VALUES (
              '917e51b3-9413-4000-8000-000000000006',
              rec.company_id,
              'gymsite-prospect',
              '{"estados_alvo": [], "janela_dias": 30, "min_capital_social": 0, "municipios_alvo": [], "model_id": "claude-sonnet-4-6"}'::jsonb
          )
        ON CONFLICT (agent_id, specialty_id) DO NOTHING;
    END LOOP;
END $$;

-- =============================================================================
-- 6. Atualiza src/agent_ids.py (comentário de referência — fazer manualmente)
-- =============================================================================
-- GYMSITE_AGENT_ID = '917e51b3-9413-4000-8000-000000000006'
-- Adicionar em src/agent_ids.py após DAEDALUS_AGENT_ID
-- e incluir em ALL_AGENT_IDS
