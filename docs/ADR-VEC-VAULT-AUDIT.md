# ADR — Auditoria do Vault de Secrets (G2.5)

> **Status:** rascunho — aguarda auditoria efetiva
> **Owner:** plataforma (decisão produto)
> **Origem:** gap 🟠 P2 da Camada 2 em `docs/AUDIT-HANDLERS-2026-05-16.md`
> **Data:** 2026-05-16

---

## Contexto

VectraClaw armazena secrets de tenant (credenciais SMTP, API keys, tokens
externos) usando RPC `upsert_company_secret` abstraindo Vault. O endpoint
expõe metadata (`id, name, description, created_at`) e nunca retorna `value`.

**O que NÃO está auditado:**
- Qual extension/feature Supabase é usada embaixo (pgsodium? pgcrypto?
  Supabase Vault built-in com KMS gerenciado?)
- Política de rotation (manual? automatizada? schedule?)
- Acesso aos secrets (quem acessou o quê quando — fica log em algum lugar?)
- Recovery (secret apagado consegue ser restaurado?)
- Encryption at rest (chave de criptografia onde está? rotacionada?)

## Decisão (pendente)

Antes de implementar qualquer mudança, **executar auditoria estruturada**
respondendo o checklist abaixo. Resultado vira ADR concreto (substitui
este rascunho).

## Checklist de auditoria

### 1. Implementação Vault

- [ ] Qual a definição da RPC `vectraclip.upsert_company_secret`?
  `SELECT pg_get_functiondef('vectraclip.upsert_company_secret'::regproc);`
- [ ] Usa `vault.secrets` (Supabase Vault gerenciado)? Ou tabela custom?
- [ ] Se custom: que algoritmo de encryption? Que extension (pgsodium/pgcrypto)?
- [ ] Onde fica a chave de criptografia? KMS? variável de ambiente? hardcoded?
- [ ] Backup encryption keys: existe? Como?

### 2. RBAC + acesso

- [ ] Quem pode ler secret value (não só metadata)? Só backend? CMA/managed_agents?
- [ ] RLS na tabela vault está habilitada?
- [ ] Há log de acesso (quem chamou `decrypt`, quando, qual secret)?
- [ ] Tenant isolation: secret de tenant A acessível por tenant B? (testar)

### 3. Rotation

- [ ] Política definida (90 dias? 180? on-demand?)
- [ ] Notificação pra rotation pendente?
- [ ] Quem rota: humano? cron? agente?
- [ ] Rotation invalida sessões/tasks em curso que usam o secret antigo?

### 4. Recovery

- [ ] Secret apagado por engano: tem backup? por quanto tempo?
- [ ] Soft-delete vs hard-delete: qual é o default?
- [ ] Restore process documentado?

### 5. Compliance

- [ ] LGPD: secret é "dado pessoal"? (depende do conteúdo — credenciais email do user sim)
- [ ] SOC2: log de acesso + rotation = controles SOC2 CC6.1, CC6.6, CC6.8
- [ ] Penetration test: já foi feito? Quando?

### 6. Documentação

- [ ] Onde está documentado pra ops como adicionar/rotacionar secret?
- [ ] Runbook de incidente (secret vazado): existe?

## Próximo passo

Quando decidir auditar, este doc vira issue/PR concreto com cada checkbox
resolvido. Estimativa: ~4-6h pra completar checklist + ~8-12h pra implementar
gaps encontrados (depende de severidade).

## Por que NÃO atacar agora

- Bloqueador hoje? Não (secrets funcionam, valores nunca expostos via API)
- ROI imediato? Baixo (compliance futuro, não bloqueia feature)
- Risco de ataque elevado? Médio — depende de threat model

**Decisão:** parquear até decisão de produto sobre roadmap compliance (SOC2/LGPD).
Quando vier, abrir issue linkando este ADR.

## Referências

- [Supabase Vault docs](https://supabase.com/docs/guides/database/vault)
- [pgsodium](https://github.com/michelp/pgsodium)
- SOC2 controls CC6.x — Security
- LGPD Art. 46-49 — segurança técnica de dados pessoais
