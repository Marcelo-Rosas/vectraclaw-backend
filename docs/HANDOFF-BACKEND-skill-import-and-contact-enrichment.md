# HANDOFF — Backend (vectraclaw-backend)

> Destino: mover para `vectraclaw-backend/docs/HANDOFF-BACKEND-skill-import-and-contact-enrichment.md`.
> Origem: sessão 2026-05-20 (cargo-flow-navigator). Cobre **tudo que é backend** discutido.
> Regras de ouro aplicáveis: #1 (espelhar antes / P7), #2 (no hardcode / catalog-driven),
> #6 (DDL só via `supabase/migrations/` + `db push`, nunca MCP/API). Ver `docs/CODE-PATTERNS.md`.

---

## Bloco A — Preparar banco para import de skills via UI (SaaS self-service)

### Contexto
Cliente externo NÃO roda migration → catálogo de skills tem que receber via UI/API em runtime.
Decisão de arquitetura (travada): **NÃO** adicionar `company_id` a `agent_specialties` —
viola contrato `CONTRACTS-AGENT-CAPABILITIES.md` §0 (catálogos = GLOBAL SSOT) e quebraria
consumidores globais (`specialty_resolver`, `morpheus_dispatcher`, `agent_daemon`, `daedalus`,
`oracle`, `athena`, `agent_skills`, `models.py`; front: `AgentBuilder`, `AdminSpecialties`,
`agentSpecialties` queries). Caminho correto = staging `skill_import_proposals` (contrato §3.2) +
governança `source`/`status` (colunas já existem) + curadoria → `agent_specialties status=draft`.

### Decisões travadas
- `source` alinhado ao contrato §2.1: `seed | athena | import_csv | markdown_upload`.
  Backfill dos dados reais: `internal → seed`, `skillforge → import_csv` (reescreve ~10 linhas sf-*).
- Catálogo continua global; tenant ativa via `agent_specialty_configs` (já per-company).
- `operation_types` vivem em `config_schema.operation_types[]` (não é campo separado do form);
  na promoção, garantir que cada op_type exista em `operation_types_catalog` (senão daemon não despacha).
- Domínio valida contra `agent_domains` (FK) — domínio novo cria global com curadoria.

### Migration 1 — alinhar `source` (escopo único, P5)
`supabase/migrations/20260521000000_align_specialty_source_to_contract.sql`
```sql
-- ESPELHEI ANTES: SELECT source, count(*) FROM vectraclip.agent_specialties GROUP BY 1;
-- Contrato §2.1: source ∈ seed|athena|import_csv|markdown_upload. Ordem: backfill ANTES do CHECK.
UPDATE vectraclip.agent_specialties SET source='seed'       WHERE source IN ('internal','seed');
UPDATE vectraclip.agent_specialties SET source='import_csv' WHERE source='skillforge';
ALTER TABLE vectraclip.agent_specialties DROP CONSTRAINT IF EXISTS agent_specialties_source_check;
ALTER TABLE vectraclip.agent_specialties
  ADD CONSTRAINT agent_specialties_source_check
  CHECK (source IN ('seed','athena','import_csv','markdown_upload'));
ALTER TABLE vectraclip.agent_specialties ALTER COLUMN source SET DEFAULT 'seed';
DO $$ BEGIN RAISE NOTICE 'source alinhado ao contrato'; END $$;
```
> ⚠️ Confirmar: alguma migration anterior já cria CHECK em `source`? `DROP ... IF EXISTS` cobre, mas auditar.

### Migration 2 — staging `skill_import_proposals` (aditiva, colateral zero)
`supabase/migrations/20260521000100_skill_import_proposals.sql`
```sql
-- ESPELHEI ANTES: gymsite_seed.sql (idempotencia/vectraclip.), pr1a (RLS global USING(true)),
--   contrato §3.2 (PMO -> agent_specialties draft). Catalogo continua GLOBAL SSOT.
CREATE TABLE IF NOT EXISTS vectraclip.skill_import_proposals (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      uuid NOT NULL,                 -- proponente (audit)
    source          text NOT NULL CHECK (source IN ('import_csv','markdown_upload')),
    status          text NOT NULL DEFAULT 'queued'
                      CHECK (status IN ('queued','curating','promoted','dismissed')),
    raw_input       text,
    name            text,
    slug            text,
    domain          text,
    description     text,
    compatible_roles text[] NOT NULL DEFAULT '{}',
    system_prompt_template text,
    config_schema   jsonb,                          -- inclui operation_types[]
    promoted_specialty_id text REFERENCES vectraclip.agent_specialties(id),
    dismissed_reason text,
    created_by      uuid,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_skill_import_proposals_company ON vectraclip.skill_import_proposals(company_id);
CREATE INDEX IF NOT EXISTS idx_skill_import_proposals_status  ON vectraclip.skill_import_proposals(status);
ALTER TABLE vectraclip.skill_import_proposals ENABLE ROW LEVEL SECURITY;
-- RLS: codebase isola company NA API (validate_jwt_company_id + service_role), nao via claim em RLS.
-- pr1a usa USING(true) p/ tabelas catalogo. ESPELHAR essa escolha:
CREATE POLICY "skill_import_proposals_select_authenticated" ON vectraclip.skill_import_proposals
  FOR SELECT TO authenticated USING (true);
GRANT SELECT ON vectraclip.skill_import_proposals TO authenticated;
GRANT ALL ON vectraclip.skill_import_proposals TO service_role;
DO $$ BEGIN RAISE NOTICE 'skill_import_proposals criada'; END $$;
```
> ⚠️ DECISÃO RLS: confirmar se isolamento por company é só na API (service_role + `validate_jwt_company_id`,
> como `create_task`) ou se há tabela company-scoped com RLS por claim a espelhar. pr1a só tem global `USING(true)`.

