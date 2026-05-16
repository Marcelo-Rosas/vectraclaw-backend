# SIPOC Data Flow — Fonte → Consumidores → Output

> **O que é este doc:** mapa de **quem produz dado**, **quem consome**, e **que output entrega valor** pra cada entidade SIPOC. Resposta direta à pergunta "qual é o papel da estrutura organizacional + RACI no produto?"
>
> Útil pra: onboarding novo dev, decisões de produto sobre o que UI mostrar, debug de "por que esse dado importa".

---

## TL;DR — As 3 fontes de verdade

1. **`sipoc_positions`** — organograma da empresa (cargos com hierarquia `reports_to_id`)
2. **`sipoc_sectors` + `sipoc_processes` + `sipoc_components`** — o mapa do trabalho (setor → processo → S/I/P/O/C + activities)
3. **`sipoc_raci`** — a ligação entre cargo e atividade (R/A/C/I)

Tudo o mais é **derivado** dessas 3.

---

## 1. `sipoc_positions` (Estrutura Organizacional)

### Papel
Espelha o **organograma real** da empresa. Cada row = um cargo (não pessoa). Pode ser cross-cutting (`sector_id=NULL`, ex: CEO/CTO) ou vinculado a setor (`sector_id` populated, ex: "Diretor Comercial").

