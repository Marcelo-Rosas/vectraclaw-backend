-- PR M Skillforge (PRD Skills Library v2) — catalog seed for 10 business skills.
-- Ref: https://github.com/chema74/skills-ia-empresariales (CATALOGO.md, CC BY-SA 4.0)
--
-- AUDIT BEFORE (run manually):
--   SELECT count(*) FROM vectraclip.agent_specialties WHERE source = 'skillforge';
--   SELECT id FROM vectraclip.operation_types_catalog WHERE id LIKE 'skillforge:%';
--
-- ESPELHEI ANTES (Regra Ouro #1):
--   agent_specialties: S3-A columns status/source exist (20260520020000).
--   operation_types_catalog: id text PK; no CHECK on id prefix.
--   agent_domains: knowledge, intelligence, crm, automation, communication exist.

-- ============================================================================
-- 1) operation_types_catalog — prefix skillforge:sf-*
--    primary_agent_id NULL → any harness with specialty binding may execute.
-- ============================================================================

INSERT INTO vectraclip.operation_types_catalog
  (id, name, description, category, primary_agent_id, default_specialty_slug, routing_score, is_active, display_order)
VALUES
  (
    'skillforge:sf-lector-documental',
    'Skillforge: Lector Inteligente Documental',
    'Extrae y organiza informacion clave de documentos empresariales (local-first).',
    'knowledge', NULL, 'sf-lector-documental', 50, true, 501
  ),
  (
    'skillforge:sf-radar-anomalias',
    'Skillforge: Radar de Anomalias',
    'Detecta patrones atipicos en series numericas de negocio (local-first).',
    'knowledge', NULL, 'sf-radar-anomalias', 50, true, 502
  ),
  (
    'skillforge:sf-forjador-informes',
    'Skillforge: Forjador de Informes',
    'Construye informes ejecutivos a partir de datos y evidencias.',
    'intelligence', NULL, 'sf-forjador-informes', 50, true, 503
  ),
  (
    'skillforge:sf-memoria-contextual-cliente',
    'Skillforge: Memoria Contextual de Cliente',
    'Mantiene contexto util de interacciones y decisiones por cliente.',
    'crm', NULL, 'sf-memoria-contextual-cliente', 50, true, 504
  ),
  (
    'skillforge:sf-pulso-riesgo',
    'Skillforge: Pulso de Riesgo',
    'Evalua senales de riesgo en procesos y decisiones.',
    'intelligence', NULL, 'sf-pulso-riesgo', 50, true, 505
  ),
  (
    'skillforge:sf-buscador-privado-aumentado',
    'Skillforge: Buscador Privado Aumentado',
    'Recupera informacion relevante desde fuentes privadas autorizadas.',
    'knowledge', NULL, 'sf-buscador-privado-aumentado', 50, true, 506
  ),
  (
    'skillforge:sf-enrutador-inteligente',
    'Skillforge: Enrutador Inteligente',
    'Decide que skill o flujo ejecutar segun intencion y contexto.',
    'automation', NULL, 'sf-enrutador-inteligente', 50, true, 507
  ),
  (
    'skillforge:sf-voz-marca-inteligente',
    'Skillforge: Voz de Marca Inteligente',
    'Ajusta textos a tono, estilo y criterios de marca.',
    'communication', NULL, 'sf-voz-marca-inteligente', 50, true, 508
  ),
  (
    'skillforge:sf-verificador-normativo',
    'Skillforge: Verificador Normativo',
    'Contrasta salidas con reglas y politicas definidas.',
    'knowledge', NULL, 'sf-verificador-normativo', 50, true, 509
  ),
  (
    'skillforge:sf-puerta-aprobacion-humana',
    'Skillforge: Puerta de Aprobacion Humana',
    'Solicita y registra validacion humana antes de acciones sensibles.',
    'automation', NULL, 'sf-puerta-aprobacion-humana', 50, true, 510
  )
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  category = EXCLUDED.category,
  default_specialty_slug = EXCLUDED.default_specialty_slug,
  routing_score = EXCLUDED.routing_score,
  is_active = EXCLUDED.is_active,
  display_order = EXCLUDED.display_order;

