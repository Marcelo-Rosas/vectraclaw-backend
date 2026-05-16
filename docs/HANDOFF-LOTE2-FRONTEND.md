# Handoff — Lote 2 Frontend (UI-first MVP)

> **Audience:** próxima sessão Claude Code (ou humano) que vai atacar o **frontend VectraClip**.
> **Repo do código:** `C:\Users\marce\VectraClip` (NÃO é o VectraClaw — repo separado).
> **Origem:** roadmap de `docs/UI-COVERAGE-MATRIX.md` §2.
>
> **Por que este doc existe:** o MVP P1 vendável pra Vectra Cargo precisa de **8-12h de frontend** pra fechar os gaps SIPOC/Org/Diagnose. Backend está 100% pronto desde 16/05 (PRs #138-#151). Sem esse Lote 2, o MVP demo continua dependendo de Postman.

---

## 0. TL;DR — o que entregar

**5 sub-PRs** no repo `vectraclip-frontend`, cada um isolado (P5 do CODE-PATTERNS):

| Sub-PR | Foco | Esforço | Bloqueia MVP? |
|---|---|---|---|
| **FE-A** | SipocManagement: botões **Delete** em sector/process/activity | 1h30 | 🔴 sim |
| **FE-B** | SipocManagement: botões **Edit** + form inline (PATCH) | 2h | 🔴 sim |
| **FE-C** | SipocManagement: componente **RACI matrix** (R/A/C/I por activity) | 3h | 🔴 sim |
| **FE-D** | SipocReport: botões **"Gerar diagnóstico"** + **"Exportar PDF"** | 1h30 | 🟡 destrava demo |
| **FE-E** | **Org chart tree view** top-down + Gap 4+5 (reports_to + cargo cross-cutting) | 2h | 🟡 destrava demo |

**Total:** ~10h. Você decide se faz tudo ou só os 🔴.

> Os 14 hits de "botões fantasmas" da outra sessão (Batidas 1-4 do `AUDIT-2026-05-16-CONSOLIDADO.md`) **não estão no Lote 2** — são frente paralela independente.

---

## 1. Antes de começar (5 minutos obrigatórios)

1. **Leia `docs/SESSOES-EM-CURSO.md`** do repo VectraClaw — confira se ninguém está mexendo em `SipocManagement.tsx`/`Org.tsx` agora. Adicione 1 linha sua antes do primeiro tool use.
2. **Leia `docs/CODE-PATTERNS.md`** — em especial **P1** (catalog-driven, no Literal). Já tem 2 exemplos aplicados (`adapter_type`, `execution_mode`); o pattern é texto livre + comentário, NÃO hardcode.
3. **Leia este doc** até o fim — endpoints, contratos, gotchas.
4. **Confirme o ambiente:**
   - Backend rodando: `curl http://localhost:3100/api/health` deve retornar `{"status":"online"}`
   - Login: email `marcelo.rosas@vectracargo.com.br`, senha `VectraClaw2026!`
   - Company de teste: `01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2` (Vectra Cargo)
   - Frontend dev server: `cd /c/Users/marce/VectraClip && npm run dev` → porta **3000** (não 5173 — `vite.config.ts` override; `reference_vectraclip_dev_ports`)
5. **MSW footgun:** se aparecer 401 em `/auth/login` mesmo com `VITE_USE_MOCKS=false`, desregistre o service worker no DevTools (`reference_vectraclip_msw_footgun`)

---

## 2. Estado backend disponível (você consome, não modifica)

### 2.1 SIPOC — CRUD completo

```bash
# Sectors
GET    /api/sipoc/sectors?company_id=<cid>
POST   /api/sipoc/sectors
PATCH  /api/sipoc/sectors/{sector_id}       ← PR #145
DELETE /api/sipoc/sectors/{sector_id}       ← PR #144 (cascade hierárquico)

# Processes
GET    /api/sipoc/processes?sector_id=<sid>
POST   /api/sipoc/processes
GET    /api/sipoc/processes/{process_id}
PATCH  /api/sipoc/processes/{process_id}    ← PR #145
DELETE /api/sipoc/processes/{process_id}    ← PR #144

# Components (activity, supplier, input, output, customer)
GET    /api/sipoc/components?process_id=<pid>
POST   /api/sipoc/components
POST   /api/sipoc/processes/{pid}/components ← PR #145 (criar activity standalone — Gap 3 dogfood)
PATCH  /api/sipoc/components/{component_id} ← PR #145
DELETE /api/sipoc/components/{component_id} ← PR #144
POST   /api/sipoc/components/{component_id}/promote

# RACI matrix (R/A/C/I por activity × position)
GET    /api/sipoc/processes/{process_id}/raci
POST   /api/sipoc/raci                       ← upsert {process_id, component_id, position_id, role}
DELETE /api/sipoc/raci/{component_id}/{position_id}

# Diagnose + PDF (Athena)
POST   /api/sipoc/diagnose                   ← PR #139 (gera diagnose_gap por setor)
GET    /api/sipoc/processes/{pid}/diagnose/pdf ← PR #140 (download PDF executivo)

# Validation / analytics
GET    /api/sipoc/processes/{process_id}/validate
GET    /api/sipoc/analytics?company_id=<cid>
```

### 2.2 Risks (G1 PMBOK — PR #150)

```bash
POST   /api/risks                            ← cria risco manual
GET    /api/companies/{cid}/risks?status=&category=&min_score=
GET    /api/risks/{risk_id}
PATCH  /api/risks/{risk_id}
DELETE /api/risks/{risk_id}
GET    /api/goals/{goal_id}/risks
GET    /api/sipoc/processes/{pid}/risks
GET    /api/sipoc/components/{cid}/risks
```

> Há **0 risks no DB ainda** pra Vectra Cargo (handler Athena bloqueado por R1 Gemini 403). Você pode criar manualmente via POST pra validar UI.

### 2.3 Positions / Org

```bash
GET    /api/sipoc/positions?company_id=<cid>
POST   /api/sipoc/positions
PATCH  /api/sipoc/positions/{position_id}    ← campo `reports_to_id` é nullable (Gap 5: cargo cross-cutting)
DELETE /api/sipoc/positions/{position_id}    ← PR #136
PATCH  /api/app_users/{id}                   ← atribui role + position_id (PR #16)
```

### 2.4 Schema de payload (camelCase aceito)

Backend tem `_normalize_sipoc_payload_to_snake` cobrindo todos os campos SIPOC (PR #146). Você pode mandar `companyId`, `sectorId`, `reportsToId`, `automationStatus`, `suggestedOperationType`, etc. — ele converte. **Mas o response sempre vem em camelCase** (snake → camel é responsabilidade do model `to_zod_dict()`).

---

## 3. Sub-PRs detalhados

### FE-A — Botões Delete em SipocManagement

**Arquivo principal:** `src/pages/SipocManagement.tsx`

**Escopo:**

| Elemento | Card | Ação |
|---|---|---|
| Sector card | header ou menu kebab | Botão Delete → `DELETE /api/sipoc/sectors/{id}` (cascade backend) |
| Process card | header ou menu kebab | Botão Delete → `DELETE /api/sipoc/processes/{id}` |
| Component (activity) | dropdown ou hover toolbar | Botão Delete → `DELETE /api/sipoc/components/{id}` |

**UX obrigatório:**

- Dialog confirm (`AlertDialog` do shadcn) com texto `"Excluir setor 'X'? Isso apaga TODOS os processos e atividades dentro dele."` em PT
- Toast cascade-aware: "Setor X removido (apagou N processos e M atividades)"
- Loading state no botão durante request
- Invalidate query keys: `queryKeys.sipocSectors.list(companyId)` e relacionadas

**Anti-pattern (✋):**

- ❌ NÃO esconda botão com `opacity-0 group-hover:opacity-100` — bug do PR #20, ainda não fixado em outros lugares (auditoria botões fantasmas C1-C5 mapeou 5 ocorrências)
- ❌ NÃO bypass o confirm (perigo destruir dados de cliente)

**RBAC:** backend bloqueia `viewer` e `sector_responsible` com 403. UI deve esconder o botão antes — `useCanWrite()` ou similar baseado em `userRole`.

---

### FE-B — Botões Edit + form inline em SipocManagement

**Escopo:**

| Card | Edit triggers | Endpoint |
|---|---|---|
| Sector | nome inline editável OU dialog "Editar setor" (name, icon, parent_sector_id, metadata) | `PATCH /api/sipoc/sectors/{id}` |
| Process | nome + description + owner inline OU dialog | `PATCH /api/sipoc/processes/{id}` |
| Component (activity) | drawer "Editar atividade": name, description, automationStatus, suggestedOperationType, responsiblePositionId | `PATCH /api/sipoc/components/{id}` |

**Padrão UX preferido:** drawer lateral (`Sheet` do shadcn) com form, NÃO modal — permite ver o card enquanto edita.

**Payload exemplo PATCH component (camelCase OK):**

```json
{
  "content": {"name": "Receber pedido"},
  "description": "Atividade de recepção via WhatsApp",
  "automationStatus": "hybrid",
  "suggestedOperationType": "email_lead",
  "responsiblePositionId": "<uuid de sipoc_positions>"
}
```

**Validators a respeitar (backend já valida, UI dá feedback antes):**

- `name` 3..200 chars (mensagem 400: "SIPOC: ...")
- `automation_status` ∈ {`manual`, `automated`, `hybrid`, `pending_review`}
- `suggested_operation_type` ∈ `operation_types_catalog` — busque via `GET /api/operation-types` e popule um Select catalog-driven (P1 CODE-PATTERNS). **Não hardcode os 41 valores.**

---

### FE-C — Componente RACI matrix

**Componente novo:** `src/components/sipoc/RaciMatrix.tsx`

**Visual:** tabela com:
- **Linhas:** activities (components do tipo `activity` do processo)
- **Colunas:** positions ativas da company
- **Cells:** dropdown com `R | A | C | I | (vazio)` — clique muda → POST `/api/sipoc/raci`

**Endpoints:**

```typescript
// Carregar matriz
GET /api/sipoc/processes/{processId}/raci
// → [{component_id, position_id, role}, ...]

// Editar cell (upsert)
POST /api/sipoc/raci
body: {process_id, component_id, position_id, role: "R"|"A"|"C"|"I"}

// Limpar cell
DELETE /api/sipoc/raci/{component_id}/{position_id}
```

**Regras PMBOK (Schmidt §Engage stakeholders):**

- Cada activity DEVE ter ≥1 `A` (Accountable) e ≥1 `R` (Responsible) pra estar "bem-mapeada"
- **Badge no header da activity:** verde se completo, amarelo se falta R ou A, vermelho se vazio
- Backend já calcula isso via `calculate_raci_stats` (service `src/services/sipoc_raci.py`) — disponível em `GET /api/sipoc/processes/{pid}/validate` provavelmente

**Side-effect importante:** quando você seta `role='R'`, backend ATUALIZA também `sipoc_components.responsible_position_id` automaticamente (PR #142). Refetch o component depois pra UI bater.

**Anti-pattern:**

- ❌ NÃO permita 2 `A`s na mesma activity (PMBOK: Accountable é único)
- ❌ NÃO hardcode roles `["R","A","C","I"]` em código de catálogo separado — é PMBOK fechado, OK constante local (P6 CODE-PATTERNS)

---

### FE-D — Diagnose UI + Export PDF em SipocReport

**Arquivo:** `src/pages/SipocReport.tsx`

**2 botões novos no toolbar:**

```typescript
// Botão "Gerar diagnóstico" (Athena)
POST /api/sipoc/diagnose
body: {company_id, sector_id?}  // sector_id opcional, se ausente diagnostica todos
// → dispatch task athena-diagnose, retorna {task_id, status: queued}
// → polling /api/tasks/{task_id} até status=done
// → recommendations aparecem em /agents/recommendations OU embedded no relatório

// Botão "Exportar PDF executivo"
GET /api/sipoc/processes/{process_id}/diagnose/pdf
// → download direto (Content-Type: application/pdf)
// → usar window.open ou anchor com download attr
```

**UX:**

- Botão "Gerar diagnóstico" → toast "Gerando diagnóstico via Athena…" + spinner + polling. Resolve em ~30-60s.
- Botão "Exportar PDF" → habilitado SÓ se já houver diagnose pro processo (verificar via GET `/api/sipoc/recommendations?process_id=X`)
- Mostrar empty state amigável se não há diagnose ainda: "Clique em 'Gerar diagnóstico' acima"

**Limitação ATIVA:** Gemini 403 (R1 do PMO log) bloqueia o handler real. UI deve mostrar erro útil: `"Athena temporariamente indisponível — equipe está resolvendo permissão Google Cloud"` se a task vir com `status=error` e `output_json.outputs.code='gemini_call_failed'`.

---

### FE-E — Org chart tree view + Gap 4+5

**Arquivo:** `src/pages/Org.tsx` (ou `OrgChart.tsx`)

**Gap 4 — Tree view top-down:**

Hoje a UI mostra lista flat. Backend já tem `parent_sector_id` (cargos sob setores) e `reports_to_id` em positions. **Renderizar como árvore vertical (CEO no topo, descendo).**

Lib sugerida: já tem `@xyflow/react` no projeto (usado em workflow canvas). Pode reusar pra layout hierárquico com `dagre` (top-down).

Alternativa simpler: tree recursiva CSS (cada nó é um card, conecta com SVG line ou border).

**Gap 4 — `reports_to_id` não persistia (bug UI):**

Backend funciona (validado via PATCH direto). UI tem bug no form: provavelmente o select não envia o campo. **Verifique no `EditPositionDialog` (ou similar) se o submit inclui `reports_to_id`** no payload PATCH.

**Gap 5 — Cargo cross-cutting (CEO sem sector):**

UI atualmente exige `sector_id` no form de criar cargo. Backend permite `sector_id=NULL` (CEO/CFO atravessam setores). **Tornar o select de sector "opcional" no form** com label "Cargo cross-cutting (sem setor específico)" + checkbox.

**Payload PATCH position:**

```json
{
  "name": "CEO",
  "reportsToId": null,
  "sectorId": null,
  "metadata": {"isCrossCutting": true}
}
```

---

## 4. Padrões obrigatórios (todos os 5 sub-PRs)

### 4.1 Catalog-driven (P1 CODE-PATTERNS)

Já aplicado em `adapter_type`, `execution_mode`. **NÃO crie `<SelectItem value="manual">` hardcoded** — onde o set de valores corresponde a uma tabela catalog do DB, busque via `useXxxCatalog()` hook + render dinâmico (`modes.map(m => <SelectItem ...>)`).

Catalogs com endpoint GET disponíveis:
- `agent_execution_modes` → `GET /api/agent-execution-modes`
- `agent_specialties` → `GET /api/agent-specialties`
- `operation_types_catalog` → `GET /api/operation-types`
- `agent_domains` → `GET /api/agent-domains`
- `workflow_logic_patterns` → `GET /api/workflow-logic-patterns`
- `workflow_trigger_types` → `GET /api/workflow-trigger-types`

Sem endpoint (você pode criar GET no backend se precisar, ou abrir issue):
- `adapter_catalog` (existe, sem GET)
- `task_tree_status` (existe, sem GET)

### 4.2 DynamicSchemaForm já existe (PR #22)

Componente reutilizável em `src/components/forms/DynamicSchemaForm.tsx`. Renderiza `config_schema` JSONB (text/textarea/number/boolean/secret/select). Use para **qualquer config baseado em catalog com config_schema**.

### 4.3 RBAC consistente

- `viewer` e `sector_responsible` NÃO podem escrever em SIPOC
- Backend retorna 403 com mensagem PT — capture e mostre toast
- **UI esconde botões** antes de habilitar — checa `userRole` via hook

### 4.4 i18n PT-BR

- Toasts: "Setor removido", "Atividade atualizada", "Falha ao salvar"
- Confirms: "Tem certeza que deseja excluir…?"
- Empty states: "Nenhum risco cadastrado ainda"

### 4.5 Encoding payload (gotcha de smoke)

Bash com `curl --data` + char acentuado quebra ("error parsing body"). Use `--data-binary @file.json` ou `axios.post(url, obj)` (encoding correto por padrão no fetch/axios do TS).

---

## 5. Definition of Done por sub-PR

Cada sub-PR só fecha quando:

1. ✅ `npx tsc --noEmit` zero erros
2. ✅ Botão/feature funciona em `localhost:3000` com user real `marcelo.rosas@vectracargo.com.br`
3. ✅ Não usa nenhum `opacity-0 group-hover:opacity-100` em CRUD button
4. ✅ Não tem `<SelectItem value="literal">` se há catalog GET disponível
5. ✅ PR description cita: arquivo:linha + endpoint consumido + test plan executado
6. ✅ Atualizou `docs/SESSOES-EM-CURSO.md` (movendo entrada de Ativas → Concluídas hoje)

---

## 6. Como rodar smoke local (template)

```bash
# Backend já está rodando (docker ps mostra vectraclaw-backend healthy)
curl http://localhost:3100/api/health

# Frontend
cd /c/Users/marce/VectraClip
npm run dev
# → http://localhost:3000

# Login com:
# email: marcelo.rosas@vectracargo.com.br
# senha: VectraClaw2026!

# Navegue para:
# /sipoc          — landing
# /sipoc/manage   — SipocManagement (FE-A/B/C)
# /sipoc/report   — SipocReport (FE-D)
# /org            — Org chart (FE-E)
```

---

## 7. Gotchas conhecidos

| Gotcha | Onde | Workaround |
|---|---|---|
| MSW SW persiste entre modos | Login 401 mesmo com `VITE_USE_MOCKS=false` | Desregistrar SW no DevTools (`reference_vectraclip_msw_footgun`) |
| `opacity-0 group-hover:opacity-100` esconde CRUD | já mapeado em 5 lugares (Goals/Tasks/StepNode/SipocSettings × 2) | NÃO replicar — sempre visível |
| `/agents/{id}?tab=skills` botão Salvar invisível | mesmo CSS bug | fix em outra batida — não tocar |
| Pequena demora schema cache pgrst | após migration backend, REST pode demorar ~5s pra refletir | `NOTIFY pgrst, 'reload schema'` já está em todas migrations recentes |
| Image Docker stale | `compose up -d` (sem `--build`) puxa imagem antiga | rodar `compose up --build -d backend` se ver regressão silenciosa |
| Multi-sessão Claude pisando | duas sessões mexem no mesmo arquivo | `docs/SESSOES-EM-CURSO.md` antes de cada checkout/commit |

---

## 8. Quando terminar

1. Atualize `docs/SESSOES-EM-CURSO.md` do VectraClaw — entries movidas pra "Concluídas hoje"
2. Reporte no chat: PRs criados, sub-PRs completados, gotchas novos encontrados
3. Se faltar tempo: deixe os sub-PRs incompletos marcados como `(WIP)` em SESSOES-EM-CURSO pra próxima sessão continuar

---

## 9. Backlog adjacente (não Lote 2)

Se o Lote 2 terminar com tempo de sobra, candidatos próximos:

- **Lote 3:** UI Risk Matrix consumindo G1 PR #150 (form CRUD + matriz 5×5 heatmap)
- **Lote 4:** Daedalus BPMN canvas (depende de PRs D-H backend que ainda não saíram)
- **Batidas 1-4 dos botões fantasmas** — outra sessão paralela é owner

Mas **pare e perguntar antes** — backlog priorizado fica em `docs/AUDIT-2026-05-16-CONSOLIDADO.md`.
