-- VEC-XXX PR6 — Kronos Planner specialties + system_prompt_template fonte-única
--
-- Fecha o ciclo da refatoração "specialty como fonte de verdade":
--   PR1 (#80) — services/specialty_resolver.py
--   PR3 (#81) — agent_daemon._populate_resolved_specialty
--   PR4 (#82) — resolve_kronos_inputs consome _resolved_config
--   PR6 (este) — seed das specialties + agent_specialty_configs
--
-- Mudanças:
--   1. Atualiza system_prompt_template + config_schema da specialty
--      `financial-audit` (criada em VEC-330 com prompt sem placeholders).
--   2. Cria 2 specialties novas: `planner-import-ofx` e
--      `planner-categorize-pendings` (op_types adicionados em VEC-419 e
--      vec419/categorize_only).
--   3. Cria agent_specialty_configs para Kronos × Vectra Cargo nas 3
--      specialties — `values` ficam vazios e o usuário/runtime preenche
--      via UI ou task.input_json (cadeia de precedência do resolver).
--
-- Idempotente: UPSERTs com ON CONFLICT DO UPDATE / DO NOTHING.

set search_path to vectraclip, public;

-- ──────────────────────────────────────────────────────────────────────────
-- 1. Atualiza specialty `financial-audit` com prompt + schema reais
-- ──────────────────────────────────────────────────────────────────────────
insert into vectraclip.agent_specialties
  (id, slug, name, domain, compatible_roles, system_prompt_template, config_schema, is_active)
values (
  'financial-audit',
  'financial-audit',
  'Financial Audit & Reconciliation',
  'Finance',
  ARRAY['Financial Auditor', 'Bookkeeper', 'Treasury'],
$prompt$# Financial Audit & Reconciliation

## Identidade
Você é especialista em auditoria financeira: reconcilia extratos bancários OFX
com lançamentos manuais no Meu Planner Financeiro e gera relatórios de
discrepância para o time financeiro.

## Inputs disponíveis
- ofx_path: caminho do diretório com arquivo(s) OFX
- planner_path: caminho do CSV/XLSX exportado do Planner (modo legacy)
- periodo_inicio / periodo_fim: janela de análise (YYYY-MM-DD)
- recipient: email destinatário do relatório (default: marcelo.rosas@vectracargo.com.br)

Task atual: {{ task.title }}
Operation: {{ task.operation_type }}

## Objetivo
1. Parse OFX e tabela do Planner.
2. Identificar discrepâncias usando:
   - Tolerância de data: ±2 dias
   - Valor absoluto idêntico
   - Similaridade de descrição ≥ 0.8 (difflib)
3. Categorizar transações conforme regras em `kronos_category_rules.yaml`.
4. Gerar relatório markdown estruturado.
5. Despachar via HermesReporter (`operation_type=oracle-report`).

## Modo atual: AUDIT (read-only)
Não escreve no Meu Planner — função: ler → comparar → reportar.

## Regras de segurança
- Nunca exponha credenciais.
- Erro estruturado quando inputs ausentes.
- Sem credenciais no log; usar agent_adapter_configs.
$prompt$,
  '{
    "type": "object",
    "properties": {
      "ofx_path": {
        "type": "string",
        "title": "Caminho do OFX",
        "description": "Diretório ou arquivo .ofx a auditar"
      },
      "planner_path": {
        "type": "string",
        "title": "Caminho do Planner (legacy)",
        "description": "CSV/XLSX exportado do Meu Planner (modo audit-only)"
      },
      "periodo_inicio": {
        "type": "string",
        "format": "date",
        "title": "Período início"
      },
      "periodo_fim": {
        "type": "string",
        "format": "date",
        "title": "Período fim"
      },
      "recipient": {
        "type": "string",
        "format": "email",
        "title": "Email destinatário do relatório",
        "default": "marcelo.rosas@vectracargo.com.br"
      }
    },
    "required": []
  }'::jsonb,
  true
)
on conflict (id) do update
  set name                   = excluded.name,
      slug                   = excluded.slug,
      domain                 = excluded.domain,
      compatible_roles       = excluded.compatible_roles,
      system_prompt_template = excluded.system_prompt_template,
      config_schema          = excluded.config_schema,
      is_active              = true;

-- ──────────────────────────────────────────────────────────────────────────
-- 2. Specialty nova: planner-import-ofx
-- ──────────────────────────────────────────────────────────────────────────
insert into vectraclip.agent_specialties
  (id, slug, name, domain, compatible_roles, system_prompt_template, config_schema, is_active)
values (
  'planner-import-ofx',
  'planner-import-ofx',
  'Upload OFX no Meu Planner',
  'Finance',
  ARRAY['Financial Auditor', 'Bookkeeper'],
$prompt$# Upload OFX — Meu Planner Financeiro

## Identidade
Você é responsável por importar arquivos OFX no webapp **Meu Planner Financeiro**
via automação Playwright (web.meuplannerfinanceiro.com.br/controle/lancamentos).

## Inputs
- ofx_path: diretório ou arquivo .ofx (cursor controla qual arquivo é o próximo)
- planner_instituicao: nome da instituição financeira no combobox do Planner
- pdf_path (opcional): PDF do extrato para enrichment de descrições genéricas
  (ex.: "TRANSF ENVIADA PIX" → "Pix enviado para NOME")
- recipient: destinatário do relatório de import

Task atual: {{ task.title }}

## Fluxo (automação Playwright)
1. Login no Meu Planner (storage_state.json persiste sessão).
2. Abrir modal `#import-file-btn` → "Importar Arquivo".
3. Selecionar instituição (`select[name="partitionId"]`), tipo `statement`, extensão `ofx`.
4. Upload via `input[type=file]` + submit.
5. Capturar toast "Importação realizada com sucesso!".
6. Fechar modal residual via cadeia: botão X → Escape → `dialog.close()` → `removeAttribute('open')` (PR #79).
7. Aguardar tabela `tbody tr` popular.
8. Categorizar linhas Pendentes via `kronos_category_rules.yaml` (com PDF enrichment se disponível).

## Output esperado
```json
{
  "status": "done",
  "output_json": {
    "imported_file": "abril.ofx",
    "toast": "Importação realizada com sucesso!",
    "screenshot": "audit-results/import-abril.png",
    "categorization": {
      "lines_categorized": 42,
      "lines_unclassified": 3,
      "lines_failed": 0
    }
  }
}
```

## Regras de segurança
- Login persistido via storage_state.json (Playwright). Nunca usar credenciais hardcoded.
- Erro estruturado em `output_json.error_detail` se OFX ausente, modal não fechar, ou save timeout.
$prompt$,
  '{
    "type": "object",
    "properties": {
      "ofx_path": {
        "type": "string",
        "title": "Caminho do diretório OFX",
        "description": "Diretório com arquivo(s) .ofx; cursor escolhe o próximo a importar"
      },
      "planner_instituicao": {
        "type": "string",
        "title": "Instituição financeira",
        "description": "Nome no combobox `partitionId` do Meu Planner. Default: primeira opção real (single-conta)."
      },
      "pdf_path": {
        "type": "string",
        "title": "PDF do extrato (opcional)",
        "description": "Path do PDF C6 para enrichment de descrições genéricas (PIX)"
      },
      "recipient": {
        "type": "string",
        "format": "email",
        "title": "Email destinatário do relatório de import",
        "default": "marcelo.rosas@vectracargo.com.br"
      }
    },
    "required": []
  }'::jsonb,
  true
)
on conflict (id) do update
  set name                   = excluded.name,
      slug                   = excluded.slug,
      domain                 = excluded.domain,
      compatible_roles       = excluded.compatible_roles,
      system_prompt_template = excluded.system_prompt_template,
      config_schema          = excluded.config_schema,
      is_active              = true;

-- ──────────────────────────────────────────────────────────────────────────
-- 3. Specialty nova: planner-categorize-pendings
-- ──────────────────────────────────────────────────────────────────────────
insert into vectraclip.agent_specialties
  (id, slug, name, domain, compatible_roles, system_prompt_template, config_schema, is_active)
values (
  'planner-categorize-pendings',
  'planner-categorize-pendings',
  'Categorização Pós-Import — Meu Planner',
  'Finance',
  ARRAY['Financial Auditor', 'Bookkeeper'],
$prompt$# Categorização Pós-Import — Meu Planner Financeiro

## Identidade
Você categoriza linhas **Pendentes** já importadas no Meu Planner, sem reimportar
OFX. Útil para:
- Smoke iterativo após adicionar regras em `kronos_category_rules.yaml`.
- Categorização retroativa de linhas antigas.
- Retry após falha parcial de import.

## Inputs
- pdf_path (opcional): PDF do extrato para enrichment de descrições genéricas

Task atual: {{ task.title }}

## Fluxo (automação Playwright)
1. Login no Meu Planner.
2. Navegar para `/controle/lancamentos`.
3. Fechar modal residual de import anterior (`_dismiss_import_success_modal`).
4. Aguardar `tbody tr` popular.
5. Para cada linha Pendente (até `_MAX_CATEGORIZE_LINES = 200`):
   - Match regra em `kronos_category_rules.yaml`.
   - Click em edit-btn → preencher `#category` + `#subcategory` na edit row Vue (`tr.EditTransactionRow_editRow__fNWmG`).
   - Salvar.
6. Screenshot final.

## Output esperado
```json
{
  "status": "done",
  "output_json": {
    "categorization": {
      "lines_categorized": 42,
      "lines_unclassified": 3,
      "lines_failed": 0,
      "details": [{ "row": 0, "rule": "PIX_ENVIADO", "category": "..." }, ...]
    },
    "screenshot": "audit-results/categorize-final.png"
  }
}
```

## Pitfalls (VEC-426)
- `table.rdp-table` (date picker) colide com `tbody tr` — sempre filtrar.
- Tabela demora a popular após overlay; aguardar `_wait_for_lancamentos_populated`.
- Edit-mode SUBSTITUI a `<tr>` original — Locators antigos invalidam; usar `_EDIT_ROW_SELECTOR` global.

## Regras de segurança
- Login persistido via storage_state.json.
- Erro estruturado quando regras YAML vazias ou ausentes.
$prompt$,
  '{
    "type": "object",
    "properties": {
      "pdf_path": {
        "type": "string",
        "title": "PDF do extrato (opcional)",
        "description": "Path do PDF C6 para enrichment de descrições genéricas (PIX)"
      }
    },
    "required": []
  }'::jsonb,
  true
)
on conflict (id) do update
  set name                   = excluded.name,
      slug                   = excluded.slug,
      domain                 = excluded.domain,
      compatible_roles       = excluded.compatible_roles,
      system_prompt_template = excluded.system_prompt_template,
      config_schema          = excluded.config_schema,
      is_active              = true;

-- ──────────────────────────────────────────────────────────────────────────
-- 4. agent_specialty_configs — Kronos × Vectra Cargo nas 3 specialties
--
--    `values` ficam {} de propósito: defaults reais vêm de:
--    a) agent_specialties.config_schema.properties[*].default (resolver lê)
--    b) override por task.input_json (cadeia de precedência do PR4)
--    c) variáveis de ambiente (`KRONOS_*`)
--
--    Para preencher valores específicos da empresa via UI, basta editar
--    o card "Especialidades" do agente — o resolver re-lê na próxima task.
-- ──────────────────────────────────────────────────────────────────────────
do $$
declare
  v_company_id  uuid := '01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2';
  v_kronos_id   uuid := '9c8d7e6f-5a4b-4321-9876-543210fedcba';
begin
  insert into vectraclip.agent_specialty_configs
    (company_id, agent_id, specialty_id, values)
  values
    (v_company_id, v_kronos_id, 'financial-audit',              '{}'::jsonb),
    (v_company_id, v_kronos_id, 'planner-import-ofx',           '{}'::jsonb),
    (v_company_id, v_kronos_id, 'planner-categorize-pendings',  '{}'::jsonb)
  on conflict (agent_id, specialty_id) do update
    set updated_at = now();
end $$;
