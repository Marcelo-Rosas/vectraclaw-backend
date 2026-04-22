# Dois clients Supabase no VectraClaw (VEC-199b)

Espelho operacional do **Fix 0** da spec canônica no repositório **VectraClip**:
`docs/VEC-199b-VectraClaw-Prompt-V1.1.md` (seção *Fix 0*).

Implementação de referência: `src/api.py` (globais `supabase` e `supabase_auth`).

---

## Sintoma

Após `POST /api/auth/login`, mutações do Heartbeat Doctor ou inserts em `vectraclip.incidents` falham com `permission denied for table incidents`.

Isso **não** indica RLS ou grants errados no Postgres se o Doctor usa `service_role` — costuma ser **contaminação do client** no `supabase-py` (ex.: 2.0.x): listeners de auth (`SIGNED_IN`, etc.) recriam o PostgREST interno com o JWT do **usuário**. Se login e Doctor usam o **mesmo** `create_client` inicializado com **service_role key**, o client “vira” `authenticated` e perde os grants de escrita do service role.

---

## Regra

| Variável / client   | Env                         | Uso |
|---------------------|-----------------------------|-----|
| `supabase`          | `SUPABASE_SERVICE_ROLE_KEY` | Doctor, `store.py`, endpoints server-side. **Nunca** chamar `.auth.*` neste client. |
| `supabase_auth`     | `SUPABASE_ANON_KEY`         | Só `sign_in`, `refresh_session`, `sign_out`. O listener pode alterar este client à vontade. |

Em ambos, no servidor: `ClientOptions(schema=..., persist_session=False)` (ver `src/api.py`).

Se `SUPABASE_ANON_KEY` estiver ausente, o código pode fazer fallback perigoso (auth no mesmo client de service role) — veja warning no log.

---

## Exemplo (alinhado ao repo)

```python
from supabase import create_client
from supabase.lib.client_options import ClientOptions

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,  # os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    options=ClientOptions(schema=SCHEMA, persist_session=False),
)

supabase_auth = create_client(
    SUPABASE_URL,
    SUPABASE_ANON_KEY,
    options=ClientOptions(schema=SCHEMA, persist_session=False),
)
```

---

## Critério de aceite

Com JWT real após login: operações do Doctor e tabelas de incidents/audit sem `permission denied` inesperado; apenas respostas HTTP esperadas (`2xx` / `4xx` de negócio).

---

## Subir a API e porta no Windows

- Entrypoint canônico: `python -m src.main serve --port 3100` (usa o mesmo `FastAPI` com middlewares definidos no projeto). Evite atalhos ad hoc com `uvicorn ...` se contornarem o bootstrap previsto.

- Se o restart falhar com porta em uso (`EADDRINUSE`):

```powershell
netstat -ano | findstr :3100
taskkill /PID <pid> /F
```

---

*Última revisão: alinhado a VEC-199b / Fix 0.*
