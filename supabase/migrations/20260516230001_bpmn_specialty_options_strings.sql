-- Hotfix Daedalus PR F — bpmn-modeling config_schema com shape errado de options
--
-- Bug reportado pelo frontend após PR #158 (PR F merged):
--   "Resposta inválida de /agent-specialties:
--    2.configSchema.0.options.0 → Expected string, received object"
--
-- Causa: PR F gerou options como [{value, label}, ...] (shape rico) mas o
-- Zod schema do frontend (e padrão das specialties existentes — Hodos etc.)
-- espera options como ["str1", "str2", ...] (strings).
--
-- Fix: re-aplicar config_schema com shape compatível:
--   - options: string[] (NÃO {value, label})
--   - defaultValue (NÃO default)
--
-- Idempotente via UPDATE WHERE id='bpmn-modeling'.

UPDATE vectraclip.agent_specialties
   SET config_schema = '[
  {
    "key": "model",
    "type": "select",
    "label": "Modelo LLM",
    "options": ["gemini-2.5-flash", "gemini-2.5-pro", "claude-sonnet-4-6", "claude-haiku-4-5"],
    "required": true,
    "defaultValue": "gemini-2.5-flash",
    "description": "Modelo LLM usado para inferência BPMN. Sonnet > Haiku para raciocínio estrutural."
  },
  {
    "key": "auto_layout",
    "type": "boolean",
    "label": "Aplicar auto-layout (dagre)",
    "defaultValue": true,
    "required": false,
    "description": "Posiciona nós automaticamente em layout top-down ou left-right."
  },
  {
    "key": "max_nodes",
    "type": "number",
    "label": "Limite de nós por diagrama",
    "defaultValue": 50,
    "required": false,
    "description": "Trava de segurança contra LLM gerar diagramas obesos."
  }
]'::jsonb
 WHERE id = 'bpmn-modeling';

NOTIFY pgrst, 'reload schema';
