# ADR — Cotação Vectra como dogfood metadata-driven (Camada 3 gap #1 redefinido)

> **Status:** decisão registrada — dogfood agendado com Marcelo + esta sessão
> **Owner:** plataforma + Marcelo
> **Origem:** gap 🔴 ALTA da Camada 3 em `docs/AUDIT-HANDLERS-2026-05-16.md` ("route-cost-calculation EXCLUDED em Morpheus")
> **Data:** 2026-05-16
> **Trigger:** provocação do Marcelo no chat 23h45 — "como pretende solucionar dentro da nossa verdade profunda?"

---

## Contexto

A auditoria de handlers (2026-05-16) reportou como gap 🔴 ALTA:

> "route-cost-calculation EXCLUDED em Morpheus → Hodos não roda"

Minha proposta inicial foi:
- Opção A: implementar `src/agents/hodos.py` + integrar QUALP API (~6-8h)
- Opção B: deixar EXCLUDED + ADR parquear até demanda real

**Ambas erradas.** Marcelo apontou que eu estava pensando **bottom-up** (fix de handler isolado) quando o sistema é desenhado **top-down via pipeline PMBOK metadata-driven**.

## A verdade profunda do VectraClaw

VectraClaw é desenhado em torno de um **pipeline PMBOK metadata-driven**:

```
Goal (criado por user via UI)
  → athena-classify (kind, confidence, business_case)
  → athena-charter (justificativa, escopo, sucesso, stakeholders)
  → athena-stakeholder-map (RACI de alto nível)
  → athena-risk-register (RBS PMBOK)
  → SIPOC mapping (Suppliers, Inputs, Activities, Outputs, Customers)
  → daedalus bpmn-generate (BPMN visual do processo)
  → workflow_definition + workflow_steps (modelo executável)
  → TaskFactory.materialize_workflow (cria tasks reais)
  → Agents executam por operation_type (Mercator quote, Hodos route-cost, HermesReporter)
  → athena-evm / prioritize / audit (loop melhoria contínua)
```

**Nenhuma capacidade de negócio nova deveria nascer como handler hardcoded.** Toda capacidade vira **Goal modelado** que dispara o pipeline.

## Decisão

### 1. EXCLUDED de `route-cost-calculation` em Morpheus está **CORRETO**

Não é bug. Morpheus não deve criar tasks `route-cost-calculation` por iniciativa porque essas tasks vêm do **workflow_engine materializando steps** de um processo SIPOC modelado (ex: "Cotação de Frete"). EXCLUDED previne Morpheus violar o design metadata-driven.

**Comentário histórico do Marcelo:**
> "Morpheus criava quando estava testando e a task era codada não metadata"

EXCLUDED foi adicionado como freio quando o sistema fez a transição de hardcoded → metadata-driven. Vestígio correto da era de transição. Manter.

### 2. Hodos NÃO precisa de `src/agents/hodos.py` custom

Hodos tem `adapter_type='claude_code'` (confirmado em `vectraclip.agents`). Quando uma task `route-cost-calculation` chega com `assigned_to_agent_id=HODOS_AGENT_ID`, o `agent_daemon._execute_task` cai no default `claude -p` (api.py:524-525). Sem necessidade de handler Python custom.

Categorias do projeto:
- **Code-implemented**: Mnemos, Kronos, Athena, Daedalus, HermesReporter (lógica determinística forte)
- **LLM-driven**: Hermes (parte), Mercator, Plutus, **Hodos** (raciocínio LLM com adapter)

Hodos foi desenhado como LLM-driven desde o começo.

### 3. O gap real é **dados**, não código

**Vectra Cargo faz cotações TODO DIA fora do sistema** (planilha, email, conhecimento na cabeça do Marcelo). Nunca foi modelada como Goal no VectraClaw.

Sem Goal "Cotação Vectra":
- Sem athena-classify → sem charter → sem stakeholder-map → sem risk-register
- Sem SIPOC mapeado → sem activities → sem workflow_steps
- Sem TaskFactory disparado → sem tasks `route-cost-calculation`
- Hodos vivo mas idle (ninguém manda task)

### 4. Solução = **dogfood via UI**, não código novo

Marcelo + esta sessão (assistida) vão executar manualmente o pipeline pra:
1. Confirmar que o caminho funciona
2. Identificar **onde quebra de verdade** (não onde a auditoria achou que quebrava)
3. Aí decidir fix com **evidência**, não hipótese

## Plano de execução (dogfood)

### Fase 1 — Criar Goal real

Via UI `/goals/new` (ou POST direto):
```
title: "Mapear e otimizar processo de cotação de frete Vectra"
description: "Hoje cotação é feita via planilha + e-mail. Mapear SIPOC,
              identificar gargalos, definir métricas de tempo/qualidade,
              gerar workflow executável."
metric: "Tempo médio de cotação (minutos)"
target: <Marcelo decide — ex: 5 min p/ rota simples>
```

### Fase 2 — Disparar athena-classify

Via UI (botão "Classificar" no GoalDetail) ou dispatch task `athena-classify`.

**Expectativa:** vai retornar `kind='operational'` (cotação é processo recorrente, não projeto único) com sub-projects de otimização.

