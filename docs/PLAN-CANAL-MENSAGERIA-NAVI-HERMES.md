# Plano de implementação — Canal mensageria (NAVI × Meta × Hermes)

> **Status:** plano mestre de execução (2026-05-19).  
> **Substitui ambiguidade:** “Hermes = canal WhatsApp” → **NAVI + `meta-whatsapp` = WhatsApp**; Hermes = runtime/skills/MCP paralelo.  
> **Documentos irmãos:** este arquivo é o **índice + sequência de PRs**. Detalhe técnico em contratos/ADRs listados abaixo.

---

## 0. Mapa de planos espalhados (onde está cada coisa)

| Tema | Documento / artefato | Repo | O que define |
|------|----------------------|------|--------------|
| **WhatsApp webhook + sessões** | [`META-WHATSAPP-WEBHOOK.md`](./META-WHATSAPP-WEBHOOK.md) | VectraClaw | GET/POST webhook, vault, multi-tenant por `phone_number_id` |
| **Intent inbound (Morpheus)** | [`ADR-VEC-INBOUND-INTENT-CLASSIFIER.md`](./ADR-VEC-INBOUND-INTENT-CLASSIFIER.md) + migration `20260518133157` | VectraClaw | Opção A: `inbound-triage` + `inbound_intent_rules` |
| **Fluxo RACI Miro** | `Miro/Fluxo Cotação WhatsApp — *.csv/pdf` | VectraClaw | NAVI (azul) vs Claw (verde) vs Clip (roxo) |
| **Templates Meta (WABA)** | migration `20260518160200_whatsapp_templates_catalog.sql` + [`whatsapp_template_sync.py`](../src/services/whatsapp_template_sync.py) | VectraClaw | Sync Graph API → `whatsapp_templates`; reply text vs template |
| **NAVI (mensageria)** | **Não há PRD único no Claw** — ADR inbound Opção C; repo **`cargo-flow-navigator`** / Edge | CFN | Conversa, intent, Meta Flow (TO-BE) |
| **Hermes runtime** | [`PRD-NOUS-HERMES-INTEGRATION.md`](./PRD-NOUS-HERMES-INTEGRATION.md) + [`CONTRACTS-NOUS-HERMES.md`](./CONTRACTS-NOUS-HERMES.md) | VectraClaw | F1 exec/health ✅; F2 MCP ❌; F4 gateway ≠ WABA |
| **Canal cliente (decisões)** | [`ADR-VEC-CANAL-CLIENTE-OPENCLAW-VS-HERMES.md`](./ADR-VEC-CANAL-CLIENTE-OPENCLAW-VS-HERMES.md) | VectraClaw | OpenClaw rejeitado; **revisado 2026-05-19 com NAVI** |
| **Skills biblioteca** | [`ADR-VEC-SKILLS-LIBRARY-AUDIT.md`](./ADR-VEC-SKILLS-LIBRARY-AUDIT.md) + plan Cursor `skills_library_architecture_*.plan.md` | VectraClaw / `.cursor/plans` | `agent_specialties`, `skill_proposals`, Agent Builder |
| **Alma do agente + apply** | [`CONTRACTS-AGENT-CAPABILITIES.md`](./CONTRACTS-AGENT-CAPABILITIES.md) | VectraClaw | `bundle_json`, Athena, apply TO-BE |
| **MCP prod + comunidade** | [`CONTRACTS-MCP-BINDINGS.md`](./CONTRACTS-MCP-BINDINGS.md) + [`HANDOFF-MCP-PHASE-A-COMMUNITY.md`](./HANDOFF-MCP-PHASE-A-COMMUNITY.md) | VectraClaw + VectraClip | Catálogo MCP; curadoria CSV |
| **W14 ferramentas / cadência** | [`AUDITORIA-FERRAMENTAS-W14.md`](./AUDITORIA-FERRAMENTAS-W14.md) | VectraClaw | `tools_catalog`, templates em `workflow_steps` |
| **PMO / backlog geral** | [`PMO-STATUS-2026-05-17.md`](./PMO-STATUS-2026-05-17.md), [`AUTOPILOT-PENDING-FOLLOWUPS.md`](./AUTOPILOT-PENDING-FOLLOWUPS.md) | VectraClaw | R1 Gemini, Lote 3 frontend, etc. |

