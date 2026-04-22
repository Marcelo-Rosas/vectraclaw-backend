# VEC-194 — VectraClaw Prompt V6.1 (Patch cirúrgico pós-auditoria)

**Issue Linear:** [VEC-194 — Auth Real (Supabase) + visualização da sessão](https://linear.app/vectra-cargo/issue/VEC-194/vec-194-auth-real-supabase-visualizacao-da-sessao)
**Documento anterior:** [`docs/VEC-194-VectraClaw-Prompt-V6.md`](./VEC-194-VectraClaw-Prompt-V6.md)
**Repositório alvo:** `VectraClaw` — arquivo `src/api.py`

---

## Contexto

Auditoria do V6 (20/Abr/2026) detectou que o **core de auth real está 100% entregue** (JWKS, `validate_supabase_jwt`, `get_authenticated_client`, middleware, login/refresh/me/logout, agents/heartbeats/approvals/audit com JWT). Este documento lista **apenas os gaps residuais** que faltam para fechar o aceite V6.

---

## Fix 1 — 🔴 `GET /tasks` precisa usar JWT do usuário (RLS ativa)

### Diagnóstico

Em `src/api.py` linhas 569-578, diferente de `get_agents`/`get_heartbeats`, o endpoint de tasks:

- **Não recebe** `request: Request` na assinatura.
- Usa `supabase.schema(SCHEMA).table(...)` (cliente **service_role**) em vez de `get_authenticated_client(request.state.token)`.
- Com isso, o caminho feliz do dashboard bypassa RLS → viola V6 §4.

### Patch

Substituir **apenas** a função `get_tasks` (manter os 3 decoradores):

```python
@app.get("/api/companies/{company_id}/tasks")
@app.get("/companies/{company_id}/tasks")
@app.get("/api/tasks")
async def get_tasks(request: Request, company_id: str = None):
    if not supabase:
        return MOCK_TASKS

    try:
        client = get_authenticated_client(request.state.token)
        query = client.table("tasks").select("*")
        if company_id:
            query = query.eq("company_id", company_id)
        res = query.execute()
        return [Task(**row).to_zod_dict() for row in res.data]
    except Exception as e:
        logger.error(f"get_tasks failed: {e}")
        return MOCK_TASKS
```

### Aceite

- `GET /api/companies/<id>/tasks` com `Authorization: Bearer <jwt>` retorna **apenas tasks da company do JWT** (RLS ativa), paridade com `agents`.
- Requisição sem Bearer cai no `auth_middleware` → 401 com headers CORS (sem bypass).

---

## Fix 2 — 🟡 `get_heartbeats` crasha se `company_id` for `None`

### Diagnóstico

Em `src/api.py` linhas 607-625, a query aplica `.eq("company_id", company_id)` **sem guard**. Quando o endpoint é chamado via rota fallback `@app.get("/api/heartbeats")` sem path param, `company_id=None` vai parar no PostgREST e quebra a query.

### Patch

```python
@app.get("/api/companies/{company_id}/heartbeats")
@app.get("/companies/{company_id}/heartbeats")
@app.get("/api/heartbeats")
async def get_heartbeats(request: Request, company_id: str = None, since: Optional[str] = None):
    if not supabase:
        return MOCK_HEARTBEATS

    try:
        client = get_authenticated_client(request.state.token)
        query = (
            client.table("heartbeats")
            .select("*")
            .order("created_at", desc=True)
            .limit(200)
        )
        if company_id:
            query = query.eq("company_id", company_id)
        if since:
            query = query.gt("created_at", since)

        res = query.execute()
        return [Heartbeat(**row).to_zod_dict() for row in res.data]
    except Exception as e:
        logger.error(f"get_heartbeats failed: {e}")
        return MOCK_HEARTBEATS
```

### Aceite

- `GET /api/companies/<id>/heartbeats` → filtrado por company, RLS ativa.
- `GET /api/heartbeats` (rota fallback) → devolve resultado amplo mas **RLS do JWT já restringe ao tenant** do usuário (sem crash).

---

## Fix 3 — 🟡 CORS: ordem dos middlewares

### Diagnóstico

Starlette executa `user_middleware.insert(0, ...)` → **último registrado = mais externo**. O `@app.middleware("http") auth_middleware` estava sendo registrado depois do `app.add_middleware(CORSMiddleware, ...)`, então **auth ficava externo** e qualquer resposta 401/500 do auth ou dos endpoints saía sem `Access-Control-Allow-Origin` → browser bloqueava com "Missing Header".

### Patch (já aplicado no repositório VectraClaw via VectraClip; confirmar)

O bloco `app.add_middleware(CORSMiddleware, ...)` deve estar **depois** da definição de `@app.middleware("http") auth_middleware` (perto do fim do arquivo, antes dos mocks). Isso garante que CORS seja o mais externo da pilha e adicione headers em **qualquer** resposta.

### Aceite

- Preflight `OPTIONS /api/companies/.../tasks` com `Origin: http://localhost:3000` → **200** com `Access-Control-Allow-Origin` no response.
- 401 em rota protegida sem Bearer → devolve JSON com headers CORS (front mostra erro de auth, não "blocked by CORS").

---

## Itens fora de escopo VEC-194 (documentar, não implementar agora)

Listar em backlog / nova issue:

- `create_agent` (561-566) e `create_task` (585-591) são stubs que não gravam no Postgres.
- `get_goals` (594-596) e `get_companies` (599-601) retornam mock puro.
- `approve_approval` (759-762) e `reject_approval` (768-771) são stubs.
- `POST /api/auth/logout` usa `supabase.auth.sign_out()` no client global (service_role) em vez de revogar o refresh_token do usuário via admin API.

Esses entram em VEC-195+ (migrar mocks restantes + goals/companies/approvals reais).

---

## Smoke test manual (depois de aplicar os 2 fixes de código)

```bash
# 1) Derrubar e resubir o Claw
# (Git Bash / PowerShell no diretório VectraClaw)
python -m src.main serve --port 3100

# 2) Login
curl -s -X POST http://localhost:3100/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"marcelo.rosas@vectracargo.com.br","password":"vectra123"}' | jq

# Copiar o accessToken da resposta → $TOK

# 3) Tasks com JWT (deve retornar apenas da company do usuário)
curl -s http://localhost:3100/api/companies/c0000000-0000-4000-8000-000000000001/tasks \
  -H "Authorization: Bearer $TOK" | jq length

# 4) Preflight CORS
curl -v -X OPTIONS http://localhost:3100/api/companies/c0000000-0000-4000-8000-000000000001/tasks \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: authorization" 2>&1 | grep -i 'access-control'
```

Resposta esperada do preflight:

```
< access-control-allow-origin: http://localhost:3000
< access-control-allow-credentials: true
< access-control-allow-methods: GET
< access-control-allow-headers: authorization
```

---

*Última atualização: 20/Abr/2026 — patch pós-auditoria V6.*