### Fonte da verdade
- Criada via `POST /api/sipoc/positions` (UI Org.tsx ou via wizard)
- Editada via `PATCH /api/sipoc/positions/{id}` (admin endpoints PR #136)
- Hierarquia via `reports_to_id` (self-FK)

### Quem consome (downstream)

| Consumidor | Como usa | Onde |
|---|---|---|
| **`app_users.assigned_position_id`** | Liga user a cargo | Auth + RBAC sector_responsible scope (PR #6) |
| **`sipoc_components.responsible_position_id`** | Atalho: quem é o R da activity | Oracle chat scoped (PR #5), diagnose (PR #9) |
| **`sipoc_raci.position_id`** | Quem é R/A/C/I em cada activity | Matrix RACI (PR #142) |
| **Org chart UI** | Renderiza árvore top-down | (Gap 4/5 — frontend pendente) |
| **Athena diagnose** | Calcula `responsibleCoveragePct` | endpoint `/api/sipoc/diagnose` |
| **PDF executivo** | Seção "Atividades sem Responsável" | endpoint `.../pdf` |

### Output que entrega valor

- **Pra cliente:** clareza de "quem responde pelo quê" — sem isso, automação não tem dono
- **Pra Athena:** scope RBAC (sector_responsible só vê suas activities)
- **Pra diagnóstico:** métrica `responsibleCoveragePct` (% activities com RACI)

### Diagrama

```
sipoc_positions
  ├── self-FK reports_to_id  (hierarquia)
  │
  ├── consumed by ──→ app_users.assigned_position_id  (login multi-tenant)
  │                       │
  │                       └─→ RBAC sector_responsible
  │                              │
  │                              └─→ Oracle chat scoped per activity
  │
  ├── consumed by ──→ sipoc_components.responsible_position_id  (atalho R)
  │                       │
  │                       └─→ Athena diagnose KPI: responsibleCoveragePct
  │                              │
  │                              └─→ PDF executivo: "Atividades sem Responsável"
  │
  └── consumed by ──→ sipoc_raci.position_id  (matrix R/A/C/I)
                          │
                          └─→ Athena stats: overloaded_positions
                                              missing_accountable
                                              multiple_accountable
```

---

## 2. `sipoc_sectors` → `sipoc_processes` → `sipoc_components` (Mapa do Trabalho)

### Papel
Decompõe a empresa em **setores → processos → atividades + componentes SIPOC** (Suppliers, Inputs, Outputs, Customers, Activities).

### Fonte da verdade
- **Setor:** `POST /api/sipoc/sectors` (admin cria; auto-slug)
- **Processo:** `POST /api/sipoc/processes` (dentro de sector)
- **Componente (activity, supplier, input, output, customer):**
  - Via marketplace: `POST /api/sipoc/processes/{pid}/import-template/{tid}` (PR #132)
  - Standalone: **Gap 3 — endpoint POST direto não existe** (só SQL ou SipocWizard)

### Quem consome (downstream)

| Consumidor | Como usa | Onde |
|---|---|---|
| **`sipoc_edges`** | Conecta componentes em fluxo S→I→A→O→C | Diagrama visual SipocManagement |
| **`sipoc_raci`** | RACI por activity (cada cell linka component + position) | Matrix RACI |
| **`sipoc_components.suggested_operation_type`** | FK pro catálogo operation_types | Athena recomenda agente que executa esse op_type |
| **`sipoc_components.automation_status`** | undefined/manual/hybrid/automated | Diagnose: distribução automação por sector |
| **`sipoc_components.diagnostic_metadata`** | JSONB livre da Athena | Diagnose + PDF |
| **`sipoc_components.cloned_from_template_id`** | Auditoria: veio do marketplace? | Analytics adoção de templates |
| **Athena diagnose agregador** | Roda KPIs por sector | `POST /api/sipoc/diagnose/{sid}` |
| **PDF executivo** | 6 seções (KPIs, gaps, candidatos) | `GET .../pdf` |
| **Athena recommendations** | Gera `kind=diagnose_gap` | tabela `athena_recommendations` |

### Output que entrega valor

- **Pra cliente:** mapa visual do que sua empresa faz (entregável de consultoria)
- **Pra Athena:** matéria-prima do diagnóstico (sem activities mapeadas, diagnose retorna vazio)
- **Pra automação (P2):** marca quais activities virar agente — vira lista de "hire_new_agent" recommendations

### Diagrama

```
sipoc_sectors  (mapa setorial)
  │ has many
  ▼
sipoc_processes  (processos do setor)
  │ has many
  ▼
sipoc_components  (S/I/P/O/C + activities)
  ├── connected by ──→ sipoc_edges  (fluxo SIPOC visual)
  │                       │
  │                       └─→ SipocManagement diagrama
  │
  ├── consumed by ──→ sipoc_raci  (papéis nas activities)
  │
  ├── automation_status ──→ Athena diagnose KPIs
  │                            │
  │                            └─→ PDF "Status Automação"
  │
  ├── suggested_operation_type ──→ Athena hireSuggestions
  │                                   │
  │                                   └─→ "Contratar agente que executa X"
  │
  └── responsible_position_id ──→ (link já mostrado em positions)
```

---

## 3. `sipoc_raci` (RACI — Matriz Stakeholder × Atividade)

### Papel
**Liga organograma ao mapa do trabalho.** Cada row = "cargo X tem papel Y na atividade Z". Schmidt PMBOK §"Engage Stakeholders".

### Fonte da verdade
- `POST /api/sipoc/raci` (upsert por `(component_id, position_id)`) — PR #142 hardened
- `DELETE /api/sipoc/raci/{component_id}/{position_id}` — PR #142

### Quem consome (downstream)

| Consumidor | Como usa | Onde |
|---|---|---|
| **`sipoc_components.responsible_position_id`** | Auto-sync quando role='R' (PR #142) | Atalho leve do R |
| **`calculate_raci_stats` (service)** | Calcula 3 alertas: | `services/sipoc_raci.py` |
|  | • overloaded_positions (>3 R's por cargo) | |
|  | • missing_accountable (activity sem A) | |
|  | • multiple_accountable (activity com >1 A) | |
| **GET process raci** | Retorna matrix + stats | `GET /api/sipoc/processes/{pid}/raci` |
| **Athena diagnose** | Detecta gaps de governança | Backlog: ainda não consumido formalmente |
| **Frontend Org/Process** | Matrix visual R/A/C/I | (Gap 7+ — UI ainda pendente) |

### Output que entrega valor

- **Pra cliente:** prova que cada atividade tem dono (A) e executor (R) — fundamento de governança
- **Pra Athena:** identifica gargalos:
  - "Operador Comercial está em 5 R's — sobrecarga"
  - "Activity X sem Accountable — risco de fracasso silencioso"
  - "Activity Y com 2 Accountables — disputa de poder"
- **Pra Schmidt:** materializa o "Engage Stakeholders" do framework
- **Pra automação (P2):** define quem aprova quando automation_status muda

### Diagrama

```
sipoc_positions  ─────┐                ┌───── sipoc_components
                       │                │      (type=activity)
                       ▼                ▼
                  ┌─────────────────────────┐
                  │     sipoc_raci          │
                  │  (matrix R/A/C/I)       │
                  └────────────┬────────────┘
                               │
                               ├─→ calculate_raci_stats (service)
                               │       ├── overloaded_positions
                               │       ├── missing_accountable
                               │       └── multiple_accountable
                               │
                               ├─→ trigger sync: responsible_position_id (PR #142)
                               │
                               └─→ Athena diagnose (futuro):
                                       └── kind=diagnose_gap incluir RACI gaps
```

---

## 4. Visão geral consolidada (todo o flow)

```
                              ENTRADA (admin UI / wizard)
                                       │
       ┌───────────────────────────────┼──────────────────────────────┐
       │                               │                              │
       ▼                               ▼                              ▼
┌──────────────┐              ┌──────────────┐              ┌──────────────┐
│sipoc_positions│             │ sipoc_sectors│             │              │
│  (cargos)    │              │  →processes  │             │  marketplace │
│              │              │  →components │◄────────────│  templates   │
│  reports_to  │              │              │   clone      │ (global)     │
│  (self-tree) │              │ S/I/O/C/A    │              │              │
└──────┬───────┘              └──────┬───────┘              └──────────────┘
       │                             │
       │                             ├──→ sipoc_edges (fluxo SIPOC)
       │                             │
       └──────────┬──────────────────┘
                  ▼
          ┌──────────────┐
          │  sipoc_raci  │  ← liga cargo a atividade (R/A/C/I)
          └──────┬───────┘
                 │
                 ├─→ calculate_raci_stats (overloaded/missing-A/multi-A)
                 │
                 └─→ auto-sync responsible_position_id em sipoc_components

                          DERIVADOS / CONSUMIDORES
                                       │
       ┌───────────────────────────────┼──────────────────────────────┐
       │                               │                              │
       ▼                               ▼                              ▼
┌──────────────┐              ┌──────────────┐              ┌──────────────┐
│app_users.    │              │ Athena       │              │ Oracle chat  │
│assigned_     │              │ diagnose     │              │ scoped per   │
│position_id   │              │ agregador    │              │ activity     │
│              │              │              │              │              │
│ RBAC scope   │              │ KPIs +       │              │ contexto +   │
│ sector_      │              │ gaps +       │              │ RAG empresa  │
│ responsible  │              │ candidatos   │              │              │
└──────────────┘              └──────┬───────┘              └──────────────┘
                                     │
                                     ├─→ athena_recommendations (kind=diagnose_gap)
                                     │
                                     └─→ PDF executivo (6 seções Vectra layout)
```

---

## 5. O que entrega valor pro cliente (síntese)

| Pergunta do cliente | Entidade que responde | Output concreto |
|---|---|---|
| "Quem manda aqui?" | `sipoc_positions` + `reports_to_id` | Org chart hierárquico top-down |
| "O que minha empresa faz?" | `sipoc_sectors` → `processes` → `components` | Mapa SIPOC visual por setor |
| "Quem é responsável por isso?" | `sipoc_raci` (role=R) | Tabela "Esta atividade é executada por X" |
| "Quem responde se der errado?" | `sipoc_raci` (role=A) | Tabela "Esta atividade tem A=Y" |
| "Onde tem gargalo?" | `calculate_raci_stats` | Lista de cargos sobrecarregados + activities sem A |
| "O que vale automatizar?" | `sipoc_components.automation_status` + Athena diagnose | Lista de candidatos com ROI estimado |
| "Quanto vou gastar automatizando?" | `operation_types_catalog` + Athena hire suggestions | "Contratar 1 agente Hermes ~$50/mês cobre 3 activities" |
| "Quero relatório executivo" | PDF endpoint | PDF Vectra branding com 6 seções |

---

## 6. Gaps conhecidos (do dogfood PR #143)

Esses **interrompem o fluxo de valor**:

| Gap | Onde fura | Impacto |
|---|---|---|
| **Gap 3** — Sem POST `/api/sipoc/processes/{pid}/components` | Não dá pra criar activity standalone via API | Pra criar activity sem template, só via SQL ou via Wizard |
| **Gap 4** — Org chart não desenha tree | UI Org.tsx lista flat | Cliente não enxerga hierarquia visual (frustrante) |
| **Gap 5** — UI sem cargo cross-cutting | Form exige sector | CEO/CTO impossível via UI (só backend) |
| **Gap 7** — UI sem botão DELETE | Org/Process/Activity sem "Remover" | User erra e fica preso (precisa pedir admin) |

Backend dos Gaps 3+7 já existe (PRs #142 #144). Gap 4+5 são frontend Org.tsx.

---

## 7. Para onde vai (futuro — Schmidt completo)

Quando Athena tiver os 4 handlers PMBOK completos (PR9 só implementou diagnose; faltam classify-metrics, identify-risks, charter):

```
sipoc_positions + sipoc_raci + sipoc_components
                       │
                       ▼
              ┌────────────────┐
              │ Athena PMO     │
              │ analise full   │
              │                │
              │ • classify     │ ← já existe (PR3)
              │ • metrics      │ ← faltam handlers
              │ • risks        │ ← faltam handlers
              │ • charter      │ ← já existe (PR4)
              └────────┬───────┘
                       │
                       └─→ athena_recommendations (8 kinds canônicos PR #141)
                              │
                              ├─→ executáveis (5): hire_new_agent, add_specialty, etc.
                              └─→ informativos (3): diagnose_gap, suggest_automation, suggest_hire_agent
```

**Diferencial Schmidt:** quando todos handlers ativarem, **cada activity terá:**
- WHO (RACI já entrega)
- WHAT/WHY (5W2H já entrega)
- HOW MUCH (athena-metrics futuro)
- WHAT IF (athena-risks futuro)
- WHERE TO (athena-charter já entrega)

Aí o produto vira **consultoria PMO completa**, não só mapeamento.
