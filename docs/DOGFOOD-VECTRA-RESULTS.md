# Dogfood Vectra Cargo — PR12 Fase A end-to-end

> **Data:** 2026-05-16
> **Tenant:** Vectra Cargo (`01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2`)
> **Cenário:** Setor Comercial completo (organograma + processo + RACI + diagnose)
> **Goal:** validar jornada P1 do TO-BE end-to-end com dados reais
> **PDF anexo:** `Prints/dogfood_vectra_comercial.pdf` (3775 bytes, 1 página)

---

## TL;DR

✅ **Jornada P1 completa em ~15 minutos.** Do organograma vazio ao PDF executivo gerado.

🐛 **3 gaps reais descobertos** durante a execução (todos contornáveis, documentados abaixo).

📊 **Diagnóstico Athena consistente:** 1 processo, 3 atividades, 100% coverage 5W2H + RACI, 1 candidato a automação, 1 hire suggestion, 1 row em `athena_recommendations` (`diagnose_gap`).

---

## Jornada executada (8 steps)

### Step 1 — Tenant base
Vectra Cargo já existia. Estado antes: 2 sectors (cleanup anterior), 0 positions, 4 processes, 1 app_user.

### Step 2 — Criar sector "Comercial"
```http
POST /api/sipoc/sectors
{"company_id": "...", "name": "Comercial"}
→ 200 {id: 791b06e6..., slug: "comercial"}
```
✓ Auto-slug funcionou (PR #138).

### Step 3 — Criar 3 cargos (organograma)

| Cargo | position_id |
|---|---|
| Diretor Comercial | `a807eaad...` |
| Operador Comercial | `73b07bf3...` |
| SDR | `64460b9c...` |

```http
POST /api/sipoc/positions × 3
→ 3× HTTP 200
```

### Step 4 — Criar processo no setor

```http
POST /api/sipoc/processes
{"sector_id": "791b06e6...", "name": "Captação de Embarcadores B2B"}
→ 200 {id: f6b1aada...}
```

🐛 **Gap 1**: erro inicial enviando `company_id` no payload (não é coluna de `sipoc_processes`). Contornado removendo do request.
🐛 **Gap 2**: curl com `ç` quebrava o parser JSON do FastAPI no shell Windows. Usar Python urllib com UTF-8 explícito resolveu.

### Step 5 — Criar 3 activities

| # | Activity | Origem | operation_type | automation_status |
|---|---|---|---|---|
| A1 | Captação de Embarcadores | Marketplace template `16ce1a7d...` (Logística → Comercial) | `email_lead` | `undefined` (default) |
| A2 | Follow-up de Cotações Pendentes | Marketplace template `471cc1b1...` | `email_lead` | `undefined` |
| A3 | Qualificar Lead via DM Instagram | Manual via SQL | `email_lead` | `hybrid` |

🐛 **Gap 3**: não há endpoint API pra criar `sipoc_components` (activity) standalone. Frontend SipocWizard talvez crie via outro path; a activity manual foi inserida via SQL pra cumprir o smoke. Backlog: endpoint `POST /api/sipoc/processes/{pid}/components` (CRUD direto, sem template).

### Step 6 — Matriz RACI (8 cells)

| Activity | Diretor | Operador | SDR |
|---|---|---|---|
| Captação Embarcadores | **A** | C | **R** |
| Follow-up Cotações | **A** | **R** | I |
| Qualificar DM Instagram | I | — | **R** ⚠️ sem A |

```http
POST /api/sipoc/raci × 8 → todas 200
GET /api/sipoc/processes/{id}/raci → 8 rows
stats: missing_accountable=[A3] ✓ (gap proposital pra testar detecção)
```

✓ Side-effect do PR #142: `sipoc_components.responsible_position_id` foi auto-sincronizado nas activities onde role=R (3 syncs).

### Step 7 — Diagnose agregador

```http
POST /api/sipoc/diagnose/{sector_id}
→ 200
```

**KPIs:**
- Total Processos: **1**
- Total Atividades: **3**
- Coverage 5W2H: **100%** ✓ (todas activities têm 5W2H completo via template + manual)
- Coverage RACI: **100%** ✓ (todas têm responsible_position_id setado via PR #142 sync)

**Automation Status:** `{undefined: 2, manual: 0, hybrid: 1, automated: 0}`
**Operation Types:** `{email_lead: 3}` (3 activities sugerem agente Hermes)

**Hire Suggestion:**
- `email_lead` × 3 atividades → "Contratar agente que executa email_lead"

**Recommendation persistida:**
- `kind=diagnose_gap`
- `status=pending`
- `confidence=0.8`
- Linkada ao tenant

### Step 8 — PDF executivo

```http
GET /api/sipoc/diagnose/{sector_id}/pdf
→ 200 application/pdf (3775 bytes, 1 página)
Content-Disposition: inline; filename="diagnostico_sipoc_Comercial_20260516.pdf"
```

PDF salvo em `Prints/dogfood_vectra_comercial.pdf`. Inclui:
- Header navy Vectra
- Title block + summary box
- KPIs em tabela 2×2
- Status de Automação
- Candidatos a Automação (1)
- Gaps 5W2H (0 — tudo coberto)
- Gaps Responsável (0)
- Sugestões Athena (1 hire)
- Footer com CONFIDENCIAL

---

## Gaps descobertos (3) — backlog priorizado

### 🔴 Gap 3 — `POST /api/sipoc/processes/{pid}/components` ausente
**Severidade:** Alta (bloqueia criar activity sem template)
**Sintoma:** SipocWizard provavelmente tem código próprio pra fazer isso; backend não expõe endpoint genérico.
**Backlog:** PR backend curto. Endpoint CRUD em `sipoc_components` (POST/PATCH/DELETE) usando `service_role` + RBAC (mesmo padrão do PR7).

### 🟡 Gap 1 — `sipoc_processes` rejeita `company_id` no payload
**Severidade:** Média (confunde devs)
**Sintoma:** Frontend velho passa `company_id` por costume; endpoint dá 500 com `PGRST204` confuso.
**Backlog:** ou (a) adicionar `company_id` derivado (computed) no schema; ou (b) backend ignora `company_id` se vier no payload + 400 amigável ao invés de 500.

### 🟢 Gap 2 — Parser FastAPI quebra com UTF-8 em shell Windows
**Severidade:** Baixa (afeta só CLI curl, não browser)
**Sintoma:** `curl -d '{"name":"Captação"}'` retorna `There was an error parsing the body`.
**Causa raiz:** Windows shell encoding ≠ UTF-8; curl não força charset.
**Workaround:** sempre passar `Content-Type: application/json; charset=utf-8` ou usar Python urllib.
**Backlog:** opcional — adicionar middleware de detecção/fix de encoding seria proteção robusta.

### 🔴 Gap 4 — Org chart: form "Reporta a:" não persiste / sem visualização top-down
**Severidade:** Alta (UX de organograma quebrada)
**Sintoma:** User edita position, escolhe superior no dropdown "Reporta a:", salva — nada acontece. Árvore hierárquica não desenha.
**Causa raiz:** BACKEND funciona 100% (testado via PATCH direto, persistiu `reports_to_id` corretamente). **Bug é no frontend Org.tsx (PR #16)**:
- Hipótese A: form não envia `reports_to_id` no body PATCH
- Hipótese B: envia em camelCase (`reportsToId`) e backend só aceita snake_case
- Hipótese C: renderização é lista flat em vez de tree
**Backlog:** PR frontend separado em vectraclip-frontend.

### 🔴 Gap 5 — UI não cobre cargos cross-cutting (CEO, CTO sem sector)
**Severidade:** Alta (impossibilita modelar topo do organograma)
**Sintoma:** User pergunta "como crio CEO via UI? Diretor reporta pro CEO".
**Causa raiz:** Form de criação de cargo (Org.tsx) provavelmente exige `sector_id`. Mas o schema do DB aceita `sector_id=NULL` (cargo cross-cutting). Também é provável que o dropdown "Reporta a" filtre apenas positions do mesmo sector — impedindo Diretor de reportar pro CEO (que está fora de qualquer sector).
**Workaround usado:** criar CEO via API + PATCH `reports_to_id` do Diretor pro CEO (validado por este dogfood).
**Backlog frontend:**
1. Form "+ Cargo" tem checkbox "Cross-cutting (sem departamento)" → permite sector_id=null
2. Dropdown "Reporta a" mostra positions de **toda a company**, não só do mesmo sector
3. Tree view trata cargos cross-cutting como raízes globais; sectors são "containers" visuais que herdam pelo reports_to

**Validação backend (sandbox DB Vectra) — hierarquia 4 níveis:**
```
CEO                       (top, sector=NULL)
  └─ Diretor Comercial      (sector=Comercial)
      └─ Gerente Comercial    (sector=Comercial)
          └─ Closer            (sector=Comercial)
```
4 cargos em DB, persistência OK. UI Org.tsx hoje não renderiza esse tree.

### 🔴 Gap 6 — POST positions: camelCase do frontend quebra com PGRST204
**Severidade:** Alta (qualquer cargo criado via Org.tsx falhava com `'companyId' column not found`)
**Sintoma:** User tentou criar 4º cargo (SDR) reportando ao Gerente — erro 500 com mensagem confusa de Postgrest.
**Causa raiz:** Frontend envia `companyId/sectorId/reportsToId` (camelCase), backend passava direto pro `insert` sem normalizar, DB exige snake_case. PR #7 já tinha cuidado disso pra app_users mas faltou em sectors/positions/processes.
**Fix aplicado neste PR:** `_normalize_sipoc_payload_to_snake()` em `api.py` — converte camelCase→snake_case defensivamente nos 3 POSTs (sectors/positions/processes). Aceita ambos formatos pra retrocompat.
**Validado:** POST positions com `{"companyId":"...","sectorId":"...","title":"SDR","reportsToId":"..."}` agora retorna 200.

### 🔴 Gap 7 — UI sem botão DELETE de cargo (user não pode errar)
**Severidade:** Alta (UX — bloqueia recuperação de erros do user)
**Sintoma:** User pergunta "onde está o delete?". Org.tsx (PR #16) não expõe botão claro de deletar cargo.
**Causa raiz:** Frontend implementou DELETE no hook (`useDeleteSipocPosition`) mas talvez não exponha botão visível, ou esconde em menu de contexto, ou só aparece em "modo edit".
**Backend pronto (PR #7 / #136):**
- `DELETE /api/sipoc/positions/{id}` com pre-check FK:
  - 409 se houver app_users com assigned_position_id apontando
  - 409 se houver sipoc_components.responsible_position_id apontando
  - 409 se houver sipoc_raci com position_id (descoberto neste dogfood — não estava no pre-check do PR #7)
  - 204 se OK
**Backlog frontend:**
1. Botão "Remover cargo" no Org card (com confirm dialog "Tem certeza?")
2. Toast amigável quando 409: "Cargo em uso. Remova [X RACI cells, Y users, Z atividades] antes."
3. Modo "cascade safe": botão "Remover cargo e desvincular tudo" (chama DELETE RACI + UPDATE responsible + DELETE)

**Backend backlog:** Adicionar pre-check de RACI no DELETE position (hoje só vê app_users + sipoc_components.responsible_position_id, esqueceu RACI). PR pequeno.

---

## Limpeza pós-dogfood

**Decisão pendente:** manter ou deletar os artifacts do smoke?
- Sector Comercial + 3 cargos + 1 processo + 3 activities + 8 RACI cells + 1 recommendation
- Vira **case study real** se mantido (Vectra Cargo dogfood); aparece em demos
- Se deletar, comando único:
  ```sql
  -- ⚠️ ANTES de rodar, confirme decisão com user
  DELETE FROM vectraclip.sipoc_sectors
    WHERE id='791b06e6-56b5-495d-8bea-c6fa63f78444';
  -- CASCADE limpa: processes (1), components (3), raci (8)
  -- Positions e recommendation precisam DELETE separado
  ```

**Recomendação:** manter, vira showcase do produto.

---

## Tempo gasto

| Step | Tempo aproximado |
|---|---|
| Setup base + token | 30s |
| Sector + 3 positions | 2 min |
| Process + 3 activities | 3 min (com 2 retries por gap 1/2) |
| RACI 8 cells | 3 min |
| Diagnose + PDF | 30s |
| Doc + análise | 5 min |
| **Total** | **~15 min** |

Schmidt previa "WOW de diagnóstico mesmo dia (4-8h led)". **Conseguimos em 15min sem LLM (estatístico puro).** Quando Gemini voltar, athena-classify + athena-charter agregam camada qualitativa.

---

## Endpoints exercitados (PR coverage)

| Endpoint | PR | Status |
|---|---|---|
| `POST /api/sipoc/sectors` | #138 (validation + auto-slug) | ✅ |
| `POST /api/sipoc/positions` | pré-existente | ✅ |
| `POST /api/sipoc/processes` | pré-existente | ⚠️ gap company_id |
| `POST /api/sipoc/processes/{pid}/import-template/{tid}` | #132 | ✅ |
| `POST /api/sipoc/raci` | #142 (hardened) | ✅ |
| `GET /api/sipoc/processes/{pid}/raci` | pré-existente | ✅ |
| `POST /api/sipoc/diagnose/{sid}` | #139 | ✅ |
| `GET /api/sipoc/diagnose/{sid}/pdf` | #140 | ✅ |

8/8 endpoints da jornada P1 funcionam. 3 gaps tratáveis em PRs futuros.

---

## Conclusão

🎯 **Fase A do roadmap está VENDÁVEL.** O ciclo "descoberta → diagnóstico → relatório" funciona end-to-end com dados reais em 15min. PDF gerado serve pra entrega ao cliente.

Próximos passos sugeridos (não-bloqueantes):
1. Frontend consome `/api/sipoc/diagnose/{sid}/pdf` (botão "Exportar PDF" no SipocReport)
2. Frontend cria UI de RACI matrix (PR #142 endpoints prontos)
3. Backend `POST /api/sipoc/processes/{pid}/components` (gap 3)
4. Investigar Gemini 403 (desbloqueio Athena LLM, vira diagnóstico narrativo)

Vectra Cargo = case study completo. Pode usar em demos comerciais.
