# PMO Status Report — VectraClaw / VectraClip
## 2026-05-17 (encerramento sessão maratona 2026-05-16)

> **Autor:** Claude Opus 4.7 (session com Marcelo)
> **Cliente:** Vectra Cargo (tenant ativo único)
> **Escopo:** estado real do produto pós-maratona 47 PRs em 1 dia
> **Honestidade:** este doc registra **o que funciona vs o que parece funcionar** — sem maquiar gap arquitetural backend↔frontend.

---

## 1. Executive Summary (verdade dura)

| Dimensão | Estado real | O que está bonito | O que está escondido |
|---|---|---|---|
| **Backend** | ~85% pronto pro MVP | Pipeline PMBOK completo, RAG dual, 11 daemons, audit log, RLS hardened, Daedalus BPMN | LLM-driven handlers (Mercator/Plutus/Hodos) dependem `claude -p` default — sem prompts ricos persistidos; cadeia upstream quebrada (sem entry points) |
| **Frontend** | ~30% pronto pro MVP | CRUD básico (Goals, Tasks, SIPOC wizard, Agents config, RAG upload, Council list) | **Pipeline PMBOK não tem UI dispatch** — Goal criado fica órfão; sem botão "Classificar/Charter/Risk-Register"; sem progress UI de tasks Athena; B7-bis intencional bloqueia recommendations real |
| **DB** | 100% schema modelado | 51 tabelas + RLS + GRANTs + 8 catalogs metadata-driven | Vectra Cargo tem **0 dados operacionais** em risks/raci/approvals; SIPOC tem dados de smoke esparsos, não modelagem real |
| **Operações** | 11 daemons online | Auto-start Task Scheduler Windows; logs separados por daemon | R1 Gemini 403 paralisa 7 de 9 handlers Athena + Oracle research; SMTP bloqueado por Cloudflare WARP; routines table vazia |

**Veredito:** Backend está pronto pra apresentar pra investidor técnico (showcase de arquitetura). Frontend **não consegue demonstrar o pipeline PMBOK em ação** — usuário final cria Goal e fica olhando porque não tem botão pra "fazer algo PMBOK com isso".

**MVP P1 vendável pra cliente leigo: ainda NÃO é demonstrável end-to-end.**

---

## 2. Maturidade real por camada (auditoria 2026-05-16)

