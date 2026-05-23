# Handoff — RLS SIPOC, CORS, WebSocket, Intelligence 404

**Data:** 2026-05-22  
**Ambiente:** `api-vectraclip.vectracargo.com.br` + `app.vectraclip.vectracargo.com.br`

## Resumo executivo

| Problema | Causa raiz | Correção |
|----------|------------|----------|
| `42501` em `sipoc_sectors` | `company_id` NULL ou divergente do JWT; cliente podia enviar tenant errado | Trigger `enforce_sipoc_tenant_company_id` + API força `company_id` do `request.state` |
| CORS bloqueado | Allowlist sem origem prod quando `CORS_ALLOW_ORIGINS` substituía defaults; erros 401 sem CORS válido | `cors_policy.py` com core fixo + headers em `HTTPException` |
| WebSocket `530` | Tunnel/proxy sem timeouts adequados ao upgrade | `cloudflared/config.yml` — `keepAlive`, `http2Origin`, `connectTimeout` |
| `404` `/api/intelligence/dashboard` | Router `intelligence.py` nunca registrado em `api.py` | `app.include_router(_intelligence_routes.router)` |

## Arquivos entregues

- `supabase/migrations/20260522120000_sipoc_sectors_tenant_trigger.sql`
- `tests/sql/test_sipoc_sectors_rls.sql`
- `src/middleware/cors_policy.py`
- `src/middleware/http_observability.py`
- `src/api.py` (CORS, intelligence, SIPOC tenant, métricas)
- `cloudflared/config.yml`
- `tests/test_cors_and_intelligence_routes.py`
- `tests/test_sipoc_sector_tenant_api.py`

## Deploy

```powershell
cd C:\Users\marce\VectraClaw
supabase db push
docker compose up -d --build backend cloudflared
```

## Smoke manual

```powershell
# Preflight CORS
curl -i -X OPTIONS "https://api-vectraclip.vectracargo.com.br/api/health" `
  -H "Origin: https://app.vectraclip.vectracargo.com.br" `
  -H "Access-Control-Request-Method: GET"

# Intelligence (com token)
curl -i "https://api-vectraclip.vectracargo.com.br/api/intelligence/dashboard" `
  -H "Authorization: Bearer <token>" `
  -H "Origin: https://app.vectraclip.vectracargo.com.br"

# WebSocket (local)
python tests/test_vec183_ws_smoke.py
```

## Plano de rollback

1. **Banco:** `supabase migration repair --status reverted 20260522120000` + redeploy migration anterior (drop triggers).
2. **API:** revert commit + `docker compose up -d --build backend`.
3. **Tunnel:** restaurar `cloudflared/config.yml` anterior + `docker compose restart cloudflared`.
4. **Feature flag:** `VECTRACLAW_AUTH_DISABLED` não usar em prod; para emergência CORS, setar `CORS_ALLOW_ORIGINS` temporário.

## Segurança multi-tenant

- **Nunca** confiar em `company_id` do frontend — trigger sobrescreve no INSERT.
- **RLS** permanece: `WITH CHECK (company_id = sipoc_company_id())`.
- **JWT** obrigatório: `app_metadata.vectraclip.company_id`.
- **CORS** allowlist explícita; sem `*` com credenciais.
- **WS** auth via `?token=`; mismatch de `company_id` fecha com `4001`.

## Observabilidade

- `GET /api/health/metrics` — contadores `http_4xx`, `http_5xx`, `cors_preflight`, `ws_upgrade_attempt`.
- Logs: `correlation_id=%s method=%s path=%s status=%s` em `api.observability`.

## Guard rails (CI recomendado)

- Rodar `pytest tests/test_cors_and_intelligence_routes.py tests/test_sipoc_sector_tenant_api.py`
- Bloquear merge se tabela `vectraclip.*` com `company_id` sem RLS + trigger tenant
- Smoke pós-release: preflight OK, WS OK, insert SIPOC OK