**Lacuna explícita:** não existe hoje um único `PRD-NAVI-MESSAGING.md` no VectraClaw — NAVI está fragmentado entre Miro, ADR inbound §C e ecossistema CFN. Este plano **centraliza a sequência**; o PRD NAVI deve nascer no repo CFN (Fase N0).

---

## 1. Arquitetura alvo (cravada)

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ Meta Cloud API (WABA, templates aprovados, webhook)                        │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
         ┌──────────────────────┴──────────────────────┐
         │ MVP / hoje (Caminho A Miro)                  │ TO-BE (Caminho C)
         ▼                                              ▼
┌─────────────────────┐                      ┌─────────────────────┐
│ VectraClaw          │◄── REST estruturado──│ NAVI                │
│ meta-whatsapp       │    (intake APIs)   │ (CFN / Edge)        │
│ connector_sessions  │                      │ intent + Meta Flow  │
│ inbound-triage    │                      │ estado conversa     │
│ whatsapp_templates│                      └─────────────────────┘
│ connector_bus       │
└─────────┬───────────┘
          │ tasks / Mercator / human-triage
          ▼
┌─────────────────────┐     ┌─────────────────────┐
│ VectraClip          │     │ Hermes-Nous         │
│ secrets, sync tmpl  │     │ NÃO dono do WABA    │
│ sessões, cadência UI│     │ Telegram interno,   │
└─────────────────────┘     │ skills, MCP F2      │
                            └─────────────────────┘
