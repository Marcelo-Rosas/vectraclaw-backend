# Plano — Limpeza de hardcode em `src/agents/` (auditoria 2026-05-20)

> Fonte: hardcode-auditor sobre `src/agents/*.py`. 0 P0, 7 P1, 9 P2.
> Cada PR ataca 1 arquivo/tema. Ordem = risco (vazamento multi-tenant > config quebrada > acoplamento > cosmético).
> Regra de Ouro #2: valor com tabela espelho não pode morar em `.py`.

---

## ✅ PR1 — oracle_checker.py modelo fixo → catalog-driven `[FEITO #285]`
- **Risco:** config de modelo por tenant não chegava no checker (maker≠checker).
- **Fix:** `generate(DEFAULT_MODEL,...)` → `generate_for_agent(ORACLE_AGENT_ID,...,fallback_model=DEFAULT_MODEL)` em 3 callers.
- **Tabela espelho:** `agent_adapter_configs` / `agent_specialty_configs.values["model_id"]`.
- **Status:** PR #285 aberto.

---

## 🔴 PR2 — kronos.py `DEFAULT_RECIPIENT` (vazamento multi-tenant) `[PRÓXIMO]`
- **Arquivo:linha:** `kronos.py:37-40` — `DEFAULT_RECIPIENT = os.getenv("KRONOS_DEFAULT_RECIPIENT", "marcelo.rosas@vectracargo.com.br")`
- **Risco P1 ALTO:** cliente novo sem env → relatório financeiro vai pro e-mail PESSOAL do Marcelo (vazamento PII + dado financeiro de outro tenant).
- **Tabela espelho:** `companies` (campo de e-mail operacional/notificação).
- **Fix:** remover literal; resolver `recipient` de `companies.<email_field>` pelo `company_id` da task no handler; se ausente → marcar task `blocked` com motivo (não chutar e-mail).
- **Pré-req:** confirmar qual coluna em `companies` guarda e-mail de notificação (SELECT antes — Regra #1). Se não existir, P2 vira migration de coluna.
- **Escopo:** `kronos.py` handler + remoção do literal. Sem migration se coluna já existe.

---

## 🟠 PR3 — kronos.py fallback silencioso de regras `[QUICK]`
- **Arquivo:linha:** `kronos.py:~999` `load_rules_from_db()` cai em `_EXPENSE_RULES`/`_REVENUE_RULES` (Python, ~130 tuplas) sem avisar.
- **Risco:** se `kronos_rules` (tabela JÁ existe) fica indisponível, Kronos roda regras velhas silenciosamente.
- **Fix mínimo (1 linha):** `logger.warning("kronos: regras do fallback hardcoded — kronos_rules indisponível", extra={"rules_source":"hardcoded_fallback"})` antes do return.
- **Fix longo (separado):** migrar as ~130 tuplas pra seed em migration; Python vira fallback de emergência só.
- **Pode bundlar com PR2** (mesmo arquivo, mesmo restart).

---

## 🟠 PR4 — oracle.py `_VECTRA_CONTEXT` → `companies.context_json`
- **Arquivo:linha:** `oracle.py:220-226` — descrição da Vectra cravada, usada pra TODO tenant.
- **Tabela espelho:** `companies.context_json` (Athena já lê via `_get_company_context(supabase, company_id)`).
- **Fix:** trocar `_VECTRA_CONTEXT` por chamada a `_get_company_context(company_id)`; popular `context_json` no `athena-onboarding`. Padrão já existe — copiar do Athena.
- **Escopo:** `oracle.py` + reuso do helper.

---

## ✅ PR5 — hermes_reporter.py header/subject tenant-locked `[FEITO #287]`
- **Arquivo:linha:** `hermes_reporter.py:117-118` (`render_html` defaults) + `:383` (subject fallback).
- **Tabela espelho:** `companies.name`.
- **Fix:** `render_html(..., company_name=None, report_type=None)` deriva header/footer de `companies.name` + report_type do payload; `_resolve_company_name(company_id)` lê DB; subject fallback genérico. Também corrigido o caller gêmeo em `agent_daemon.py:1059` ("Vectra Cargo — Oracle Research" → params genéricos).
- **Conecta com cotação:** Hermes Reporter agora genérico (header/assunto por payload) — pré-requisito do fluxo de resposta de cotação.

## 🔴 PR8 — agent_daemon.py:1052 recipient literal (NOVO — achado no PR5)
- **Arquivo:linha:** `agent_daemon.py:1052` — `os.getenv("ORACLE_REPORT_EMAIL", "marcelo.rosas@vectracargo.com.br")` no envio do oracle-research report.
- **Risco P1:** mesma classe do kronos DEFAULT_RECIPIENT — multi-tenant vaza relatório Oracle pro e-mail pessoal do Marcelo.
- **Tabela espelho:** `companies.notification_email` (já criada no #286).
- **Fix:** resolver de `companies.notification_email` pelo company_id da task; fail-loud se ausente.

---

## 🟡 PR6 — oracle.py `thinking_budget=4096` fixo
- **Arquivo:linha:** `oracle.py:808` — `ThinkingConfig(thinking_budget=4096)` no research handler.
- **Tabela espelho:** `agent_specialty_configs.values["thinking_budget"]` (Athena já resolve via `resolve_value`).
- **Fix:** `resolve_value("thinking_budget", ..., default=4096)`.

---

## 🟣 PR7 — agent_daemon.py dispatch por op_type literal → `operation_types_catalog` `[ESTRUTURAL — separado]`
- **Arquivo:linha:** `agent_daemon.py:548-661` — dispatch roteia por string literal de operation_type.
- **Tabela espelho:** `operation_types_catalog` (55+ rows JÁ existe) + as 3 listas sincronizadas (Pydantic em `models.py` + CHECK no DB + dispatch).
- **Risco:** estrutural — impede roteamento dinâmico; é a raiz do caso `oracle-report` (op_type content-specific cravado).
- **Escopo GRANDE:** toca 3 listas + handlers + tasks existentes. **NÃO é PR pequeno.** Requer:
  1. dispatch ler `operation_types_catalog` (op_type → agent + handler)
  2. desacoplar `oracle-report` → capability genérica `email-send` (Hermes Reporter já tem specialty `responsavel-pelo-disparo-de-e-mails`)
  3. migrar tasks `oracle-report` existentes
- **Decisão Marcelo antes:** atacar agora (raio grande) OU só depois do fluxo de cotação definir o `email-send`? Conecta com ADR-VEC-INBOUND-INTENT-CLASSIFIER (decisão pendente).

---

## P2 (backlog — sem tabela espelho ainda)
- `oracle.py` dicts labels SIPOC (`_PROFILE_LABELS`, `_STAGE_LABELS`, `_SIPOC_TYPE_LABELS`) → candidato `sipoc_config` futura
- `_VALID_PATTERNS` (6 padrões, duplicado oracle_maker+checker) → tabela se crescer
- `athena.py` thresholds quality grade (`>=200`, `>=1000`); `confidence=0.9`
- magic numbers truncamento (`_RESEARCH_SECTIONS_MAX_CHARS`, `[:12000]`)

---

## Ordem recomendada
1. ✅ PR1 oracle_checker (#285)
2. 🔴 PR2+PR3 kronos (vazamento e-mail + log fallback) — **mesmo PR, alto risco**
3. 🟠 PR4 oracle _VECTRA_CONTEXT
4. 🟡 PR5 hermes_reporter genérico (destrava cotação)
5. 🟡 PR6 oracle thinking_budget
6. 🟣 PR7 dispatch estrutural — só após decisão de escopo
