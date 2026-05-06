"""
src.api_routes — pacote de roteadores FastAPI por feature.

Cada submodule define um `router: APIRouter` que é registrado em `src.api`
via `app.include_router(<feature>.router)`. O `api.py` mantém:

- `app` (FastAPI instance), middleware, lifespan, deps globais
- Helpers compartilhados que cruzam features (`_emit_heartbeat_internal`,
  `_resolve_company_id`, `validate_jwt`, etc.)
- Endpoints legados/agregados que ainda não foram extraídos

Padrão de submodule:
    from fastapi import APIRouter, Request
    router = APIRouter(prefix="", tags=["<feature>"])

    @router.get("/api/<feature>/...")
    async def list_X(request: Request, ...):
        ...

E em `api.py`:
    from src.api_routes import <feature>
    app.include_router(<feature>.router)

Ver `CLAUDE.md` neste diretório para regras detalhadas.
"""