```

| Pergunta | Resposta |
|----------|----------|
| Quem recebe webhook Meta hoje? | **VectraClaw** (`/api/connectors/whatsapp/webhook`) |
| Quem é o “NAVI” no produto? | Camada de **conversa + intent** (CFN); no MVP o Claw faz triage Morpheus |
| Hermes substitui NAVI no WhatsApp? | **Não** — Hermes não compete pela mesma URL WABA |
| Onde entram templates Meta? | **`whatsapp_templates`** + `connector_bus` (janela 24h) + **W14** (cadência explícita) |
| Skills Hermes vs `agent_specialties`? | Duas camadas; ponte TO-BE (ver [`CONTRACTS-AGENT-CAPABILITIES.md`](./CONTRACTS-AGENT-CAPABILITIES.md) § futuro) |

---

## 2. Bloqueadores para **iniciar execução**

### 2.1 Não bloqueiam (pode começar já)

| Item | Evidência |
|------|-----------|
| Webhook Meta + sessões | Mergeado W3–W7; doc [`META-WHATSAPP-WEBHOOK.md`](./META-WHATSAPP-WEBHOOK.md) |
| Roteamento catalog-driven | `connector_channels` + `_dispatch_inbound_task` |
| Triage Morpheus (W9) | Código `morpheus_inbound_triage.py` + migration `20260518133157` (`whatsapp` → `inbound-triage`) |
| Catálogo templates | Tabela + `POST .../whatsapp/templates/sync` |
| Reply inbound→outbound | `agent_daemon._maybe_reply_to_connector_session` + `connector_bus` |
| MCP bindings API | `agent_mcp_bindings.py` + seeds N5 |

### 2.2 Bloqueadores **duros** (resolver antes de declarar “WhatsApp E2E pronto”)

| ID | Bloqueador | Impacto | Ação no plano |
|----|------------|---------|---------------|
| ~~**B1**~~ | ~~Migration W9 não confirmada no remoto~~ | **✅ VERIFICADO 2026-05-19** — ver §8 abaixo | — |
| **B2** | **ADR inbound ainda diz “OPEN / decidir A/B/C”** | Time executa em cima de doc errado | Fase 0: fechar ADR → Accepted A (W9) |
| **B3** | **Mercator `freight-quotation` human-in-loop** | Cliente não recebe resposta útil automática | Fase 1: resposta mínima + task humana |
| **B4** | **`meta_client.py` lê `.env`** | Outbound inconsistente com vault/catalog | Fase 1: migrar send para `connector_bus` only / deprecar env path |
| **B5** | **Fora da janela 24h: sem template automático** | Follow-up comercial trava | Fase 2: W14 + UI template picker |
| **B6** | **NAVI (CFN) inexistente** | Meta Flow + intake estruturado não existem | Fase N (repo CFN) — **não bloqueia Fase 1** |

### 2.3 Bloqueadores **moles** (paralelizáveis)

| ID | Item | Track |
|----|------|-------|
| S1 | `src/mcp_server/` não existe | Hermes F2 + NAVI tools |
| S2 | `POST .../recommendations/{id}/apply` | Agent capabilities |
| S3 | R1 Gemini 403 | Athena handlers (não WhatsApp) |
| S4 | `commercial_followup_rules.channel` sem valor canônico pós-OpenClaw | Migration `meta` documentado |

**Veredito:** **Não há bloqueador para iniciar Fase 0 + Fase 1** (WhatsApp hardening no Claw). Bloqueiam “produto conversacional completo”: B3, B5, B6.

---

## 3. Plano de implementação por fases

### Fase 0 — Alinhamento e verificação (0,5–1 dia) ✅ pode começar hoje

| # | Entrega | Repo | DoD |
|---|---------|------|-----|
| 0.1 | Atualizar ADR inbound → **Accepted Opção A (W9)** | Claw | Doc sem “decidir” |
| 0.2 | Atualizar ADR canal → **NAVI = WABA conversa; Hermes ≠ WABA** | Claw | §1.2 neste plano refletido |
| 0.3 | Confirmar migration `20260518133157` aplicada | Claw/Supabase | `connector_channels.whatsapp.default_inbound_operation_type = inbound-triage` |
| 0.4 | Smoke webhook (handshake + 1 POST teste) | Claw | [`META-WHATSAPP-WEBHOOK.md`](./META-WHATSAPP-WEBHOOK.md) checklist |
| 0.5 | Criar `docs/PRD-NAVI-MESSAGING.md` (rascunho) | **CFN** ou Claw stub apontando CFN | Escopo P0-3/P0-5/P0-6 do Miro |

### Fase 1 — WhatsApp MVP no VectraClaw (3–5 dias)

**Objetivo:** mensagem inbound → triage → resposta ou fila humana; dentro da 24h texto útil.

| # | Entrega | Arquivos / área |
|---|---------|-----------------|
| 1.1 | Seed `inbound_intent_rules` replicável (template por company) | migration ou admin API |
| 1.2 | Fallback `human-triage` com notificação Clip (task visível) | VectraClip inbox/sessões |
| 1.3 | Mercator: `output_text` útil quando dados incompletos (perguntas origem/destino/peso) | `mercator.py` |
| 1.4 | Admin: botão **Sync templates** + listagem `APPROVED` | VectraClip `/admin/connectors` ✅ (2026-05-19) |
| 1.5 | Documentar janela 24h + “não auto-template” | este plano + tooltips UI |
| 1.6 | Deprecar / encapsular `meta_client.py` env path | usar só `connector_bus` + vault |

**Não inclui:** NAVI Edge, Hermes gateway WABA, Agent Builder bundle.

### Fase 2 — Templates Meta na cadência (4–6 dias)

**Objetivo:** follow-up comercial **fora da 24h** via template aprovado (W14).

| # | Entrega |
|---|---------|
| 2.1 | `workflow_steps.ferramentas` aceita `whatsapp_template_name` + `language` + `params[]` |
| 2.2 | Dispatcher cadência chama `connector_bus.reply(..., template_name_override=...)` |
| 2.3 | UI step editor: picker de `whatsapp_templates` (source catalog) |
| 2.4 | `commercial_followup_rules.channel = 'meta'` (migration CHECK se necessário) |
| 2.5 | Registro opt-in / categoria UTILITY vs MARKETING (compliance) |

**Depende:** Fase 1 estável; W14.1 `tools_catalog` já seedado (verificado M3 migration).

### Fase N0–N2 — NAVI mensageria (repo `cargo-flow-navigator`, 2–4 sprints)

| Fase | Entrega |
|------|---------|
| **N0** | PRD NAVI + contrato REST com Claw (`POST /api/quotation/intake`, etc.) |
| **N1** | Edge: intent + roteamento; opcional redirect webhook (Caminho C) |
| **N2** | Meta Flow forms (cotação estruturada); estado em NAVI, execução no Claw |

**Webhook:** só migrar URL Meta para NAVI quando N1 passar smoke — até lá **Caminho A** (Meta → Claw) permanece.

### Fase H — Hermes (paralelo, não bloqueia WhatsApp)

| # | Entrega | Depende |
|---|---------|---------|
| H1 | F2 `src/mcp_server/` (tools: tasks, intake, rag query) | — |
| H2 | F3 adapter CMA estável | H1 opcional |
| H3 | F4 gateway **Telegram interno** + SOUL.md do DB | H1 |
| H4 | Ponte skills Hermes ↔ `agent_specialties` (draft import) | P3 ADR |

**Explicitamente fora:** `hermes gateway run` como receptor do webhook WABA.

### Fase A — Agent capabilities / Athena (paralelo)

Sequência do [`CONTRACTS-AGENT-CAPABILITIES.md`](./CONTRACTS-AGENT-CAPABILITIES.md) §12: AC-1 → AC-2 → AC-4 (bundle + apply).

---

## 4. Sequência recomendada de PRs (próximas 2 semanas)

```text
Semana 1
  PR-0  docs: ADR inbound Accepted + ADR canal NAVI + este plano
  PR-1  fix: Mercator inbound copy + human-triage UX
  PR-2  ops: confirmar W9 migration + inbound rules seed multi-tenant
  PR-3  feat: Clip template sync UI polish

