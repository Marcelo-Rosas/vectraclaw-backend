-- Daedalus PR F — seed da specialty bpmn-modeling + agent Daedalus + config
--
-- Doc de planejamento: docs/EXECUCAO-G1-RISK-REGISTER-E-DAEDALUS.md §2.1-§2.3
-- Decisão arquitetural: engine BPMN própria, sem Camunda
-- (memória: feedback_no_camunda_keep_custom_engine).
--
-- Provisiona 4 inserts idempotentes:
--   1. agent_domains: novo domain 'modeling'
--   2. agent_specialties: 'bpmn-modeling' (specialty PMBOK pra modelagem visual)
--   3. agents: Daedalus (per-company via DO loop; AGENT_ID fixo cross-tenant)
--   4. agent_specialty_configs: vincula Daedalus → bpmn-modeling com values default
--
-- AGENT_ID Daedalus: d4ed4145-0000-4000-8000-000000000005 (DAED-tematic, grepável,
-- v4 UUID válido). Será referenciado pelo handler (PR G) e launcher (PR H).

-- =============================================================================
-- 1. Domain 'modeling' (novo)
-- =============================================================================

INSERT INTO vectraclip.agent_domains (id, name, description, icon, color, display_order, is_active)
VALUES (
  'modeling',
  'Modelagem & Processos',
  'Modelagem visual de processos BPMN, fluxos a partir de SIPOC/Charter, validação de diagramas.',
  'workflow',
  'text-orange-600',
  35,
  true
)
ON CONFLICT (id) DO NOTHING;

-- =============================================================================
-- 2. Specialty 'bpmn-modeling'
-- =============================================================================

INSERT INTO vectraclip.agent_specialties (
  id, slug, name, domain, description, compatible_roles,
  system_prompt_template, config_schema, is_active
)
VALUES (
  'bpmn-modeling',
  'bpmn-modeling',
  'BPMN Process Modeling',
  'modeling',
  'Gera diagramas BPMN visuais a partir de descrição textual de processo, SIPOC mapeado, ou Charter PMBOK. Retorna JSON nativo (não BPMN 2.0 XML) consumível pelo canvas @xyflow/react.',
  ARRAY['executor'],
  $PROMPT$# Daedalus — Modelador de Processos BPMN

Você é Daedalus, especialista em modelagem visual de processos.
Mitologia: arquiteto do labirinto — você transforma descrições textuais
em diagramas estruturados.

## Responsabilidade principal

Receber input estruturado (SIPOC process, Charter PMBOK, ou descrição
textual livre) e gerar diagrama BPMN-style em JSON nativo do canvas
@xyflow/react.

## NÃO faz

- Não gera BPMN 2.0 XML (Camunda) — engine própria, formato próprio
- Não executa workflow (papel de Morpheus + daemons)
- Não decide se atividade vira automated/hybrid/manual (papel da Athena)
- Não atribui RACI (papel do humano via UI)

## Fluxo esperado

1. Carrega contexto:
   - sipoc_process: lê sipoc_components + edges do processo
   - charter: lê workflow_definitions.charter
   - freeform: usa apenas o texto fornecido
2. Inferência: gera lista de nós BPMN-style
   - start_event, end_event
   - task (user_task | service_task | manual_task)
   - gateway_exclusive (if/else)
   - gateway_parallel (fork/join)
   - intermediate_event
3. Inferência: gera arestas (sequence_flow) com labels (sim/não nos gateways)
4. Se auto_layout=true: aplica dagre rankdir LR
5. Validação BPMN-rules:
   - Cada gateway tem ≥2 saídas
   - Cada start_event tem 0 entradas e ≥1 saída
   - Cada end_event tem ≥1 entrada e 0 saídas
   - Sem nós órfãos
6. Retorna JSON nativo + validation block + metadata

## Hierarquia

Reports to Morpheus (orquestrador). Daedalus é executor, não decide.
$PROMPT$,
  $SCHEMA$[
    {
      "key": "model",
      "type": "select",
      "label": "Modelo LLM",
      "options": [
        {"value": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
        {"value": "gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
        {"value": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6"},
        {"value": "claude-haiku-4-5", "label": "Claude Haiku 4.5"}
      ],
      "required": true,
      "default": "gemini-2.5-flash",
      "description": "Modelo LLM usado pra inferência BPMN. Sonnet > Haiku para raciocínio estrutural."
    },
    {
      "key": "auto_layout",
      "type": "boolean",
      "label": "Aplicar auto-layout (dagre)",
      "default": true,
      "required": false,
      "description": "Posiciona nós automaticamente em layout top-down ou left-right."
    },
    {
      "key": "max_nodes",
      "type": "number",
      "label": "Limite de nós por diagrama",
      "default": 50,
      "required": false,
      "description": "Trava de segurança contra LLM gerar diagramas obesos."
    }
  ]$SCHEMA$::jsonb,
  true
)
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  domain = EXCLUDED.domain,
  description = EXCLUDED.description,
  compatible_roles = EXCLUDED.compatible_roles,
  system_prompt_template = EXCLUDED.system_prompt_template,
  config_schema = EXCLUDED.config_schema,
  is_active = EXCLUDED.is_active;

-- =============================================================================
-- 3. Agent Daedalus (per company; AGENT_ID fixo) + 4. config
-- =============================================================================

DO $$
DECLARE
  daedalus_id CONSTANT UUID := 'd4ed4145-0000-4000-8000-000000000005';
  morpheus_id CONSTANT UUID := '00000000-0000-0000-0000-000000000001';
  rec RECORD;
  morpheus_in_company UUID;
BEGIN
  FOR rec IN SELECT company_id FROM vectraclip.companies LOOP
    -- Confere se Morpheus existe nesta company (reports_to_id condicional)
    SELECT id INTO morpheus_in_company
      FROM vectraclip.agents
     WHERE id = morpheus_id AND company_id = rec.company_id
     LIMIT 1;

    INSERT INTO vectraclip.agents (
      id, company_id, name, role, reports_to_id, status,
      token_budget, current_burn_rate, adapter_type,
      system_prompt, requires_approval, is_system
    )
    VALUES (
      daedalus_id,
      rec.company_id,
      'Daedalus',
      'BPMN Process Modeler',
      morpheus_in_company,  -- NULL se Morpheus não existe nesta company (não bloqueia)
      'idle',
      100000,               -- token_budget generoso (modelagem usa muito contexto)
      0,
      'gemini',
      NULL,                 -- system_prompt compilado fica em handler/runtime
      false,
      true                  -- is_system=true (Daedalus é agente de plataforma)
    )
    ON CONFLICT (id) DO UPDATE SET
      role = EXCLUDED.role,
      adapter_type = EXCLUDED.adapter_type,
      is_system = EXCLUDED.is_system,
      reports_to_id = COALESCE(vectraclip.agents.reports_to_id, EXCLUDED.reports_to_id);

    -- Specialty config: 1 por company (FK em company_id + agent_id)
    INSERT INTO vectraclip.agent_specialty_configs (
      company_id, agent_id, specialty_id, values
    )
    VALUES (
      rec.company_id,
      daedalus_id,
      'bpmn-modeling',
      jsonb_build_object(
        'model', 'gemini-2.5-flash',
        'auto_layout', true,
        'max_nodes', 50
      )
    )
    ON CONFLICT DO NOTHING;
  END LOOP;
END $$;

-- =============================================================================
-- NOTIFY pgrst — recarrega schema cache da REST API
-- =============================================================================

NOTIFY pgrst, 'reload schema';
