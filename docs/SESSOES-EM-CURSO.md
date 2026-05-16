# Sessões em curso

> **Antes de começar qualquer trabalho não-trivial, leia esta tabela.**
> Se já tem alguém mexendo no que você ia mexer, escolha outra coisa ou alinhe.
>
> **Quando você começar**, adicione 1 linha aqui (mesmo PR/branch).
> **Quando terminar**, mova pra "Concluídas hoje" ou remova.

---

## Ativas

| Sessão | Owner | Branch / PR | Arquivos | Iniciada | ETA |
|---|---|---|---|---|---|
| Dogfood cotação Vectra (ADR PMBOK) — UI manual + standby pra investigar quebras | esta sessão + Marcelo | `docs/adr-cotacao-dogfood-freight` (PR aberto) | `docs/ADR-VEC-COTACAO-DOGFOOD-FREIGHT.md` (novo), `docs/AUDIT-HANDLERS-2026-05-16.md` | 2026-05-17 00:30 | indefinido (dogfood manual) |

---

## Concluídas hoje (2026-05-16)

| O que | PR | Closed |
|---|---|---|
| **fix bug #3 E2E Lote 2** — GET /sipoc/sectors embed processes[] (SipocProcessSummary novo + PostgREST embed); validado em prod end-to-end; bug #1 também confirmado RESOLVED em prod | #174 | hoje |
| **Daedalus PR G+H** (FINAL): handler estatístico + dispatch + launcher (11º daemon online) | #159 | hoje |
| **Daedalus PR F**: specialty bpmn-modeling + agent Daedalus + config (13/13 smoke) | #158 | hoje |
| **Daedalus PR E**: CRUD bpmn_diagrams + duplicate + versions + hotfix SECURITY DEFINER | #156 | hoje |
| **Daedalus PR D**: bpmn_diagrams + bpmn_diagram_versions + trigger snapshot inteligente | #154 | hoje |
| **Lote 2 Frontend handoff** doc autossuficiente (5 sub-PRs FE-A..E ~10h) | #153 | hoje |
| **G1 Risk Register PMBOK completo (A+B+C)**: tabela `vectraclip.risks` + CRUD + persistência Athena | #149 + #150 + #151 | hoje |
| execution_mode catalog-driven (backend) + CODE-PATTERNS / AUDIT / SESSOES docs | backend #146 | hoje |
| AgentExecutionCard catalog-driven + DynamicSchemaForm reutilizável (frontend) | frontend #22 | merged |
| Auditoria de botões fantasmas + semáforo de sessões em curso (frontend) | _(commit `8cb2d8f` na branch `docs/sessoes-em-curso-e-auditoria-botoes`)_ | hoje (sessão paralela) |
| Lote 1 SIPOC BE-A/B/C (PATCH sectors/processes, POST/PATCH components) | #145 | hoje |
| DELETE hierárquico SIPOC | #144 | hoje |
| Dogfood Vectra Cargo end-to-end | #143 | hoje |
| Athena diagnose agregador por setor (PR9 Fase A) | #139 | hoje |
| SIPOC input validation + auto-slug nos POSTs | #138 | hoje |

### Decisões registradas (não executadas) — vindas da auditoria de botões fantasmas

| Item | Decisão | Owner |
|---|---|---|
| `UserMenu.tsx:75,80` "Perfil" / "Configurações" toasts vazios | ✅ **APROVADO (2026-05-16): Opção B** — apontar para `/settings/user` (já existe). Aguarda execução pela sessão paralela. | sessão paralela (frontend) |
| `SipocReport.tsx:498` "Detalhes em breve" | **Manter** — placeholder consciente do PR #18 | — |
| `SipocSettings.tsx:48` "Exportar RACI consolidada" | Decisão pendente: remover botão até backend existir OU manter como signal de roadmap | user |
| `CompanySettings.tsx:150` "Convidar" disabled hard-coded | Investigar motivo antes de remover ou habilitar | user |

### Incidente registrado — colisão de checkout (evidência viva do problema)

Em 2026-05-16, duas sessões caíram acidentalmente na branch `feat/agent-execution-card-catalog-driven` uma da outra e cada uma pensou que estava em "branch alheia". Resolvido sem perda de trabalho (a sessão paralela recriou sua branch limpa em cima de main; os 2 docs untracked sobreviveram). É o caso de uso exato que motivou criar este `SESSOES-EM-CURSO.md`. Memory `multi-session-coordination` atualizada com o incidente como exemplo.

---

## Como usar este arquivo

- **Edite no início da sessão**, antes do primeiro tool use significativo
- 1 linha por workstream, não por commit
- `Arquivos` = lista dos paths que vai tocar (greppável)
- Se outra sessão precisa esperar, comente no PR dela em vez de bloquear silenciosamente
- O `MEMORY.md` é histórico privado; este aqui é o **agora compartilhado**