**Risco:** R1 Gemini 403 pode bloquear. Fallback manual: setar `goals.kind='operational'` via SQL e seguir.

### Fase 3 — Mapear SIPOC do processo

Via UI `/sipoc/management` (ou wizard `/sipoc/wizard`):

| Categoria | Conteúdo provável |
|---|---|
| **Suppliers** | Cliente, transportadoras parceiras, tabela de fretes interna, ANTT |
| **Inputs** | Origem, destino, peso, cubagem, tipo carga, urgência, observações |
| **Activities** | Receber pedido → consultar tabela → calcular rota → aprovar internamente → enviar cotação ao cliente |
| **Outputs** | PDF de cotação, registro no CRM, email enviado |
| **Customers** | Cliente final, RH/Comercial (se confirmar venda) |

**Quem mapeia:** Marcelo (sabe o processo real) com Oracle SSE chat ajudando estagiar 5W2H por activity.

### Fase 4 — Daedalus bpmn-generate

Botão "Gerar BPMN" no SipocProcessDetail (se existir) OU dispatch task `bpmn-generate` com `source_type='sipoc_process'`. Fallback estatístico já funciona (PR #159).

### Fase 5 — workflow_definition + workflow_steps

**Aqui suspeito gap real:** mapear automaticamente `sipoc_components(type='activity')` → `workflow_steps(operation_type)`. Provavelmente:
- "Calcular rota" → `operation_type='route-cost-calculation'`, `assigned_to=HODOS_ID`
- "Enviar cotação" → `operation_type='oracle-report'` ou `crm-fill`, `assigned_to=HermesReporter` ou Plutus

**Se quebra aqui:** identificamos que falta um endpoint POST `/api/workflow-steps/from-sipoc-process/{id}` que faz o materializar.

### Fase 6 — Ativar workflow + observar TaskFactory criar tasks

TaskFactory deve materializar 1 task por workflow_step quando workflow é "ativado". Tasks `route-cost-calculation` aparecem na fila do Hodos.

### Fase 7 — Hodos processa

Daemon Hodos (precisa estar rodando — `start_all_daemons.py` inclui) executa `claude -p` com o prompt da task. Output vai pra `task.output_json` + `audit_log` (G1.6).

## Onde provavelmente vai quebrar

Hipóteses ranqueadas por probabilidade (alta → baixa):

| # | Hipótese | Onde |
|---|---|---|
| 1 | UI `/sipoc/wizard` ou `/sipoc/management` tem bug que impede mapear processo end-to-end | Frontend (sessão paralela cuida) |
| 2 | SIPOC → workflow_steps não tem endpoint nativo de "promote" | `src/services/sipoc_promotion.py` parcial? Verificar |
| 3 | TaskFactory não conecta workflow_step.operation_type → assigned_to_agent_id automaticamente | `src/services/task_factory.py` |
| 4 | R1 Gemini 403 paralisa Athena handlers do início | Fallback manual SQL |
| 5 | Hodos daemon não está rodando (Task Scheduler inativo) | Reiniciar launcher |
| 6 | Hodos `claude -p` falha em prompt vazio/genérico (sem system_prompt rico) | Refinar prompt do agente |

## O que NÃO fazer

❌ Implementar `src/agents/hodos.py` antes do dogfood — viola P0 metadata-driven
❌ Remover `route-cost-calculation` do EXCLUDED_TYPES — semântica correta
❌ Criar endpoint cotação especial fora do pipeline PMBOK — anti-pattern (foi exatamente o que Marcelo apontou como erro do agente)
❌ Assumir que o gap é do código sem evidência do dogfood

## Critério de saída (quando este ADR vira issue concreto)

Quando rodarmos o dogfood E **uma das hipóteses acima se confirmar com evidência**:
- Bug capturado com stacktrace ou comportamento errado
- Decisão de fix tomada com base no que QUEBROU, não no que a auditoria CHUTOU
- Issue/PR com escopo cirúrgico do verdadeiro gap

## Atualização no AUDIT-HANDLERS

Gap "route-cost-calculation EXCLUDED" será marcado:
> 🟢 **REDEFINIDO** — Gap inicial era erro de diagnóstico (auditor pensou em handler missing; verdade é Goal não modelado). EXCLUDED é semântica correta. Ver `ADR-VEC-COTACAO-DOGFOOD-FREIGHT.md`. Dogfood agendado.

## Lição pra próxima sessão

**Antes de propor fix de qualquer "gap" em VectraClaw**, perguntar: este gap é de **código** ou de **dados** (Goal/SIPOC/workflow não modelado)? Sistema é metadata-driven — capacidade de negócio nasce como **Goal**, não como handler.

Atualizar `docs/CODE-PATTERNS.md` P0/P1 com este princípio num próximo PR (quando rodarmos o dogfood e tivermos exemplo concreto).

## Próximo passo

Marcelo executa Fase 1-7 via UI. Esta sessão (ou próxima Claude) acompanha em standby pra:
- Investigar quando quebrar
- Aplicar fix cirúrgico com evidência
- Registrar aprendizado em PR + atualizar este ADR

**O dogfood é o teste real do MVP P1 vendável.** Se a Vectra Cargo consegue modelar sua própria cotação no produto, qualquer consultor consegue modelar a operação dos clientes.
