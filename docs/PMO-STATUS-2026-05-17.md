# PMO Status Report — VectraClaw / VectraClip
## 2026-05-17 (madrugada — pós-maratona ~50 PRs + signup self-service)

> **Autor:** Claude Opus 4.7 (session com Marcelo)
> **Cliente piloto:** Vectra Cargo (a ser criada via UI pelo Marcelo)
> **Tenant SaaS atual:** VECTRA IA SERVICES (única company existente)
> **Honestidade:** doc consolidado que o Marcelo cobrou na madrugada. Promessa não cumprida durante o dia, registrada aqui agora.
> **Status do dogfood Vectra Cargo:** **pronto pra você criar via UI** após Cloudflare Pages build (#33) terminar (~2min).

---

## 1. Executive Summary (verdade dura)

| Dimensão | Estado real | Funciona | Falta |
|---|---|---|---|
| **Backend** | ~90% pra MVP P1 | Pipeline PMBOK, RAG dual, 11 daemons, audit log integrado em 8 endpoints, RLS hardened em 4 tabelas, Daedalus BPMN, **self-service signup PR #177 ✅** | LLM handlers Mercator/Plutus/Hodos sem prompt rico persistido; cadeia upstream sem entry points (sem freight quotation endpoint, sem CRM webhook) |
| **Frontend** | ~35% pra MVP P1 | CRUD Goals/Tasks/SIPOC/Agents, RAG upload, Council list, **signup form completo PR #33 ✅**, UserMenu Perfil/Configurações OK (PR #32) | Pipeline PMBOK não tem UI dispatch — Goal criado fica órfão sem botão "Classificar/Charter/Risk-Register"; B7-bis intencional broken bloqueia /agents/recommendations |
| **DB** | 100% schema modelado | 51+ tabelas + RLS + GRANTs + 9 catalogs metadata-driven; audit_log nascente | Vectra Cargo (nova company) será criada via signup; demais dados operacionais ainda vazios |
| **Operações** | 11 daemons online | Auto-start Task Scheduler, logs separados, audit trail funcionando | R1 Gemini 403 paralisa 7 de 9 handlers Athena + Oracle research; SMTP bloqueado por Cloudflare WARP (R3); routines table vazia |

**Veredito sincero:** entrega de hoje da signup self-service **finalmente fecha o gap arquitetural #1 do dogfood** (criar empresa via UI). Mas backend continua sentando em capacidade que o frontend não dispara (pipeline PMBOK). Próximo passo crítico ainda é Lote 3 frontend de dispatch (estimativa: 40-60h).

---

## 2. O que mudou desde a última versão deste doc (madrugada 2026-05-17)

| Mudança | PRs |
|---|---|
| **Backend self-service signup atomic** (POST /api/auth/signup com create_user auto-confirm + company + app_user + JWT app_metadata + audit_log + rollback parcial) | backend #177 |
| Migration `companies.mission` text field (corrige mentira do response anterior que retornava mission echoed mas não persistia) | backend #177 |
| **Frontend signup form completo** (Login.tsx 5 campos com Zod, AuthContext.signup, endpoint client) | frontend #33 |
| Outra sessão paralela: fix UserMenu Perfil/Configurações (apontam pra /settings/user) | frontend #32 |
| Outra sessão paralela: fix operation-types adapter shape | frontend #31 |

**Trabalho coordenado:** worktree isolado em `/tmp/vectraclip-signup` pra signup form, respeitando a sessão paralela que estava editando UserMenu. Multi-sessão funcionou — `SESSOES-EM-CURSO.md` semáforo cumpriu seu papel.

---

## 3. Maturidade real por camada (auditoria 2026-05-16 + signup hoje)

| Camada | Maturidade | Status |
|---|---|---|
| **1 Governance** | 95% (5/7 RESOLVED + 2 ADR parqueado) | audit_log, risks lifecycle, RACI invalidado, WS broadcast + RBAC catalog parqueados em ADR |
| **2 Admin** | **100%** | RLS hardening, cache warning, 3 ADRs — todos os 5 gaps fechados |
| **3 Comercial/Operações** | ~50% (Kronos 100%, Hermes parcial, signup novo) | Mercator/Plutus/Hodos handlers TODO P2; cotação dogfood ADR; cadeia upstream sem entry points |
| **4 Estratégia** | 70% (Mnemos+Daedalus OK; Athena+Oracle bloqueados R1) | Daedalus pipeline completo, audit log foundation, risks state machine |

---

## 4. Backlog priorizado pro MVP P1 vendável

### 4.1 BLOQUEADORES P0

| # | Item | Owner | Esforço | Bloqueia |
|---|---|---|---|---|
| 1 | **R1 Gemini 403** resolver (Google Cloud OU pivot Claude) | **Marcelo** | ? | 7 handlers Athena + Oracle research + future Daedalus LLM |
| 2 | **Lote 3 Frontend — UI dispatch pipeline PMBOK** (botão "Classificar Goal" → Athena classify → ver progresso task → próximo botão) | sessão frontend separada | 40-60h | MVP demo end-to-end |

### 4.2 ALTO valor

| # | Item | Esforço |
|---|---|---|
| 3 | Cloudflare WARP SMTP fix (Resend recomendado) | 3h |
| 4 | Athena handlers Python fallback sem Gemini | 4h por handler |
| 5 | Executor real de `athena-recommend` (destrava B7-bis) | 4-6h |

### 4.3 MÉDIO valor

| # | Item | Esforço |
|---|---|---|
| 6 | Mercator/Plutus/Hodos prompts ricos | 1-2h cada |
| 7 | Heartbeats retention TTL 30d | 1h |
| 8 | UI Risk Matrix consumindo G1.2 lifecycle | 4h |
| 9 | Vault audit (compliance ADR existe) | 4-6h + 8-12h fix |

### 4.4 BAIXO valor / parqueado em ADR

- RBAC catalog table
- WS broadcast governance
- `adapter_field_type` catalog
- `agent_domains` CRUD via UI

---

## 5. Risk Register operacional (atualizado pós-signup)

| ID | Risco | Prob | Imp | Score | Resposta | Owner |
|---|---|---|---|---|---|---|
| R1 | Gemini 403 PERMISSION_DENIED | 1.0 | 9 | 9.0 | Não tratado | **Marcelo** |
| R2 | Frontend sem dispatch PMBOK | 1.0 | 8 | 8.0 | Não tratado | **frontend session** |
| R3 | Cloudflare WARP bloqueia SMTP | 1.0 | 7 | 7.0 | **Mitigado parcial:** signup usa `admin.create_user(email_confirm=True)` em vez de sign_up — não depende SMTP | **Marcelo** ou pivot Resend |
| R4 | Daemons sem load_dotenv (VEC-414) | 0.4 | 7 | 2.8 | Workaround manual | tech debt |
| R5 | Image Docker stale após `compose up -d` | 0.7 | 5 | 3.5 | Documentado | docs OK |
| R6 | 502 intermitente Cloudflare tunnel | 0.3 | 6 | 1.8 | Investigado, sem causa raiz | monitorar |
| R7 | Multi-sessão Claude pisa em working tree | 0.5 | 4 | 2.0 | `SESSOES-EM-CURSO.md` + worktrees | **mitigado — comprovado hoje no signup** |

**Top 3 a tratar:** R1, R2, R3. Esses 3 valem 24 score points de 33.1 total.

---

## 6. Decisões aguardando Marcelo (atualizado)

| # | Decisão | Status |
|---|---|---|
| D1 | R1 Gemini — Google Cloud OU pivot Claude | aberta — bloqueia Camada 4 |
| D2 | Lote 3 Frontend — quando começar? | aberta — define MVP timeline |
| D3 | SMTP fix: Resend vs WARP exception vs Postmark? | aberta (mas R3 mitigado pra signup) |
| D4 | Daedalus LLM branch — esperar R1? | recomendação: esperar |
| D5 | Vault audit — quando priorizar? | recomendação: Q2 |
| D6 | **Plano dogfood pós-signup** — vai criar Vectra Cargo agora? | **aberta — pronta pra você executar via UI** |

---

## 7. Plano dogfood imediato (segunda-feira ou agora)

### Passo 1 — Aguardar Cloudflare Pages deploy

PR #33 frontend em build. Acompanhar:
<https://dash.cloudflare.com/?to=/361e9e1383bfa8e95e1db54e6c2a3bba/pages/view/vectraclip-frontend/e5b7dacc-0644-4fb6-86dd-045cb13ff29d>

ETA: 2-3min após este doc.

### Passo 2 — Marcelo cria Vectra Cargo via UI

1. Abrir <https://app.vectraclip.vectracargo.com.br/login>
2. Clicar "Criar conta + empresa"
3. Preencher:
   - **Seu nome:** algo tipo "Marcelo Cargo" (você decide)
   - **Nome da empresa:** "Vectra Cargo" (literal)
   - **Email:** novo email @vectracargo.com.br (você inventa — ex: `cargo@vectracargo.com.br`, `frete@...`, etc.)
   - **Senha:** mínimo 8 chars
   - **Missão:** opcional ("cotação de frete em 5 min" pra ficar fiel ao ADR cotação-dogfood)
4. Submit → login automático → `/dashboard` da Vectra Cargo

### Passo 3 — Verificar tenant novo criado

- Conferir Sidebar mostra "Vectra Cargo" como company atual
- GET /api/companies/<vectra-cargo-id> retorna `name: "Vectra Cargo"`, `tier: "trial"`, `mission` populada (se preencheu)
- audit_log captura `action='auth.signup'` com payload completo

### Passo 4 — Tentar pipeline PMBOK (vai bater no Lote 3 missing)

- Criar Goal "Cotação de Frete" via `/goals/new`
- **Vai parar aqui** — sem botão "Classificar com Athena" (gap conhecido R2)
- Documentar onde quebra (validação do ADR cotação-dogfood)

### Passo 5 — Continuar dogfood até onde der

- `/sipoc/management` ou `/sipoc/wizard` — mapear processo SIPOC (Lote 2 FE-A/B/C já merged)
- `/risks` — pode criar manual + transicionar status (G1.2 funciona)
- `/admin/specialties`, `/admin/connectors`, `/admin/models` — admin já completo

---

## 8. O que ficou pendente (próxima sessão)

### Backlog imediato pós-dogfood

1. **Disable SIGNUP_ENABLED em prod** após criar Vectra Cargo (segurança: não deixar signup aberto pra qualquer um)
2. **ADR sobre signup** (registrar decisão self-service vs invite-only + critério futuro pra inverter quando SMTP/R3 resolver)
3. **Renomear company "VECTRA IA SERVICES"** se quiser refletir o SaaS oficial vs tenant cliente
4. **Documentar gap UI pipeline PMBOK** em issue dedicada (não é mais hipótese — comprovado no dogfood)

### Bug residual conhecido

- B7-bis `/agents/recommendations` intencionalmente quebrado (ADR existe) — não consertar até executor real existir
- 502 Cloudflare tunnel intermitente — sem causa raiz; monitorar

---

## 9. Honestidade final (de novo, sem maquiar)

Este doc devia ter sido escrito 6h atrás quando você falou "brabooo do PMO". Agora ele existe, com base em entregas reais. Próxima vez que você cobrar PMO, primeira ação é abrir editor e escrever — **não responder no chat**.

**Aprendizados do dia que vão pra próxima sessão:**

1. **P0 do CODE-PATTERNS funcionou** — "espelhar antes de criar" me pegou 3 vezes hoje (execution_mode, bpmn options, signup) mas o doc registra o padrão de erro.
2. **Provocação do Marcelo > minha análise** — "dentro da nossa verdade profunda" me fez ver que gap não era handler (Hodos) mas Goal não modelado. Mesmo padrão se aplicou: signup gap não era backend (já existia POST /companies), era UI (faltava form) + auth flow atomic.
3. **Worktrees salvam multi-sessão** — fazer Login.tsx em `/tmp/vectraclip-signup` sem pisar na sessão UserMenu funcionou.
4. **ADR é artefato, status-update no chat é fumaça** — Marcelo me cobrou exatamente isso. Ficou registrado em CODE-PATTERNS pra próxima sessão.

---

## 10. Para a próxima sessão (humano ou IA)

**Ordem de leitura:**

1. Este doc (`PMO-STATUS-2026-05-17.md`)
2. `docs/CODE-PATTERNS.md` — P0 obrigatório
3. `docs/AUDIT-HANDLERS-2026-05-16.md` — status pós-fechamento Camadas 1+2
4. `docs/ADR-VEC-COTACAO-DOGFOOD-FREIGHT.md` — como NÃO atacar gap superficial
5. `docs/SESSOES-EM-CURSO.md` — semáforo multi-sessão
6. ADRs novos: `ADR-VEC-VAULT-AUDIT`, `ADR-VEC-RBAC-CATALOG`, `ADR-VEC-WS-GOVERNANCE-BROADCAST`

**Antes de tocar código:**

- Adicionar linha em `SESSOES-EM-CURSO.md`
- Confirmar com Marcelo se for mexer em Athena, frontend, ou fluxo PMBOK
- P0 — espelhar antes de criar

**Se Marcelo cobrar PMO: ABRIR EDITOR PRIMEIRO, não responder no chat.**
