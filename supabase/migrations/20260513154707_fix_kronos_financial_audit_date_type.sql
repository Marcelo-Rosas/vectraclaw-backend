-- HOTFIX 2: o frontend (Zod) só aceita type ∈ {text, secret, boolean, number, select}
-- mas a migration 20260513154309 usou type="date" em periodo_inicio/periodo_fim
-- do financial-audit. Sintoma na UI:
--
--   Falha ao carregar dados.
--   Resposta inválida de /agent-specialties: 6.configSchema.2.type →
--     Invalid enum value. Expected 'text' | 'secret' | 'boolean' | 'number' | 'select',
--     received 'date'
--
-- Convertendo para "text" (a UI exibe campo livre; o agente parseia formato YYYY-MM-DD).

set search_path to vectraclip, public;

update vectraclip.agent_specialties
set config_schema = '[
  {
    "key": "ofx_path",
    "label": "Caminho do OFX",
    "type": "text",
    "required": false,
    "description": "Diretório ou arquivo .ofx a auditar"
  },
  {
    "key": "planner_path",
    "label": "Caminho do Planner (legacy)",
    "type": "text",
    "required": false,
    "description": "CSV/XLSX exportado do Meu Planner (modo audit-only)"
  },
  {
    "key": "periodo_inicio",
    "label": "Período início (YYYY-MM-DD)",
    "type": "text",
    "required": false,
    "description": "Data início no formato ISO YYYY-MM-DD"
  },
  {
    "key": "periodo_fim",
    "label": "Período fim (YYYY-MM-DD)",
    "type": "text",
    "required": false,
    "description": "Data fim no formato ISO YYYY-MM-DD"
  },
  {
    "key": "recipient",
    "label": "Email destinatário do relatório",
    "type": "text",
    "required": false,
    "default": "marcelo.rosas@vectracargo.com.br"
  }
]'::jsonb
where id = 'financial-audit';
