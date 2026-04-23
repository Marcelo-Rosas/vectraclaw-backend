import os
from uuid import UUID
import asyncio
import logging
import fnmatch
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Literal, Union
from urllib.parse import urlparse
from dotenv import load_dotenv
import requests
from jose import jwt
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, validator

# supabase import
try:
    from supabase import create_client, Client
except ImportError:
    pass

from postgrest.exceptions import APIError as PostgrestAPIError

from src.models import (
    Agent, Task, Goal, Heartbeat, AuditLogEntry, CouncilApproval, User, AuthSession,
    Incident, IncidentAudit, AdapterCatalogItem, AdapterFieldDefinition, AgentAdapterConfig,
    AgentExecutionConfig, LlmModel, AgentSpecialty, Routine,
    SipocCompany, SipocSector, SipocPosition, SipocProcess, SipocComponent,
)
from src.services.heartbeat_doctor.loop import doctor_tick
from src.services.heartbeat_doctor import audit as incident_audit
from src.services.heartbeat_doctor import store as incident_store
from src.ws_manager import manager as ws_manager
from src.agents.sipoc_researcher import research_sector

logger = logging.getLogger("VectraClawAPI")
app = FastAPI(title="Vectra Claw Backend API", version="0.1.0")

# OpenAPI: o JWT é validado no middleware (não via `Security()` por rota), então o schema
# padrão não mostra o cadeado. Declaramos HTTP Bearer aqui para o Swagger UI exibir
# **Authorize** e enviar `Authorization: Bearer <token>` nos "Try it out".
_OPENAPI_PUBLIC_PATHS = frozenset(
    {
        "/",
        "/api/auth/login",
        "/api/auth/refresh",
        "/api/health",
        "/auth/login",
        "/auth/refresh",
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/favicon.ico",
        "/sw.js",
        "/mockServiceWorker.js",
        "/login",
    }
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    # Sem `servers`, algumas versões do Swagger UI montam URL inválida → "Failed to fetch"
    # / esquema inválido. "/" = mesmo host/porta de onde o /openapi.json foi carregado.
    if not openapi_schema.get("servers"):
        openapi_schema["servers"] = [
            {"url": "/", "description": "Mesmo host (ex.: http://localhost:3100)"}
        ]
    openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})[
        "HTTPBearer"
    ] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Access token Supabase (campo accessToken de POST /api/auth/login).",
    }
    # Padrão global: a maioria das rotas exige Bearer (alinhado ao auth_middleware).
    # Rotas públicas sobrescrevem com security: [] (sem auth no Swagger).
    openapi_schema["security"] = [{"HTTPBearer": []}]
    for _path, path_item in openapi_schema.get("paths", {}).items():
        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            if _path in _OPENAPI_PUBLIC_PATHS:
                op["security"] = []
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    logger.error(f"Global exception: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"detail": "internal_server_error"},
    )


LLM_PRICE_CACHE_TTL = timedelta(hours=24)
_llm_price_cache: Dict[str, Dict[str, float]] = {}
_llm_price_cache_loaded_at: Optional[datetime] = None


class AgentStatus:
    IDLE = "idle"
    WORKING = "working"
    PAUSED = "paused"
    OFFLINE = "offline"


class AgentPatch(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    token_budget: Optional[int] = Field(default=None, alias="tokenBudget")
    reports_to_id: Optional[str] = Field(default=None, alias="reportsToId")

    class Config:
        allow_population_by_field_name = True
        extra = "ignore"


def _session_expires_to_utc(expires_at: Union[None, int, float, str, datetime]) -> datetime:
    """
    GoTrue / supabase-py pode devolver `expires_at` como:
    - int/float (epoch segundos)
    - str numérica ("1776663893")
    - str ISO-8601
    - datetime

    `datetime.fromtimestamp(str)` quebra com: 'str' object cannot be interpreted as an integer.
    """
    if expires_at is None:
        raise ValueError("session missing expires_at")
    if isinstance(expires_at, datetime):
        dt = expires_at
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if isinstance(expires_at, (int, float)):
        return datetime.fromtimestamp(float(expires_at), tz=timezone.utc)
    if isinstance(expires_at, str):
        s = expires_at.strip()
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return datetime.fromtimestamp(float(s), tz=timezone.utc)
    raise TypeError(f"unexpected expires_at type: {type(expires_at)}")


def _user_created_at_to_utc(created_at: Union[None, str, datetime]) -> datetime:
    if created_at is None:
        return datetime.now(timezone.utc)
    if isinstance(created_at, datetime):
        dt = created_at
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if isinstance(created_at, str):
        return datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    raise TypeError(f"unexpected created_at type: {type(created_at)}")


def _zod_user_role(raw: Optional[str]) -> Literal["admin", "member"]:
    """Frontend Zod só aceita admin | member; mapeia operator/viewer → member."""
    if raw == "admin":
        return "admin"
    return "member"

# CORS — regra do Starlette: com allow_credentials=True, allow_origins=["*"] é
# silenciosamente ignorado (browser não aceita wildcard + credenciais).
# Usamos lista explícita + regex para aceitar qualquer porta de localhost.
# Override em produção via env CORS_ALLOW_ORIGINS (CSV) ou CORS_ALLOW_ORIGIN_REGEX.
_cors_origins_env = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
_cors_origins = (
    [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
    if _cors_origins_env
    else [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3100",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3100",
    ]
)
_cors_origin_regex = os.getenv(
    "CORS_ALLOW_ORIGIN_REGEX",
    r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
)

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SCHEMA = os.getenv("SUPABASE_SCHEMA", "vectraclip")

# Cache para JWKS com TTL de 1 hora
_JWKS_CACHE = None
_JWKS_CACHE_LOADED_AT: Optional[datetime] = None
_JWKS_TTL = timedelta(hours=1)

def get_jwks():
    global _JWKS_CACHE, _JWKS_CACHE_LOADED_AT
    now = datetime.now(timezone.utc)
    if _JWKS_CACHE and _JWKS_CACHE_LOADED_AT and (now - _JWKS_CACHE_LOADED_AT) < _JWKS_TTL:
        return _JWKS_CACHE
    try:
        url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        res = requests.get(url, timeout=5)
        res.raise_for_status()
        _JWKS_CACHE = res.json()
        _JWKS_CACHE_LOADED_AT = now
        return _JWKS_CACHE
    except Exception as e:
        logger.error(f"Failed to fetch JWKS: {e}")
        return _JWKS_CACHE  # serve o cache expirado se disponível em vez de falhar

def validate_supabase_jwt(token: str):
    jwks = get_jwks()
    if not jwks:
        logger.warning("JWKS indisponível — JWT não validado")
        return None
    try:
        # Supabase usa ES256 (ECDSA P-256) em projetos modernos.
        # Aceitar RS256 também para compat. com configs legadas.
        payload = jwt.decode(
            token,
            jwks,
            algorithms=["ES256", "RS256"],
            audience="authenticated"
        )
        return payload
    except Exception as e:
        logger.debug(f"JWT validation failed: {e}")
        return None

def get_authenticated_client(token: str) -> Client:
    """Retorna um cliente Supabase com o JWT do usuário injetado para RLS."""
    # VEC-DEBUG: se estivermos em modo bypass, usamos o client service_role direto
    if token == "dev-token" and supabase:
        return supabase

    from supabase.lib.client_options import ClientOptions
    client = create_client(
        SUPABASE_URL,
        SUPABASE_ANON_KEY,
        options=ClientOptions(schema=SCHEMA),
    )
    client.postgrest.auth(token)
    return client

# VEC-199b — DOIS clients Supabase distintos:
#   * `supabase`       → service_role (ignora RLS) usado pelo Doctor + endpoints server-side.
#   * `supabase_auth`  → anon key, dedicado a sign_in/refresh/logout do usuário.
#
# Motivo: `supabase-py 2.0.2` tem um listener (`_listen_to_auth_events`) que em
# `SIGNED_IN | TOKEN_REFRESHED | SIGNED_OUT` zera `self._postgrest` e reconstrói
# usando o `Authorization: Bearer <jwt-do-usuario>` recém-logado. Se chamarmos
# `.auth.sign_in_with_password` no mesmo client que é service_role, o Doctor
# passa a escrever `incidents` com a role `authenticated` (sem INSERT grant)
# e bate `permission denied`. Isolando em dois clients o problema some.
# Documentação: docs/SUPABASE_DUAL_CLIENT.md
supabase = None
supabase_auth = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        from supabase.lib.client_options import ClientOptions

        # `ClientOptions.schema` pina o schema para todas as reconstruções futuras
        # de `_postgrest` — sobrevive inclusive se algum fluxo dispara SIGNED_IN
        # neste client (embora não devesse, já que não usamos .auth aqui).
        supabase = create_client(
            SUPABASE_URL,
            SUPABASE_KEY,
            options=ClientOptions(schema=SCHEMA, persist_session=False),
        )

        if SUPABASE_ANON_KEY:
            supabase_auth = create_client(
                SUPABASE_URL,
                SUPABASE_ANON_KEY,
                options=ClientOptions(schema=SCHEMA, persist_session=False),
            )
        else:
            # Sem anon key no .env → fallback pro próprio client service_role (usar
            # .auth nele é o que criava a contaminação; mas pior que poluir é não
            # logar). Log warning ostensivo.
            logger.warning(
                "SUPABASE_ANON_KEY ausente — usando client service_role para auth."
                " Isso pode causar contaminação do _postgrest (VEC-199b)."
            )
            supabase_auth = supabase
    except Exception as e:
        logger.error(f"Failed to boot Supabase: {e}")


def _refresh_llm_price_cache(force: bool = False) -> None:
    """Carrega tabela llm_models em memória para evitar query por heartbeat."""
    global _llm_price_cache_loaded_at, _llm_price_cache
    if not supabase:
        return

    now = datetime.now(timezone.utc)
    if (
        not force
        and _llm_price_cache_loaded_at is not None
        and now - _llm_price_cache_loaded_at < LLM_PRICE_CACHE_TTL
    ):
        return

    cache: Dict[str, Dict[str, Any]] = {}
    try:
        res = (
            supabase.table("llm_models")
            .select(
                "id,input_cost_per_1m,output_cost_per_1m,cache_read_cost_per_1m,effective_from,is_active"
            )
            .eq("is_active", True)
            .order("effective_from", desc=True)
            .execute()
        )
        for row in res.data or []:
            model_id = row.get("id")
            if not model_id or model_id in cache:
                # como ordena desc por effective_from, o primeiro é a versão atual
                continue
            cache[model_id] = {
                "input": float(row.get("input_cost_per_1m") or 0.0),
                "output": float(row.get("output_cost_per_1m") or 0.0),
                "cache_read": float(row.get("cache_read_cost_per_1m") or 0.0),
            }
        _llm_price_cache = cache
        _llm_price_cache_loaded_at = now
    except Exception as e:
        logger.warning(f"llm price cache refresh failed: {e}")


def _resolve_model_prices(model_id: Optional[str]) -> Optional[Dict[str, float]]:
    if not model_id:
        return None
    _refresh_llm_price_cache()
    return _llm_price_cache.get(model_id)


def _calculate_heartbeat_cost_usd(
    *,
    model_id: Optional[str],
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
) -> Optional[float]:
    prices = _resolve_model_prices(model_id)
    if not prices:
        return None
    total = (
        input_tokens * prices["input"]
        + output_tokens * prices["output"]
        + cache_read_tokens * prices["cache_read"]
    ) / 1_000_000
    return float(round(total, 8))


def _accumulate_task_cost(task_id: Optional[str], heartbeat_cost_usd: Optional[float]) -> None:
    if not supabase or not task_id or heartbeat_cost_usd is None:
        return
    try:
        supabase.rpc(
            "increment_task_cost",
            {"p_task_id": task_id, "p_delta": round(float(heartbeat_cost_usd), 8)},
        ).execute()
    except Exception as e:
        logger.warning(f"task cost accumulation failed task={task_id}: {e}")

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # CORS preflight: o browser não envia Authorization no OPTIONS.
    if request.method == "OPTIONS":
        return await call_next(request)

    # Normalizar barras duplas (ex: //auth/login → /auth/login) que ocorrem
    # quando o baseUrl do frontend termina com "/" e o path começa com "/"
    path = "/" + request.url.path.lstrip("/")

    # Defesa em profundidade: injeta CORS headers no próprio erro 401.
    # O CORSMiddleware é registrado DEPOIS deste middleware, então já é a
    # camada mais externa e também adicionaria os headers — mas mantemos
    # aqui para sobreviver a mudanças futuras na ordem de registro.
    origin = request.headers.get("Origin", "*")
    def cors_error(status: int, detail: str) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={"detail": detail},
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Credentials": "true",
            },
        )

    # Pular auth em rotas públicas
    # Inclui /sw.js e /favicon.ico: o browser não envia Bearer nesses GETs; se
    # retornarem 401, o service worker falha e o DevTools fica em loop estranho.
    public_paths = {
        "/",
        "/api",
        "/api/",
        "/api/auth/login",
        "/api/auth/refresh",
        "/api/health",
        "/auth/login",
        "/auth/refresh",
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/favicon.ico",
        "/sw.js",
        "/mockServiceWorker.js",
        "/login",
    }
    if path in public_paths or path.rstrip("/") in public_paths:
        return await call_next(request)

    auth_header = request.headers.get("Authorization")
    # Bypass para desenvolvimento local (VEC-DEBUG) — proibido em produção
    if os.getenv("VECTRACLAW_AUTH_DISABLED") == "true":
        if os.getenv("ENVIRONMENT", "development").lower() == "production":
            logger.critical("VECTRACLAW_AUTH_DISABLED=true is not allowed in ENVIRONMENT=production — rejecting request")
            return cors_error(500, "invalid_server_configuration")
        request.state.token = "dev-token"
        request.state.user_id = MOCK_USER["id"]
        request.state.company_id = MOCK_USER["companyId"]
        request.state.role = "admin"
        return await call_next(request)

    if not auth_header or not auth_header.startswith("Bearer "):
        return cors_error(401, "Missing Authorization Header")

    token = auth_header.split(" ")[1]
    payload = validate_supabase_jwt(token)

    if not payload:
        return cors_error(401, "Invalid or expired token")

    # Claims conforme Prompt V6: app_metadata -> vectraclip -> company_id/role
    app_meta = payload.get("app_metadata", {}).get("vectraclip", {})

    request.state.token = token
    request.state.user_id = payload.get("sub")
    request.state.company_id = app_meta.get("company_id")
    request.state.role = _zod_user_role(app_meta.get("role"))

    return await call_next(request)

# CORSMiddleware registrado DEPOIS do auth_middleware para ser a camada
# MAIS EXTERNA do stack (Starlette: insert(0) → último registrado fica no topo).
# Garante que TODA resposta — inclusive 401/500 devolvidos pelo auth ou por
# endpoints — saia com Access-Control-Allow-Origin e não seja bloqueada pelo browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Length", "Content-Type"],
    max_age=600,
)

@app.get("/")
@app.get("/api")
async def root():
    return {
        "name": "VectraClaw API",
        "version": "0.1.0",
        "status": "online",
        "documentation": "/docs"
    }


# =====================================================================
# SIPOC Builder (VEC-246) — Input models
# =====================================================================

class NewSipocCompanyInput(BaseModel):
    name: str
    logo_url: Optional[str] = None
    website: Optional[str] = None
    metadata: Dict[str, Any] = {}

    class Config:
        extra = "ignore"


class NewSipocSectorInput(BaseModel):
    name: str
    slug: str
    icon: Optional[str] = None
    parent_sector_id: Optional[str] = None
    metadata: Dict[str, Any] = {}

    class Config:
        extra = "ignore"


