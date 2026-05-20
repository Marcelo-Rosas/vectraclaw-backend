# ADR — Canal Cliente: Hermes Gateway (Nous Research) — decisão fechada

> **Status:** **Accepted — stack híbrida revisada 2026-05-19.**  
> **Decisão:** OpenClaw **rejeitado**. **WhatsApp Business = NAVI (conversa) + VectraClaw `meta-whatsapp` (Graph API, webhook, templates).** Hermes-Nous = runtime/skills/MCP/Telegram interno — **não** receptor do webhook WABA.  
> **Plano de execução:** [`PLAN-CANAL-MENSAGERIA-NAVI-HERMES.md`](./PLAN-CANAL-MENSAGERIA-NAVI-HERMES.md)  
> **Owner:** Marcelo (produto). **Data original:** 2026-05-17. **Revisão:** 2026-05-19 (NAVI + templates Meta).
> **PRDs relacionados:** [`PRD-NOUS-HERMES-INTEGRATION.md`](./PRD-NOUS-HERMES-INTEGRATION.md), [`PRD-ATHENA-HR-TRAJECTORY-INGEST.md`](./PRD-ATHENA-HR-TRAJECTORY-INGEST.md)
> **ADR pai:** [`ADR-VEC-MAPEAR-ANALISAR-AUTOMATIZAR.md`](./ADR-VEC-MAPEAR-ANALISAR-AUTOMATIZAR.md) — depende de **P3** (agent_skills × agent_specialties), **P6** (multi-tenant primeira venda externa), **P12** (UI Mapeamento/Orquestração), **D13** (UI é fonte de dados). Acoplamento detalhado em §13.
> **Regras de ouro aplicadas:** [[mirror-before-create]] (#1) — todos os fatos sobre schema re-verificados via SQL em 2026-05-17. [[metadata-driven-no-hardcode]] (#2) — violações pontuais listadas em §13.2.

---

## 1. Context

VectraClaw precisa de **canal cliente conversacional** (WhatsApp Business como principal, Telegram secundário) pra cliente final da Vectra Cargo interagir com agentes — cotação de frete, status de CT-e, onboarding self-service, follow-up comercial. Sem isso, todo cliente precisa abrir o dashboard VectraClip, o que limita adoção.

Três abordagens foram avaliadas (2026-05-17). **Decisão revisada 2026-05-19:**

| Camada | Escolha |
|--------|---------|
| **WhatsApp WABA** | **NAVI** (mensageria/intent/Flow no `cargo-flow-navigator`) + **transporte Meta** no VectraClaw (`meta-whatsapp`, webhook, `whatsapp_templates`) |
| **MVP enquanto NAVI não sobe** | Caminho A Miro: Meta → webhook **VectraClaw** + Morpheus `inbound-triage` (W9) |
| **Hermes-Nous** | Runtime F1–F3 + MCP F2 + gateway **Telegram interno** (F4) — **não** substitui NAVI no WhatsApp |
| ~~OpenClaw~~ | **REJEITADO** |
| ~~Hermes como único canal WhatsApp~~ | **REJEITADO** (correção pós-decisão inicial B) |

### 1.1 Estado atual (verdade-base)

Schema VectraClaw já registra a intenção de canal:

| Tabela | Coluna | Valores aceitos | Significado |
|---|---|---|---|
| `commercial_followup_rules` | `channel` | `openclaw`, `email`, `meta` | Legado: `openclaw` era reserva do gateway descartado — **migration TO-BE:** acrescentar `nous_hermes` (ou alias `hermes`) e migrar regras novas |
| `commercial_followup_runs` | `channel` | mesmo CHECK | Histórico de envio |
| `commercial_message_events` | `channel` | mesmo CHECK | Log de eventos |
| `adapter_catalog` | `slug` | inclui `meta-whatsapp`, `mcp-slack`, `mcp-gmail`, `mcp-imap`, `mcp-github` | **Infraestrutura de conector já existe** |

**Implicação:** o conector **`meta-whatsapp`** é a SSOT de transporte WABA no VectraClaw. **NAVI** orquestra conversa e chama APIs de intake no Claw; **Hermes** não registra o webhook Meta. Templates aprovados: tabela `whatsapp_templates` + sync Graph API (ver plano §5).

### 1.2 O que NÃO está em jogo

- ❌ **Runtime interno** (Hermes-Nous como provider de inferência pros daemons) — decidido em `PRD-NOUS-HERMES-INTEGRATION.md`. Não conflita com OpenClaw
- ❌ **MCP server VectraClaw** (Fase 2 do mesmo PRD) — é zero-arrependimento, **ambas as opções A/B consomem**
- ❌ **Trajectory ingest** (`PRD-ATHENA-HR-TRAJECTORY-INGEST.md`) — uso interno, ortogonal

Esta decisão é **exclusivamente sobre quem responde no WhatsApp/Telegram do cliente final**.

---

## 2. Forças em jogo (decision drivers)

| # | Driver | Peso | Por quê |
|---|---|---|---|
| F1 | **Branding / IP** | Alto | Vectra Cargo vende a si, não a "Nous". Mensagem ao cliente final deve parecer Vectra puro. Hermes Gateway expõe terceiros (mesmo configurável, há rastros) |
| F2 | **Multi-tenant escalabilidade** | Crítico | Vectra tem N companies clientes (e meta de crescer). Solução precisa escalar pra 50-500+ tenants sem 1 container por tenant |
| F3 | **Time-to-value (MVP)** | Alto | Cada sprint que passa sem canal cliente é demanda perdida. Quem entrega primeiro um POC funcional vence |
| F4 | **Custo operacional** | Médio | Mensal. Cloudflare Worker idle (~$5/mo) vs container 24/7 (~$15-30/mo) por tenant |
| F5 | **Controle do prompt** | Alto | Frase exata que o cliente lê precisa ser auditável e ajustável sem mexer em código terceiro |
| F6 | **LGPD / soberania de dado** | Crítico | Conversa cliente contém PII (CNPJ, telefone, endereço de entrega, CT-e). Cada hop em terceiro = risco regulatório |
| F7 | **Skill creation autônoma** | Médio | Hermes aprende skills observando uso. Pode ser arma competitiva ou caos sem governance |
| F8 | **Reaproveitamento do MCP server da F2** | Alto | Ambas as opções consomem o mesmo MCP. Não diferencia |
| F9 | **Manutenção / debug** | Médio | Time pequeno hoje. Stack que time domina (TypeScript via cargo-flow-navigator) reduz risco operacional |
| F10 | **Reversibilidade** | Alto | Trocar de OpenClaw = reescrever tudo. Trocar de Hermes = perde gateway, mantém MCP+adapter |
| F11 | **Aderência ao schema existente** | Médio | `channel='openclaw'` está em CHECK constraint em 3 tabelas. Adotar Hermes Gateway exige rename/migration desses CHECKs |
| F12 | **Maturidade do produto Hermes** | Médio | Hermes-Nous é v0.x — APIs podem mudar. OpenClaw é produto interno, mudança controlada |

---

## 3. Opção A — OpenClaw (build próprio TypeScript)

### 3.1 Arquitetura proposta

```
[Cliente WhatsApp] → [Meta Business API] → [OpenClaw Gateway (Cloudflare Worker)]
                                                       │
                                                       ▼
                                          [main agent (router intent)]
                                                       │
                                  ┌────────────────────┼────────────────────┐
                                  ▼                    ▼                    ▼
                          [cotacao-agent]     [financeiro-agent]    [motorista-agent]
                                  │                    │                    │
                                  └────────────────────┼────────────────────┘
                                                       ▼
                                           [MCP Server VectraClaw]
                                                       │
                                                       ▼
                                       [Supabase / api.py / daemons]
```

14 agentes nomeados (documentados na skill `vectra-mcp-builder`):
`main`, `brain-agent`, `cotacao-agent`, `financeiro-agent`, `motorista-agent`, `inbox-agent`, … (lista completa precisa ser fechada)

### 3.2 Stack proposta

- **Linguagem:** TypeScript (alinhado com `cargo-flow-navigator`)
- **Deploy:** Cloudflare Workers (Worker por company OU tenant resolution via JWT no roteamento)
- **Auth cliente:** Supabase Auth + phone-based pairing (signup self-service por WhatsApp)
- **MCP:** consome `src/mcp_server/` da Vectra via streamable HTTP transport
- **Conector WhatsApp:** reusa `adapter_catalog.slug='meta-whatsapp'` (já existente)
- **Branding:** 100% Vectra. Nome OpenClaw exposto ou agentes nomeados (Hera, Atlas, Hermes-VectraClient — definir)

### 3.3 Prós

- ✅ **Branding total** — Vectra puro, sem "powered by"
- ✅ **Multi-tenant nativo** — Cloudflare Worker isola por subdomain/route, custo idle baixo
- ✅ **Schema aderente** — `channel='openclaw'` já reservado em 3 CHECKs
- ✅ **Controle total do prompt** — você escreve cada agente
- ✅ **LGPD favorável** — dado não sai do perímetro Vectra+Cloudflare+Supabase (já LGPD-compatíveis)
- ✅ **Reversibilidade alta** — código próprio, troca de stack futura é controlada

### 3.4 Contras

- ❌ **Time-to-value lento** — 2-3 sprints só pro gateway + 1 agente
- ❌ **14 agentes pra escrever** — muito código antes de validar produto
- ❌ **Skill creation manual** — sem aprendizado autônomo nativo (pode adicionar depois com trajectory + Athena HR)
- ❌ **Você mantém tudo** — upgrade de Meta API, parser de webhook, retry, dead letter queue
- ❌ **Sem multi-canal nativo** — adicionar Telegram = mais código (vs Hermes que já tem)

### 3.5 Risco principal

Time pequeno entregando POC pode levar 3+ sprints pra ter algo testável com cliente. Janela de oportunidade pode fechar (concorrência, mudança de prioridade).

---

## 4. Opção B — Hermes Gateway (Nous Research como canal cliente)

### 4.1 Arquitetura proposta

```
[Cliente WhatsApp] → [Hermes Gateway (container Docker per company)] → [Hermes Agent]
                            │                                              │
                            │ (pairing DM + allowlist)                     ▼
                            │                              [MCP Server VectraClaw]
                            │                                              │
                            └─→ [Telegram, Discord, Signal, ...]           ▼
                                                              [Supabase / api.py]
```

1 agente Hermes camaleônico cuja personalidade muda por `SOUL.md` + skills + system prompt. Multi-canal nativo (~20+ plataformas).

### 4.2 Stack proposta

- **Runtime:** Hermes-Nous CLI em container Docker (mesmo do `nous-hermes-runtime` do PRD principal, mas instance separada com `gateway run`)
- **Deploy:** 1 container por company (workaround pra falta de RBAC nativo)
- **Auth cliente:** pairing DM com código de 8 chars (TTL 1h, lockout 5 tentativas)
- **MCP:** consome `src/mcp_server/` da Vectra via `hermes mcp add --url`
- **Conector WhatsApp:** Hermes Gateway tem driver próprio, mas pode reusar `meta-whatsapp` via MCP
- **Branding:** "Vectra Bot" com SOUL.md custom — mas a stack é Hermes

### 4.3 Prós

- ✅ **Time-to-value rápido** — 1 sprint pro POC (subir container + pairing + 1 skill)
- ✅ **Multi-canal nativo** — WhatsApp+Telegram+Discord+Slack+Signal sem código adicional
- ✅ **Skill creation autônoma** — agente aprende padrões de uso, alimenta Athena HR
- ✅ **Trajectory export nativo** — JSONL pronto pra fine-tune
- ✅ **Tools 70+ built-in** — busca web, visão, geração de imagem, TTS prontos
- ✅ **Aprovação smart** — LLM avalia risco de comandos automaticamente

### 4.4 Contras

- ❌ **Sem RBAC multi-tenant nativo** — 1 container por company escala mal em 50+
- ❌ **Branding terceiro visível** — "Hermes (powered by Nous)" rastreável (configurável mas com esforço)
- ❌ **Controle indireto do prompt** — SOUL.md + skills (em vez de código próprio)
- ❌ **Schema CHECK colide** — `channel='openclaw'` precisa virar `channel IN ('hermes', 'openclaw', ...)` ou rename completo (migration intrusiva)
- ❌ **LGPD risk** — cada inferência via Nous Portal/OpenRouter = hop adicional de PII
- ❌ **Reversibilidade baixa** — pairing, allowlist, skill creation acumulam estado em `~/.hermes/` por tenant
- ❌ **Maturidade incerta** — Hermes-Nous é projeto novo, API CLI pode mudar

### 4.5 Risco principal

Escalar pra 50+ companies vira problema de ops (orquestração de containers, rotação de credenciais por tenant). Migrar a partir desse ponto seria caro.

---

## 5. Opção C — Híbrido (Hermes interno + OpenClaw cliente)

### 5.1 Arquitetura

```
USO INTERNO (equipe Vectra):
   [Marcelo + equipe via Telegram] → [Hermes Gateway (1 container)] → [MCP Server VectraClaw]

USO CLIENTE FINAL:
   [Cliente WhatsApp] → [Meta API] → [OpenClaw Gateway (Cloudflare Worker)] → [MCP Server VectraClaw]
```

Mesmo MCP server alimenta os dois. Diferença é só o gateway.

### 5.2 Prós

- ✅ Aproveita rapidez de Hermes pra valor imediato (equipe Vectra opera mais rápido)
- ✅ Mantém branding Vectra puro pro cliente final
- ✅ MCP server F2 do PRD principal é reaproveitado por ambos — zero custo marginal
- ✅ Trajectory de uso interno alimenta Athena HR e informa design dos agentes OpenClaw
- ✅ Permite validar valor antes de escrever OpenClaw todo
- ✅ Reversibilidade alta — Hermes pode ser desligado a qualquer momento sem impactar cliente final

### 5.3 Contras

- ❌ **Dois sistemas a manter** — operação duplicada
- ❌ **Risco de divergência** — uso interno descobre padrão que OpenClaw não consegue reproduzir
- ❌ **Investimento dividido** — sprints divididos entre as duas stacks

### 5.4 Risco principal

Sucesso rápido do Hermes interno cria gravidade que atrasa investimento em OpenClaw. Cliente final fica indefinidamente sem canal próprio.

---

## 6. Comparação consolidada

| Driver | Peso | A. OpenClaw | B. Hermes Gateway | C. Híbrido |
|---|---|---|---|---|
| F1. Branding / IP | Alto | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ (no cliente) |
| F2. Multi-tenant escalável | Crítico | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ (no cliente) |
| F3. Time-to-value MVP | Alto | ⭐ | ⭐⭐⭐ | ⭐⭐⭐ (interno) / ⭐ (cliente) |
| F4. Custo operacional | Médio | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ |
| F5. Controle do prompt | Alto | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ (no cliente) |
| F6. LGPD / soberania | Crítico | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ (no cliente) |
| F7. Skill creation autônoma | Médio | ⭐ (manual) | ⭐⭐⭐ | ⭐⭐ (interno aprende) |
| F8. Reaproveitamento MCP F2 | Alto | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| F9. Manutenção / debug | Médio | ⭐⭐ (você mantém) | ⭐⭐ (Nous mantém core) | ⭐ (dois stacks) |
| F10. Reversibilidade | Alto | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ |
| F11. Aderência schema | Médio | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ |
| F12. Maturidade produto | Médio | ⭐⭐⭐ (você decide) | ⭐⭐ (v0.x) | ⭐⭐ |

**Leitura:** Opção C ganha em quase todos os drivers críticos (F1, F2, F6) mas perde em F9 (operação dupla). Opção B ganha em F3/F7 (velocidade + autonomia) mas perde em F1/F2/F6/F11. Opção A é a mais conservadora mas a mais lenta.

---

## 7. Decisão adotada (2026-05-19)

**Opção B — Hermes Gateway** para canal cliente (interno **e** cliente final na mesma stack).

Sequência de entrega (atualizada):

1. **Fases 1–3** do [`PRD-NOUS-HERMES-INTEGRATION.md`](./PRD-NOUS-HERMES-INTEGRATION.md) — runtime, MCP server Vectra, adapter CMA (pré-requisito).
2. **Fase 4 (canal)** — `hermes gateway run` por company (ou estratégia multi-tenant em `companies.context_json` quando escala exigir); SOUL.md / branding Vectra; pairing + allowlist em catálogo (não hardcode).
3. **Gates §8** — permanecem como **validação operacional** (custo, LGPD, branding), não como critério para escolher OpenClaw de novo.
4. **Schema** — migration `channel` CHECK: incluir `nous_hermes`; novas regras comerciais usam esse valor; `openclaw` legado até backfill (opcional rename de rows históricas).

---

## 8. Gates objetivos pra fechar este ADR

Decisão final só após **todos os gates respondidos com dado**, não com opinião:

| Gate | Pergunta | Como medir | Quem responde |
|---|---|---|---|
| G1 | Custo real Hermes-Nous por mensagem cliente? | Após 30d de uso interno: total OpenRouter $ / total mensagens. Projetar pra 1k mensagens/dia/company × N companies | Métricas OpenRouter + trajectory ingest |
| G2 | Taxa de sucesso de intent routing no Hermes interno? | Athena HR mede `final_success` / total trajectories no `agent_prompt_history`. Threshold: ≥ 85% pra considerar Hermes viável pra cliente | PRD Trajectory Ingest |
| G3 | Volume real esperado de tenants em 12 meses? | Forecast de vendas Vectra Cargo. <10 = container-per-tenant viável; ≥50 = obrigatório multi-tenant nativo | Marcelo |
| G4 | Branding "Hermes" é aceitável pro cliente B2B fitness/logística? | Teste qualitativo com 3 clientes piloto: "qual sua reação ao mensageiro ser Hermes (Nous Research)?" | Marcelo / Hermes interno como POC |
| G5 | LGPD: trafegar PII de cliente por OpenRouter+Nous é aceitável? | Consulta jurídica + DPA da OpenRouter + DPA da Nous (se aplicável). Threshold: ambos com cláusulas EU/BR-compatíveis | Marcelo + jurídico Vectra |
| G6 | Arquitetura gateway aguenta N companies? | Load test Hermes gateway + roteamento (container-per-tenant vs roteador único). Threshold definido em Fase 4 | Engenharia pós-F3 |
| G7 | Skill creation autônoma do Hermes converge ou diverge? | Após 30d: contagem de skills geradas. Análise qualitativa: quantas são úteis vs ruído? | Athena HR via trajectory |
| G8 | ~~Time para 2 stacks~~ | **N/A** — decisão única stack Hermes | — |

**Critério de fechamento (pós-decisão):** gates medem **viabilidade da Opção B**, não reabrem OpenClaw. Gate vermelho em G5 (LGPD) → mitigação (DPA, anonimização, modelo on-prem/Ollama no adapter) — **não** retorno a OpenClaw.

---

## 9. Consequências previstas

### 9.1 Se decidir Opção A (OpenClaw)

- ✅ Vectra dona de stack inteira do canal cliente
- ✅ Schema `channel='openclaw'` mantém-se, zero migration intrusiva
- ❌ 2-3 sprints sem canal cliente ativo
- ❌ Skill creation precisa ser construída do zero (ou postada pós-Athena HR)
- ❌ Adicionar novos canais (Discord, Slack pro cliente) = código adicional

### 9.2 Se decidir Opção B (Hermes Gateway)

- ✅ POC em 1 sprint, multi-canal de graça
- ✅ Skill creation + trajectory nativa
- ❌ Migration `channel IN ('hermes', ...)` em 3 CHECKs (intrusiva)
- ❌ 1 container Docker por company — operação pesada acima de 20-30 tenants
- ❌ Branding terceiro visível
- ❌ PII de cliente trafega por Nous Portal/OpenRouter

### 9.3 Se decidir Opção C (Híbrido)

- ✅ Valor imediato interno + branding puro pro cliente
- ✅ MCP server F2 single source of truth pra ambos
- ✅ Trajectory de uso interno informa design dos agentes OpenClaw
- ❌ Operação dupla — duas stacks pra manter
- ❌ Risco de divergência funcional entre os dois
- ❌ Investimento dividido — pode atrasar entrega final do OpenClaw

---

## 10. Próximas ações (pós-decisão B)

1. ~~Decidir OpenClaw vs Hermes~~ — **feito (Hermes).**
2. **Executar PRD Fases 1–3** — runtime + MCP + adapter.
3. **Especificar Fase 4 (canal)** no PRD — gateway, pairing, SOUL.md, integração `meta-whatsapp` / drivers Hermes.
4. **Migration canal:** `ALTER CHECK` em `commercial_followup_*` para incluir `nous_hermes`.
5. **Arquivar referências OpenClaw** — skill `openclaw-integration.md` = legado; não usar em novos PRs.
6. **Coletar gates §8** durante dogfood (custo, LGPD, branding) — mitigar riscos da Opção B, não reverter stack.

---

## 11. Glossário

- **Canal cliente:** WhatsApp Business / Telegram / Web Chat pelo qual cliente final da Vectra Cargo (ex: dono de academia, gestor de loja) conversa com agente
- **Multi-tenant nativo:** capacidade de servir N companies sem instanciar 1 processo dedicado por company
- **MCP server VectraClaw:** `src/mcp_server/` da Fase 2 do PRD principal — expõe tasks, quotes, clients, RAG como tools consumíveis por agente externo
- **Adapter catalog:** tabela `vectraclip.adapter_catalog` com conectores externos (`meta-whatsapp`, `mcp-slack`, etc.) e LLMs. Padrão metadata-driven
- **SOUL.md:** arquivo de personalidade padrão do Hermes — define tom, restrições, contexto fixo

---

## 12. Anexos

- Plano de execução interno: `~/.claude/plans/graceful-sparking-flamingo.md`
- ~~Skill OpenClaw~~ (legado, não usar): `~/.claude/skills/vectra-mcp-builder/references/openclaw-integration.md`
- Documentação Hermes-Nous: https://hermes-agent.nousresearch.com/docs
- ADR irmão: `docs/ADR-VEC-MAPEAR-ANALISAR-AUTOMATIZAR.md`
- Schema `commercial_followup_rules.channel`: `supabase/migrations/20260506025418_remote_schema.sql:3718`

---

## 13. Acoplamento ao ADR pai (MAPEAR → ANALISAR → AUTOMATIZAR)

### 13.1 Dependências cruzadas

Este ADR **não pode ser fechado** sem antes ter respostas dos seguintes itens do ADR pai:

| Item ADR pai | Conexão com este ADR | Onde aparece aqui |
|---|---|---|
| **D13** — UI é fonte de dados | Toda config do gateway (allowlist, ativação, channel routing) precisa vir de tabela editável via UI, não de arquivo/env | §10.4 corrigido; §13.2 violações |
| **P3** — `agent_skills` × `agent_specialties` + bug `/agents/{id}?tab=skills` | Opção B (Hermes) faz skill creation autônoma — quem é dono dessas skills, como persistem, como auditam? Mesma colisão que PRD-NOUS-HERMES R9. ADR pai P3 foi expandido em 2026-05-17 incluindo cenário "skills criadas autonomamente por providers externos" | §4.3 prós Hermes; §5.2 prós Híbrido |
| **P6** — Multi-tenant primeira venda externa (bloqueia pós-D) | F2 (Multi-tenant escalabilidade) é driver crítico aqui. P6 do ADR pai precisa ser respondido **antes** dos gates G3/G6 deste ADR | §2 F2; §8 G3, G6 |
| **P12** — UI Mapeamento/Orquestração SPA única ou apps separados | Canal cliente é **outra superfície de UI** (admin do gateway + monitoring). Decisão de SPA do P12 afeta onde a UI do gateway mora | §3.2 OpenClaw stack; §6.4 UI mínima do Hermes Gateway |
| Memory `vectraclaw-3-modules-business-model` (renomeada 2026-05-17 — antes `vectraclaw-2-modules`) | Canal cliente serve principalmente o **Módulo 2 (Orquestração)** — interface conversacional da orquestração contínua. Modo 3 (Project on-demand, GymSite) usa canais próprios do cliente final (relatório PDF, dashboard de entregável) e não depende deste ADR | §1 Context (implícito) |
| Memory `agent-hiring-ritual` | Opção A propõe 14 agentes nomeados — cada um precisa de ritual completo (perfil §6.1 do ADR pai, skills, responsabilidades, métricas)? Ou são "skills" de 1 agente? Ambiguidade arquitetural a resolver antes de §3 virar implementação | §3.1 lista de 14 agentes |
| Memory `mirror-before-create` (#1) | Toda afirmação sobre schema neste ADR foi re-verificada via SQL 2026-05-17 (CHECK em 3 tabelas, slugs do adapter_catalog, ausência de `companies.slug`, existência de `agent_prompt_history`) | §1.1 + §10.4 corrigido |
| Memory `metadata-driven-no-hardcode` (#2) | Violações listadas em §13.2 | §13.2 |

### 13.2 Violações da Regra de Ouro #2 (NO HARDCODE) no próprio ADR

Re-varredura à luz de [[metadata-driven-no-hardcode]] revelou itens hardcoded neste ADR (mesmos padrões corrigidos no PRD-NOUS-HERMES §11.1):

| # | Hardcode no ADR | Tabela espelho | Fix proposto |
|---|---|---|---|
| C1 | "allowlist = 3 emails" (§10.4) | Catálogo (nova `gateway_allowlist` ou `companies.context_json.gateway_users`) | Allowlist vive em tabela editável via UI; gateway lê do DB no boot |
| C2 | SOUL.md como arquivo fixo em container (§4.2, §10.4) | `agent_adapter_configs.field_values_json.soul_md` ou `agent_specialty_configs.system_prompt` (pattern existente da casa) | SOUL.md gerado do DB no startup (consistente com `bootstrap_config()` proposto no PRD §6.1) |
| C3 | "1 container por company" (§4.2, §5.1) — premissa de deploy | `companies.context_json.gateway_deployment` ou tabela `tenant_runtimes` | Decisão de deploy per company é metadata (não constante no compose); resolver pós-P6 do ADR pai |
| C4 | Worker per company vs JWT tenant resolution (§3.2 OpenClaw) | Mesma — `companies.context_json` ou `tenant_routing_strategy` | Estratégia escolhida vira config, não código |
| C5 | "14 agentes nomeados" lista interna do OpenClaw (§3.1) | Catálogo `openclaw_agents` (a criar) ou reusar `agents` existente | Lista de agentes do OpenClaw vive em DB, não em código TypeScript |

**Itens que NÃO são violações (estimativas/thresholds aceitáveis):**
- §2 F4 custos ($5/mo, $15-30/mo) — hipóteses a validar nos gates
- §8 G2/G3/G6 thresholds (≥85%, <10 vs ≥50, 1000 req/s) — critérios de decisão registrados intencionalmente

### 13.3 Pendência proposta pro ADR pai

**P14** (proposta a Marcelo): "Canal cliente — OpenClaw (build próprio) vs Hermes Gateway vs Híbrido. Decisão delegada a `ADR-VEC-CANAL-CLIENTE-OPENCLAW-VS-HERMES.md`; gates §8 fecham após Fase 3 do PRD-NOUS-HERMES + 30d de dogfood interno." Bloqueia: produção do canal cliente; depende de: P3, P6, P12.

### 13.4 Sincronização com PRD-NOUS-HERMES-INTEGRATION

Mudanças aplicadas ao PRD em 2026-05-17 (sessão de auditoria das regras de ouro) afetam este ADR:

- PRD §11.1 H1-H7: config do runtime Hermes vive em `adapter_catalog`/`llm_models`/`agent_adapter_configs`. **Consequência aqui:** Opção B (Hermes Gateway) também herda essa disciplina — `gateway run` precisa carregar pairing/allowlist/SOUL.md do DB no startup, não de `~/.hermes/` ou env.
- PRD §6.4 (UI mínima): se Opção B for adotada parcialmente (Híbrido), UI de admin do gateway mora junto com a UI do runtime (rota `/admin/runtimes` ou `/admin/connectors`).
- PRD ADR pai P3 expandido: skill creation autônoma do Hermes já está catalogada como faceta de P3 — não é pendência separada deste ADR.
