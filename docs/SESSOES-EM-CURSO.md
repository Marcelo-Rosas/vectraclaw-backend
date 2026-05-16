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
| Auditoria Botões Fantasmas → Batidas 1-4 | sessão paralela do user | _(a definir)_ | `GoalTree`, `TaskCard`, `StepNode`, `SipocSettings`, `SipocManagement`, `UserMenu`, `SipocReport`, `CompanySettings`, `SipocDiagnosticCard`, `SipocWizard` | 2026-05-16 | aberto |
| execution_mode catalog-driven + CODE-PATTERNS | esta sessão (Opus 4.7) | `feat/agent-execution-catalog-driven` | `models.py:463`, `api.py:5125,5938`, `AgentExecutionCard.tsx`, `types/api.ts`, `schemas.ts`, `agents.ts`, `keys.ts`, `queries/agents.ts`, novo `DynamicSchemaForm.tsx`, novos `docs/CODE-PATTERNS.md`, `docs/AUDIT-2026-05-16-CONSOLIDADO.md`, este | 2026-05-16 | fechando |

---

## Concluídas hoje (2026-05-16)

| O que | PR | Closed |
|---|---|---|
| Lote 1 SIPOC BE-A/B/C (PATCH sectors/processes, POST/PATCH components) | #145 | hoje |
| DELETE hierárquico SIPOC | #144 | hoje |
| Dogfood Vectra Cargo end-to-end | #143 | hoje |
| Athena diagnose agregador por setor (PR9 Fase A) | #139 | hoje |
| SIPOC input validation + auto-slug nos POSTs | #138 | hoje |

---

## Como usar este arquivo

- **Edite no início da sessão**, antes do primeiro tool use significativo
- 1 linha por workstream, não por commit
- `Arquivos` = lista dos paths que vai tocar (greppável)
- Se outra sessão precisa esperar, comente no PR dela em vez de bloquear silenciosamente
- O `MEMORY.md` é histórico privado; este aqui é o **agora compartilhado**