-- ============================================================================
-- 2) agent_specialties — 10 rows, source=skillforge, status=active
-- ============================================================================

INSERT INTO vectraclip.agent_specialties
  (id, slug, name, domain, description, compatible_roles, system_prompt_template, config_schema, is_active, status, source)
VALUES
  (
    'sf-lector-documental',
    'sf-lector-documental',
    'Lector Inteligente Documental',
    'knowledge',
    'Extrae y organiza informacion clave de documentos empresariales (Skillforge).',
    ARRAY['document_analyst', 'knowledge_worker'],
    $$Eres el Lector Inteligente Documental. Analiza el documento en {{ texto_documento }} y devuelve resumen estructurado con trazas.$$,
    '[
      {"key": "texto_documento", "label": "Documento", "type": "textarea", "required": true, "default": ""},
      {"key": "max_secciones", "label": "Max secciones", "type": "number", "required": false, "default": 10},
      {"key": "palabras_clave", "label": "Palabras clave", "type": "json", "required": false, "default": []}
    ]'::jsonb,
    true, 'active', 'skillforge'
  ),
  (
    'sf-radar-anomalias',
    'sf-radar-anomalias',
    'Radar de Anomalias',
    'knowledge',
    'Detecta patrones atipicos en datos de negocio (Skillforge).',
    ARRAY['analyst', 'finance_ops'],
    $$Analiza la serie numerica y reporta anomalias priorizadas por z-score.$$,
    '[
      {"key": "serie", "label": "Serie numerica", "type": "json", "required": true, "default": []},
      {"key": "umbral_desviaciones", "label": "Umbral (desv.)", "type": "number", "required": false, "default": 2.0}
    ]'::jsonb,
    true, 'active', 'skillforge'
  ),
  (
    'sf-forjador-informes',
    'sf-forjador-informes',
    'Forjador de Informes',
    'intelligence',
    'Construye informes ejecutivos a partir de datos y evidencias (Skillforge).',
    ARRAY['reporting', 'executive_assistant'],
    $$Genera informe ejecutivo con secciones a partir de {{ evidencias }}.$$,
    '[
      {"key": "titulo", "label": "Titulo", "type": "text", "required": true, "default": ""},
      {"key": "evidencias", "label": "Evidencias", "type": "json", "required": false, "default": []}
    ]'::jsonb,
    true, 'active', 'skillforge'
  ),
  (
    'sf-memoria-contextual-cliente',
    'sf-memoria-contextual-cliente',
    'Memoria Contextual de Cliente',
    'crm',
    'Mantiene contexto util de interacciones por cliente (Skillforge).',
    ARRAY['crm', 'account_manager'],
    $$Actualiza ficha contextual del cliente {{ cliente_id }} con nuevos eventos.$$,
    '[
      {"key": "cliente_id", "label": "Cliente", "type": "text", "required": true, "default": ""},
      {"key": "eventos", "label": "Eventos", "type": "json", "required": false, "default": []}
    ]'::jsonb,
    true, 'active', 'skillforge'
  ),
  (
    'sf-pulso-riesgo',
    'sf-pulso-riesgo',
    'Pulso de Riesgo',
    'intelligence',
    'Evalua senales de riesgo en procesos y decisiones (Skillforge).',
    ARRAY['risk', 'compliance'],
    $$Evalua factores de riesgo y devuelve matriz priorizada.$$,
    '[
      {"key": "factores", "label": "Factores", "type": "json", "required": true, "default": []}
    ]'::jsonb,
    true, 'active', 'skillforge'
  ),
  (
    'sf-buscador-privado-aumentado',
    'sf-buscador-privado-aumentado',
    'Buscador Privado Aumentado',
    'knowledge',
    'Recupera informacion desde fuentes privadas autorizadas (Skillforge).',
    ARRAY['research', 'knowledge_base'],
    $$Busca en corpus privado y responde con referencias internas.$$,
    '[
      {"key": "consulta", "label": "Consulta", "type": "text", "required": true, "default": ""},
      {"key": "documentos", "label": "Documentos", "type": "json", "required": false, "default": []}
    ]'::jsonb,
    true, 'active', 'skillforge'
  ),
  (
    'sf-enrutador-inteligente',
    'sf-enrutador-inteligente',
    'Enrutador Inteligente',
    'automation',
    'Decide que skill o flujo ejecutar segun intencion (Skillforge).',
    ARRAY['router', 'orchestrator'],
    $$Clasifica intencion y propone plan de ejecucion enrutable.$$,
    '[
      {"key": "intencion", "label": "Intencion", "type": "text", "required": true, "default": ""},
      {"key": "skills_disponibles", "label": "Skills", "type": "json", "required": false, "default": []}
    ]'::jsonb,
    true, 'active', 'skillforge'
  ),
  (
    'sf-voz-marca-inteligente',
    'sf-voz-marca-inteligente',
    'Voz de Marca Inteligente',
    'communication',
    'Ajusta textos a tono y estilo de marca (Skillforge).',
    ARRAY['marketing', 'communications'],
    $$Transforma {{ texto_original }} al tono de marca definido en guia.$$,
    '[
      {"key": "texto_original", "label": "Texto", "type": "textarea", "required": true, "default": ""},
      {"key": "guia_marca", "label": "Guia de marca", "type": "json", "required": false, "default": {}}
    ]'::jsonb,
    true, 'active', 'skillforge'
  ),
  (
    'sf-verificador-normativo',
    'sf-verificador-normativo',
    'Verificador Normativo',
    'knowledge',
    'Contrasta salidas con reglas y politicas (Skillforge).',
    ARRAY['compliance', 'quality'],
    $$Verifica cumplimiento normativo de la salida propuesta.$$,
    '[
      {"key": "salida", "label": "Salida a verificar", "type": "textarea", "required": true, "default": ""},
      {"key": "reglas", "label": "Reglas", "type": "json", "required": false, "default": []}
    ]'::jsonb,
    true, 'active', 'skillforge'
  ),
  (
    'sf-puerta-aprobacion-humana',
    'sf-puerta-aprobacion-humana',
    'Puerta de Aprobacion Humana',
    'automation',
    'Solicita validacion humana antes de acciones sensibles (Skillforge).',
    ARRAY['governance', 'approval'],
    $$Registra solicitud de aprobacion humana para accion sensible.$$,
    '[
      {"key": "accion_propuesta", "label": "Accion", "type": "text", "required": true, "default": ""},
      {"key": "motivo", "label": "Motivo", "type": "textarea", "required": false, "default": ""}
    ]'::jsonb,
    true, 'active', 'skillforge'
  )
ON CONFLICT (id) DO UPDATE SET
  slug = EXCLUDED.slug,
  name = EXCLUDED.name,
  domain = EXCLUDED.domain,
  description = EXCLUDED.description,
  compatible_roles = EXCLUDED.compatible_roles,
  system_prompt_template = EXCLUDED.system_prompt_template,
  config_schema = EXCLUDED.config_schema,
  is_active = EXCLUDED.is_active,
  status = EXCLUDED.status,
  source = EXCLUDED.source;

-- AUDIT AFTER:
--   SELECT status, source, count(*) FROM vectraclip.agent_specialties WHERE source = 'skillforge' GROUP BY 1, 2;
--   SELECT id, default_specialty_slug FROM vectraclip.operation_types_catalog WHERE id LIKE 'skillforge:%' ORDER BY display_order;
