# ADR — RBAC catalog table (G1.5)

> **Status:** parqueado — atacar quando operação crescer
> **Owner:** plataforma + segurança
> **Origem:** gap 🟠 BAIXA da Camada 1 em `docs/AUDIT-HANDLERS-2026-05-16.md`
> **Data:** 2026-05-16

## Contexto

Roles do sistema (`admin, platform_admin, consultant, company_admin,
sector_responsible, viewer, member`) são **hardcoded** em vários lugares:

- `src/api.py` — `_SIPOC_DELETE_BLOCKED_ROLES`, `_SIPOC_EDIT_BLOCKED_ROLES`, `_RACI_ADMIN_BLOCKED_ROLES`, `_RISK_WRITE_BLOCKED_ROLES`, `_BPMN_WRITE_BLOCKED_ROLES`, `_VALID_ROLES`
- `src/api_routes/admin.py` — `_ADMIN_BLOCKED_ROLES`, `_VALID_ROLES`
- `models.py` — `User.role: Literal[admin, member]` (subset desatualizado)
- Migrations (RLS policies) — arrays inline `ARRAY['admin','platform_admin','consultant','company_admin']`

**Resultado:** adicionar role novo = code change em 8+ lugares + migration pra atualizar todas RLS policies. Não tem CRUD pra criar role via UI.

## Por que NÃO atacar agora

1. **Roles são vocabulário curado.** Diferente de `agent_specialties` ou `adapter_catalog`, roles definem **estrutura de poder organizacional** — adicionar role novo via UI sem alinhar com produto = risco de gov (sombra de permissões).

2. **Mudança é rara.** Roles do projeto não mudaram desde PR #135 (`sector_responsible` adicionado, ~2 semanas). Catalog dinâmico tem ROI baixo quando mudança é trimestral.

3. **Refactor é caro.** Estimativa: 4h migration + 2h refactor `_VALID_ROLES` em ~8 lugares + 1h refactor `Literal[admin,member]` em models + 1h refactor RLS policies pra fazer JOIN com `roles_catalog` em vez de array inline + 2h smoke tenant-aware. **Total: ~10h** pra benefício marginal hoje.

4. **Workaround atual (code change) é o pattern certo** enquanto não há demanda real. Tenant não cria roles — quem cria é a plataforma.

## Quando reverter (condição de saída)

Quando AO MENOS UMA destas condições:

- **Multi-tenant com modelos de permissão diferentes** (tenant A quer role `auditor_interno` que tenant B não quer)
- **Plataforma vira marketplace** (consultorias adicionam roles próprias)
- **Compliance SOC2/ISO** pede separação de duties customizável por tenant
- **Adicionar role exige >3 PRs em uma sprint** (sinal de friction real)

## Implementação esperada (quando vier)

### 1. Migration `vectraclip.roles_catalog`

```sql
CREATE TABLE vectraclip.roles_catalog (
  id TEXT PRIMARY KEY,  -- 'admin', 'platform_admin', etc.
  name TEXT NOT NULL,   -- "Administrador"
  description TEXT,
  scope TEXT NOT NULL CHECK (scope IN ('platform', 'tenant', 'sector')),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  display_order INTEGER NOT NULL DEFAULT 100,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO vectraclip.roles_catalog (id, name, scope, display_order) VALUES
  ('platform_admin', 'Admin Plataforma', 'platform', 10),
  ('admin', 'Admin', 'tenant', 20),
  ('consultant', 'Consultor', 'tenant', 30),
  ('company_admin', 'Admin Empresa', 'tenant', 40),
  ('sector_responsible', 'Responsável Setor', 'sector', 50),
  ('viewer', 'Leitor', 'tenant', 60),
  ('member', 'Membro', 'tenant', 70);
```

### 2. Helper Python

```python
# src/services/rbac.py
_ROLES_CACHE = {"ids": None, "fetched_at": 0.0}

def load_valid_roles() -> set:
    """Cacheado 60s. Substitui _VALID_ROLES hardcoded."""
    ...

def roles_with_write_access(action_scope: str) -> set:
    """Substitui _SIPOC_EDIT_BLOCKED_ROLES etc.
    Retorna roles que NÃO estão na blocklist desse action_scope."""
    ...
```

### 3. Refactor RLS policies

Trocar `role = ANY(ARRAY['admin','platform_admin','consultant','company_admin'])`
por uma function `vectraclip.has_role_access(action_scope text)` que consulta o catalog.

Esforço: ~10h (estimado). Smoke tenant-aware é o passo mais caro.

## Decisão

Parquear até condição de saída acima. Quando vier, este ADR vira PRD/issue concreto.

## Risco de NÃO fazer

- Sessão futura adiciona role novo e esquece 1 dos 8 lugares hardcoded → RBAC inconsistente entre endpoints (gap real de segurança)
- **Mitigação:** quando adicionar role, grep obrigatório `grep -nE "_VALID_ROLES\|BLOCKED_ROLES\|_VALID|sector_responsible" src/` antes de commit
- Adicionar regra em `docs/CODE-PATTERNS.md` próximo PR: "ao adicionar role novo, atualizar TODAS as 8 entries (lista abaixo)"