### API (vectraclaw-backend, runtime — NÃO migration)
1. `AgentSpecialtyInput` (api.py:9245) + `create_agent_specialty` (9255): passar a aceitar e gravar
   `source` e `status` (colunas já existem; hoje o handler ignora → cai no default). `company_id` do JWT só p/ audit, NÃO no catálogo.
2. `POST /api/skill-import-proposals` — bulk (array CSV-row / markdown) → insere em staging `status=queued`.
3. `POST /api/skill-import-proposals/{id}/promote` — proposal → `agent_specialties status=draft, source=import_csv|markdown_upload`;
   garantir `operation_types[]` do `config_schema` existam em `operation_types_catalog` (upsert);
   validar/`criar` `domain` em `agent_domains`.
4. `categories.yaml` é vocabulário de import, NÃO substitui `agent_domains` (contrato §3.2).

### Front (vectraclip-frontend — fora deste handoff, mas dependente)
- `CreateAgentSpecialtyDialog.tsx`: domínio `<Input>` → combobox lendo `/api/agent-domains` (mata FK 500); select de `source`.
- Tela de import/curadoria consumindo `skill_import_proposals`.

---

## Bloco B — Workflow contact-enrichment (academias) — backend

### Contexto
Enriquecer email/telefone de clientes academia (CNAE 9313100, 298/310 sem email). Lógica vive em
`workflow_definitions` + `workflow_steps` (BPMN), Daedalus orquestra, GymSite executa. Plano completo:
`~/.claude/plans/quero-montar-um-agente-delightful-giraffe.md`. Frente B (migration public.clients
`contact_enrichment_at`+`enrichment_sources`) JÁ FEITA em cargo-flow-navigator (branch
`feat/contact-enrichment-fields`, commit 0a9a12a).

### Backend pendente (tudo via migration de seed + service, regra #6)
1. **Seed migration** (`vectraclaw-backend/supabase/migrations/`, espelhar `gymsite_seed.sql` + P7 header):
   - `operation_types_catalog`: op_types dos steps (ex.: `gymsite-enrich-contact`).
   - `agent_domains`: garantir `prospeccao` (já existe).
   - `agent_specialties`: `prospeccao-gymsite` (domain `prospeccao`, compatible_roles inclui `executor`,
     config_schema SÓ negócio — SEM `model_id`; modelo vem do adapter do agente via `agent_llm`).
   - `workflow_definitions` `gymsite-contact-enrichment` (is_scheduled, cron) + `workflow_steps`
     S1 select → S2 Hunter domain-search → S3 finder → S4 verifier → S5 revisão (requires_approval) → S6 persist.
   - `agent_specialty_configs`: ligar specialty ao GymSite (id 917e51b3-9413-4000-8000-000000000006).
2. **Hunter como SERVICE** (NÃO adapter — é chamada HTTP do op_type): `src/services/hunter.py`
   (domain-search/email-finder/email-verifier), `base_url` em config, **api_key no vault**
   (`vectraclip.company_secrets` + RPC `get_vault_secret`, espelhar `notification-hub`/W5.1).
3. **Persistência** em `public.clients` via **dual client** (`docs/SUPABASE_DUAL_CLIENT.md`), client public.
   Regra de ouro: email/phone FILL-ONLY; email só grava `email_status=deliverable`; nunca `name`; idempotente via `contact_enrichment_at`.
4. **Bloqueante**: `routine_runner.py` é STUB (loop autônomo é TODO). Decidir: terminar runner OU rodar
   via caminho `gymsite-enrich-lead` existente.
5. Fonte primária de email = padrão de grupo (cnpj_root): UTF CACHAMORRA `IVAN.BLOCH@ULTRAACADEMIA.COM.BR`
   → `{PRIMEIRO}.{ULTIMO}@dominio`. Apollo descartado (free plan bloqueia people/match).

---

## Checklist regras de ouro (antes do PR)
- [ ] #1 P7 header "ESPELHEI ANTES" em cada migration nova
- [ ] #2 nada hardcoded em Python — valores em catálogo/seed (source via CHECK alinhado contrato; op_type catalog-driven)
- [ ] #6 DDL/seed só em `supabase/migrations/` + `db push` — NUNCA MCP/SQL Editor/API
- [ ] #5 scripts one-off em Docker ephemeral
- [ ] #3 pós-merge: `docker cp` + restart antes do smoke
- [ ] #4 rodar `hardcode-auditor` antes de melhorar código existente

## Verificação
- Migration 1: `SELECT source, count(*) FROM vectraclip.agent_specialties GROUP BY 1;` → só os 4 valores do contrato.
- Migration 2: insert de proposta dummy → promote → aparece em `agent_specialties status=draft`.
- Bloco B: smoke grupo UTF (derivação + Hunter verifier deliverable) → cobertura email antes/depois em public.clients academias.

## Decisões abertas (precisam de dono backend)
1. RLS de `skill_import_proposals`: API-layer (service_role + validate_jwt_company_id) vs RLS por claim?
2. Mapeamento `skillforge → import_csv` confirmado? (reescreve ~10 sf-*)
3. routine_runner stub: terminar vs reusar enrich-lead?
4. Onde a promoção upserta `operation_types_catalog` (qual handler).
