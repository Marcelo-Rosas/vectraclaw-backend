# `src/api_routes/` — Roteadores FastAPI por feature

Submodules que extraem endpoints do monolito `src/api.py`. Cada arquivo é uma "feature área" com seu próprio `APIRouter`.

---

## Padrão obrigatório por submodule

```python
# src/api_routes/<feature>.py
from fastapi import APIRouter, Request, HTTPException
from typing import Any, Dict

router = APIRouter(tags=["<feature>"])


@router.get("/api/<feature>")
async def list_X(request: Request) -> list:
    """Doc curta do endpoint."""
    ...
```

E registro em `src/api.py`:
```python
from src.api_routes import <feature>
app.include_router(<feature>.router)
```

---

## O que vai em submodule, o que fica em `api.py`

| Tipo | Local |
|---|---|
| Endpoints que pertencem a 1 feature área (Prospects, Workflows, Kronos rules, etc.) | submodule |
| Helper usado por múltiplos submodules (`_emit_heartbeat_internal`, `_resolve_company_id`, `validate_jwt`) | `api.py` (re-exportado se preciso) |
| Background tasks (`hermes_scheduler`, `_oracle_session_gc_loop`) | `api.py` (lifespan-bound) |
| Middleware (`auth_middleware`, CORS) | `api.py` |
| App instance + lifespan + dependências globais | `api.py` |

---

## Regras de import

- **Submodule pode importar de `src.api`** para helpers globais — apesar do nome parecer circular, FastAPI resolve OK porque os imports são top-level e os routers são incluídos *após* api.py terminar de carregar.
- **`src.api` importa submodules no fim do arquivo** (após definir helpers globais), antes do `app.include_router(...)`.
- **Não criar imports cruzados entre submodules.** Se `prospects.py` precisa de algo de `workflows.py`, esse "algo" provavelmente deveria estar num service em `src/services/` ou ser helper global em `api.py`.

---

## Convenção de URL

- Sempre **`/api/<resource>`** como path principal.
- Manter alias **`/<resource>`** (sem `/api`) quando já existir no main para retrocompat — adicionar via **dois decoradores**:
  ```python
  @router.get("/api/companies/{id}/prospects")
  @router.get("/companies/{id}/prospects")
  async def list_prospects(...):
      ...
  ```

---

## Testes

- Cada submodule de feature pode ter seu próprio `tests/test_<feature>_routes.py`.
- Testar via `from fastapi.testclient import TestClient` + `from src.api import app`.
- Mockar Supabase no nível do test (não dentro do submodule).

---

## Migração progressiva (Step 8.x)

A transição de monolito para submodules é feita em PRs sucessivas:

| PR | Feature | Submodule |
|---|---|---|
| 8.1 | Foundations (heartbeat helper extraído) | (sem submodule, só scaffold) |
| 8.2 | Prospects + Research templates | `prospects.py`, `research_templates.py` |
| 8.3 | Workflows | `workflows.py` |
| 8.4 | System control | `system.py` |
| 8.5 | Kronos rules | `kronos_rules.py` |
| 8.6 | Tasks workflow + Specialties | `tasks_workflow.py`, `specialties.py` |
| 8.7 | Incidents + Companies extras | `incidents.py`, `companies_extras.py` |
| 8.8 | Oracle chat + cleanup | `oracle_chat.py` + edits em `api.py` |

Cada PR shippa apenas seu submodule + a linha `app.include_router(...)` correspondente em `api.py`.