class NewSipocPositionInput(BaseModel):
    sector_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    reports_to_id: Optional[str] = None
    metadata: Dict[str, Any] = {}

    class Config:
        extra = "ignore"


class NewSipocProcessInput(BaseModel):
    sector_id: str
    name: str
    description: Optional[str] = None
    status: Optional[str] = "rascunho"
    responsible_id: Optional[str] = None
    position_id: Optional[str] = None
    metadata: Dict[str, Any] = {}

    class Config:
        extra = "ignore"


class UpsertSipocComponentInput(BaseModel):
    id: Optional[str] = None
    process_id: str
    type: str
    content: Dict[str, Any]
    order: int = 0
    validation_status: Optional[str] = "verde"
    validation_notes: Optional[str] = None
    metadata: Dict[str, Any] = {}

    class Config:
        extra = "ignore"


# =====================================================================
# SIPOC Builder (VEC-246)
# =====================================================================

@app.get("/api/sipoc/companies")
async def list_sipoc_companies(request: Request):
    if not supabase:
        return []
    try:
        # service_role bypassa RLS; filtra manualmente por request.state.company_id.
        # Em dev mode, request.state.token = "dev-token" não é JWT válido, então
        # vectraclip.sipoc_company_id() retorna NULL e o RLS bloquearia tudo.
        query = supabase.table("sipoc_companies").select("*").order("name")
        if request.state.company_id:
            query = query.eq("id", str(request.state.company_id))
        res = query.execute()
        return [SipocCompany(**row).to_zod_dict() for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_sipoc_companies failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

@app.post("/api/sipoc/companies")
async def create_sipoc_company(request: Request, payload: NewSipocCompanyInput):
    if not supabase:
        return {"id": request.state.company_id or "mock-id", "name": payload.name}
    try:
        # service_role bypassa RLS — bootstrap necessário pois o JWT ainda não tem
        # um sipoc_company_id para a política de INSERT verificar.
        # O id é fixado ao company_id do vectraclip para que as políticas de
        # SELECT/UPDATE/DELETE funcionem imediatamente após a criação.
        insert_row = {
            **payload.dict(exclude_none=True),
            "id": request.state.company_id,
        }
        res = supabase.table("sipoc_companies").insert(insert_row).execute()
        return SipocCompany(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"create_sipoc_company failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

@app.get("/api/sipoc/sectors")
async def list_sipoc_sectors(request: Request, company_id: UUID = Query(...)):
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("sipoc_sectors").select("*").eq("company_id", company_id).order("name").execute()
        return [SipocSector(**row).to_zod_dict() for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_sipoc_sectors failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

@app.post("/api/sipoc/sectors")
async def create_sipoc_sector(request: Request, payload: NewSipocSectorInput, company_id: UUID = Query(...)):
    if not supabase:
        return {"id": "mock-id", "name": payload.name}
    try:
        client = get_authenticated_client(request.state.token)
        insert_row = {**payload.dict(exclude_none=True), "company_id": str(company_id)}
        res = client.table("sipoc_sectors").insert(insert_row).execute()
        return SipocSector(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"create_sipoc_sector failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

@app.get("/api/sipoc/positions")
async def list_sipoc_positions(request: Request, company_id: UUID = Query(...)):
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("sipoc_positions").select("*").eq("company_id", company_id).order("title").execute()
        return [SipocPosition(**row).to_zod_dict() for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_sipoc_positions failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

@app.post("/api/sipoc/positions")
async def create_sipoc_position(request: Request, payload: NewSipocPositionInput, company_id: UUID = Query(...)):
    if not supabase:
        return {"id": "mock-id", "title": payload.title}
    try:
        client = get_authenticated_client(request.state.token)
        insert_row = {**payload.dict(exclude_none=True), "company_id": str(company_id)}
        res = client.table("sipoc_positions").insert(insert_row).execute()
        return SipocPosition(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"create_sipoc_position failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

@app.get("/api/sipoc/processes")
async def list_sipoc_processes(request: Request, sector_id: UUID = Query(...)):
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("sipoc_processes").select("*").eq("sector_id", sector_id).order("name").execute()
        return [SipocProcess(**row).to_zod_dict() for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_sipoc_processes failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

@app.post("/api/sipoc/processes")
async def create_sipoc_process(request: Request, payload: NewSipocProcessInput):
    if not supabase:
        return {"id": "mock-id", "name": payload.name}
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("sipoc_processes").insert(payload.dict(exclude_none=True)).execute()
        return SipocProcess(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"create_sipoc_process failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

@app.get("/api/sipoc/processes/{process_id}")
async def get_sipoc_process(request: Request, process_id: UUID):
    if not supabase:
        return {}
    try:
        client = get_authenticated_client(request.state.token)
        # Buscar processo
        proc_res = client.table("sipoc_processes").select("*").eq("id", process_id).single().execute()
        if not proc_res.data:
            raise HTTPException(status_code=404, detail="Process not found")
        
        # Buscar componentes vinculados
        comp_res = client.table("sipoc_components").select("*").eq("process_id", process_id).order("order").execute()
        
        process = SipocProcess(**proc_res.data).to_zod_dict()
        process["components"] = [SipocComponent(**row).to_zod_dict() for row in (comp_res.data or [])]
        
        return process
    except Exception as e:
        logger.error(f"get_sipoc_process failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

@app.get("/api/sipoc/components")
async def list_sipoc_components(request: Request, process_id: UUID = Query(...)):
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("sipoc_components").select("*").eq("process_id", process_id).order("order").execute()
        return [SipocComponent(**row).to_zod_dict() for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_sipoc_components failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

@app.post("/api/sipoc/components")
async def upsert_sipoc_component(request: Request, payload: UpsertSipocComponentInput):
    if not supabase:
        return {"id": "mock-id", "type": payload.type}
    try:
        client = get_authenticated_client(request.state.token)
        if payload.id:
            update_data = payload.dict(exclude={"id"}, exclude_none=True)
            res = client.table("sipoc_components").update(update_data).eq("id", payload.id).eq("process_id", payload.process_id).execute()
        else:
            res = client.table("sipoc_components").insert(payload.dict(exclude={"id"}, exclude_none=True)).execute()

        return SipocComponent(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"upsert_sipoc_component failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

class SipocResearchInput(BaseModel):
    sector: str

    class Config:
        extra = "ignore"


@app.post("/sipoc/research")
@app.post("/api/sipoc/research")
async def sipoc_research(request: Request, payload: SipocResearchInput):
    try:
        client = get_authenticated_client(request.state.token) if supabase else None
        result = await research_sector(payload.sector, supabase_client=client)
        return result
    except Exception as e:
        logger.error(f"sipoc_research failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

# === Heartbeat Doctor Scheduler ===

async def doctor_scheduler(interval_s: int):
    logger.info(f"[doctor] scheduler started interval={interval_s}s")
    while True:
        try:
            # O Doctor roda como service_role permanente (via variável 'supabase' que já é service_role)
            if supabase:
                await doctor_tick(supabase, app.state)
            else:
                logger.debug("[doctor] skip tick: no supabase client")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[doctor] scheduler error: {e}")
        await asyncio.sleep(interval_s)

@app.on_event("startup")
async def startup_event():
    _refresh_llm_price_cache(force=True)
    # Registrar tick de 30s
    app.state.doctor_task = asyncio.create_task(doctor_scheduler(interval_s=30))

@app.on_event("shutdown")
async def shutdown_event():
    if hasattr(app.state, "doctor_task"):
        app.state.doctor_task.cancel()
        try:
            await app.state.doctor_task
        except asyncio.CancelledError:
            pass

# =====================================================================
# Database Mocks (Adequados perfeitamente ao Zod Schema do VectraClip)
# =====================================================================

MOCK_USER = {
    "id": "40000000-0000-4000-8000-000000000001",
    "name": "Marcelo Rosas",
    "email": "marcelo@vectracargo.com",
    "role": "admin",
    "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
    "avatarUrl": None,
    "createdAt": "2026-04-19T00:00:00Z"
}

MOCK_SESSION = {
    "accessToken": "fake-jwt-token-123",
    "refreshToken": "fake-refresh-token",
    "expiresAt": "2030-01-01T00:00:00Z",
    "user": MOCK_USER
}

MOCK_AGENTS = [
  {
    "id": "a0000000-0000-4000-8000-000000000001",
    "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
    "name": "Apollo",
    "role": "Oracle (Inteligência Central)",
    "status": "working",
    "tokenBudget": 500000,
    "currentBurnRate": 12.5,
    "adapterType": "claude_code",
    "createdAt": "2026-04-01T00:00:00Z"
  },
  {
    "id": "a0000000-0000-4000-8000-000000000002",
    "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
    "name": "Themis",
    "role": "Inbox Triage & Classificação",
    "status": "idle",
    "tokenBudget": 20000,
    "currentBurnRate": 0,
    "adapterType": "claude_code",
    "createdAt": "2026-04-02T00:00:00Z"
  },
  {
    "id": "a0000000-0000-4000-8000-000000000003",
    "name": "Chronos",
    "role": "Monitoramento & Health Check",
    "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
    "status": "working",
    "tokenBudget": 100000,
    "currentBurnRate": 85000,
    "adapterType": "claude_code",
    "createdAt": "2026-04-03T00:00:00Z"
  },
  {
    "id": "a0000000-0000-4000-8000-000000000004",
    "name": "Pitágoras",
    "role": "Atlas Code Review",
    "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
    "status": "working",
    "tokenBudget": 50000,
    "currentBurnRate": 60000,
    "adapterType": "claude_code",
    "createdAt": "2026-04-04T00:00:00Z"
  }
]

MOCK_TASKS = [
  {
    "id": "7a5c0000-0000-4000-8000-000000000001",
    "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
    "assignedToAgentId": "a0000000-0000-4000-8000-000000000001",
    "parentTaskId": None,
    "title": "Extrair BL MEDU1234567",
    "description": "Parser de Bill of Lading PDF",
    "status": "in_progress",
    "budgetLimit": 20000,
    "spent": 8000,
    "claimedAt": "2026-04-19T18:00:00Z",
    "goalId": "60a10000-0000-4000-8000-000000000001",
    "createdAt": "2026-04-19T17:50:00Z"
  },
  {
    "id": "7a5c0000-0000-4000-8000-000000000002",
    "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
    "assignedToAgentId": "a0000000-0000-4000-8000-000000000003",
    "parentTaskId": None,
    "title": "Cotação Santos → Curitiba (Helios)",
    "description": "Calcular frete via tabela ANTT",
    "status": "in_progress",
    "budgetLimit": 10000,
    "spent": 8800,
    "claimedAt": "2026-04-19T19:00:00Z",
    "goalId": None,
    "createdAt": "2026-04-19T18:50:00Z"
  },
  {
    "id": "7a5c0000-0000-4000-8000-000000000003",
    "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
    "assignedToAgentId": "a0000000-0000-4000-8000-000000000004",
    "parentTaskId": None,
    "title": "Otimizar rota multimodal CPS-NVT",
    "description": "Stuck em loop de retries",
    "status": "in_progress",
    "budgetLimit": 5000,
    "spent": 6200,
    "claimedAt": "2026-04-19T16:00:00Z",
    "goalId": None,
    "createdAt": "2026-04-19T15:50:00Z"
  }
]

MOCK_GOALS = [{
    "id": "60a10000-0000-4000-8000-000000000001",
    "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
    "parentGoalId": None,
    "title": "Clear 50 Containers",
    "metric": "clearances",
    "target": 50,
    "current": 12
}]

MOCK_COMPANIES = [{
    "id": "c0000000-0000-4000-8000-000000000001",
    "name": "Vectra Cargo",
    "mission": "Logística Aduaneira Autônoma",
    "ownerUserId": "40000000-0000-4000-8000-000000000001",
    "createdAt": "2026-04-19T00:00:00Z"
}]

MOCK_ROUTINES = [
    {
        "id": "rot00000-0000-4000-8000-000000000001",
        "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
        "name": "Morning Oracle Briefing",
        "status": "active",
        "schedule": {"cron": "30 9 * * 1-5", "timezone": "America/Sao_Paulo", "human": "Dias úteis às 09:30"},
        "agentId": "a0000000-0000-4000-8000-000000000001", # Apollo
        "metadata": {
            "blueprint": "apollo_morning",
            "trigger_type": "cron",
            "connectors": ["google_calendar", "slack_navi"],
            "output_format": "executive_summary_markdown"
        }
    },
    {
        "id": "rot00000-0000-4000-8000-000000000002",
        "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
        "name": "Hades Inbox Triage",
        "status": "active",
        "schedule": {"cron": "0 12 * * 1-5", "timezone": "America/Sao_Paulo", "human": "Dias úteis às 12:00"},
        "agentId": "a0000000-0000-4000-8000-000000000002", # Themis
        "metadata": {
            "blueprint": "hades_inbox",
            "connectors": ["gmail", "supabase_hades"],
            "priority_logic": "signals_summary_v2"
        }
    },
    {
        "id": "rot00000-0000-4000-8000-000000000003",
        "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
        "name": "Olympus Health Check",
        "status": "active",
        "schedule": {"cron": "0 9 * * *", "timezone": "America/Sao_Paulo", "human": "Diário às 09:00"},
        "agentId": "a0000000-0000-4000-8000-000000000003", # Chronos
        "metadata": {
            "blueprint": "olympus_health",
            "connectors": ["datadog", "sentry", "hades_db"],
            "alert_status": "stuck_hard"
        }
    }
]

MOCK_HEARTBEATS = [{
    "id": "h0000000-0000-4000-8000-000000000001",
    "agentId": "a0000000-0000-4000-8000-000000000001",
    "taskId": "7a5c0000-0000-4000-8000-000000000001",
    "status": "working",
    "tokensUsed": 150,
    "logExcerpt": "Parse of PDF finished in 1s.",
    "createdAt": "2026-04-19T00:00:00Z"
}]

MOCK_ADAPTERS = [
    {
        "id": "adp00000-0000-4000-8000-000000000001",
        "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
        "slug": "claude_code",
        "displayName": "Claude Code",
        "provider": "anthropic",
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
    {
        "id": "adp00000-0000-4000-8000-000000000002",
        "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
        "slug": "codex",
        "displayName": "Codex",
        "provider": "openai",
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
    {
        "id": "adp00000-0000-4000-8000-000000000003",
        "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
        "slug": "mcp-gmail",
        "displayName": "Google Gmail (MCP)",
        "provider": "google",
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
    },
    {
        "id": "adp00000-0000-4000-8000-000000000004",
        "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
        "slug": "mcp-slack",
        "displayName": "Slack Connect (MCP)",
        "provider": "slack",
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
    },
    {
        "id": "adp00000-0000-4000-8000-000000000005",
        "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
        "slug": "mcp-github",
        "displayName": "GitHub Ops (MCP)",
        "provider": "github",
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
    },
]

MOCK_ADAPTER_FIELDS = [
    {
        "id": "fld00000-0000-4000-8000-000000000001",
        "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
        "adapterId": "adp00000-0000-4000-8000-000000000001",
        "fieldKey": "model_id",
        "fieldLabel": "Modelo LLM",
        "fieldType": "select",
        "isRequired": True,
        "optionsJson": {"source": "llm_models", "provider": "anthropic"},
        "triggerCondition": None,
        "sortOrder": 10,
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
    {
        "id": "fld00000-0000-4000-8000-000000000002",
        "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
        "adapterId": "adp00000-0000-4000-8000-000000000001",
        "fieldKey": "temperature",
        "fieldLabel": "Temperature",
        "fieldType": "number",
        "isRequired": False,
        "optionsJson": None,
        "triggerCondition": None,
        "sortOrder": 20,
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
]

MOCK_AGENT_ADAPTER_CONFIGS = [
    {
        "id": "cfg00000-0000-4000-8000-000000000001",
        "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
        "agentId": "a0000000-0000-4000-8000-000000000001",
        "adapterId": "adp00000-0000-4000-8000-000000000001",
        "fieldValuesJson": {
            "model_id": "claude-opus-4-7-thinking-high",
            "temperature": 0.2,
            "max_tokens": 8192,
        },
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
]

MOCK_AGENT_EXECUTION_CONFIGS = [
    {
        "id": "exe00000-0000-4000-8000-000000000001",
        "companyId": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
        "agentId": "a0000000-0000-4000-8000-000000000001",
        "executionMode": "REALTIME",
        "triggerConfig": {},
        "functionUrl": None,
        "authSecretRef": None,
        "authHeaderName": None,
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
]

MOCK_AUDIT = [{
    "id": "7a5c0000-0000-4000-8000-000000000001",
    "company_id": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
    "actor_type": "system",
    "actor_id": "system-1",
    "action": "boot",
    "target": "system",
    "payload": {},
    "created_at": "2026-04-19T00:00:00Z"
}]

MOCK_APPROVAL = [{
    "id": "7a5c0000-0000-4000-8000-000000000001",
    "company_id": "88aa2edc-6a9e-4048-9bd8-c588e0dcae4c",
    "request_type": "task_done",
    "payload": {
        "taskId": "7a5c0000-0000-4000-8000-000000000001",
        "taskCode": "ATL-2026-04-0001",
        "title": "Analisar amostra NCM para dossiê de importação",
        "completedByAgentId": "a0000000-0000-4000-8000-000000000001",
        "completedByAgentName": "Atlas",
        "spent": 6200,
        "budgetLimit": 5000,
        "logExcerpt": "Task finalizada com checklist de compliance e resumo anexado.",
    },
    "status": "pending",
    "approved_by_user_id": None,
    "created_at": "2026-04-19T00:00:00Z",
    "updated_at": "2026-04-19T00:00:00Z"
}]

MOCK_LLM_MODELS = [
    {"id": "claude-opus-4-5", "provider": "anthropic", "display_name": "Claude Opus 4.5", "input_cost_per_1m": 15.0, "output_cost_per_1m": 75.0, "cache_read_cost_per_1m": 1.5, "context_window_k": 200, "is_active": True, "effective_from": "2026-01-01"},
    {"id": "claude-sonnet-4-6", "provider": "anthropic", "display_name": "Claude Sonnet 4.6", "input_cost_per_1m": 3.0, "output_cost_per_1m": 15.0, "cache_read_cost_per_1m": 0.3, "context_window_k": 200, "is_active": True, "effective_from": "2026-03-01"},
    {"id": "claude-haiku-4-5", "provider": "anthropic", "display_name": "Claude Haiku 4.5", "input_cost_per_1m": 0.8, "output_cost_per_1m": 4.0, "cache_read_cost_per_1m": 0.08, "context_window_k": 200, "is_active": True, "effective_from": "2026-01-01"},
]

MOCK_AGENT_SPECIALTIES = [
    {
        "id": "email-monitoring",
        "name": "Monitoramento de E-mail",
        "slug": "monitoramento-email",
        "domain": "Comunicação",
        "description": "Monitora inbox via IMAP, categoriza e resume e-mails.",
        "compatible_roles": ["Inteligência de E-mail", "Assistente de Inbox", "Comunicação"],
        "is_active": True,
        "config_schema": [
            {"key": "inbox_imap_host", "label": "Servidor IMAP", "type": "text", "required": True, "default": "imap.secureserver.net"},
            {"key": "inbox_email", "label": "E-mail", "type": "text", "required": True},
            {"key": "inbox_password", "label": "Senha", "type": "password", "required": True},
            {"key": "auto_delete_spam", "label": "Auto-deletar Spam", "type": "boolean", "default": False},
            {"key": "monitor_senders", "label": "Whitelist de Remetentes", "type": "text", "placeholder": "email1@ex.com, email2@ex.com"}
        ]
    },
    {"id": "web-research", "name": "Pesquisa Web", "slug": "pesquisa-web", "domain": "Pesquisa", "description": "Pesquisa web, extração e síntese de informação.", "compatible_roles": ["Pesquisador", "Analista", "Scout"], "is_active": True},
    {"id": "data-analysis", "name": "Análise de Dados", "slug": "analise-dados", "domain": "Analytics", "description": "Análise de dados tabulares e geração de insights.", "compatible_roles": ["Analista de Dados", "BI", "Analytics"], "is_active": True},
    {"id": "file-processing", "name": "Processamento de Arquivos", "slug": "processamento-arquivos", "domain": "Operações", "description": "Processamento de arquivos, ETL e transformação de documentos.", "compatible_roles": ["Processador", "ETL", "Operador de Documentos"], "is_active": True},
]

# VEC-199 In-Memory Fallback
app.state.incidents = []
app.state.incident_audit = []
app.state.agent_runtime = {}

# =====================================================================
# Auth Endpoints (VEC-140 Parity)
# =====================================================================

class LoginPayload(BaseModel):
    email: str
    password: str

@app.post("/auth/login") # VEC-140: Rota direta para compatibilidade
@app.post("/api/auth/login")
async def login(payload: LoginPayload):
    if not supabase:
        return MOCK_SESSION
    
    try:
        # Tenta login real no Supabase
        # VEC-199b: usa client dedicado a auth — NUNCA `supabase` (service_role),
        # senão o listener SIGNED_IN zera `_postgrest` e faz o Doctor virar
        # authenticated role, causando `permission denied`.
        res = supabase_auth.auth.sign_in_with_password({
            "email": payload.email,
            "password": payload.password,
        })
        
        if not res.session or not res.user:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Mapeamento do usuário do Supabase para o modelo do VectraClip.
        # Claims de tenant ficam em app_metadata.vectraclip (VEC-194), não em user_metadata.
        user_meta = res.user.user_metadata or {}
        app_meta = getattr(res.user, "app_metadata", None) or {}
        vc = app_meta.get("vectraclip") or {}
        if not isinstance(vc, dict):
            vc = {}

        raw_role = vc.get("role") or user_meta.get("role") or "admin"
        company_id = vc.get("company_id") or app_meta.get("company_id") or MOCK_USER["companyId"]
        display_name = (
            user_meta.get("full_name")
            or user_meta.get("name")
            or (res.user.email.split("@")[0] if res.user.email else "User")
        )

        user_data = User(
            id=res.user.id,
            name=display_name,
            email=res.user.email or "",
            role=_zod_user_role(str(raw_role) if raw_role is not None else None),
            company_id=str(company_id),
            avatar_url=user_meta.get("avatar_url"),
            created_at=_user_created_at_to_utc(getattr(res.user, "created_at", None)),
        )

        session = AuthSession(
            access_token=res.session.access_token,
            refresh_token=res.session.refresh_token,
            expires_at=_session_expires_to_utc(res.session.expires_at),
            user=user_data
        )

        return session.to_zod_dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid login credentials")

@app.get("/auth/me")
@app.get("/api/auth/me")
async def auth_me(request: Request):
    if not supabase:
        return MOCK_USER
    
    # Busca usuário real na tabela app_users do Supabase usando RLS
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("app_users").select("*").eq("id", request.state.user_id).execute()
        
        if not res.data:
            # Caso não exista na tabela customizada (primeiro login?), fallback para mock ou erro
            return MOCK_USER

        row = res.data[0]
        user_data = User(
            id=row["id"],
            name=row.get("name", "User"),
            email=row.get("email", ""),
            role=_zod_user_role(row.get("role")),
            company_id=row.get("company_id") or request.state.company_id or MOCK_USER["companyId"],
            avatar_url=row.get("avatar_url"),
            created_at=_user_created_at_to_utc(row.get("created_at"))
        )
        return user_data.to_zod_dict()
    except Exception as e:
        logger.error(f"auth_me failed: {e}")
        return MOCK_USER

class RefreshPayload(BaseModel):
    refreshToken: str

@app.post("/auth/refresh")
@app.post("/api/auth/refresh")
async def auth_refresh(payload: RefreshPayload):
    if not supabase:
        return MOCK_SESSION
        
    try:
        res = supabase_auth.auth.refresh_session(payload.refreshToken)
        if not res.session or not res.user:
            raise HTTPException(401, "Refresh failed")

        metadata = res.user.user_metadata or {}
        app_meta = getattr(res.user, "app_metadata", {}).get("vectraclip", {})
        
        user_data = User(
            id=res.user.id,
            name=metadata.get("full_name", "User"),
            email=res.user.email or "",
            role=_zod_user_role(app_meta.get("role")),
            company_id=app_meta.get("company_id") or MOCK_USER["companyId"],
            avatar_url=metadata.get("avatar_url"),
            created_at=_user_created_at_to_utc(res.user.created_at)
        )

        session = AuthSession(
            access_token=res.session.access_token,
            refresh_token=res.session.refresh_token,
            expires_at=_session_expires_to_utc(res.session.expires_at),
            user=user_data
        )
        return session.to_zod_dict()
    except Exception as e:
        logger.error(f"Refresh failed: {e}")
        raise HTTPException(401, str(e))

@app.post("/auth/logout")
@app.post("/api/auth/logout")
async def auth_logout():
    if supabase_auth:
        try:
            supabase_auth.auth.sign_out()
        except Exception as e:
            logger.debug(f"logout error (ignorando): {e}")
    return {"success": True}

# =====================================================================
# REST Resources (VectraClip Zod Schemas)
# =====================================================================

@app.get("/api/companies/{company_id}/agents")
@app.get("/companies/{company_id}/agents")
@app.get("/api/agents")
async def get_agents(request: Request, company_id: str = None):
    if not supabase:
        return MOCK_AGENTS
        
    try:
        client = get_authenticated_client(request.state.token)
        query = client.table("agents").select("*")
        if company_id:
            query = query.eq("company_id", company_id)
        res = query.execute()
        return [Agent(**row).to_zod_dict() for row in res.data]
    except Exception as e:
        logger.error(f"get_agents failed: {e}")
        return MOCK_AGENTS

class NewAgentInput(BaseModel):
    name: str
    role: str
    adapterType: str
    tokenBudget: int

@app.post("/api/companies/{company_id}/agents")
@app.post("/companies/{company_id}/agents")
async def create_agent(company_id: str, payload: NewAgentInput):
    adapter_map = {
        "claude_code": "claude_code",
        "codex": "cursor",
        "shell": "bot",
        "webhook": "bot",
        "cursor": "cursor",
        "bot": "bot",
    }
    adapter_type = adapter_map.get(payload.adapterType, "bot")

    row: Dict[str, Any] = {
        "company_id": company_id,
        "name": payload.name,
        "role": payload.role,
        "reports_to_id": None,
        "status": AgentStatus.IDLE,
        "token_budget": payload.tokenBudget,
        "current_burn_rate": 0,
        "adapter_type": adapter_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if not supabase:
        new_agent = MOCK_AGENTS[0].copy()
        new_agent["id"] = f"agt_tmp_{int(datetime.now().timestamp())}"
        new_agent["companyId"] = company_id
        new_agent["name"] = payload.name
        new_agent["role"] = payload.role
        new_agent["reportsToId"] = None
        new_agent["status"] = "idle"
        new_agent["tokenBudget"] = payload.tokenBudget
        new_agent["currentBurnRate"] = 0
        new_agent["adapterType"] = adapter_type
        new_agent["createdAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        MOCK_AGENTS.append(new_agent)
        return new_agent

    try:
        # service_role para evitar bloqueio por grants RLS incompletos
        res = supabase.table("agents").insert(row).execute()
        if not res.data:
            raise HTTPException(status_code=500, detail="insert_returned_empty")
        return Agent(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_agent failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

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

class NewTaskInput(BaseModel):
    """
    VEC-182 — espelha CreateTaskInput do VectraClip (tasks.ts).
    Campos obrigatórios: title, description, budgetLimit.
    Campos opcionais: status (default backlog), parentTaskId, assignedToAgentId, goalId.
    """

    title: str
    description: str
    budgetLimit: int
    operationType: Optional[
        Literal[
            "orchestration",
            "code_generation",
            "code_review",
            "research",
            "document_generation",
            "qa_testing",
            "other",
        ]
    ] = "other"
    status: Optional[
        Literal["backlog", "queued", "in_progress", "review", "done", "blocked"]
    ] = "backlog"
    parentTaskId: Optional[str] = None
    assignedToAgentId: Optional[str] = None
    goalId: Optional[str] = None

    @validator("parentTaskId", "assignedToAgentId", "goalId", pre=True)
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v


class UpdateTaskInput(BaseModel):
    """
    Corpo PATCH alinhado ao UpdateTaskInput do VectraClip (Zod partial da Task).
    VEC-182 — apenas campos mutáveis; `id` / `companyId` / `createdAt` vêm da linha existente.
    """

    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[
        Literal["backlog", "queued", "in_progress", "review", "done", "blocked"]
    ] = None
    operation_type: Optional[
        Literal[
            "orchestration",
            "code_generation",
            "code_review",
            "research",
            "document_generation",
            "qa_testing",
            "other",
        ]
    ] = Field(default=None, alias="operationType")
    budget_limit: Optional[int] = Field(default=None, alias="budgetLimit")
    spent: Optional[float] = None
    cost_usd: Optional[float] = Field(default=None, alias="costUsd")
    assigned_to_agent_id: Optional[str] = Field(
        default=None, alias="assignedToAgentId"
    )
    parent_task_id: Optional[str] = Field(default=None, alias="parentTaskId")
    goal_id: Optional[str] = Field(default=None, alias="goalId")

    class Config:
        allow_population_by_field_name = True
        extra = "ignore"

    @validator("spent", pre=True)
    def parse_spent(cls, v):
        if v is None:
            return v
        return float(v)

    @validator("assigned_to_agent_id", "parent_task_id", "goal_id", pre=True)
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v


def _task_patch_payload_to_camel(patch_snake: Dict[str, Any]) -> Dict[str, Any]:
    key_map = {
        "title": "title",
        "description": "description",
        "status": "status",
        "operation_type": "operationType",
        "budget_limit": "budgetLimit",
        "spent": "spent",
        "cost_usd": "costUsd",
        "assigned_to_agent_id": "assignedToAgentId",
        "parent_task_id": "parentTaskId",
        "goal_id": "goalId",
    }
    return {key_map[k]: v for k, v in patch_snake.items()}


@app.post("/api/companies/{company_id}/tasks")
@app.post("/companies/{company_id}/tasks")
async def create_task(request: Request, company_id: str, payload: NewTaskInput):
    """
    VEC-182 — insert real na tabela `vectraclip.tasks`.
    Usa service_role para garantir write mesmo quando grants de INSERT não estão
    abertos para `authenticated`; company_id é fixado pela rota (não pelo body)
    para evitar cross-company injection.
    """
    insert_row: Dict[str, Any] = {
        "company_id": company_id,
        "title": payload.title,
        "description": payload.description,
        "budget_limit": payload.budgetLimit,
        "operation_type": payload.operationType or "other",
        "status": payload.status or "backlog",
        "spent": 0,
        "cost_usd": 0,
        "parent_task_id": payload.parentTaskId,
        "assigned_to_agent_id": payload.assignedToAgentId,
        "goal_id": payload.goalId,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if supabase:
        try:
            res = supabase.table("tasks").insert(insert_row).execute()
            if not res.data:
                raise HTTPException(status_code=500, detail="insert_returned_empty")
            return Task(**res.data[0]).to_zod_dict()
        except HTTPException:
            raise
        except Exception as e:
            # VEC-188 — self-healing: devolve contexto estruturado para o agente
            from src.services.brain.db_failover import build_failover_result
            fr = build_failover_result(
                exc=e,
                operation="insert:tasks",
                table="tasks",
                original_payload=insert_row,
                retry_hint=f"POST /api/companies/{company_id}/tasks",
            )
            logger.error("create_task DB failed [%s]: %s", fr.error_category, fr.error_detail)
            raise HTTPException(status_code=fr.http_status, detail=fr.to_http_detail())

    # Mock fallback (sem Supabase)
    new_task = MOCK_TASKS[0].copy()
    new_task.update({
        "id": f"tmp_{int(datetime.now().timestamp())}",
        "companyId": company_id,
        "title": payload.title,
        "description": payload.description,
        "budgetLimit": payload.budgetLimit,
        "operationType": payload.operationType or "other",
        "status": payload.status or "backlog",
        "spent": 0,
        "costUsd": 0,
        "parentTaskId": payload.parentTaskId,
        "assignedToAgentId": payload.assignedToAgentId,
        "goalId": payload.goalId,
        "claimedAt": None,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })
    return new_task

@app.get("/api/companies/{company_id}/goals")
@app.get("/api/goals")
async def get_goals(request: Request, company_id: str = None):
    if not supabase:
        if company_id:
            return [g for g in MOCK_GOALS if g.get("companyId") == company_id]
        return MOCK_GOALS
    try:
        client = get_authenticated_client(request.state.token)
        query = client.table("goals").select("*")
        if company_id:
            query = query.eq("company_id", company_id)
        res = query.execute()
        return [Goal(**row).to_zod_dict() for row in res.data]
    except Exception as e:
        logger.error(f"get_goals failed: {e}")
        return MOCK_GOALS


class NewGoalInput(BaseModel):
    title: str
    metric: str
    target: float
    current: float = 0.0
    parentGoalId: Optional[str] = None

    @validator("parentGoalId", pre=True)
    def empty_to_none(cls, v):
        return None if v == "" else v


class UpdateGoalInput(BaseModel):
    title: Optional[str] = None
    metric: Optional[str] = None
    target: Optional[float] = None
    current: Optional[float] = None
    parentGoalId: Optional[str] = None

    class Config:
        extra = "ignore"

    @validator("parentGoalId", pre=True)
    def empty_to_none(cls, v):
        return None if v == "" else v


@app.post("/api/companies/{company_id}/goals")
@app.post("/companies/{company_id}/goals")
async def create_goal(request: Request, company_id: str, payload: NewGoalInput):
    """VEC-144 — Cria goal na tabela Supabase ou fallback mock."""
    insert_row: Dict[str, Any] = {
        "company_id": company_id,
        "parent_goal_id": payload.parentGoalId,
        "title": payload.title,
        "metric": payload.metric,
        "target": payload.target,
        "current": payload.current,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if supabase:
        try:
            client = get_authenticated_client(request.state.token)
            res = client.table("goals").insert(insert_row).execute()
            if not res.data:
                raise HTTPException(status_code=500, detail="insert_returned_empty")
            return Goal(**res.data[0]).to_zod_dict()
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"create_goal DB failed: {e}")
            raise HTTPException(status_code=500, detail="internal_server_error")
    # Mock fallback
    new_goal = {
        "id": f"gol_tmp_{int(datetime.now().timestamp())}",
        "companyId": company_id,
        "parentGoalId": payload.parentGoalId,
        "title": payload.title,
        "metric": payload.metric,
        "target": payload.target,
        "current": payload.current,
    }
    MOCK_GOALS.append(new_goal)
    return new_goal


@app.patch("/api/goals/{goal_id}")
@app.patch("/goals/{goal_id}")
async def patch_goal(request: Request, goal_id: str, patch: UpdateGoalInput):
    """VEC-144 — Atualização parcial do goal."""
    payload: Dict[str, Any] = {}
    if patch.title is not None:
        payload["title"] = patch.title
    if patch.metric is not None:
        payload["metric"] = patch.metric
    if patch.target is not None:
        payload["target"] = patch.target
    if patch.current is not None:
        payload["current"] = patch.current
    if patch.parentGoalId is not None:
        payload["parent_goal_id"] = patch.parentGoalId
    if not payload:
        raise HTTPException(status_code=400, detail="empty_patch")
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()

    if not supabase:
        row = next((g for g in MOCK_GOALS if g.get("id") == goal_id), None)
        if row is None:
            raise HTTPException(status_code=404, detail="goal_not_found")
        if patch.title is not None:
            row["title"] = patch.title
        if patch.metric is not None:
            row["metric"] = patch.metric
        if patch.target is not None:
            row["target"] = patch.target
        if patch.current is not None:
            row["current"] = patch.current
        if patch.parentGoalId is not None:
            row["parentGoalId"] = patch.parentGoalId
        return row
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("goals").update(payload).eq("id", goal_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="goal_not_found")
        return Goal(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_goal DB failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")


@app.delete("/api/goals/{goal_id}")
@app.delete("/goals/{goal_id}")
async def delete_goal(request: Request, goal_id: str):
    """VEC-144 — Remove o goal. Retorna 204 No Content."""
    if not supabase:
        global MOCK_GOALS
        before = len(MOCK_GOALS)
        MOCK_GOALS = [g for g in MOCK_GOALS if g.get("id") != goal_id]
        if len(MOCK_GOALS) == before:
            raise HTTPException(status_code=404, detail="goal_not_found")
        return Response(status_code=204)
    try:
        client = get_authenticated_client(request.state.token)
        # supabase-py v1: DELETE não suporta .select() — executa e confia no
        # resultado. Se a linha não existir, retorna 404 via check abaixo.
        check = client.table("goals").select("id").eq("id", goal_id).execute()
        if not check.data:
            raise HTTPException(status_code=404, detail="goal_not_found")
        client.table("goals").delete().eq("id", goal_id).execute()
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_goal DB failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")


@app.get("/api/companies")
@app.get("/companies")
async def get_companies():
    return MOCK_COMPANIES


class NewCompanyInput(BaseModel):
    name: str
    mission: str


class UpdateCompanyInput(BaseModel):
    name: Optional[str] = None
    mission: Optional[str] = None
    tier: Optional[str] = None

    class Config:
        extra = "ignore"


@app.post("/api/companies")
@app.post("/companies")
async def create_company(request: Request, payload: NewCompanyInput):
    """
    Cria uma company (VEC-224 - critério CRUD).
    """
    now = datetime.now(timezone.utc).isoformat()
    # Schema real atual de vectraclip.companies: id, name, tier, created_at, updated_at
    # (sem mission/owner_user_id). Mantemos `mission` no contrato de resposta para
    # compatibilidade com o frontend.
    row: Dict[str, Any] = {
        "name": payload.name,
        "tier": "trial",
        "created_at": now,
        "updated_at": now,
    }

    if not supabase:
        new_company = {
            "id": f"cmp_tmp_{int(datetime.now().timestamp())}",
            "name": payload.name,
            "mission": payload.mission,
            "ownerUserId": MOCK_USER["id"],
            "createdAt": now.replace("+00:00", "Z"),
        }
        MOCK_COMPANIES.append(new_company)
        return new_company

    try:
        # service_role para contornar grants de escrita ainda incompletos.
        res = supabase.table("companies").insert(row).execute()
        if not res.data:
            raise HTTPException(status_code=500, detail="insert_returned_empty")
        created = res.data[0]
        company_id = created["id"]

        # Garante entrada espelhada em sipoc_companies com o mesmo id,
        # necessário para GET /api/sipoc/companies retornar a nova empresa.
        supabase.table("sipoc_companies").upsert({
            "id": company_id,
            "name": created["name"],
            "metadata": {"mission": payload.mission},
        }, on_conflict="id").execute()

        return {
            "id": company_id,
            "name": created["name"],
            "mission": payload.mission,
            "ownerUserId": getattr(request.state, "user_id", None) or MOCK_USER["id"],
            "createdAt": str(created.get("created_at", now)).replace("+00:00", "Z"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_company failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")


@app.patch("/api/companies/{company_id}")
@app.patch("/companies/{company_id}")
async def patch_company(request: Request, company_id: str, patch: UpdateCompanyInput):
    payload = patch.dict(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="empty_patch")

    # Schema real atual não tem mission; ignoramos para compat com frontend.
    payload.pop("mission", None)
    if "tier" in payload and payload["tier"] not in ("trial", "standard", "enterprise"):
        payload["tier"] = "standard"
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()

    if not supabase:
        row = next((c for c in MOCK_COMPANIES if c.get("id") == company_id), None)
        if not row:
            raise HTTPException(status_code=404, detail="company_not_found")
        if "name" in payload:
            row["name"] = payload["name"]
        return row

    try:
        res = supabase.table("companies").update(payload).eq("id", company_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="company_not_found")
        row = res.data[0]
        return {
            "id": row["id"],
            "name": row["name"],
            "mission": "",
            "ownerUserId": getattr(request.state, "user_id", None) or MOCK_USER["id"],
            "createdAt": str(row.get("created_at")).replace("+00:00", "Z"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_company failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")


@app.delete("/api/companies/{company_id}")
@app.delete("/companies/{company_id}")
async def delete_company(company_id: str):
    if not supabase:
        global MOCK_COMPANIES
        before = len(MOCK_COMPANIES)
        MOCK_COMPANIES = [c for c in MOCK_COMPANIES if c.get("id") != company_id]
        if len(MOCK_COMPANIES) == before:
            raise HTTPException(status_code=404, detail="company_not_found")
        return Response(status_code=204)

    try:
        check = supabase.table("companies").select("id").eq("id", company_id).execute()
        if not check.data:
            raise HTTPException(status_code=404, detail="company_not_found")
        supabase.table("companies").delete().eq("id", company_id).execute()
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_company failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

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

class NewHeartbeatInput(BaseModel):
    """
    VEC-183 — POST /api/heartbeats: agentes reportam status em tempo real.
    O Claw persiste no DB e emite evento WS `heartbeat` para todos os sockets
    conectados na company.
    """

    agentId: str
    status: Literal["idle", "working", "offline", "error", "paused"]
    tokensUsed: int = 0
    inputTokens: int = 0
    outputTokens: int = 0
    cacheReadTokens: int = 0
    modelId: Optional[str] = None
    logExcerpt: str = ""
    taskId: Optional[str] = None


@app.post("/api/heartbeats")
async def post_heartbeat(request: Request, payload: NewHeartbeatInput):
    """Agente reporta heartbeat; Claw persiste e emite WS `heartbeat`."""
    now = datetime.now(timezone.utc).isoformat()
    input_tokens = max(0, int(payload.inputTokens or 0))
    output_tokens = max(0, int(payload.outputTokens or 0))
    cache_read_tokens = max(0, int(payload.cacheReadTokens or 0))
    tokens_used = max(
        0,
        int(payload.tokensUsed or 0) or (input_tokens + output_tokens + cache_read_tokens),
    )
    heartbeat_cost = _calculate_heartbeat_cost_usd(
        model_id=payload.modelId,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
    )
    row: Dict[str, Any] = {
        "agent_id": payload.agentId,
        "status": payload.status,
        "tokens_used": tokens_used,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "model_id": payload.modelId,
        "cost_usd": heartbeat_cost,
        "log_excerpt": payload.logExcerpt,
        "task_id": payload.taskId,
        "created_at": now,
        "updated_at": now,
    }

    if supabase:
        try:
            # Busca company_id do agente (service_role para não depender de JWT do daemon)
            agent_res = supabase.table("agents").select("company_id").eq("id", payload.agentId).execute()
            if agent_res.data:
                row["company_id"] = agent_res.data[0]["company_id"]
            res = supabase.table("heartbeats").insert(row).execute()
            if res.data:
                hb_dict = Heartbeat(**res.data[0]).to_zod_dict()
                company_id = row.get("company_id")
                _accumulate_task_cost(payload.taskId, heartbeat_cost)
                if company_id:
                    await ws_manager.emit_heartbeat(company_id, hb_dict)
                return hb_dict
        except Exception as e:
            logger.error(f"post_heartbeat DB failed: {e}")

    # Fallback mock
    mock_hb = {
        "id": f"hb_mock_{int(datetime.now().timestamp())}",
        "agentId": payload.agentId,
        "taskId": payload.taskId,
        "status": payload.status,
        "tokensUsed": tokens_used,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "cacheReadTokens": cache_read_tokens,
        "modelId": payload.modelId,
        "costUsd": heartbeat_cost,
        "logExcerpt": payload.logExcerpt,
        "createdAt": now.replace("+00:00", "Z"),
    }
    return mock_hb


@app.get("/api/companies/{company_id}/audit-log")
@app.get("/companies/{company_id}/audit-log")
@app.get("/api/audit-log")
async def get_audit(request: Request, company_id: str = None):
    if not supabase: return [AuditLogEntry(**row).to_zod_dict() for row in MOCK_AUDIT]
    
    try:
        client = get_authenticated_client(request.state.token)
        query = client.table("audit_log").select("*").order("created_at", desc=True).limit(100)
        if company_id:
            query = query.eq("company_id", company_id)
            
        res = query.execute()
        return [AuditLogEntry(**row).to_zod_dict() for row in res.data]
    except PostgrestAPIError as e:
        if e.code == "PGRST205":
            logger.warning("vectraclip.audit_log missing; serving mock audit")
            return [AuditLogEntry(**row).to_zod_dict() for row in MOCK_AUDIT if not company_id or row["company_id"] == company_id]
        raise
    except Exception as e:
        logger.error(f"get_audit failed: {e}")
        return [AuditLogEntry(**row).to_zod_dict() for row in MOCK_AUDIT]

def _mock_approvals_payload(company_id: Optional[str]) -> List[dict]:
    """MOCK_APPROVAL até existir `vectraclip.approvals` no Postgres (VEC piloto)."""
    rows = MOCK_APPROVAL
    if company_id:
        rows = [r for r in rows if r.get("company_id") == company_id]
    return [CouncilApproval(**row).to_zod_dict() for row in rows]


@app.get("/api/companies/{company_id}/approvals")
@app.get("/companies/{company_id}/approvals")
@app.get("/api/approvals")
async def get_approvals(request: Request, company_id: str = None):
    if not supabase: return [CouncilApproval(**row).to_zod_dict() for row in MOCK_APPROVAL]
    
    try:
        client = get_authenticated_client(request.state.token)
        query = client.table("approvals").select("*").order("created_at", desc=True)
        if company_id:
            query = query.eq("company_id", company_id)
            
        res = query.execute()
        return [CouncilApproval(**row).to_zod_dict() for row in res.data]
    except PostgrestAPIError as e:
        if e.code == "PGRST205":
            logger.warning("vectraclip.approvals missing; serving mock approvals")
            return [CouncilApproval(**row).to_zod_dict() for row in MOCK_APPROVAL if not company_id or row["company_id"] == company_id]
        raise
    except Exception as e:
        logger.error(f"get_approvals failed: {e}")
        return [CouncilApproval(**row).to_zod_dict() for row in MOCK_APPROVAL]

# === Operações sobre item ===

@app.get("/api/agents/{agent_id}")
async def get_agent_endpoint(request: Request, agent_id: str):
    if not supabase: return next((a for a in MOCK_AGENTS if a["id"] == agent_id), MOCK_AGENTS[0])
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("agents").select("*").eq("id", agent_id).execute()
        if not res.data: raise HTTPException(404, "Target Agent Not Found")
        return Agent(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"get_agent failed: {e}")
        raise HTTPException(500, str(e))


def _request_company_id(request: Request) -> Optional[str]:
    return getattr(request.state, "company_id", None)


def _dispatch_host_allowlist() -> List[str]:
    raw = os.getenv("DISPATCH_URL_HOST_ALLOWLIST", "").strip()
    if raw:
        return [p.strip() for p in raw.split(",") if p.strip()]
    # Default seguro para MVP: Supabase Edge Functions + localhost (dev).
    return ["*.supabase.co", "localhost", "127.0.0.1"]


def _host_matches_allowlist(host: str, patterns: List[str]) -> bool:
    h = (host or "").lower().strip().strip(".")
    if not h:
        return False
    for p in patterns:
        pat = (p or "").lower().strip()
        if not pat:
            continue
        if fnmatch.fnmatch(h, pat):
            return True
    return False


def _validate_function_url(function_url: Optional[str]) -> str:
    if not function_url:
        raise HTTPException(status_code=400, detail="function_url_required")
    try:
        u = urlparse(function_url)
    except Exception:
        raise HTTPException(status_code=400, detail="function_url_invalid")

    if u.scheme not in ("https", "http"):
        raise HTTPException(status_code=400, detail="function_url_scheme_invalid")
    if not u.netloc:
        raise HTTPException(status_code=400, detail="function_url_host_missing")

    if not _host_matches_allowlist(u.hostname or "", _dispatch_host_allowlist()):
        raise HTTPException(status_code=400, detail="function_url_host_not_allowed")

    return function_url


def _validate_execution_setup_payload(
    *,
    execution_mode: str,
    trigger_config: Dict[str, Any],
    function_url: Optional[str],
) -> None:
    if execution_mode == "CRON":
        cron = (trigger_config or {}).get("cron")
        tz = (trigger_config or {}).get("timezone")
        if not cron or not isinstance(cron, str):
            raise HTTPException(status_code=400, detail="cron_required_in_trigger_config")
        if not tz or not isinstance(tz, str):
            raise HTTPException(status_code=400, detail="timezone_required_in_trigger_config")
    if execution_mode == "TRIGGER":
        event_type = (trigger_config or {}).get("eventType") or (trigger_config or {}).get(
            "event_type"
        )
        if not event_type or not isinstance(event_type, str):
            raise HTTPException(status_code=400, detail="event_type_required_in_trigger_config")

    # Se existe URL, ela precisa passar no allowlist (mesmo em REALTIME).
    if function_url:
        _validate_function_url(function_url)


def _resolve_dispatch_secret(auth_secret_ref: Optional[str]) -> Optional[str]:
    if not auth_secret_ref:
        return None
    ref = auth_secret_ref.strip()
    if not ref:
        return None
    if ref.lower().startswith("env:"):
        key = ref.split(":", 1)[1].strip()
        return os.getenv(key)
    # Convenção: `DISPATCH_SECRET__<REF>` (ref em UPPER_SNAKE)
    env_key = f"DISPATCH_SECRET__{ref.upper()}"
    return os.getenv(env_key)


def _chronos_log_dispatch_event(payload: Dict[str, Any]) -> None:
    """
    Hook mínimo de observabilidade (Chronos). Não persiste ainda se não houver tabela dedicada;
    structured log permite ingestão futura sem mudar o call-site.
    """
    try:
        logger.info("chronos.dispatch %s", payload)
    except Exception:
        # logging não deve derrubar dispatch
        pass


# -----------------------------------------------------------------------------
# Adapters & Connectors (VEC-242 / VEC-201)
# -----------------------------------------------------------------------------

class NewAdapterInput(BaseModel):
    slug: str
    displayName: str
    provider: str

class UpdateAdapterInput(BaseModel):
    displayName: Optional[str] = None
    provider: Optional[str] = None
    isActive: Optional[bool] = None

class NewAdapterFieldInput(BaseModel):
    fieldKey: str
    fieldLabel: str
    fieldType: Literal["text", "textarea", "number", "boolean", "select", "multiselect", "file_upload", "secret"]
    isRequired: bool
    sortOrder: int = 10

class UpdateAdapterFieldInput(BaseModel):
    fieldLabel: Optional[str] = None
    fieldType: Optional[str] = None
    isRequired: Optional[bool] = None
    sortOrder: Optional[int] = None
    isActive: Optional[bool] = None


@app.get("/api/companies/{company_id}/adapters")
@app.get("/companies/{company_id}/adapters")
async def list_adapters(request: Request, company_id: str):
    if not supabase:
        return [
            a
            for a in MOCK_ADAPTERS
            if a.get("companyId") == company_id and a.get("isActive", True)
        ]

    try:
        caller_company = _request_company_id(request)
        if caller_company and caller_company != company_id:
            raise HTTPException(status_code=403, detail="cross_company_forbidden")

        client = get_authenticated_client(request.state.token)
        res = (
            client.table("adapter_catalog")
            .select("*")
            .eq("company_id", company_id)
            .eq("is_active", True)
            .order("slug")
            .execute()
        )
        return [AdapterCatalogItem(**row).to_zod_dict() for row in (res.data or [])]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"list_adapters failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")


@app.post("/api/companies/{company_id}/adapters")
@app.post("/companies/{company_id}/adapters")
async def create_adapter(request: Request, company_id: str, payload: NewAdapterInput):
    row = {
        "company_id": company_id,
        "slug": payload.slug,
        "display_name": payload.displayName,
        "provider": payload.provider,
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if not supabase:
        new_item = row.copy()
        new_item["id"] = f"adp_tmp_{int(datetime.now().timestamp())}"
        # Convert to camelCase for mock parity
        new_item["companyId"] = new_item.pop("company_id")
        new_item["displayName"] = new_item.pop("display_name")
        new_item["isActive"] = new_item.pop("is_active")
        new_item["createdAt"] = new_item.pop("created_at")
        new_item["updatedAt"] = new_item.pop("updated_at")
        MOCK_ADAPTERS.append(new_item)
        return new_item

    try:
        res = supabase.table("adapter_catalog").insert(row).execute()
        if not res.data:
            raise HTTPException(status_code=500, detail="insert_failed")
        return AdapterCatalogItem(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"create_adapter failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")


@app.put("/api/adapters/{adapter_id}")
@app.put("/adapters/{adapter_id}")
async def update_adapter(request: Request, adapter_id: str, payload: UpdateAdapterInput):
    update_data = {}
    if payload.displayName is not None: update_data["display_name"] = payload.displayName
    if payload.provider is not None: update_data["provider"] = payload.provider
    if payload.isActive is not None: update_data["is_active"] = payload.isActive
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    if not supabase:
        idx = next((i for i, a in enumerate(MOCK_ADAPTERS) if a["id"] == adapter_id), -1)
        if idx == -1: raise HTTPException(404)
        MOCK_ADAPTERS[idx].update({k.replace("_", ""): v for k, v in update_data.items()})
        return MOCK_ADAPTERS[idx]

    try:
        res = supabase.table("adapter_catalog").update(update_data).eq("id", adapter_id).execute()
        if not res.data: raise HTTPException(404)
        return AdapterCatalogItem(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"update_adapter failed: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/adapters/{adapter_id}/fields")
@app.get("/adapters/{adapter_id}/fields")
async def list_adapter_fields(request: Request, adapter_id: str):
    if not supabase:
        return [
            f
            for f in MOCK_ADAPTER_FIELDS
            if f.get("adapterId") == adapter_id and f.get("isActive", True)
        ]

    try:
        caller_company = _request_company_id(request)
        client = get_authenticated_client(request.state.token)

        adapter_res = (
            client.table("adapter_catalog")
            .select("id,company_id")
            .eq("id", adapter_id)
            .limit(1)
            .execute()
        )
        if not adapter_res.data:
            raise HTTPException(status_code=404, detail="adapter_not_found")

        adapter_company = adapter_res.data[0].get("company_id")
        if caller_company and adapter_company and caller_company != adapter_company:
            raise HTTPException(status_code=403, detail="cross_company_forbidden")

        res = (
            client.table("adapter_field_definitions")
            .select("*")
            .eq("adapter_id", adapter_id)
            .eq("is_active", True)
            .order("sort_order")
            .execute()
        )
        return [AdapterFieldDefinition(**row).to_zod_dict() for row in (res.data or [])]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"list_adapter_fields failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")


@app.post("/api/adapters/{adapter_id}/fields")
@app.post("/adapters/{adapter_id}/fields")
async def create_adapter_field(request: Request, adapter_id: str, payload: NewAdapterFieldInput):
    # Precisamos saber o company_id do adapter
    if not supabase:
        adapter = next((a for a in MOCK_ADAPTERS if a["id"] == adapter_id), None)
        company_id = adapter["companyId"] if adapter else "c0000000-0000-4000-8000-000000000001"
    else:
        res = supabase.table("adapter_catalog").select("company_id").eq("id", adapter_id).single().execute()
        company_id = res.data["company_id"]

    row = {
        "company_id": company_id,
        "adapter_id": adapter_id,
        "field_key": payload.fieldKey,
        "field_label": payload.fieldLabel,
        "field_type": payload.fieldType,
        "is_required": payload.isRequired,
        "sort_order": payload.sortOrder,
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if not supabase:
        new_field = row.copy()
        new_field["id"] = f"fld_tmp_{int(datetime.now().timestamp())}"
        # CamelCase sync
        new_field["companyId"] = new_field.pop("company_id")
        new_field["adapterId"] = new_field.pop("adapter_id")
        new_field["fieldKey"] = new_field.pop("field_key")
        new_field["fieldLabel"] = new_field.pop("field_label")
        new_field["fieldType"] = new_field.pop("field_type")
        new_field["isRequired"] = new_field.pop("is_required")
        new_field["sortOrder"] = new_field.pop("sort_order")
        new_field["isActive"] = new_field.pop("is_active")
        new_field["createdAt"] = new_field.pop("created_at")
        new_field["updatedAt"] = new_field.pop("updated_at")
        MOCK_ADAPTER_FIELDS.append(new_field)
        return new_field

    try:
        res = supabase.table("adapter_field_definitions").insert(row).execute()
        return AdapterFieldDefinition(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"create_field failed: {e}")
        raise HTTPException(500, str(e))


@app.put("/api/adapters/fields/{field_id}")
@app.put("/adapters/fields/{field_id}")
async def update_adapter_field(request: Request, field_id: str, payload: UpdateAdapterFieldInput):
    update_data = {}
    if payload.fieldLabel is not None: update_data["field_label"] = payload.fieldLabel
    if payload.fieldType is not None: update_data["field_type"] = payload.fieldType
    if payload.isRequired is not None: update_data["is_required"] = payload.isRequired
    if payload.sortOrder is not None: update_data["sort_order"] = payload.sortOrder
    if payload.isActive is not None: update_data["is_active"] = payload.isActive
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    if not supabase:
        idx = next((i for i, f in enumerate(MOCK_ADAPTER_FIELDS) if f["id"] == field_id), -1)
        if idx == -1: raise HTTPException(404)
        MOCK_ADAPTER_FIELDS[idx].update({k.replace("_", ""): v for k, v in update_data.items()})
        return MOCK_ADAPTER_FIELDS[idx]

    try:
        res = supabase.table("adapter_field_definitions").update(update_data).eq("id", field_id).execute()
        if not res.data: raise HTTPException(404)
        return AdapterFieldDefinition(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"update_field failed: {e}")
        raise HTTPException(500, str(e))


@app.delete("/api/adapters/fields/{field_id}")
@app.delete("/adapters/fields/{field_id}")
async def delete_adapter_field(request: Request, field_id: str):
    # Soft delete (isActive = False)
    if not supabase:
        idx = next((i for i, f in enumerate(MOCK_ADAPTER_FIELDS) if f["id"] == field_id), -1)
        if idx != -1: MOCK_ADAPTER_FIELDS[idx]["isActive"] = False
        return {"success": True}

    try:
        supabase.table("adapter_field_definitions").update({"is_active": False}).eq("id", field_id).execute()
        return {"success": True}
    except Exception as e:
        logger.error(f"delete_field failed: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/companies/{company_id}/routines")
@app.get("/companies/{company_id}/routines")
async def list_routines(request: Request, company_id: str):
    if not supabase:
        return [r for r in MOCK_ROUTINES if r.get("companyId") == company_id]

    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("routines").select("*").eq("company_id", company_id).execute()
        return [Routine(**row).to_zod_dict() for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_routines failed: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/companies/{company_id}/routines")
@app.post("/companies/{company_id}/routines")
async def create_routine(request: Request, company_id: str, payload: Dict[str, Any]):
    # Payload raw para flexibilidade de triggers
    row = {
        "company_id": company_id,
        "name": payload.get("name"),
        "status": "active",
        "schedule": payload.get("schedule"),
        "agent_id": payload.get("agentId"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if not supabase:
        new_rot = row.copy()
        new_rot["id"] = f"rot_tmp_{int(datetime.now().timestamp())}"
        new_rot["companyId"] = new_rot.pop("company_id")
        new_rot["createdAt"] = new_rot.pop("created_at")
        MOCK_ROUTINES.append(new_rot)
        return new_rot

    try:
        res = supabase.table("routines").insert(row).execute()
        return Routine(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"create_routine failed: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/agents/{agent_id}/adapter-config")
@app.get("/agents/{agent_id}/adapter-config")
async def get_agent_adapter_config(request: Request, agent_id: str):
    if not supabase:
        row = next((r for r in MOCK_AGENT_ADAPTER_CONFIGS if r.get("agentId") == agent_id), None)
        if not row:
            raise HTTPException(status_code=404, detail="agent_adapter_config_not_found")
        return row

    try:
        caller_company = _request_company_id(request)
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("agent_adapter_configs")
            .select("*")
            .eq("agent_id", agent_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="agent_adapter_config_not_found")
        row = res.data[0]
        if caller_company and row.get("company_id") and row.get("company_id") != caller_company:
            raise HTTPException(status_code=403, detail="cross_company_forbidden")
        return AgentAdapterConfig(**row).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_agent_adapter_config failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")


class UpdateAgentAdapterConfigInput(BaseModel):
    adapterId: str
    fieldValuesJson: Dict[str, Any] = Field(default_factory=dict)
    isActive: Optional[bool] = True


@app.put("/api/agents/{agent_id}/adapter-config")
@app.put("/agents/{agent_id}/adapter-config")
async def put_agent_adapter_config(
    request: Request,
    agent_id: str,
    payload: UpdateAgentAdapterConfigInput,
):
    now_iso = datetime.now(timezone.utc).isoformat()
    if not supabase:
        global MOCK_AGENT_ADAPTER_CONFIGS
        existing = next((r for r in MOCK_AGENT_ADAPTER_CONFIGS if r.get("agentId") == agent_id), None)
        if existing:
            existing["adapterId"] = payload.adapterId
            existing["fieldValuesJson"] = payload.fieldValuesJson
            existing["isActive"] = bool(payload.isActive)
            existing["updatedAt"] = now_iso.replace("+00:00", "Z")
            return existing

        new_row = {
            "id": f"cfg_tmp_{int(datetime.now().timestamp())}",
            "companyId": MOCK_USER["companyId"],
            "agentId": agent_id,
            "adapterId": payload.adapterId,
            "fieldValuesJson": payload.fieldValuesJson,
            "isActive": bool(payload.isActive),
            "createdAt": now_iso.replace("+00:00", "Z"),
            "updatedAt": now_iso.replace("+00:00", "Z"),
        }
        MOCK_AGENT_ADAPTER_CONFIGS.append(new_row)
        return new_row

    try:
        caller_company = _request_company_id(request)
        # service_role para mutação consistente; validações de tenant são explícitas.
        agent_row = (
            supabase.table("agents")
            .select("id,company_id")
            .eq("id", agent_id)
            .limit(1)
            .execute()
        )
        if not agent_row.data:
            raise HTTPException(status_code=404, detail="target_agent_not_found")
        company_id = agent_row.data[0].get("company_id")
        if caller_company and company_id and caller_company != company_id:
            raise HTTPException(status_code=403, detail="cross_company_forbidden")

        adapter_row = (
            supabase.table("adapter_catalog")
            .select("id,company_id,is_active")
            .eq("id", payload.adapterId)
            .limit(1)
            .execute()
        )
        if not adapter_row.data:
            raise HTTPException(status_code=404, detail="adapter_not_found")
        adapter_company = adapter_row.data[0].get("company_id")
        if company_id != adapter_company:
            raise HTTPException(status_code=400, detail="adapter_company_mismatch")

        existing = (
            supabase.table("agent_adapter_configs")
            .select("id")
            .eq("agent_id", agent_id)
            .limit(1)
            .execute()
        )
        row_payload = {
            "company_id": company_id,
            "agent_id": agent_id,
            "adapter_id": payload.adapterId,
            "field_values_json": payload.fieldValuesJson,
            "is_active": bool(payload.isActive),
            "updated_at": now_iso,
        }
        if existing.data:
            res = (
                supabase.table("agent_adapter_configs")
                .update(row_payload)
                .eq("agent_id", agent_id)
                .execute()
            )
        else:
            row_payload["created_at"] = now_iso
            res = supabase.table("agent_adapter_configs").insert(row_payload).execute()

        if not res.data:
            raise HTTPException(status_code=500, detail="agent_adapter_config_upsert_empty")
        return AgentAdapterConfig(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"put_agent_adapter_config failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")


class AgentExecutionSetupInput(BaseModel):
    executionMode: Literal["REALTIME", "CRON", "TRIGGER"]
    triggerConfig: Dict[str, Any] = Field(default_factory=dict)
    functionUrl: Optional[str] = None
    authSecretRef: Optional[str] = None
    authHeaderName: Optional[str] = None
    isActive: Optional[bool] = True

    class Config:
        allow_population_by_field_name = True
        extra = "ignore"

    @validator("functionUrl", "authSecretRef", "authHeaderName", pre=True)
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v


class TaskDispatchInput(BaseModel):
    taskId: str
    idempotencyKey: Optional[str] = None
    attempt: int = 1

    class Config:
        allow_population_by_field_name = True
        extra = "ignore"


@app.get("/api/agents/{agent_id}/execution-config")
@app.get("/agents/{agent_id}/execution-config")
async def get_agent_execution_config(request: Request, agent_id: str):
    if not supabase:
        row = next((r for r in MOCK_AGENT_EXECUTION_CONFIGS if r.get("agentId") == agent_id), None)
        if not row:
            raise HTTPException(status_code=404, detail="agent_execution_config_not_found")
        return row

    try:
        caller_company = _request_company_id(request)
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("agent_execution_configs")
            .select("*")
            .eq("agent_id", agent_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="agent_execution_config_not_found")
        row = res.data[0]
        if caller_company and row.get("company_id") and row.get("company_id") != caller_company:
            raise HTTPException(status_code=403, detail="cross_company_forbidden")
        return AgentExecutionConfig(**row).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_agent_execution_config failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")


@app.put("/api/agents/{agent_id}/execution-setup")
@app.put("/agents/{agent_id}/execution-setup")
async def put_agent_execution_setup(request: Request, agent_id: str, payload: AgentExecutionSetupInput):
    now_iso = datetime.now(timezone.utc).isoformat()

    _validate_execution_setup_payload(
        execution_mode=payload.executionMode,
        trigger_config=payload.triggerConfig or {},
        function_url=payload.functionUrl,
    )

    if not supabase:
        global MOCK_AGENT_EXECUTION_CONFIGS
        existing = next((r for r in MOCK_AGENT_EXECUTION_CONFIGS if r.get("agentId") == agent_id), None)
        if existing:
            existing["executionMode"] = payload.executionMode
            existing["triggerConfig"] = payload.triggerConfig or {}
            existing["functionUrl"] = payload.functionUrl
            existing["authSecretRef"] = payload.authSecretRef
            existing["authHeaderName"] = payload.authHeaderName
            existing["isActive"] = bool(payload.isActive)
            existing["updatedAt"] = now_iso.replace("+00:00", "Z")
            return existing

        new_row = {
            "id": f"exe_tmp_{int(datetime.now().timestamp())}",
            "companyId": MOCK_USER["companyId"],
            "agentId": agent_id,
            "executionMode": payload.executionMode,
            "triggerConfig": payload.triggerConfig or {},
            "functionUrl": payload.functionUrl,
            "authSecretRef": payload.authSecretRef,
            "authHeaderName": payload.authHeaderName,
            "isActive": bool(payload.isActive),
            "createdAt": now_iso.replace("+00:00", "Z"),
            "updatedAt": now_iso.replace("+00:00", "Z"),
        }
        MOCK_AGENT_EXECUTION_CONFIGS.append(new_row)
        return new_row

    try:
        caller_company = _request_company_id(request)
        agent_row = (
            supabase.table("agents")
            .select("id,company_id")
            .eq("id", agent_id)
            .limit(1)
            .execute()
        )
        if not agent_row.data:
            raise HTTPException(status_code=404, detail="target_agent_not_found")
        company_id = agent_row.data[0].get("company_id")
        if caller_company and company_id and caller_company != company_id:
            raise HTTPException(status_code=403, detail="cross_company_forbidden")

        existing = (
            supabase.table("agent_execution_configs")
            .select("id")
            .eq("agent_id", agent_id)
            .limit(1)
            .execute()
        )
        row_payload: Dict[str, Any] = {
            "company_id": company_id,
            "agent_id": agent_id,
            "execution_mode": payload.executionMode,
            "trigger_config": payload.triggerConfig or {},
            "function_url": payload.functionUrl,
            "auth_secret_ref": payload.authSecretRef,
            "auth_header_name": payload.authHeaderName,
            "is_active": bool(payload.isActive),
            "updated_at": now_iso,
        }
        if existing.data:
            res = (
                supabase.table("agent_execution_configs")
                .update(row_payload)
                .eq("agent_id", agent_id)
                .execute()
            )
        else:
            row_payload["created_at"] = now_iso
            res = supabase.table("agent_execution_configs").insert(row_payload).execute()

        if not res.data:
            raise HTTPException(status_code=500, detail="agent_execution_config_upsert_empty")
        return AgentExecutionConfig(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"put_agent_execution_setup failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")


def _dispatch_internal_authorized(request: Request) -> bool:
    expected = os.getenv("MORPHEUS_DISPATCH_TOKEN", "").strip()
    if not expected:
        return False
    got = (request.headers.get("x-internal-token") or "").strip()
    return bool(got) and got == expected


@app.post("/api/tasks/dispatch")
@app.post("/tasks/dispatch")
async def post_task_dispatch(request: Request, payload: TaskDispatchInput):
    started = datetime.now(timezone.utc)
    internal_ok = _dispatch_internal_authorized(request)
    caller_company = _request_company_id(request)

    if not internal_ok:
        # Modo dev/MVP: permite disparo autenticado como usuário, mas exige alinhamento de tenant.
        if not caller_company:
            raise HTTPException(status_code=401, detail="dispatch_unauthorized")

    if not supabase:
        return {
            "ok": True,
            "mode": "mock",
            "taskId": payload.taskId,
            "internal": internal_ok,
        }

    try:
        if payload.idempotencyKey:
            cache = getattr(app.state, "dispatch_idempotency_cache", None)
            if cache is None:
                cache = {}
                app.state.dispatch_idempotency_cache = cache
            cache_key = f"{caller_company or 'internal'}:{payload.taskId}:{payload.idempotencyKey}"
            cached = cache.get(cache_key)
            if isinstance(cached, dict) and cached.get("expires_at"):
                exp = cached["expires_at"]
                if isinstance(exp, datetime) and exp > datetime.now(timezone.utc):
                    return cached.get("response", {"ok": True, "deduped": True})

        task_res = (
            supabase.table("tasks")
            .select("id,company_id,assigned_to_agent_id,title,status")
            .eq("id", payload.taskId)
            .limit(1)
            .execute()
        )
        if not task_res.data:
            raise HTTPException(status_code=404, detail="task_not_found")
        task = task_res.data[0]
        task_company = task.get("company_id")
        agent_id = task.get("assigned_to_agent_id")
        if not agent_id:
            raise HTTPException(status_code=400, detail="task_missing_assignee")

        if not internal_ok:
            if not caller_company or caller_company != task_company:
                raise HTTPException(status_code=403, detail="cross_company_forbidden")

        adapter_cfg: Optional[Dict[str, Any]] = None
        try:
            ac_res = (
                supabase.table("agent_adapter_configs")
                .select("adapter_id,field_values_json,is_active")
                .eq("agent_id", agent_id)
                .limit(1)
                .execute()
            )
            if ac_res.data:
                adapter_cfg = ac_res.data[0]
        except PostgrestAPIError:
            adapter_cfg = None
        except Exception:
            adapter_cfg = None

        exec_res = (
            supabase.table("agent_execution_configs")
            .select("*")
            .eq("agent_id", agent_id)
            .limit(1)
            .execute()
        )
        exec_row = exec_res.data[0] if exec_res.data else None
        function_url = (exec_row or {}).get("function_url")
        if not function_url:
            duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            _chronos_log_dispatch_event(
                {
                    "event": "dispatch.skipped",
                    "reason": "missing_function_url",
                    "companyId": task_company,
                    "agentId": agent_id,
                    "taskId": payload.taskId,
                    "durationMs": duration_ms,
                }
            )
            response = {"ok": True, "dispatched": False, "reason": "missing_function_url"}
            if payload.idempotencyKey:
                cache = getattr(app.state, "dispatch_idempotency_cache", None)
                if isinstance(cache, dict):
                    cache_key = f"{caller_company or 'internal'}:{payload.taskId}:{payload.idempotencyKey}"
                    cache[cache_key] = {
                        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
                        "response": response,
                    }
            return response

        function_url = _validate_function_url(str(function_url))

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        auth_header_name = (exec_row or {}).get("auth_header_name") or "Authorization"
        secret = _resolve_dispatch_secret((exec_row or {}).get("auth_secret_ref"))
        if secret:
            headers[str(auth_header_name)] = str(secret)

        body = {
            "type": "vectraclip.task.dispatch",
            "task": task,
            "adapterConfig": adapter_cfg,
            "executionConfig": exec_row,
            "attempt": payload.attempt,
            "idempotencyKey": payload.idempotencyKey,
        }

        resp = requests.post(
            function_url,
            json=body,
            headers=headers,
            timeout=float(os.getenv("DISPATCH_HTTP_TIMEOUT_S", "15")),
            allow_redirects=False,
        )
        duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        _chronos_log_dispatch_event(
            {
                "event": "dispatch.http",
                "companyId": task_company,
                "agentId": agent_id,
                "taskId": payload.taskId,
                "httpStatus": resp.status_code,
                "durationMs": duration_ms,
                "responseBytes": len(resp.content or b""),
            }
        )

        response = {
            "ok": resp.ok,
            "dispatched": True,
            "httpStatus": resp.status_code,
            "durationMs": duration_ms,
        }
        if payload.idempotencyKey:
            cache = getattr(app.state, "dispatch_idempotency_cache", None)
            if isinstance(cache, dict):
                cache_key = f"{caller_company or 'internal'}:{payload.taskId}:{payload.idempotencyKey}"
                cache[cache_key] = {
                    "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
                    "response": response,
                }
        return response
    except HTTPException:
        raise
    except requests.RequestException as e:
        duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        _chronos_log_dispatch_event(
            {
                "event": "dispatch.http_error",
                "taskId": payload.taskId,
                "durationMs": duration_ms,
                "error": str(e),
            }
        )
        raise HTTPException(status_code=502, detail="dispatch_upstream_failed")
    except Exception as e:
        logger.error(f"post_task_dispatch failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

async def supabase_update_agent_status(token: str, agent_id: str, update: Union[str, Dict[str, Any]]):
    if isinstance(update, str):
        patch = {"status": update}
    else:
        patch = update

    new_status = patch.get("status")
    # Agente sem CPU consumindo = burn zero.
    # Vale para os dois terminais: paused (pausa humana) e offline (kill lógico).
    if new_status in (AgentStatus.PAUSED, AgentStatus.OFFLINE):
        patch["current_burn_rate"] = 0

    if not supabase:
        a = next((a for a in MOCK_AGENTS if a["id"] == agent_id), MOCK_AGENTS[0]).copy()
        for k, v in patch.items():
            if k == "current_burn_rate": a["currentBurnRate"] = v
            elif k == "company_id": a["companyId"] = v
            elif k == "token_budget": a["tokenBudget"] = v
            elif k == "adapter_type": a["adapterType"] = v
            elif k == "reports_to_id": a["reportsToId"] = v
            else: a[k] = v
        return a

    client = get_authenticated_client(token)
    res = client.table("agents").update(patch).eq("id", agent_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Target Agent Not Found")
    agent_dict = Agent(**res.data[0]).to_zod_dict()
    company_id = res.data[0].get("company_id")
    if company_id:
        await ws_manager.emit_agent_updated(company_id, agent_dict)
    return agent_dict

@app.post("/api/agents/{agent_id}/pause")
@app.post("/agents/{agent_id}/pause")
async def pause_agent(agent_id: str, request: Request):
    return await supabase_update_agent_status(request.state.token, agent_id, AgentStatus.PAUSED)


@app.post("/api/agents/{agent_id}/resume")
@app.post("/agents/{agent_id}/resume")
async def resume_agent(agent_id: str, request: Request):
    return await supabase_update_agent_status(request.state.token, agent_id, AgentStatus.IDLE)


@app.post("/api/agents/{agent_id}/kill")
@app.post("/agents/{agent_id}/kill")
async def kill_agent(agent_id: str, request: Request):
    return await supabase_update_agent_status(request.state.token, agent_id, AgentStatus.OFFLINE)


@app.patch("/api/agents/{agent_id}")
@app.patch("/agents/{agent_id}")
async def patch_agent(agent_id: str, patch: AgentPatch, request: Request):
    # Só envia o que o cliente mandou (partial update verdadeiro).
    payload = patch.dict(by_alias=False, exclude_none=True)
    if not payload:
        raise HTTPException(status_code=400, detail="empty_patch")
    
    if not supabase:
        return await supabase_update_agent_status(request.state.token, agent_id, payload)

    client = get_authenticated_client(request.state.token)
    res = client.table("agents").update(payload).eq("id", agent_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Target Agent Not Found")
    agent_dict = Agent(**res.data[0]).to_zod_dict()
    company_id = res.data[0].get("company_id")
    if company_id:
        await ws_manager.emit_agent_updated(company_id, agent_dict)
    return agent_dict


@app.delete("/api/agents/{agent_id}")
@app.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, request: Request):
    """
    VEC-224 - DELETE de agent para validação CRUD humana.
    """
    if not supabase:
        global MOCK_AGENTS
        before = len(MOCK_AGENTS)
        MOCK_AGENTS = [a for a in MOCK_AGENTS if a.get("id") != agent_id]
        if len(MOCK_AGENTS) == before:
            raise HTTPException(status_code=404, detail="Target Agent Not Found")
        return Response(status_code=204)

    try:
        client = get_authenticated_client(request.state.token)
        check = client.table("agents").select("id,company_id").eq("id", agent_id).execute()
        if not check.data:
            raise HTTPException(status_code=404, detail="Target Agent Not Found")
        company_id = check.data[0].get("company_id")
        client.table("agents").delete().eq("id", agent_id).execute()
        if company_id:
            await ws_manager.emit_agent_updated(company_id, {"id": agent_id, "deleted": True})
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_agent failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")

@app.get("/api/tasks/{task_id}")
async def get_task_endpoint(request: Request, task_id: str):
    if not supabase: return next((t for t in MOCK_TASKS if t["id"] == task_id), MOCK_TASKS[0])
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("tasks").select("*").eq("id", task_id).execute()
        if not res.data: raise HTTPException(404, "Target Task Not Found")
        return Task(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"get_task failed: {e}")
        raise HTTPException(500, str(e))


@app.patch("/api/tasks/{task_id}")
async def patch_task(request: Request, task_id: str, patch: UpdateTaskInput):
    """
    VEC-182 — atualização parcial JSON; corpo = UpdateTaskInput (camelCase no wire).
    """
    payload = patch.dict(exclude_unset=True, by_alias=False)
    if not payload:
        raise HTTPException(status_code=400, detail="empty_patch")

    payload["updated_at"] = datetime.now(timezone.utc).isoformat()

    if not supabase:
        row = next((t for t in MOCK_TASKS if t["id"] == task_id), None)
        if row is None:
            raise HTTPException(status_code=404, detail="Target Task Not Found")
        for k, v in _task_patch_payload_to_camel(
            {k: v for k, v in payload.items() if k != "updated_at"}
        ).items():
            row[k] = v
        if "updatedAt" not in row:
            row["updatedAt"] = row.get("createdAt", payload["updated_at"])
        else:
            row["updatedAt"] = payload["updated_at"].replace("+00:00", "Z")
        return row

    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("tasks").update(payload).eq("id", task_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Target Task Not Found")
        task_dict = Task(**res.data[0]).to_zod_dict()
        company_id = res.data[0].get("company_id")
        if company_id:
            await ws_manager.emit_task_updated(company_id, task_dict)
        return task_dict
    except HTTPException:
        raise
    except Exception as e:
        # VEC-188 — self-healing
        from src.services.brain.db_failover import build_failover_result
        fr = build_failover_result(
            exc=e,
            operation="update:tasks",
            table="tasks",
            original_payload=payload,
            retry_hint=f"PATCH /api/tasks/{task_id}",
        )
        logger.error("patch_task DB failed [%s]: %s", fr.error_category, fr.error_detail)
        raise HTTPException(status_code=fr.http_status, detail=fr.to_http_detail())


@app.delete("/api/tasks/{task_id}")
@app.delete("/tasks/{task_id}")
async def delete_task(request: Request, task_id: str):
    """
    VEC-224 - DELETE de task para validação CRUD humana.
    """
    if not supabase:
        global MOCK_TASKS
        before = len(MOCK_TASKS)
        MOCK_TASKS = [t for t in MOCK_TASKS if t.get("id") != task_id]
        if len(MOCK_TASKS) == before:
            raise HTTPException(status_code=404, detail="Target Task Not Found")
        return Response(status_code=204)

    try:
        client = get_authenticated_client(request.state.token)
        check = client.table("tasks").select("id,company_id").eq("id", task_id).execute()
        if not check.data:
            raise HTTPException(status_code=404, detail="Target Task Not Found")
        company_id = check.data[0].get("company_id")
        client.table("tasks").delete().eq("id", task_id).execute()
        if company_id:
            await ws_manager.emit_task_updated(company_id, {"id": task_id, "deleted": True})
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_task failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")


@app.post("/api/tasks/{task_id}/claim")
async def claim_task(request: Request, task_id: str):
    if not supabase: return MOCK_TASKS[0]
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("tasks").update({
            "status": "in_progress",
            "claimed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", task_id).execute()
        if not res.data: raise HTTPException(404, "Target Task Not Found")
        task_dict = Task(**res.data[0]).to_zod_dict()
        company_id = res.data[0].get("company_id")
        if company_id:
            await ws_manager.emit_task_updated(company_id, task_dict)
        return task_dict
    except Exception as e:
        logger.error(f"claim_task failed: {e}")
        raise HTTPException(500, str(e))

# =====================================================================
# Heartbeat Doctor Endpoints (VEC-199 + VEC-199b)
# =====================================================================

def _resolve_company_id(request: Request) -> str:
    """Retorna company_id do JWT; fallback para MOCK_USER em dev sem claim."""
    return getattr(request.state, "company_id", None) or MOCK_USER["companyId"]


def _incident_to_zod(row: Union[dict, Incident]) -> dict:
    """Normaliza dict DB (snake) ou Incident para o contrato camelCase do frontend."""
    if isinstance(row, Incident):
        return row.to_zod_dict()
    return Incident(**row).to_zod_dict()


@app.get("/api/incidents")
async def get_incidents(request: Request, status: str = "all", limit: int = 50):
    company_id = _resolve_company_id(request)
    decision_filter = status if status in ("pending_council", "auto_healed") else None

    # DB first
    if supabase:
        try:
            incidents = await incident_store.list_incidents(
                company_id, decision=decision_filter, limit=limit
            )
            return [i.to_zod_dict() for i in incidents]
        except Exception as e:
            logger.warning(f"get_incidents from DB failed: {e}. Falling back to memory.")

    # Memory fallback (ambiente sem Supabase OU falha transitória)
    rows = [i for i in app.state.incidents if i.get("company_id") == company_id]
    if decision_filter:
        rows = [r for r in rows if r.get("decision") == decision_filter]
    return [_incident_to_zod(r) for r in rows[:limit]]


@app.get("/api/incidents/{incident_id}")
async def get_incident(request: Request, incident_id: str):
    """VEC-199b §Fix 3 — retorna 404 limpo quando incidente não existe (antes: 500)."""
    company_id = _resolve_company_id(request)

    if supabase:
        try:
            found = await incident_store.get_incident_by_id(incident_id, company_id)
            if found is not None:
                return found.to_zod_dict()
        except Exception as e:
            logger.warning(f"get_incident DB failed: {e}. Trying memory fallback.")

    mem = next(
        (
            i
            for i in app.state.incidents
            if i.get("id") == incident_id and i.get("company_id") == company_id
        ),
        None,
    )
    if not mem:
        raise HTTPException(status_code=404, detail="incident_not_found")
    return _incident_to_zod(mem)


class ApprovePayload(BaseModel):
    approved: bool
    reason: Optional[str] = "manual review"


@app.post("/api/incidents/{incident_id}/approve")
async def approve_incident(incident_id: str, payload: ApprovePayload, request: Request):
    company_id = _resolve_company_id(request)

    # 1. Buscar incidente (DB → memória).
    incident_row: Optional[dict] = None
    if supabase:
        try:
            found = await incident_store.get_incident_by_id(incident_id, company_id)
            if found is not None:
                incident_row = found.dict()
                incident_row["company_id"] = str(found.company_id)
                incident_row["id"] = str(found.id)
        except Exception as e:
            logger.warning(f"approve_incident fetch failed: {e}")

    if incident_row is None:
        incident_row = next(
            (
                i
                for i in app.state.incidents
                if i.get("id") == incident_id and i.get("company_id") == company_id
            ),
            None,
        )
    if incident_row is None:
        raise HTTPException(status_code=404, detail="incident_not_found")

    if incident_row.get("decision") != "pending_council":
        raise HTTPException(status_code=400, detail="incident_not_pending_council")

    new_decision = "approved" if payload.approved else "rejected"
    resolved_at_iso = datetime.now(timezone.utc).isoformat()

    # 2. Persistir decisão + audit.
    if supabase:
        try:
            await incident_store.update_incident_decision(
                incident_id,
                company_id,
                decision=new_decision,
                resolved=True,
            )
        except Exception as e:
            logger.warning(f"approve_incident update failed: {e}")

    await incident_audit.append_audit(
        incident_id,
        event=incident_audit.EVENT_COUNCIL_APPROVED
        if payload.approved
        else incident_audit.EVENT_COUNCIL_REJECTED,
        actor=str(getattr(request.state, "user_id", "unknown")),
        payload={"reason": payload.reason},
    )

    # 3. Sincronizar cópia em memória (fallback).
    mem_inc = next(
        (i for i in app.state.incidents if i.get("id") == incident_id),
        None,
    )
    if mem_inc:
        mem_inc["decision"] = new_decision
        mem_inc["resolved_at"] = resolved_at_iso

    return {"status": "ok", "decision": new_decision}


@app.post("/api/incidents/{incident_id}/undo")
async def undo_incident(incident_id: str, request: Request):
    """
    VEC-199b §Fix 4 — validar janela de undo.

    Regras:
    - 404 se incidente não existe.
    - 400 se `decision` não é `auto_healed`.
    - 400 se `undo_expires_at` é NULL (severidade LOW não permite undo).
    - 400 se janela expirou (`undo_expires_at` no passado).
    """
    company_id = _resolve_company_id(request)

    # 1. Fetch (DB → memória).
    incident_row: Optional[dict] = None
    if supabase:
        try:
            found = await incident_store.get_incident_by_id(incident_id, company_id)
            if found is not None:
                incident_row = found.dict()
                incident_row["id"] = str(found.id)
                incident_row["company_id"] = str(found.company_id)
                # Manter datetime cru para comparação de janela.
                incident_row["undo_expires_at"] = found.undo_expires_at
        except Exception as e:
            logger.warning(f"undo_incident fetch failed: {e}")

    if incident_row is None:
        incident_row = next(
            (
                i
                for i in app.state.incidents
                if i.get("id") == incident_id and i.get("company_id") == company_id
            ),
            None,
        )
    if incident_row is None:
        raise HTTPException(status_code=404, detail="incident_not_found")

    if incident_row.get("decision") != "auto_healed":
        raise HTTPException(status_code=400, detail="only_auto_healed_can_be_undone")

    # VEC-199b §Fix 4 — janela de undo obrigatória e não expirada.
    undo_expires = incident_row.get("undo_expires_at")
    if not undo_expires:
        raise HTTPException(status_code=400, detail="undo_window_unavailable")

    if isinstance(undo_expires, str):
        try:
            undo_expires_dt = datetime.fromisoformat(
                undo_expires.replace("Z", "+00:00")
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="undo_window_invalid")
    elif isinstance(undo_expires, datetime):
        undo_expires_dt = undo_expires
    else:
        raise HTTPException(status_code=400, detail="undo_window_invalid")

    if undo_expires_dt.tzinfo is None:
        undo_expires_dt = undo_expires_dt.replace(tzinfo=timezone.utc)

    if datetime.now(timezone.utc) > undo_expires_dt:
        raise HTTPException(status_code=400, detail="undo_window_expired")

    # 2. Marca como undone + grava audit (V1: stub sem rollback semântico).
    if supabase:
        try:
            await incident_store.update_incident_decision(
                incident_id,
                company_id,
                decision="undone",
                resolved=True,
            )
        except Exception as e:
            logger.warning(f"undo_incident update failed: {e}")

    await incident_audit.append_audit(
        incident_id,
        event=incident_audit.EVENT_UNDO,
        actor=str(getattr(request.state, "user_id", "unknown")),
        payload={"original_decision": "auto_healed"},
    )

    mem_inc = next(
        (i for i in app.state.incidents if i.get("id") == incident_id),
        None,
    )
    if mem_inc:
        mem_inc["decision"] = "undone"
        mem_inc["resolved_at"] = datetime.now(timezone.utc).isoformat()

    return {"status": "ok", "decision": "undone"}

# =====================================================================
# Test Endpoints (VEC-199 Simulador)
# =====================================================================

class BurnSimPayload(BaseModel):
    burn: float

@app.post("/api/_test/agents/{agent_id}/set-burn")
async def test_set_burn(agent_id: str, payload: BurnSimPayload, request: Request):
    # Update direto via service_role para simular anomalia
    if supabase:
        try:
            # Schema já está fixado no boot (VEC-199b): dropa a reatribuição redundante.
            res = supabase.table("agents").update({"current_burn_rate": payload.burn}).eq("id", agent_id).execute()
            if res.data: return {"status": "ok", "agentId": agent_id, "newBurn": payload.burn}
        except Exception as e:
            logger.warning(f"test_set_burn DB failed: {e}. Using mock fallback.")
    
    # Mock fallback
    for a in MOCK_AGENTS:
        if a["id"] == agent_id:
            a["currentBurnRate"] = payload.burn
            return {"status": "ok", "agentId": agent_id, "newBurn": payload.burn}
            
    raise HTTPException(404, "Agent not found in mocks")

@app.post("/api/tasks/{task_id}/complete")
async def complete_task(request: Request, task_id: str):
    if not supabase: return MOCK_TASKS[0]
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("tasks").update({"status": "done"}).eq("id", task_id).execute()
        if not res.data: raise HTTPException(404, "Target Task Not Found")
        task_dict = Task(**res.data[0]).to_zod_dict()
        company_id = res.data[0].get("company_id")
        if company_id:
            await ws_manager.emit_task_updated(company_id, task_dict)
        return task_dict
    except Exception as e:
        logger.error(f"complete_task failed: {e}")
        raise HTTPException(500, str(e))

def _mock_set_approval_status(approval_id: str, status: str) -> dict:
    for appr in MOCK_APPROVAL:
        if appr.get("id") == approval_id:
            appr["status"] = status
            if status == "approved":
                appr["approved_by_user_id"] = appr.get("approved_by_user_id") or "usr_marcelo"
            elif status == "rejected":
                appr["approved_by_user_id"] = None
            return CouncilApproval(**appr).to_zod_dict()
    raise HTTPException(404, "Approval not found")


async def _set_approval_status(request: Request, approval_id: str, status: str) -> dict:
    if not supabase:
        return _mock_set_approval_status(approval_id, status)

    patch: Dict[str, Any] = {"status": status}
    if status == "rejected":
        patch["approved_by_user_id"] = None

    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("approvals").update(patch).eq("id", approval_id).execute()
        if not res.data:
            raise HTTPException(404, "Target Approval Not Found")
        return CouncilApproval(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except PostgrestAPIError as e:
        if e.code == "PGRST205":
            logger.warning("vectraclip.approvals missing on update; using mock approvals")
            return _mock_set_approval_status(approval_id, status)
        raise HTTPException(500, str(e))
    except Exception as e:
        logger.error(f"set_approval_status failed: {e}")
        # Mantém a UX funcional em ambiente de dev mesmo sem tabela pronta.
        return _mock_set_approval_status(approval_id, status)


@app.post("/api/approvals/{approval_id}/approve")
@app.post("/approvals/{approval_id}/approve")
async def approve_approval(request: Request, approval_id: str):
    return await _set_approval_status(request, approval_id, "approved")


class RejectApprovalInput(BaseModel):
    reason: Optional[str] = None


@app.post("/api/approvals/{approval_id}/reject")
@app.post("/approvals/{approval_id}/reject")
async def reject_approval(
    request: Request,
    approval_id: str,
    payload: Optional[RejectApprovalInput] = None,
):
    _ = payload  # reason é opcional por enquanto; endpoint mantém compatibilidade.
    return await _set_approval_status(request, approval_id, "rejected")

@app.get("/api/health")
async def health_check():
    return {"status": "online", "service": "VectraClaw Agent Engine"}

# =====================================================================
# WebSocket Real-Time Interface (VEC-183)
# =====================================================================
#
# Rota: /ws/companies/{company_id}?token=<jwt>
#
# Auth: JWT via query param `token` (WebSocket API do browser não permite
# headers customizados). Validamos o token com a mesma lógica do middleware
# HTTP. Se o token for inválido ou o company_id do claim divergir do da rota,
# fechamos imediatamente com código 4001.
#
# Eventos emitidos pelo servidor (JSON):
#   { "type": "hello",            "companyId": str }
#   { "type": "heartbeat",        "payload": <Heartbeat camelCase> }
#   { "type": "agent_updated",    "payload": <Agent camelCase> }
#   { "type": "task_updated",     "payload": <Task camelCase> }
#   { "type": "incident_updated", "payload": <Incident camelCase> }
#
# O cliente pode enviar qualquer texto — ignorado (ping keep-alive).


@app.websocket("/ws/companies/{company_id}")
@app.websocket("/api/ws/companies/{company_id}")
async def websocket_companies(
    websocket: WebSocket,
    company_id: str,
    token: Optional[str] = Query(default=None),
):
    # Handshake deve ser concluído antes de qualquer close() —
    # caso contrário o browser nunca recebe o 101 e dispara onerror.
    await websocket.accept()

    # --- Auth ---
    if token:
        try:
            claims = validate_supabase_jwt(token)
            token_company = claims.get("company_id") or claims.get(
                "user_metadata", {}
            ).get("company_id")
            if token_company and token_company != company_id:
                await websocket.close(code=4001, reason="company_mismatch")
                return
        except Exception as exc:
            logger.warning("WS auth failed: %s", exc)
            await websocket.close(code=4001, reason="invalid_token")
            return

    await ws_manager.connect(websocket, company_id)
    await ws_manager.emit_hello(company_id)

    try:
        while True:
            # Mantém a conexão viva; o cliente pode enviar pings de texto.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WS error company=%s: %s", company_id, exc)
    finally:
        ws_manager.disconnect(websocket, company_id)


@app.websocket("/ws")
async def websocket_legacy(websocket: WebSocket):
    """Mantido para compatibilidade; redireciona log para nova rota."""
    await websocket.accept()
    await websocket.send_text(
        '{"type":"error","message":"Use /ws/companies/{company_id}"}'
    )
    await websocket.close(code=4000)

# ---------------------------------------------------------------------------
# VEC-189 – Parity report: GET /api/audit/parity
# ---------------------------------------------------------------------------

@app.get("/api/audit/parity")
async def api_audit_parity(request: Request):
    """
    VEC-189 — Relatório de paridade E2E do VectraClaw backend.

    Executa verificações rápidas (sem escrita) em cada subsistema implementado
    e retorna um mapa de saúde. Útil para validar que todos os endpoints
    respondem corretamente antes de um ciclo E2E.
    """
    company_id = getattr(request.state, "company_id", None)
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company_id": company_id,
        "checks": {},
    }

    # M3 Tools
    try:
        from src.m3_tools import TOOLS_REGISTRY
        report["checks"]["m3_tools"] = {
            "status": "ok",
            "tools": list(TOOLS_REGISTRY.keys()),
        }
    except Exception as e:
        report["checks"]["m3_tools"] = {"status": "error", "detail": str(e)}

    # Brain – System Prompt
    try:
        from src.services.brain.system_prompt import system_prompt_meta
        report["checks"]["system_prompt"] = {"status": "ok", **system_prompt_meta()}
    except Exception as e:
        report["checks"]["system_prompt"] = {"status": "error", "detail": str(e)}

    # Brain – Workflow
    try:
        from src.services.brain.workflow_aduaneiro import WORKFLOW_STEPS
        report["checks"]["workflow_aduaneiro"] = {
            "status": "ok",
            "steps": len(WORKFLOW_STEPS),
            "ids": [s.id for s in WORKFLOW_STEPS],
        }
    except Exception as e:
        report["checks"]["workflow_aduaneiro"] = {"status": "error", "detail": str(e)}

    # DB Failover classifier
    try:
        from src.services.brain.db_failover import _CATEGORIES
        report["checks"]["db_failover"] = {
            "status": "ok",
            "categories": len(_CATEGORIES),
        }
    except Exception as e:
        report["checks"]["db_failover"] = {"status": "error", "detail": str(e)}

    # WhatsApp client config
    try:
        from src.services.whatsapp.meta_client import _phone_number_id, _api_version
        report["checks"]["whatsapp"] = {
            "status": "ok",
            "phone_number_id": _phone_number_id(),
            "api_version": _api_version(),
        }
    except Exception as e:
        report["checks"]["whatsapp"] = {"status": "error", "detail": str(e)}

    # Supabase connectivity
    if supabase:
        try:
            res = supabase.table("agents").select("id").limit(1).execute()
            report["checks"]["supabase"] = {
                "status": "ok",
                "sample_agents": len(res.data),
            }
        except Exception as e:
            report["checks"]["supabase"] = {"status": "error", "detail": str(e)}
    else:
        report["checks"]["supabase"] = {"status": "skipped", "detail": "client not initialized"}

    # WebSocket manager
    try:
        from src.ws_manager import manager as ws_manager_check
        report["checks"]["ws_manager"] = {
            "status": "ok",
            "active_companies": len(ws_manager_check._connections),
        }
    except Exception as e:
        report["checks"]["ws_manager"] = {"status": "error", "detail": str(e)}

    # BL/PL parser
    try:
        from src.services.logistics.bl_pl_parser import parse_pdf_bytes, _BL_PATTERNS
        report["checks"]["bl_pl_parser"] = {
            "status": "ok",
            "bl_fields": list(_BL_PATTERNS.keys()),
        }
    except Exception as e:
        report["checks"]["bl_pl_parser"] = {"status": "error", "detail": str(e)}

    # Heartbeat Doctor store
    try:
        from src.services.heartbeat_doctor.store import INCIDENTS_TABLE
        report["checks"]["heartbeat_doctor"] = {"status": "ok", "incidents_table": INCIDENTS_TABLE}
    except Exception as e:
        report["checks"]["heartbeat_doctor"] = {"status": "error", "detail": str(e)}

    # Summary
    statuses = [v.get("status") for v in report["checks"].values()]
    errors = [k for k, v in report["checks"].items() if v.get("status") == "error"]
    report["summary"] = {
        "total": len(statuses),
        "ok": statuses.count("ok"),
        "error": statuses.count("error"),
        "skipped": statuses.count("skipped"),
        "failed_checks": errors,
        "overall": "healthy" if not errors else "degraded",
    }
    return report


# ---------------------------------------------------------------------------
# VEC-187 – Brain endpoints: system prompt + workflow aduaneiro
# ---------------------------------------------------------------------------

@app.get("/api/agent/system-prompt")
async def api_system_prompt(format: Optional[str] = Query(default="json")):
    """
    Retorna o Master System Prompt do Orquestrador VectraClaw.

    Query params:
      - format=json  (default) → { meta: {...}, prompt: "..." }
      - format=text            → texto plano do prompt (para uso direto na API do LLM)
    """
    from src.services.brain.system_prompt import build_system_prompt, system_prompt_meta

    prompt = build_system_prompt()
    if format == "text":
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=prompt, media_type="text/plain; charset=utf-8")

    return {
        "meta": system_prompt_meta(),
        "prompt": prompt,
    }


@app.get("/api/agent/workflow")
async def api_workflow():
    """
    Retorna o Workflow Aduaneiro Padrão da Vectra Cargo (W1–W7) em JSON estruturado.
    Inclui etapas, ferramentas, regras de negócio, tolerâncias e canais SISCOMEX.
    """
    from src.services.brain.workflow_aduaneiro import workflow_to_dict

    return workflow_to_dict()


# ---------------------------------------------------------------------------
# VEC-188 – Self-healing DB retry endpoint
# ---------------------------------------------------------------------------

class DbRetryInput(BaseModel):
    """
    Payload para retentar uma operação de banco após self-healing.
    O agente corrige o `corrected_payload` e reenvia com os metadados
    originais para auditoria.
    """
    operation: str               # ex: "insert:tasks", "update:agents"
    table: str                   # tabela alvo
    corrected_payload: Dict[str, Any]  # payload corrigido pelo agente
    original_error_category: str  # error_category do FailoverResult original
    retry_hint: Optional[str] = None  # endpoint sugerido (informativo)

    class Config:
        extra = "ignore"


@app.post("/api/db/retry")
async def api_db_retry(request: Request, body: DbRetryInput):
    """
    VEC-188 — Endpoint de retry após self-healing.

    O agente, ao receber um FailoverResult, corrige o payload e reenvia aqui.
    O sistema executa a operação corrigida com o cliente service_role e retorna
    o resultado ou um novo FailoverResult se ainda falhar.

    Operações suportadas:
      - insert:tasks
      - update:tasks
      - insert:agents
      - update:agents
    """
    from src.services.brain.db_failover import build_failover_result

    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_unavailable")

    op = body.operation.lower()
    table = body.table
    corrected = body.corrected_payload

    logger.info("DB retry: op=%s table=%s category=%s", op, table, body.original_error_category)

    try:
        if op.startswith("insert:"):
            res = supabase.table(table).insert(corrected).execute()
            if not res.data:
                raise HTTPException(status_code=500, detail="retry_insert_returned_empty")
            return {"success": True, "operation": op, "data": res.data[0]}

        elif op.startswith("update:"):
            # Precisa de um campo identificador — procura id, task_id, agent_id
            row_id = corrected.get("id") or corrected.get("task_id") or corrected.get("agent_id")
            if not row_id:
                raise HTTPException(
                    status_code=422,
                    detail="corrected_payload deve conter 'id' para operações de update",
                )
            payload_no_id = {k: v for k, v in corrected.items() if k != "id"}
            res = supabase.table(table).update(payload_no_id).eq("id", row_id).execute()
            if not res.data:
                raise HTTPException(status_code=404, detail="retry_record_not_found")
            return {"success": True, "operation": op, "data": res.data[0]}

        else:
            raise HTTPException(
                status_code=422,
                detail=f"Operação '{op}' não suportada. Use 'insert:<table>' ou 'update:<table>'.",
            )

    except HTTPException:
        raise
    except Exception as exc:
        fr = build_failover_result(
            exc=exc,
            operation=f"retry:{op}",
            table=table,
            original_payload=corrected,
            retry_hint=body.retry_hint or "",
        )
        logger.error("DB retry still failing [%s]: %s", fr.error_category, fr.error_detail)
        raise HTTPException(status_code=fr.http_status, detail=fr.to_http_detail())


# ---------------------------------------------------------------------------
# VEC-186 – WhatsApp endpoint: POST /api/tools/send-whatsapp
# ---------------------------------------------------------------------------

class WhatsAppTextInput(BaseModel):
    phone: str
    message: Optional[str] = None
    type: Optional[Literal["text", "template"]] = "text"
    template_name: Optional[str] = None
    language: Optional[str] = "pt_BR"
    components: Optional[list] = None

    class Config:
        extra = "ignore"


@app.post("/api/tools/send-whatsapp")
async def api_send_whatsapp(payload: WhatsAppTextInput):
    """
    Envia mensagem WhatsApp via Meta Cloud API.

    Modo texto (dentro da janela 24 h):
      { "phone": "+5547999990000", "message": "Texto aqui" }

    Modo template (proativo):
      { "phone": "+5547999990000", "type": "template",
        "template_name": "notificacao_frete", "language": "pt_BR",
        "components": [{"type": "body", "parameters": [...]}] }
    """
    try:
        from src.services.whatsapp.meta_client import (
            send_text,
            send_template,
            WhatsAppAPIError,
        )

        if payload.type == "template":
            if not payload.template_name:
                raise HTTPException(status_code=422, detail="template_name obrigatório para type=template")
            result = send_template(
                phone=payload.phone,
                template_name=payload.template_name,
                language=payload.language or "pt_BR",
                components=payload.components,
            )
        else:
            if not payload.message:
                raise HTTPException(status_code=422, detail="message obrigatório para type=text")
            result = send_text(phone=payload.phone, message=payload.message)

        msg_id = result.get("messages", [{}])[0].get("id", "")
        return {"success": True, "message_id": msg_id, "to": payload.phone}

    except HTTPException:
        raise
    except Exception as exc:
        # WhatsAppAPIError e outros erros de integração
        status = getattr(exc, "status_code", 502)
        detail = str(getattr(exc, "detail", exc))
        logger.error("send-whatsapp error: %s", detail)
        raise HTTPException(status_code=status if isinstance(status, int) else 502, detail=detail)


# ---------------------------------------------------------------------------
# VEC-184 – OCR endpoint: POST /api/tools/extract-bl-pl
# ---------------------------------------------------------------------------

@app.post("/api/tools/extract-bl-pl")
async def api_extract_bl_pl(
    file: UploadFile = File(...),
    cross_ref: bool = False,
):
    """
    Upload a PDF (Bill of Lading or Packing List) and extract structured fields.

    - **file**: PDF binary (multipart/form-data).
    - **cross_ref**: if true and the doc is mixed (BL+PL), run cross-reference comparison.

    Returns a JSON with `doc_type`, `bl`, `pl`, `containers`, `dates`, and optionally
    `cross_reference`.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="only_pdf_accepted")

    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=422, detail="empty_file")

    try:
        from src.services.logistics.bl_pl_parser import parse_pdf_bytes, cross_reference

        parsed = parse_pdf_bytes(pdf_bytes)

        result: dict = {"success": True, "filename": file.filename, **parsed}

        if cross_ref and parsed.get("doc_type") == "mixed":
            xref = cross_reference(
                bl_data=parsed.get("bl", {}),
                pl_data=parsed.get("pl", {}),
            )
            result["cross_reference"] = xref

        return result

    except RuntimeError as exc:
        logger.error(f"extract_bl_pl runtime error: {exc}")
        raise HTTPException(status_code=503, detail="service_unavailable")
    except Exception as exc:
        logger.exception("extract_bl_pl endpoint error")
        raise HTTPException(status_code=500, detail="internal_server_error")


# =====================================================================
# LLM Models + Agent Specialties (VEC-241)
# =====================================================================

@app.get("/api/llm-models")
@app.get("/llm-models")
async def list_llm_models(request: Request, active: Optional[str] = None):
    active_only = active != "false"
    if not supabase:
        rows = [r for r in MOCK_LLM_MODELS if not active_only or r["is_active"]]
        return [LlmModel(**r).to_zod_dict() for r in rows]
    try:
        client = get_authenticated_client(request.state.token)
        q = client.table("llm_models").select("id,provider,display_name,input_cost_per_1m,output_cost_per_1m,cache_read_cost_per_1m,context_window_k,is_active,effective_from")
        if active_only:
            q = q.eq("is_active", True)
        res = q.order("display_name").execute()
        return [LlmModel(**row).to_zod_dict() for row in (res.data or [])]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"list_llm_models failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")


@app.get("/api/agent-specialties")
@app.get("/agent-specialties")
async def list_agent_specialties(request: Request):
    if not supabase:
        return [AgentSpecialty(**r).to_zod_dict() for r in MOCK_AGENT_SPECIALTIES if r["is_active"]]
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("agent_specialties")
            .select("id,name,slug,domain,description,compatible_roles,is_active")
            .eq("is_active", True)
            .order("name")
            .execute()
        )
        return [AgentSpecialty(**row).to_zod_dict() for row in (res.data or [])]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"list_agent_specialties failed: {e}")
        raise HTTPException(status_code=500, detail="internal_server_error")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)
