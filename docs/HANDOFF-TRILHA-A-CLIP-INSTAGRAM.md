# Handoff — Trilha A (Clip) + Instagram PR0 validado

> **Data:** 2026-05-22 (atualizado pós-merge Clip #63)  
> **Backend repo:** `vectraclaw-backend` (VectraClaw) — `main` @ #295 + #296 + handoff #297  
> **Frontend repo:** `vectraclip-frontend` — `main` @ `fa6c95bf` ([PR #63](https://github.com/Marcelo-Rosas/vectraclip-frontend/pull/63) mergeado)  
> **ADR backbone:** `docs/ADR-VEC-MAPEAR-ANALISAR-AUTOMATIZAR.md` §5  
> **Plano detalhado:** `.cursor/plans/pr-b1_b2_trilha_a_c4c5c7a7.plan.md`  
> **Espelho Clip (fonte de verdade UI):** `vectraclip-frontend/docs/HANDOFF-TRILHA-A-CLIP.md`

## Conteúdo (estrutura)

| Seção | Para quê |
|--------|----------|
| [Resumo executivo](#resumo-executivo) | Instagram PR0 OK; backend #295/#296; status Clip P0 |
| [Duas trilhas](#duas-trilhas-separadas-não-misturar) | A = backbone processo; B = cada DM (sem `athena-classify` por lead) |
| [PRs mergeados](#prs-mergeados-backend) | Links #295 / #296 |
| [Instagram validado](#instagram--estado-validado-2026-05-22) | Pipeline webhook, HMAC, inbound-triage, smoke pytest |
| [APIs Clip](#apis-prontas-para-o-clip-trilha-a) | PR-B1 routines, PR-B2 goals, BPMN materialize, from-workflow |
| [Checklist FE-GAP](#checklist-clip--ordem-p0-fe-gap) | P0 1–6 ✅ em `main` Clip #63; 7 = P1 |
| [Smoke E2E pós-deploy](#smoke-e2e-pós-deploy-clip-63--api) | 5 passos em prod (Pages + API) |
| [O que NÃO fazer](#o-que-não-fazer) | IGAA no verify token, classify por DM, etc. |
| [Prompt agente](#prompt-curto-pós-merge--validação-ou-p1) | Smoke prod ou PR P1 |

---

## Resumo executivo

| Trilha | Status | Notas |
|--------|--------|-------|
| **Instagram DM (PR0)** | Validado em prod/tunnel | DM teste → resposta automática human-triage |
| **PR-B1** routine↔workflow | Em `main` (#295) | `workflowDefinitionId` create/patch/get + FK |
| **PR-B2** goal classify wire | Em `main` (#295) | `kind`, `confidence`, `classifiedAt` no GET goals |
| **Clip Trilha A UI** | **P0 em `main`** ([#63](https://github.com/Marcelo-Rosas/vectraclip-frontend/pull/63) → `fa6c95bf`) | 19 arquivos, itens 1–6; P1 (FE-GAP-07/08) pendente. Deploy: Cloudflare Pages |

## Duas trilhas (separadas — não misturar)

- **Trilha A (uma vez):** Goal → SIPOC → BPMN materialize → classify → workflow → routine → tasks  
- **Trilha B (cada DM IG):** webhook → sessão → `inbound-triage` → resposta (Mercator depois, sem `athena-classify` por lead)

---

## PRs mergeados

### VectraClip (`vectraclip-frontend`)

| Item | Detalhe |
|------|---------|
| Branch | `feat/trilha-a-clip-p0` → squash **`fa6c95bf`** |
| PR | [#63](https://github.com/Marcelo-Rosas/vectraclip-frontend/pull/63) — **MERGED** |
| Escopo | 19 arquivos — Trilha A P0 apenas (sem intelligence/specialties/BPMN gateway WIP) |
| CI | Nenhum check GitHub (`statusCheckRollup` vazio); typecheck OK em Docker antes do push |
| Deploy | Cloudflare Pages no push em `main` → https://app.vectraclip.vectracargo.com.br (hard refresh ~2–5 min após merge) |

### VectraClaw (`vectraclaw-backend`)

| PR | Título | O que desbloqueia no Clip |
|----|--------|---------------------------|
| [#295](https://github.com/Marcelo-Rosas/vectraclaw-backend/pull/295) | PR-B1/B2 Trilha A wire | RoutineEditor + GoalDetail pós-classify |
| [#296](https://github.com/Marcelo-Rosas/vectraclaw-backend/pull/296) | PR0 Instagram webhook | Trilha B; filtro sessões IG |
| [#297](https://github.com/Marcelo-Rosas/vectraclaw-backend/pull/297) | Handoff canônico | Este documento + checklist P0 |
| [#298](https://github.com/Marcelo-Rosas/vectraclaw-backend/pull/298) | Pointer handoff em `CLAUDE.md` | — |
| [#299](https://github.com/Marcelo-Rosas/vectraclaw-backend/pull/299) | Disciplina PR para docs/handoff | — |

**WIP local no Claw** (Kronos, Dockerfile, `postgrest_coerce`, migrations, etc.) **não** entrou nos merges acima — próximo PR por escopo.

---

## Instagram — estado validado (2026-05-22)

**Aceite:** DM para @vectra_cargo → mensagem do tipo:

> Recebi sua mensagem! 👋 Vou direcionar pro time humano analisar…

**Pipeline confirmado:**

```text
Meta POST → /api/connectors/instagram/webhook (public_paths, sem JWT)
  → HMAC (app_secret 32 hex; VECTRACLAW_IG_WEBHOOK_PARENT_APP_ONLY=true)
  → connector_sessions (channel=instagram)
  → inbound-triage (catalog connector_channels)
  → reply graph.instagram.com/v21.0/me/messages (token IGAA*)
```

**Config operacional (não commitar secrets):**

| Item | Valor / nota |
|------|----------------|
| Company | `01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2` |
| Webhook URL | `https://api-vectraclip.vectracargo.com.br/api/connectors/instagram/webhook` |
| Verify token | Campo **Webhook Verify Token** no wizard (64 chars `5f9a1a53…`) — **não** colar `IGAA` aqui |
| Access token | Campo **Access Token** — token `IGAA…` (~185 chars) |
| App Secret | Campo **App Secret** — 32 hex do app pai (Basic Settings) |
| Health | `GET http://localhost:3100/api/health` → `{"status":"online"}` |

**Deploy local padrão:**

```powershell
cd C:\Users\marce\VectraClaw
git checkout main && git pull origin main
supabase db push   # se houver migration pendente
docker compose build backend
docker compose up -d backend
```

**Smoke:**

```powershell
python -m pytest tests/test_instagram_webhook_e2e.py tests/test_instagram_parser.py -q
```

---

## APIs prontas para o Clip (Trilha A)

### PR-B1 — Rotinas

| Método | Path | Body / wire |
|--------|------|-------------|
| POST | `/api/companies/{companyId}/routines` | `workflowDefinitionId` (camelCase) |
| PATCH | `/api/routines/{id}` | `workflowDefinitionId` (nullable = desvincular) |
| GET | `/api/routines/{id}` | resposta inclui `workflowDefinitionId` |
| POST | `/api/routines/{id}/run-now` | com `workflow_definition_id` preenchido → parent + subtasks (TaskFactory) |

Validação FK: workflow da mesma `company_id` (422 se inválido).

### PR-B2 — Goals pós-classify

| Campo wire (nullable) | Origem |
|----------------------|--------|
| `kind` | `athena-classify` UPDATE em `goals` |
| `confidence` | idem |
| `businessCaseStrength` | idem |
| `classifiedAt` | idem |
| `classificationRationale`, `nextHandlerSuggested` | flatten de `pmoia_metadata` |

**Fluxo UI Classificar:**

1. Criar task `operation_type: athena-classify`, `input_json: { goal_id }`, agent Athena  
2. Aguardar `status: done`  
3. `GET /api/goals/{goalId}` — exibir badge projeto/operação (não parsear só `task.output_json`)

### BPMN / workflow (já existentes no backend)

- Materialize: rota BPMN materialize (ver `HANDOFF-BPMN-BACKEND-PRIORIDADE.md`)  
- `POST /api/companies/{companyId}/tasks/from-workflow` — materializar workflow em tasks  
- Workflows CRUD: `/api/companies/{companyId}/workflows`

---

## Checklist Clip — ordem P0 → P1 (FE-GAP)

**Estado (2026-05-22):** P0 itens **1–6 em `main` do Clip** ([#63](https://github.com/Marcelo-Rosas/vectraclip-frontend/pull/63)); item **7 = P1**. Próximo passo = **smoke E2E em prod** (Pages + API #295/#296), não novo PR de P0.

Backend **#295** / **#296** devem estar em prod antes de validar **run-now** com workflow.

| # | Item | FE-GAP | Backend | Status Clip (`main` #63) |
|---|------|--------|---------|-------------------------|
| 1 | `BpmnMaterializeButton` no `BpmnEditor` | FE-GAP-01 | materialize API | ✅ |
| 2 | “Classificar com Athena” + badge em `GoalDetail` | FE-GAP-02/10 | **#295** GET goal | ✅ |
| 3 | `Routine` + select `workflowDefinitionId` | FE-GAP-03 | **#295** | ✅ |
| 4 | Cadência nos steps (canvas + templates 4h/23h/3d/7d) | FE-GAP-04/05 | workflow PUT | ✅ |
| 5 | Run workflow na UI | FE-GAP-09 | from-workflow | ✅ |
| 6 | Filtro canal Instagram em sessões | FE-GAP-06 | PR0 `instagram` | ✅ |
| 7 | Wizard Meta IG / picker RAG | FE-GAP-07/08 | adapters catalog | ⬜ P1 |

**Tipos TypeScript (Clip — já em `src/types/api.ts`):**

- `Routine.workflowDefinitionId: string | null`
- `Goal.kind`, `confidence`, `businessCaseStrength`, `classifiedAt`, `classificationRationale`, `nextHandlerSuggested` (todos `| null`)

**Notas de implementação:**

- Pós-materialize: navegação para `/workflow?slug={workflowSlug}` (não `/workflow/:uuid`).
- Classify: `operation_type` = `athena-classify`, `inputJson: { goal_id }`, agente via `primary_agent_id` do catálogo.
- Cadência ADR no Agent Builder: `generateSpinWorkflow({ profile: 'instagram_prospection_adr' })` (UI do dialog ainda usa perfil default).

---

## O que NÃO fazer

- Chamar `athena-classify` por cada DM Instagram (Trilha B ≠ Trilha A).  
- Colocar token `IGAA` no campo Verify Token da Meta.  
- Deploy RoutineEditor antes do backend com **#295** em prod (run-now sem workflow persistido).  
- `MOCK_*` em runtime de API (Regra #8).

---

## WIP local (backend, fora do GitHub)

Ainda há alterações não commitadas no workspace (Kronos, Dockerfile, `agent_daemon`, migrations locais, etc.). **Não bloqueiam** Clip Trilha A nem Instagram validado.

Stash opcional: `git stash list` → `agent_daemon wip`.

Próximos PRs backend sugeridos (escopo pequeno):

1. Scripts ops IG (`repair_meta_instagram_vault`, `upsert_meta_app_secret`) + `.env.example` JWT quotes  
2. Eros PR1 — `operation_types` social + daemon (plano Eros)

---

## Referências

- BPMN FE: [HANDOFF-BPMN-FRONTEND-PRIORIDADE.md](./HANDOFF-BPMN-FRONTEND-PRIORIDADE.md)  
- BPMN BE: [HANDOFF-BPMN-BACKEND-PRIORIDADE.md](./HANDOFF-BPMN-BACKEND-PRIORIDADE.md)  
- Padrões: [CODE-PATTERNS.md](./CODE-PATTERNS.md)  
- Análise FE Eros/PR0b: `ANÁLISE-FRONTEND-EROS-INSTAGRAM-PR0b.md` (repo VectraClip)

---

## Smoke E2E pós-deploy (Clip #63 + API)

Rodar em https://app.vectraclip.vectracargo.com.br (hard refresh após `fa6c95bf`) contra API com #295/#296:

1. `/bpmn/:id` → **Materializar** → `/workflow?slug=...`
2. `/goals/:id` → **Classificar com Athena** → badge `kind` no GET goal
3. `/routines/:id` → `workflowDefinitionId` → **run-now**
4. `/workflow` → painel step → **Cadência** (templates 4h/23h/3d/7d)
5. `/connectors/sessions` → filtro **Instagram**

**P1 Clip (próximo PR):** FE-GAP-07/08 — wizard Meta help, picker RAG.

---

## Prompt curto (pós-merge — validação ou P1)

```text
Clip main fa6c95bf (#63) + Backend #295/#296/#297 mergeados. P0 Trilha A shipped.

Smoke E2E em app.vectraclip.vectracargo.com.br (não reimplementar P0).
P1: FE-GAP-07/08 wizard Meta + RAG picker → PR dedicado vectraclip-frontend.

Handoff: vectraclip-frontend/docs/HANDOFF-TRILHA-A-CLIP.md
        vectraclaw-backend/docs/HANDOFF-TRILHA-A-CLIP-INSTAGRAM.md
```