| Camada | Maturidade | Fechados hoje | Restantes |
|---|---|---|---|
| **1 Governance** | 95% (5/7 RESOLVED + 2 ADR parqueado) | audit_log, risks lifecycle, RACI invalidado | WS broadcast (espera FE), RBAC catalog (parqueado) |
| **2 Admin** | 100% (5/5 fechados) | RLS hardening app_users+companies+llm_models, cache warning, 3 ADRs | nenhum |
| **3 Comercial/Operações** | **45%** (Kronos 100% + Hermes parcial; Mercator/Plutus/Hodos 0% — mas é "0%" estratégico, ver §4.3) | 1 gap redefinido como dogfood (ADR) | 5 restantes |
| **4 Estratégia** | 70% (Mnemos+Daedalus funcionais; Athena+Oracle bloqueados R1) | Daedalus pipeline completo (PRs #154-#159) | R1 Gemini, executor recommend, mais 4 |

---

## 3. Gap arquitetural — Backend pronto vs Frontend primitivo

**Este é o achado mais importante do dia. Não estava no AUDIT de manhã; emergiu do dogfood da noite quando Marcelo perguntou "cadê o botão Classificar?".**

### O que o backend implementa (capacidade real)

```
Goal (criado por user)
  → athena-classify (kind, confidence, business_case)  [bloqueado R1]
  → athena-charter (escopo, sucesso, stakeholders)      [bloqueado R1]
  → athena-stakeholder-map (RACI alto nível)            [bloqueado R1]
  → athena-risk-register (RBS PMBOK)                    [bloqueado R1]
  → SIPOC mapping (endpoints REST OK)
  → daedalus bpmn-generate (✅ fallback estatístico OK)
  → workflow_definition + workflow_steps                 [parcial — sem promoter SIPOC→workflow]
  → TaskFactory materializa tasks                        [Kronos provou; outros não testados]
  → Agents executam (Mercator/Plutus/Hodos LLM-driven)  [vivos mas sem entry point]
  → HermesReporter SMTP                                  [funcional + R4 WARP block]
  → athena-evm / prioritize / audit (loop)              [bloqueado R1]
```

### O que o frontend dispara via UI hoje

```
Goal (UI criar/editar/deletar) → fica órfão sem botão pra próximo passo
SIPOC (wizard + management, Lote 2 em curso)
Tasks (CRUD)
Agents config (Lote já entregue + B7-bis intencional broken)
RAG upload + query
Recommendations (visualizar quebrada — B7-bis)
```

### Conclusão honesta

**Frontend implementa <30% das capacidades do backend.** O backend está sentado em capacidade que ninguém consegue usar via UI. Pra MVP P1 demonstrável:
- **Não basta** terminar Lote 2 SIPOC (já em curso pela outra sessão)
- **Precisa** Lote 3+ Frontend: UI de dispatch do pipeline PMBOK (~40-60h)

---

## 4. Backlog priorizado pro MVP P1 vendável

Ordem por **valor de negócio** (não por severidade técnica):

### 4.1 BLOQUEADORES P0 (sem isso, NÃO existe MVP)

| # | Item | Owner | Esforço | Bloqueia |
|---|---|---|---|---|
| 1 | **R1 Gemini 403** resolver | Marcelo (Google Cloud Console) | ? | 7 handlers Athena + Oracle research + UI Daedalus quando implementada |
| 2 | **Lote 3 Frontend — UI dispatch pipeline PMBOK** | Sessão frontend separada (não existe ainda) | 40-60h | Demo end-to-end. Sem isso, Goal fica órfão |

### 4.2 ALTO valor MVP (depende do P0)

| # | Item | Esforço | Justificativa |
|---|---|---|---|
| 3 | Lote 2 Frontend SIPOC completo (FE-A/B/C em curso pela outra sessão) | ~6h restantes | Destrava SIPOC management — UI consegue mapear processos reais |
| 4 | Cloudflare WARP SMTP fix (Resend recomendado) | 3h | HermesReporter envia emails em prod (compliance e ops) |
| 5 | Athena handlers fallback Python sem Gemini | 4h por handler | Mitigar R1 Gemini sem esperar Google Cloud |
| 6 | Executor real de `athena-recommend` | 4-6h backend | Destrava B7-bis intencional broken; UI Recommendations volta a ter sentido |

### 4.3 MÉDIO valor (depois do MVP)

| # | Item | Esforço | Justificativa |
|---|---|---|---|
| 7 | Mercator/Plutus/Hodos prompts ricos + system_prompts | 1-2h cada | Hodos já roda via claude-p; só falta prompt rico documentado |
| 8 | Heartbeats retention TTL (30d) | 1h | Antecipar problema 125M rows/ano |
| 9 | Daedalus LLM branch (quando R1 destravar) | 3h | Diagrama BPMN inteligente vs LINEAR fallback atual |
| 10 | UI Risk Matrix consumindo G1.2 lifecycle | 4h | Mostra risks fluindo entre statuses |
| 11 | Vault audit (compliance ADR já existe) | 4-6h auditoria + 8-12h fix | LGPD/SOC2 prep |

### 4.4 BAIXO valor / parqueado

| # | Item | Decisão |
|---|---|---|
| 12 | RBAC catalog table | ADR parqueado (roles vocabulário curado, ~10h pra benefício marginal) |
| 13 | WS broadcast governance | ADR parqueado (espera demanda frontend) |
| 14 | adapter_field_type catalog | DECIDED P6 (enum local UI) |
| 15 | agent_domains CRUD | ACCEPTED workaround SQL |

---

## 5. Risk Register operacional (PMBOK §11)

| ID | Risco | Probabilidade | Impacto | Score | Resposta atual | Owner |
|---|---|---|---|---|---|---|
| R1 | Gemini 403 PERMISSION_DENIED bloqueia Athena+Oracle | 1.0 (ocorrendo) | 9 | 9.0 | Não tratado | **Marcelo** |
| R2 | Frontend não consegue dispatch pipeline PMBOK (sem botões) | 1.0 (descoberto hoje no dogfood) | 8 | 8.0 | Não tratado | **frontend session** |
| R3 | Cloudflare WARP bloqueia GoDaddy SMTP | 1.0 (intermitente) | 7 | 7.0 | Workaround manual (pausar WARP) | **Marcelo** ou pivot Resend |
| R4 | Daemons sem `load_dotenv` (VEC-414) viram no-op silencioso | 0.4 | 7 | 2.8 | Workaround: exportar .env antes do launcher | tech debt |
| R5 | Image Docker stale após `compose up -d` | 0.7 | 5 | 3.5 | Documentado; `--build` resolve | docs OK |
| R6 | 502 intermitente Cloudflare tunnel | 0.3 | 6 | 1.8 | Investigado hoje, sem causa raiz; logs limpos | monitorar |
| R7 | Multi-sessão Claude paralela pisa em working tree | 0.5 | 4 | 2.0 | `SESSOES-EM-CURSO.md` semáforo | mitigado |

**Top 3 a tratar:** R1 (Gemini), R2 (frontend dispatch), R3 (SMTP WARP). Esses 3 valem 24 score points dos 34.1 totais.

---

## 6. Decisões aguardando você (Marcelo)

| # | Decisão | Custo de adiar | Recomendação minha |
|---|---|---|---|
| D1 | R1 Gemini — resolver no Google Cloud OU pivot pra Claude managed via Anthropic SDK | ALTO — 70% Camada 4 inoperante | Pivot Claude (rápido, sua conta MAX cobre) |
| D2 | Lote 3 Frontend pipeline PMBOK — quando começar? | ALTO — define se MVP existe em N semanas | Imediato após Lote 2 fechar (próximas 2 sessões frontend) |
| D3 | SMTP fix: Resend vs WARP exception vs Postmark? | MÉDIO — HermesReporter degradado | Resend (você já tem bookmark; API moderna) |
| D4 | Daedalus LLM branch — esperar R1 OU usar Claude direto? | BAIXO (fallback estatístico cobre MVP) | Esperar R1 |
| D5 | Vault audit — quando priorizar? | BAIXO hoje, ALTO se buscar SOC2 | Backlog Q2 |

---

## 7. Recomendação executiva (pra próximos 7 dias)

### Caminho ótimo

**Sprint 1 (você):** D1 (Gemini ou pivot Claude) + D2 (autorizar Lote 3 frontend) — 2 decisões em <2h, destrava todo o resto.

**Sprint 2 (outra sessão frontend):** Lote 2 SIPOC completar (já em curso) + começar Lote 3 PMBOK dispatch (botão por botão, incremental).

**Sprint 3 (esta sessão backend):** R3 SMTP fix + executor `athena-recommend` (destrava B7-bis intencional) + Athena fallbacks Python sem Gemini (mitiga R1).

**Em 7-10 dias úteis:** MVP P1 demo-ready ao cliente leigo Vectra Cargo (que dogfood próprio do produto deles).

### Anti-recomendação

- ❌ Mais agentes/specialties novos (Mercator/Plutus/Hodos handlers Python) — viola P0 metadata-driven, **gap real não é falta de agent, é falta de UI dispatch**
- ❌ Mais backend features sem UI consumer — capacidade que ninguém usa via UI é **dívida**
- ❌ Fechar gap por gap do AUDIT sem priorizar valor — leva pra "100% green" sem demo funcional

---

## 8. Estado de execução pós-maratona (47 PRs)

### O que fechou hoje (alto level)

- **Camada 2 Admin** 100% fechada (5 gaps)
- **Camada 1 Governance** 95% fechada (5 resolved + 2 ADR + 1 invalidated)
- **G1 Risk Register PMBOK** completo end-to-end (#149-#151)
- **Daedalus BPMN** completo D+E+F+G+H (#154-#159) — 4º agente core
- **execution_mode catalog-driven** (#146 backend + #22 frontend) — pattern P1 aplicado
- **Audit log foundation** (#167) + 5 integrações (PRs #167+#170)
- **CODE-PATTERNS.md** com P0 ("espelhar antes") + P6 (enums locais) + P8 (broken windows intencionais)
- **5 ADRs** documentando decisões parqueadas (não é "não fizemos", é "decidimos não fazer agora com critério de saída")

### O que ainda dói

- Frontend gap descoberto no dogfood (este doc)
- Vectra Cargo sem dados modelados no produto (cotações fora do sistema)
- R1 Gemini paralisa Camada 4

---

## 9. Para a próxima sessão (humano ou IA)

**Ler nesta ordem antes de tocar código:**

1. Este doc (`PMO-STATUS-2026-05-17.md`)
2. `docs/CODE-PATTERNS.md` — P0 obrigatório
3. `docs/AUDIT-HANDLERS-2026-05-16.md` — gaps por camada (com status atualizado)
4. `docs/AUDIT-2026-05-16-CONSOLIDADO.md` — outros gaps no-hardcode
5. `docs/ADR-VEC-COTACAO-DOGFOOD-FREIGHT.md` — exemplo de como NÃO atacar gap superficial
6. `docs/SESSOES-EM-CURSO.md` — semáforo multi-sessão

**Não começar sem:**

- Adicionar linha em `SESSOES-EM-CURSO.md`
- Confirmar Marcelo aprovou (especial se for mexer no fluxo PMBOK, frontend, ou Athena)
- Validar contra P0 ("espelhar antes de criar")

---

## 10. Honestidade final

Este doc deveria ter sido escrito **hoje cedo**, quando Marcelo perguntou "cadê o doc PMO". Em vez disso entreguei:
- Status update no chat (efêmero)
- ADRs táticos (úteis mas isolados)
- 47 PRs (entregáveis mas sem visão consolidada)

Marcelo me cobrou na noite: "Cade seu DOC especial de PMO QUE IA ME ENTREGAR". Tinha razão. Documento PMBOK status consolidado é responsabilidade básica do PMO, não bonus.

Lição registrada: **quando user pede "doc PMO", ele quer ARTEFATO AUDITÁVEL, não resposta de chat**. Próxima vez que aparecer "brabooo do PMO" ou similar, primeira ação é abrir editor e escrever doc.

Este aqui é o piso. Vai ser atualizado quando o MVP P1 estiver demo-ready (sprint 2-3).
