-- HOTFIX: PR6 (20260513134730) inseriu config_schema como JSON Schema dict
-- ({type:"object", properties:{...}}), mas o Pydantic model `AgentSpecialty`
-- em src/models.py:680 espera `Optional[List[Dict[str, Any]]]` (field descriptors:
-- {key, label, type, required, default}). Resultado: GET /api/agent-specialties
-- retorna 500 (`list_agent_specialties failed: Input should be a valid list`).
--
-- Esta migration converte as 3 specialties impactadas para o formato esperado.
-- Idempotente: pode rodar quantas vezes precisar.

set search_path to vectraclip, public;

-- ──────────────────────────────────────────────────────────────────────────
-- 1. financial-audit
-- ──────────────────────────────────────────────────────────────────────────
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
    "label": "Período início",
    "type": "date",
    "required": false
  },
  {
    "key": "periodo_fim",
    "label": "Período fim",
    "type": "date",
    "required": false
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

-- ──────────────────────────────────────────────────────────────────────────
-- 2. planner-import-ofx
-- ──────────────────────────────────────────────────────────────────────────
update vectraclip.agent_specialties
set config_schema = '[
  {
    "key": "ofx_path",
    "label": "Caminho do diretório OFX",
    "type": "text",
    "required": false,
    "description": "Diretório com arquivo(s) .ofx; cursor escolhe o próximo a importar"
  },
  {
    "key": "planner_instituicao",
    "label": "Instituição financeira",
    "type": "text",
    "required": false,
    "description": "Nome no combobox `partitionId` do Meu Planner. Default: primeira opção real."
  },
  {
    "key": "pdf_path",
    "label": "PDF do extrato (opcional)",
    "type": "text",
    "required": false,
    "description": "Path do PDF C6 para enrichment de descrições genéricas (PIX)"
  },
  {
    "key": "recipient",
    "label": "Email destinatário do relatório de import",
    "type": "text",
    "required": false,
    "default": "marcelo.rosas@vectracargo.com.br"
  }
]'::jsonb
where id = 'planner-import-ofx';

-- ──────────────────────────────────────────────────────────────────────────
-- 3. planner-categorize-pendings
-- ──────────────────────────────────────────────────────────────────────────
update vectraclip.agent_specialties
set config_schema = '[
  {
    "key": "pdf_path",
    "label": "PDF do extrato (opcional)",
    "type": "text",
    "required": false,
    "description": "Path do PDF C6 para enrichment de descrições genéricas (PIX)"
  }
]'::jsonb
where id = 'planner-categorize-pendings';