Semana 2
  PR-4  feat: W14 whatsapp template binding (backend)
  PR-5  feat: W14 template picker (frontend)
  PR-6  chore: meta_client → connector_bus only

Paralelo (outro dev / sessão)
  PR-N  CFN: PRD NAVI + intake API stub
  PR-H  Claw: mcp_server scaffold (F2)
```

---

## 5. Templates Meta — regra de uso (resumo operacional)

| Situação | Mecanismo | Código |
|----------|-----------|--------|
| Cliente mandou msg &lt; 24h | `type=text` free | `connector_bus._reply_whatsapp_meta` sem override |
| Cliente mandou msg &gt; 24h | **Obrigatório** template `APPROVED` | `template_name_override` + params |
| Agente terminou task e reply automático | text se in-window | `agent_daemon._maybe_reply_to_connector_session` |
| Cadência comercial / touch-planner | template explícito no step | Fase 2 W14 |
| Hermes gateway | **não envia** template WABA | usa Graph API só via Claw |

Sync: `POST /api/connectors/whatsapp/templates/sync` → lê `whatsapp_templates` na UI.

---

## 6. Decisões a cravar com Marcelo (1 reunião, 15 min)

| # | Pergunta | Default proposto |
|---|----------|------------------|
| D1 | MVP WhatsApp fica **só Claw** até NAVI N1? | **Sim** (Caminho A) |
| D2 | Hermes F4 primeiro canal? | **Telegram interno**, não WABA |
| D3 | Follow-up comercial `channel` | **`meta`** (não `nous_hermes`) |
| D4 | Prioridade vs Agent Builder bundle | **Fase 1–2 WhatsApp antes de AC-2** |

---

## 8. Verificação remota (Fase 0.3 — 2026-05-19)

Projeto Supabase `epgedaiukjippepujuzc`.

| Check | Resultado |
|-------|-----------|
| Migration `morpheus_inbound_triage` (`20260518133157`) | **Aplicada** (consta em `list_migrations`) |
| `connector_channels.whatsapp.default_inbound_operation_type` | **`inbound-triage`** ✅ |
| `connector_channels.whatsapp.fallback_operation_type` | **`human-triage`** ✅ |
| `operation_types_catalog` | `inbound-triage` → Morpheus; `human-triage` → agent NULL ✅ |
| `agent_specialties` slug `inbound-triage` | **Ativo** ✅ |
| `inbound_intent_rules` (company VECTRA) | **6 rules ativas** (priority 10–50) |
| Tasks WhatsApp 14d (`meta_whatsapp_webhook`) | 4× `inbound-triage` done, 4× `freight-quotation` done, 3× `human-triage` queued |
| `whatsapp_templates` (VECTRA) | **15 APPROVED** ativos |

**Conclusão B1:** bloqueador **removido** — roteamento W9 está vivo em produção. Tasks antigas `freight-quotation` são histórico pré-W9 ou filhas do triage.

---

## 7. Changelog

| Data | Versão |
|------|--------|
| 2026-05-19 | 1.0 — Plano mestre; mapa de docs; bloqueadores; fases 0–A/N/H |
| 2026-05-19 | 1.1 — §8 verificação remota Fase 0.3 (B1 fechado) |
