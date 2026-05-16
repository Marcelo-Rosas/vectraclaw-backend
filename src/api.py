import os
from uuid import UUID
import asyncio
import logging
import fnmatch
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Literal, Union
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import httpx
import requests
from jose import jwt  # pyright: ignore[reportMissingModuleSource]
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Query, UploadFile, File  # pyright: ignore[reportMissingImports]
from fastapi.middleware.cors import CORSMiddleware  # pyright: ignore[reportMissingImports]
from fastapi.openapi.utils import get_openapi  # pyright: ignore[reportMissingImports]
from fastapi.responses import JSONResponse, Response, StreamingResponse  # pyright: ignore[reportMissingImports]
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, validator

# supabase import
try:
    from supabase import create_client, Client
except ImportError:
    pass

from postgrest.exceptions import APIError as PostgrestAPIError

from src.models import (
    Agent, Task, Goal, Heartbeat, AuditLogEntry, CouncilApproval, User, AuthSession,
    Incident, IncidentAudit, AdapterCatalogItem, AdapterFieldDefinition, AgentAdapterConfig,
    AgentExecutionConfig, LlmModel, AgentSpecialty, AgentSpecialtyConfig, AgentSharedConfig,
    AgentDomain, AgentExecutionMode, WorkflowLogicPattern, WorkflowTriggerType,
    OperationType, Routine,
    SipocCompany, SipocSector, SipocPosition, SipocProcess, SipocComponent,
    Project, Run, RunTranscriptEntry,
)
from src.services.heartbeat_doctor.loop import doctor_tick
from src.services.heartbeat_doctor import audit as incident_audit
from src.services.heartbeat_doctor import store as incident_store
from src.services.morpheus_dispatcher import MorpheusDispatcher
from src.ws_manager import manager as ws_manager
from src.tenant_ids import company_row_public_id
from src.agents.sipoc_researcher import research_sector
from src.services.sipoc_promotion import promote_activity_to_automation
from src.services.sipoc_validator import validate_sipoc_consistency
from src.services.sipoc_raci import calculate_raci_stats
from src.services.sipoc_templates import get_templates_list, get_template_detail
from src.services.sipoc_analytics import calculate_sipoc_kpis
from src.services.sipoc_approvals import handle_status_transition
from src.services.sipoc_diagnostics import run_diagnostic

logger = logging.getLogger("VectraClawAPI")

# Windows ProactorEventLoop dispara ConnectionResetError 10054 quando o cliente
# fecha a conexão abruptamente — é ruído do OS, não um bug da aplicação.
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

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
        "/auth/me",
        "/api/auth/me",
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
            {"url": "/", "description": "Host atual (Auto-detectado)"}
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


LLM_PRICE_CACHE_TTL = timedelta(hours=24)
_llm_price_cache: Dict[str, Dict[str, float]] = {}
_llm_price_cache_loaded_at: Optional[datetime] = None


class AgentStatus:
    IDLE = "idle"
    WORKING = "working"
    PAUSED = "paused"
    OFFLINE = "offline"


class AgentPatch(BaseModel):
    """PATCH /api/agents/{id} — partial update.

    Inclui campos editáveis via UI das tabs:
    - instructions: system_prompt
    - configuration: token_budget, platform_url
    - misc (header do agente): name, role, reports_to_id, requires_approval

    `extra = "ignore"` significa que campos enviados mas não declarados aqui
    são SILENCIOSAMENTE descartados — se a UI envia algo que não vira UPDATE,
    o endpoint retorna 400 `empty_patch` (todos os campos viraram None).
    Quando adicionar suporte a um campo novo, lembre de declará-lo aqui.
    """

    name: Optional[str] = None
    role: Optional[str] = None
    token_budget: Optional[int] = Field(default=None, alias="tokenBudget")
    reports_to_id: Optional[str] = Field(default=None, alias="reportsToId")
    system_prompt: Optional[str] = Field(default=None, alias="systemPrompt")
    platform_url: Optional[str] = Field(default=None, alias="platformUrl")
    requires_approval: Optional[bool] = Field(default=None, alias="requiresApproval")

    class Config:
        populate_by_name = True
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

# Cache para JWKS
_JWKS_CACHE = None

def get_jwks():
    global _JWKS_CACHE
    if _JWKS_CACHE:
        return _JWKS_CACHE
    try:
        url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        res = requests.get(url)
        res.raise_for_status()
        _JWKS_CACHE = res.json()
        return _JWKS_CACHE
    except Exception as e:
        logger.error(f"Failed to fetch JWKS: {e}")
        return None

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

    from supabase import ClientOptions
    client = create_client(
        SUPABASE_URL,
        SUPABASE_ANON_KEY,
        options=ClientOptions(schema=SCHEMA),
    )
    client.postgrest.auth(token)
    return client


def _extract_vectraclip_claims(token: str) -> dict:
    """Decodifica o payload do JWT (sem verificação de assinatura) e retorna o bloco vectraclip."""
    import base64, json as _json
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        claims = _json.loads(base64.b64decode(payload_b64))
        return (claims.get("app_metadata") or {}).get("vectraclip") or {}
    except Exception:
        return {}


def validate_jwt(token: Optional[str]) -> None:
    """Exige JWT válido (ou dev-token). Usado por rotas sensíveis (ex: /api/system/*)."""
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    if token == "dev-token":
        return
    if validate_supabase_jwt(token) is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def validate_jwt_company_id(token: str, url_company_id: str) -> None:
    """Lança HTTPException 403 se o JWT não tiver ou divergir do company_id da URL.

    Espelha a validação do frontend TypeScript:
      1. Lê app_metadata.vectraclip.company_id do JWT
      2. Valida que o claim existe
      3. Valida que corresponde ao company_id da URL
    Não é chamado em modo dev-token (bypass explícito).
    """
    if token == "dev-token":
        return
    vc = _extract_vectraclip_claims(token)
    jwt_company_id = vc.get("company_id")
    if not jwt_company_id:
        raise HTTPException(
            status_code=403,
            detail="JWT sem app_metadata.vectraclip.company_id",
        )
    if str(jwt_company_id) != str(url_company_id):
        raise HTTPException(
            status_code=403,
            detail="company_id do payload difere do company_id do JWT",
        )


# ─────────────────────────────────────────────────────────────────────────────
# PR6 Fase A — RBAC sector_responsible: helpers de scope do user
# ─────────────────────────────────────────────────────────────────────────────

def _extract_jwt_sub(token: str) -> Optional[str]:
    """Lê o claim `sub` (auth.uid) do JWT. None se inválido."""
    if not token or token == "dev-token":
        return None
    import base64, json as _json
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        claims = _json.loads(base64.b64decode(payload_b64))
        return claims.get("sub")
    except Exception:
        return None


def get_user_scope(token: str) -> dict:
    """Resolve o scope do user a partir do JWT + (se preciso) lookup em app_users.

    Retorna dict:
      - company_id: str | None     (do JWT.app_metadata.vectraclip.company_id)
      - role: str                  ('admin'|'platform_admin'|'consultant'|'company_admin'|'sector_responsible'|'viewer')
      - user_id: str | None        (JWT.sub == app_users.id == auth.users.id)
      - position_id: str | None    (app_users.assigned_position_id; populado SÓ se role=sector_responsible)

    Bypass dev-token: retorna scope global ('platform_admin', None pra ids).

    O lookup em app_users só roda pra sector_responsible (otimização — outros
    roles não precisam de position_id). Falha silenciosa → position_id=None,
    o que faz assert_activity_in_scope lançar 403 informativo.
    """
    if token == "dev-token":
        return {"company_id": None, "role": "platform_admin", "user_id": None, "position_id": None}

    vc = _extract_vectraclip_claims(token)
    company_id = vc.get("company_id")
    role = vc.get("role") or "company_admin"
    user_id = _extract_jwt_sub(token)

    position_id = None
    if role == "sector_responsible" and user_id and supabase:
        try:
            res = (
                supabase.table("app_users")
                .select("assigned_position_id")
                .eq("id", user_id)
                .limit(1)
                .execute()
            )
            if res.data:
                position_id = res.data[0].get("assigned_position_id")
        except Exception as e:
            logger.warning("get_user_scope app_users lookup failed user=%s: %s", user_id, e)

    return {
        "company_id": company_id,
        "role": role,
        "user_id": user_id,
        "position_id": position_id,
    }


def assert_activity_in_scope(scope: dict, activity_row: dict) -> None:
    """Lança HTTPException 403 se sector_responsible não puder acessar a activity.

    - Roles amplas (admin, platform_admin, consultant, company_admin, viewer):
      pass-through. RLS já filtra por company_id.
    - sector_responsible: activity.responsible_position_id DEVE bater com
      scope.position_id. Caso contrário, 403.
    - sector_responsible sem position_id atribuído: 403 informativo
      ("pedir admin pra atribuir cargo").
    """
    if scope.get("role") != "sector_responsible":
        return

    user_position = scope.get("position_id")
    if not user_position:
        raise HTTPException(
            status_code=403,
            detail="sector_responsible sem assigned_position_id — peça ao admin pra atribuir seu cargo no organograma",
        )

    activity_responsible = activity_row.get("responsible_position_id")
    if activity_responsible != user_position:
        raise HTTPException(
            status_code=403,
            detail="Atividade fora do seu escopo (responsible_position_id não corresponde ao seu cargo)",
        )


def require_role_not(scope: dict, blocked_roles: list, action: str) -> None:
    """Lança HTTPException 403 se scope.role estiver em blocked_roles.

    Útil pra impedir sector_responsible/viewer de fazer ações de admin
    (ex: criar/editar templates, importar atividades em processes alheios).
    """
    if scope.get("role") in blocked_roles:
        raise HTTPException(
            status_code=403,
            detail=f"Seu role ({scope.get('role')}) não pode {action}",
        )


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
        from supabase import create_client, ClientOptions

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


def _validate_active_model_id(model_id: Optional[str]) -> None:
    """
    Garante que o model_id informado no heartbeat existe e está ativo em llm_models.
    Se model_id vier vazio, a validação é ignorada (heartbeat sem pricing modelado).
    """
    if not model_id:
        return
    if _resolve_model_prices(model_id) is None:
        raise HTTPException(
            status_code=400,
            detail=f"invalid_model_id_or_inactive:{model_id}",
        )


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
        current = (
            supabase.table("tasks")
            .select("id,company_id,assigned_to_agent_id,cost_usd,budget_limit,status")
            .eq("id", task_id)
            .limit(1)
            .execute()
        )
        if not current.data:
            return
        row = current.data[0]
        next_cost = float(row.get("cost_usd") or 0.0) + float(heartbeat_cost_usd)
        update_payload: Dict[str, Any] = {
            "cost_usd": round(next_cost, 8),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        budget_limit = float(row.get("budget_limit") or 0.0)
        status = str(row.get("status") or "")
        if budget_limit > 0 and next_cost > budget_limit and status not in ("done", "blocked"):
            # Circuit breaker financeiro: pausa execução quando excede orçamento.
            update_payload["status"] = "blocked"
        update_res = (
            supabase.table("tasks")
            .update(update_payload)
            .eq("id", task_id)
            .execute()
        )
        if update_res.data and row.get("company_id"):
            try:
                task_dict = Task(**update_res.data[0]).to_zod_dict()
                ws_manager.broadcast_nowait(
                    row["company_id"],
                    {"type": "task_updated", "payload": task_dict},
                )
            except Exception:
                pass
        if update_payload.get("status") == "blocked":
            _emit_budget_blocked_heartbeat(
                company_id=row.get("company_id"),
                agent_id=row.get("assigned_to_agent_id"),
                task_id=task_id,
                cost_usd=next_cost,
                budget_limit=budget_limit,
            )
    except Exception as e:
        logger.warning(f"task cost accumulation failed task={task_id}: {e}")


def _emit_budget_blocked_heartbeat(
    *,
    company_id: Optional[str],
    agent_id: Optional[str],
    task_id: Optional[str],
    cost_usd: float,
    budget_limit: float,
) -> None:
    if not supabase or not company_id or not agent_id or not task_id:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    row: Dict[str, Any] = {
        "company_id": company_id,
        "agent_id": agent_id,
        "task_id": task_id,
        "status": "error",
        "tokens_used": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "model_id": None,
        "cost_usd": round(float(cost_usd), 8),
        "log_excerpt": (
            f"Circuit breaker: budget_limit_exceeded "
            f"(cost_usd={round(float(cost_usd), 4)}, budget_limit={round(float(budget_limit), 4)})"
        ),
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    try:
        res = supabase.table("heartbeats").insert(row).execute()
        if res.data:
            hb_payload = Heartbeat(**res.data[0]).to_zod_dict()
        else:
            hb_payload = {
                "id": f"hb_budget_{int(datetime.now().timestamp())}",
                "agentId": agent_id,
                "taskId": task_id,
                "status": "error",
                "tokensUsed": 0,
                "inputTokens": 0,
                "outputTokens": 0,
                "cacheReadTokens": 0,
                "costUsd": round(float(cost_usd), 8),
                "logExcerpt": row["log_excerpt"],
                "createdAt": now_iso.replace("+00:00", "Z"),
            }
        ws_manager.broadcast_nowait(
            company_id,
            {"type": "heartbeat", "payload": hb_payload},
        )
    except Exception as e:
        logger.warning(f"emit budget blocked heartbeat failed task={task_id}: {e}")


def _task_over_budget(task: Dict[str, Any]) -> bool:
    try:
        budget_limit = float(task.get("budget_limit") or 0.0)
        if budget_limit <= 0:
            return False
        return float(task.get("cost_usd") or 0.0) > budget_limit
    except Exception:
        return False


def _task_is_approved(task: Dict[str, Any]) -> bool:
    return bool(task.get("approved_at") or task.get("approved_by_user_id"))


def _agent_requires_approval(agent_id: Optional[str]) -> bool:
    if not supabase or not agent_id:
        return False
    try:
        res = (
            supabase.table("agents")
            .select("requires_approval")
            .eq("id", agent_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            return False
        return bool(res.data[0].get("requires_approval"))
    except Exception:
        return False


def _enforce_task_execution_gates(task: Dict[str, Any], *, source: str) -> None:
    """
    Gates obrigatórios para iniciar/retomar execução:
    - orçamento excedido -> bloqueia task e nega execução
    - agente requer aprovação humana -> exige approved_at/by antes de executar
    """
    task_id = task.get("id")
    if _task_over_budget(task):
        try:
            if supabase and task_id and str(task.get("status") or "") not in ("done", "blocked"):
                supabase.table("tasks").update(
                    {
                        "status": "blocked",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                ).eq("id", task_id).execute()
        except Exception:
            pass
        raise HTTPException(status_code=409, detail="budget_limit_exceeded")

    if _agent_requires_approval(task.get("assigned_to_agent_id")) and not _task_is_approved(task):
        try:
            if supabase and task_id and str(task.get("status") or "") not in ("review", "done"):
                supabase.table("tasks").update(
                    {
                        "status": "review",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                ).eq("id", task_id).execute()
        except Exception:
            pass
        raise HTTPException(status_code=409, detail=f"task_requires_approval:{source}")

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
    public_paths = [
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
    ]
    if any(path == p for p in public_paths):
        return await call_next(request)

    # WebSocket upgrade: o browser não envia Authorization header; o token
    # chega como query param e a autenticação é feita dentro do route handler.
    if path.startswith("/ws/") or path.startswith("/api/ws/"):
        return await call_next(request)

    auth_header = request.headers.get("Authorization")
    # Bypass para desenvolvimento local (VEC-DEBUG)
    if os.getenv("VECTRACLAW_AUTH_DISABLED") == "true":
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
# SIPOC Builder (VEC-246)
# =====================================================================

@app.get("/api/sipoc/companies")
async def list_sipoc_companies(request: Request):
    if not supabase:
        return []
    try:
        res = supabase.table("sipoc_companies").select("*").order("name").execute()
        return [SipocCompany(**row).to_zod_dict() for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_sipoc_companies failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─────────────────────────────────────────────────────────────────────────────
# SIPOC input validation — previne "dados lixo" (frases de chat virando nome
# de setor/processo, etc.). Aplicado em POST sectors/processes/positions/companies.
# Helper exportado pra outros submodules que precisem do mesmo padrão.
# ─────────────────────────────────────────────────────────────────────────────
import re as _re_sipoc

# Prefixos típicos de frase de chat que NÃO devem virar nome de entidade.
_SIPOC_BAD_PREFIXES = (
    "quero ", "acho ", "vou ", "preciso ", "devo ",
    "tenho que ", "mapear ", "gostaria ", "pretendo ",
)


def _validate_sipoc_name(raw: Any, *, kind: str, min_len: int = 3, max_len: int = 50) -> str:
    """Valida e normaliza um nome de entidade SIPOC (sector/process/position/company).

    Regras:
      - Tipo string não-vazia (após trim)
      - Length entre min_len e max_len
      - Sem quebras de linha
      - Não começa com prefixo de frase de chat ('Quero', 'Acho', 'Vou', etc.)
      - Não é todo numérico ou só caracteres especiais

    Lança HTTPException 400 com mensagem em PT explicando o problema.
    Retorna o nome normalizado (trimmed).
    """
    if not isinstance(raw, str):
        raise HTTPException(400, f"{kind}: nome deve ser texto")
    name = raw.strip()
    if not name:
        raise HTTPException(400, f"{kind}: nome obrigatório")
    if "\n" in name or "\r" in name:
        raise HTTPException(400, f"{kind}: nome não pode ter quebras de linha")
    if len(name) < min_len:
        raise HTTPException(400, f"{kind}: nome muito curto (mínimo {min_len} caracteres)")
    if len(name) > max_len:
        raise HTTPException(400, f"{kind}: nome muito longo (máximo {max_len} caracteres). Não escreva frases — use um nome curto e descritivo.")
    low = name.lower()
    for bad in _SIPOC_BAD_PREFIXES:
        if low.startswith(bad):
            raise HTTPException(
                400,
                f"{kind}: nome não pode começar com '{bad.strip().capitalize()}'. Use um nome direto (ex: 'Contas a Pagar', 'Cotação de Frete'). Não escreva o que você quer fazer — escreva o nome da entidade.",
            )
    if _re_sipoc.fullmatch(r"[\d\s\-_.,;:!?]+", name):
        raise HTTPException(400, f"{kind}: nome precisa ter pelo menos uma letra")
    return name


@app.post("/api/sipoc/companies")
async def create_sipoc_company(request: Request, payload: Dict[str, Any]):
    if not supabase:
        return {"id": "mock-id", "name": payload.get("name")}
    # Validação de nome (PR cleanup pós-AS-IS)
    payload["name"] = _validate_sipoc_name(payload.get("name"), kind="Empresa SIPOC")
    try:
        res = supabase.table("sipoc_companies").insert(payload).execute()
        return SipocCompany(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"create_sipoc_company failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
        raise HTTPException(status_code=500, detail=str(e))

def _slugify_sipoc(name: str) -> str:
    """Slug simples a partir de um nome SIPOC: lowercase + hifens + sem acento."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    slug = _re_sipoc.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug or "sem-nome"


def _normalize_sipoc_payload_to_snake(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Aceita payload em camelCase OU snake_case (frontend velho mistura).
    DB exige snake_case. Defensive transform — não quebra clients corretos.

    Inclui campos de TODAS as tabelas SIPOC pra reuso entre handlers
    (sectors, processes, components, positions, raci).
    """
    camel_to_snake = {
        # IDs e refs
        "companyId": "company_id",
        "sectorId": "sector_id",
        "reportsToId": "reports_to_id",
        "processId": "process_id",
        "componentId": "component_id",
        "positionId": "position_id",
        "parentSectorId": "parent_sector_id",
        "responsibleId": "responsible_id",
        "responsiblePositionId": "responsible_position_id",
        "suggestedOperationType": "suggested_operation_type",
        # Status/flags
        "automationStatus": "automation_status",
        "validationStatus": "validation_status",
        "validationNotes": "validation_notes",
        "clonedFromTemplateId": "cloned_from_template_id",
        # Metadados
        "diagnosticMetadata": "diagnostic_metadata",
        "createdAt": "created_at",
        "updatedAt": "updated_at",
    }
    out = {}
    for k, v in payload.items():
        snake = camel_to_snake.get(k, k)
        # snake_case version wins se ambos presentes
        if snake not in out:
            out[snake] = v
    return out


@app.post("/api/sipoc/sectors")
async def create_sipoc_sector(request: Request, payload: Dict[str, Any]):
    if not supabase:
        return {"id": "mock-id", "name": payload.get("name")}
    payload = _normalize_sipoc_payload_to_snake(payload)
    payload["name"] = _validate_sipoc_name(payload.get("name"), kind="Setor")
    # Auto-gera slug se não fornecido (coluna NOT NULL no DB)
    if not payload.get("slug"):
        payload["slug"] = _slugify_sipoc(payload["name"])
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("sipoc_sectors").insert(payload).execute()
        return SipocSector(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_sipoc_sector failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sipoc/positions")
async def create_sipoc_position(request: Request, payload: Dict[str, Any]):
    if not supabase:
        return {"id": "mock-id", "title": payload.get("title")}
    payload = _normalize_sipoc_payload_to_snake(payload)
    payload["title"] = _validate_sipoc_name(payload.get("title"), kind="Cargo")
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("sipoc_positions").insert(payload).execute()
        return SipocPosition(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_sipoc_position failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sipoc/processes")
async def create_sipoc_process(request: Request, payload: Dict[str, Any]):
    if not supabase:
        return {"id": "mock-id", "name": payload.get("name")}
    payload = _normalize_sipoc_payload_to_snake(payload)
    # sipoc_processes não tem coluna company_id — silenciosamente ignora se vier
    payload.pop("company_id", None)
    # Processes podem ter nome um pouco maior (até 80) — descrição operacional.
    payload["name"] = _validate_sipoc_name(payload.get("name"), kind="Processo", max_len=80)
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("sipoc_processes").insert(payload).execute()
        return SipocProcess(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_sipoc_process failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
        raise HTTPException(status_code=500, detail=str(e))

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
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sipoc/components")
async def upsert_sipoc_component(request: Request, payload: Dict[str, Any]):
    if not supabase:
        return {"id": "mock-id", "type": payload.get("type")}
    # Normaliza camelCase → snake_case (frontend manda processId/automationStatus/etc.).
    # Os irmãos POST sectors/processes/positions já chamam isso; este endpoint estava
    # esquecido — bug reportado por user em 2026-05-16 (auditoria de handlers).
    payload = _normalize_sipoc_payload_to_snake(payload)
    try:
        client = get_authenticated_client(request.state.token)
        # Se tiver ID, atualiza; senão, insere.
        comp_id = payload.get("id")
        if comp_id:
            res = client.table("sipoc_components").update(payload).eq("id", comp_id).execute()
        else:
            res = client.table("sipoc_components").insert(payload).execute()

        return SipocComponent(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"upsert_sipoc_component failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sipoc/research")
async def sipoc_research(request: Request, payload: Dict[str, Any]):
    sector_name = payload.get("sector")
    if not sector_name:
        raise HTTPException(status_code=400, detail="Sector name is required")
    try:
        result = await research_sector(sector_name)
        return result
    except Exception as e:
        logger.error(f"sipoc_research failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─────────────────────────────────────────────────────────────────────────────
# DELETE hierárquico SIPOC (sector / process / component)
#
# FKs já definem cascade no DB:
#   sipoc_processes.sector_id      → CASCADE
#   sipoc_components.process_id    → CASCADE
#   sipoc_edges.process_id         → CASCADE
#   sipoc_edges.source_id/target_id → CASCADE
#   sipoc_raci.process_id          → CASCADE
#   sipoc_raci.component_id        → CASCADE
#   sipoc_positions.sector_id      → SET NULL (positions ficam cross-cutting)
#
# RBAC: bloqueia sector_responsible/viewer (ação destrutiva).
# Retorna contagens do que será deletado pra frontend mostrar feedback.
# ─────────────────────────────────────────────────────────────────────────────

_SIPOC_DELETE_BLOCKED_ROLES = ["sector_responsible", "viewer"]


@app.delete("/api/sipoc/sectors/{sector_id}")
async def delete_sipoc_sector(request: Request, sector_id: UUID):
    """Remove um setor (cascateia processes + components + edges + raci).

    Positions vinculadas ao setor ficam cross-cutting (sector_id=NULL via
    FK SET NULL) — não são deletadas. RBAC bloqueia roles operacionais.
    """
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    scope = get_user_scope(request.state.token)
    require_role_not(scope, _SIPOC_DELETE_BLOCKED_ROLES, "remover setores SIPOC")
    try:
        client = get_authenticated_client(request.state.token)
        proc_ids = [r["id"] for r in (
            client.table("sipoc_processes").select("id").eq("sector_id", str(sector_id)).execute().data or []
        )]
        comp_count = 0
        if proc_ids:
            comp_count = (client.table("sipoc_components").select("id", count="exact")
                          .in_("process_id", proc_ids).execute().count or 0)
        res = supabase.table("sipoc_sectors").delete().eq("id", str(sector_id)).execute()
        if not res.data:
            raise HTTPException(404, "sector_not_found_or_not_accessible")
        logger.info("delete_sipoc_sector sector=%s cascade processes=%d components=%d by=%s",
                    sector_id, len(proc_ids), comp_count, scope.get("user_id"))
        return {"deleted": True, "sectorId": str(sector_id),
                "cascade": {"processes": len(proc_ids), "components": comp_count,
                            "edgesAndRaci": "auto via FK CASCADE"}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_sipoc_sector failed: {e}")
        raise HTTPException(500, str(e))


@app.delete("/api/sipoc/processes/{process_id}")
async def delete_sipoc_process(request: Request, process_id: UUID):
    """Remove um processo (cascateia components + edges + raci). Sector permanece."""
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    scope = get_user_scope(request.state.token)
    require_role_not(scope, _SIPOC_DELETE_BLOCKED_ROLES, "remover processos SIPOC")
    try:
        client = get_authenticated_client(request.state.token)
        comp_count = (client.table("sipoc_components").select("id", count="exact")
                      .eq("process_id", str(process_id)).execute().count or 0)
        raci_count = (client.table("sipoc_raci").select("id", count="exact")
                      .eq("process_id", str(process_id)).execute().count or 0)
        res = supabase.table("sipoc_processes").delete().eq("id", str(process_id)).execute()
        if not res.data:
            raise HTTPException(404, "process_not_found_or_not_accessible")
        logger.info("delete_sipoc_process process=%s cascade components=%d raci=%d by=%s",
                    process_id, comp_count, raci_count, scope.get("user_id"))
        return {"deleted": True, "processId": str(process_id),
                "cascade": {"components": comp_count, "raci": raci_count,
                            "edges": "auto via FK CASCADE"}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_sipoc_process failed: {e}")
        raise HTTPException(500, str(e))


@app.delete("/api/sipoc/components/{component_id}")
async def delete_sipoc_component(request: Request, component_id: UUID):
    """Remove um component (supplier/input/activity/output/customer).

    Cascateia edges (sipoc_edges.source_id/target_id) + raci (component_id).
    """
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    scope = get_user_scope(request.state.token)
    require_role_not(scope, _SIPOC_DELETE_BLOCKED_ROLES, "remover atividades/componentes SIPOC")
    try:
        client = get_authenticated_client(request.state.token)
        raci_count = (client.table("sipoc_raci").select("id", count="exact")
                      .eq("component_id", str(component_id)).execute().count or 0)
        res = supabase.table("sipoc_components").delete().eq("id", str(component_id)).execute()
        if not res.data:
            raise HTTPException(404, "component_not_found_or_not_accessible")
        logger.info("delete_sipoc_component component=%s cascade raci=%d by=%s",
                    component_id, raci_count, scope.get("user_id"))
        return {"deleted": True, "componentId": str(component_id),
                "cascade": {"raci": raci_count, "edges": "auto via FK CASCADE"}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_sipoc_component failed: {e}")
        raise HTTPException(500, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# PATCH hierárquico SIPOC (sector / process / component) — UI-first MVP
#
# Backend dos 3 endpoints PATCH que UI precisa pra editar nome/descrição
# sem CLI. Padrão idêntico aos DELETEs acima:
# - require_role_not bloqueia sector_responsible/viewer
# - service_role no UPDATE (consistente com hotfix #137)
# - validate_sipoc_name reaproveitado pros campos name/title
# - normalize_payload aceita camelCase do frontend
# ─────────────────────────────────────────────────────────────────────────────

_SIPOC_EDIT_BLOCKED_ROLES = _SIPOC_DELETE_BLOCKED_ROLES  # mesma matriz


@app.patch("/api/sipoc/sectors/{sector_id}")
async def patch_sipoc_sector(request: Request, sector_id: UUID, payload: Dict[str, Any]):
    """Edita um setor SIPOC (name, icon, metadata, parent_sector_id).

    Schema real: id, company_id, name, slug, icon, metadata, parent_sector_id.
    NÃO tem `description` (esse campo é só de processes/components).
    """
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    scope = get_user_scope(request.state.token)
    require_role_not(scope, _SIPOC_EDIT_BLOCKED_ROLES, "editar setores SIPOC")

    payload = _normalize_sipoc_payload_to_snake(payload)
    update_data: Dict[str, Any] = {}
    if "name" in payload and payload["name"] is not None:
        update_data["name"] = _validate_sipoc_name(payload["name"], kind="Setor")
        # Se nome mudou, slug pode estar stale; re-gerar (idempotente)
        update_data["slug"] = _slugify_sipoc(update_data["name"])
    if "icon" in payload:
        update_data["icon"] = payload["icon"]
    if "metadata" in payload and isinstance(payload["metadata"], dict):
        update_data["metadata"] = payload["metadata"]
    if "parent_sector_id" in payload:
        update_data["parent_sector_id"] = payload["parent_sector_id"] or None

    if not update_data:
        raise HTTPException(400, "no_valid_fields")

    try:
        res = supabase.table("sipoc_sectors").update(update_data).eq("id", str(sector_id)).execute()
        if not res.data:
            raise HTTPException(404, "sector_not_found_or_not_accessible")
        logger.info("patch_sipoc_sector sector=%s fields=%s by=%s",
                    sector_id, list(update_data.keys()), scope.get("user_id"))
        return SipocSector(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_sipoc_sector failed: {e}")
        raise HTTPException(500, str(e))


@app.patch("/api/sipoc/processes/{process_id}")
async def patch_sipoc_process(request: Request, process_id: UUID, payload: Dict[str, Any]):
    """Edita um processo SIPOC (name, description, status, position_id, etc.)."""
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    scope = get_user_scope(request.state.token)
    require_role_not(scope, _SIPOC_EDIT_BLOCKED_ROLES, "editar processos SIPOC")

    payload = _normalize_sipoc_payload_to_snake(payload)
    update_data: Dict[str, Any] = {}
    if "name" in payload and payload["name"] is not None:
        update_data["name"] = _validate_sipoc_name(payload["name"], kind="Processo", max_len=80)
    if "description" in payload:
        update_data["description"] = payload["description"]
    if "status" in payload:
        update_data["status"] = payload["status"]
    if "sector_id" in payload:
        update_data["sector_id"] = payload["sector_id"]
    if "position_id" in payload:
        update_data["position_id"] = payload["position_id"] or None
    if "responsible_id" in payload:
        update_data["responsible_id"] = payload["responsible_id"] or None
    if "metadata" in payload and isinstance(payload["metadata"], dict):
        update_data["metadata"] = payload["metadata"]

    if not update_data:
        raise HTTPException(400, "no_valid_fields")

    try:
        res = supabase.table("sipoc_processes").update(update_data).eq("id", str(process_id)).execute()
        if not res.data:
            raise HTTPException(404, "process_not_found_or_not_accessible")
        logger.info("patch_sipoc_process process=%s fields=%s by=%s",
                    process_id, list(update_data.keys()), scope.get("user_id"))
        return SipocProcess(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_sipoc_process failed: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/sipoc/processes/{process_id}/components")
async def create_sipoc_component_standalone(
    request: Request, process_id: UUID, payload: Dict[str, Any]
):
    """Cria um component SIPOC (activity, supplier, input, output, customer)
    standalone, sem precisar de template do marketplace.

    Resolve Gap 3 do dogfood — antes só dava pra criar via SipocWizard ou SQL.

    Body esperado:
      {
        "type": "activity" | "supplier" | "input" | "output" | "customer",
        "content": {"name": "...", "description": "...", "what": "...", ...},
        "order": <int opcional, default=99>,
        "automation_status": <opcional para activity>,
        "suggested_operation_type": <opcional>,
        "responsible_position_id": <opcional UUID>
      }
    """
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    scope = get_user_scope(request.state.token)
    require_role_not(scope, _SIPOC_EDIT_BLOCKED_ROLES, "criar componentes SIPOC")

    payload = _normalize_sipoc_payload_to_snake(payload)

    # Valida type contra os 5 valores aceitos no SIPOC
    valid_types = {"supplier", "input", "output", "customer", "activity"}
    comp_type = payload.get("type")
    if comp_type not in valid_types:
        raise HTTPException(
            400,
            f"type inválido: '{comp_type}'. Aceito: {sorted(valid_types)}",
        )

    # Valida content
    content = payload.get("content") or {}
    if not isinstance(content, dict):
        raise HTTPException(400, "content deve ser objeto JSON")
    content_name = content.get("name") or content.get("title")
    if content_name:
        # Usa mesma validação dos sectors (3-80 chars, sem 'Quero...', etc.)
        kind = "Atividade" if comp_type == "activity" else f"Componente {comp_type}"
        content["name"] = _validate_sipoc_name(content_name, kind=kind, max_len=80)
        # Remove título se existir pra evitar duplicação
        content.pop("title", None)

    insert_row = {
        "process_id": str(process_id),
        "type": comp_type,
        "content": content,
        "order": payload.get("order", 99),
    }
    # Campos opcionais do PR2 (PR #131) — só se vier no payload
    if comp_type == "activity":
        if "automation_status" in payload:
            insert_row["automation_status"] = payload["automation_status"]
        if "suggested_operation_type" in payload:
            insert_row["suggested_operation_type"] = payload["suggested_operation_type"]
        if "responsible_position_id" in payload:
            insert_row["responsible_position_id"] = payload["responsible_position_id"] or None
    if "metadata" in payload and isinstance(payload["metadata"], dict):
        insert_row["metadata"] = payload["metadata"]

    try:
        res = supabase.table("sipoc_components").insert(insert_row).execute()
        if not res.data:
            raise HTTPException(500, "insert_returned_empty")
        component = res.data[0]
        logger.info("create_sipoc_component_standalone process=%s type=%s component=%s by=%s",
                    process_id, comp_type, component["id"], scope.get("user_id"))
        return {
            "id": component["id"],
            "processId": str(process_id),
            "type": component["type"],
            "content": component["content"],
            "order": component.get("order"),
            "automationStatus": component.get("automation_status"),
            "suggestedOperationType": component.get("suggested_operation_type"),
            "responsiblePositionId": component.get("responsible_position_id"),
            "createdAt": component.get("created_at"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_sipoc_component_standalone failed: {e}")
        raise HTTPException(500, str(e))


@app.patch("/api/sipoc/components/{component_id}")
async def patch_sipoc_component(request: Request, component_id: UUID, payload: Dict[str, Any]):
    """Edita um component (content, order, automation_status, etc.)."""
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    scope = get_user_scope(request.state.token)
    require_role_not(scope, _SIPOC_EDIT_BLOCKED_ROLES, "editar componentes SIPOC")

    payload = _normalize_sipoc_payload_to_snake(payload)
    update_data: Dict[str, Any] = {}

    if "content" in payload:
        content = payload["content"]
        if not isinstance(content, dict):
            raise HTTPException(400, "content deve ser objeto JSON")
        # Valida nome se enviado no content (mesmo padrão dos POSTs)
        if content.get("name"):
            content["name"] = _validate_sipoc_name(content["name"], kind="Componente", max_len=80)
        update_data["content"] = content

    if "order" in payload:
        update_data["order"] = payload["order"]
    if "automation_status" in payload:
        update_data["automation_status"] = payload["automation_status"]
    if "suggested_operation_type" in payload:
        update_data["suggested_operation_type"] = payload["suggested_operation_type"]
    if "responsible_position_id" in payload:
        update_data["responsible_position_id"] = payload["responsible_position_id"] or None
    if "diagnostic_metadata" in payload and isinstance(payload["diagnostic_metadata"], dict):
        update_data["diagnostic_metadata"] = payload["diagnostic_metadata"]
    if "validation_status" in payload:
        update_data["validation_status"] = payload["validation_status"]
    if "validation_notes" in payload:
        update_data["validation_notes"] = payload["validation_notes"]
    if "metadata" in payload and isinstance(payload["metadata"], dict):
        update_data["metadata"] = payload["metadata"]

    if not update_data:
        raise HTTPException(400, "no_valid_fields")

    try:
        res = supabase.table("sipoc_components").update(update_data).eq("id", str(component_id)).execute()
        if not res.data:
            raise HTTPException(404, "component_not_found_or_not_accessible")
        logger.info("patch_sipoc_component component=%s fields=%s by=%s",
                    component_id, list(update_data.keys()), scope.get("user_id"))
        component = res.data[0]
        return {
            "id": component["id"],
            "processId": component.get("process_id"),
            "type": component["type"],
            "content": component["content"],
            "order": component.get("order"),
            "automationStatus": component.get("automation_status"),
            "suggestedOperationType": component.get("suggested_operation_type"),
            "responsiblePositionId": component.get("responsible_position_id"),
            "updatedAt": component.get("updated_at"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_sipoc_component failed: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/sipoc/components/{component_id}/promote")
async def promote_sipoc_activity(request: Request, component_id: UUID):
    if not supabase:
        return {"success": False, "message": "Supabase not configured"}
    try:
        # Usamos o supabase principal (service_role) para criação de agentes/rotinas
        result = await promote_activity_to_automation(supabase, str(component_id))
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except Exception as e:
        logger.error(f"promote_sipoc_activity failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sipoc/processes/{process_id}/validate")
async def validate_sipoc_process(request: Request, process_id: UUID):
    if not supabase:
        return {"score": 0, "issues": [], "is_valid": False}
    try:
        client = get_authenticated_client(request.state.token)
        # Buscar todos os componentes do processo
        res = client.table("sipoc_components").select("*").eq("process_id", process_id).execute()
        
        result = validate_sipoc_consistency(res.data or [])
        return result
    except Exception as e:
        logger.error(f"validate_sipoc_process failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sipoc/processes/{process_id}/raci")
async def get_process_raci(request: Request, process_id: UUID):
    if not supabase:
        return {"matrix": [], "stats": {}}
    try:
        client = get_authenticated_client(request.state.token)
        # Buscar dados da matriz
        matrix_res = client.table("sipoc_raci").select("*").eq("process_id", process_id).execute()
        # Buscar cargos para nomes
        positions_res = client.table("sipoc_positions").select("*").execute()
        
        stats = calculate_raci_stats(matrix_res.data or [], positions_res.data or [])
        return {"matrix": matrix_res.data or [], "stats": stats}
    except Exception as e:
        logger.error(f"get_process_raci failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

_RACI_VALID_ROLES = {"R", "A", "C", "I"}
_RACI_ADMIN_BLOCKED_ROLES = ["sector_responsible", "viewer"]


@app.post("/api/sipoc/raci")
async def update_raci_cell(request: Request, payload: Dict[str, Any]):
    """Upsert de uma cell RACI (process+component+position → R/A/C/I).

    Schmidt §"Engage stakeholders": cada activity (component) DEVE ter ao
    menos 1 'A' (Accountable) e 1 'R' (Responsible) para ser considerada
    bem-mapeada. Side-effect: quando role='R' é setado, atualiza também
    o atalho `sipoc_components.responsible_position_id` (usado pelo
    sector_responsible scope no Oracle chat, PR6).

    RBAC: bloqueia sector_responsible/viewer (ação consultiva/admin).
    Validação de role contra _RACI_VALID_ROLES (CHECK constraint do DB
    rejeita inválidos com 23514, mas validamos antes pra mensagem em PT).
    """
    if not supabase:
        return {"success": False}

    # Validação de input
    required = ("process_id", "component_id", "position_id", "role")
    missing = [k for k in required if not payload.get(k)]
    if missing:
        raise HTTPException(400, f"RACI: campos obrigatórios faltando: {', '.join(missing)}")

    role = payload.get("role")
    if role not in _RACI_VALID_ROLES:
        raise HTTPException(
            400,
            f"RACI: role '{role}' inválido. Esperado: R (Responsible), A (Accountable), C (Consulted), I (Informed).",
        )

    # RBAC
    scope = get_user_scope(request.state.token)
    require_role_not(scope, _RACI_ADMIN_BLOCKED_ROLES, "editar matriz RACI do organograma")

    try:
        client = get_authenticated_client(request.state.token)
        clean_payload = {k: payload[k] for k in required if k in payload}
        res = client.table("sipoc_raci").upsert(
            clean_payload, on_conflict="component_id,position_id"
        ).execute()

        # Side-effect: se role='R', sincronizar atalho em sipoc_components.
        # Schmidt: o "Responsible" é o executor único da activity — match natural
        # com responsible_position_id (criado no PR2).
        if role == "R":
            try:
                supabase.table("sipoc_components").update(
                    {"responsible_position_id": payload["position_id"]}
                ).eq("id", payload["component_id"]).execute()
            except Exception as sync_err:
                logger.warning(
                    "RACI: sync responsible_position_id falhou (não-fatal) component=%s: %s",
                    payload["component_id"], sync_err,
                )

        logger.info(
            "RACI upsert process=%s component=%s position=%s role=%s by=%s",
            payload.get("process_id"), payload.get("component_id"),
            payload.get("position_id"), role, scope.get("user_id"),
        )
        return {"success": True, "data": res.data[0] if res.data else None}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"update_raci_cell failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/sipoc/raci/{component_id}/{position_id}")
async def delete_raci_cell(request: Request, component_id: UUID, position_id: UUID):
    """Remove uma cell RACI (component, position).

    Se a cell era role='R', limpa também o atalho responsible_position_id
    em sipoc_components (não deixar dado "fantasma").
    """
    if not supabase:
        return {"success": False}

    scope = get_user_scope(request.state.token)
    require_role_not(scope, _RACI_ADMIN_BLOCKED_ROLES, "remover cells da matriz RACI")

    try:
        client = get_authenticated_client(request.state.token)

        # Lê role antes pra decidir se precisa limpar responsible_position_id
        existing = (
            client.table("sipoc_raci")
            .select("role")
            .eq("component_id", str(component_id))
            .eq("position_id", str(position_id))
            .limit(1)
            .execute()
        )
        was_responsible = existing.data and existing.data[0].get("role") == "R"

        res = (
            client.table("sipoc_raci")
            .delete()
            .eq("component_id", str(component_id))
            .eq("position_id", str(position_id))
            .execute()
        )

        if was_responsible:
            try:
                # Só limpa se o responsible ainda for esse position
                supabase.table("sipoc_components").update(
                    {"responsible_position_id": None}
                ).eq("id", str(component_id)).eq(
                    "responsible_position_id", str(position_id)
                ).execute()
            except Exception as sync_err:
                logger.warning(
                    "RACI delete: clear responsible_position_id falhou (não-fatal): %s",
                    sync_err,
                )

        logger.info(
            "RACI delete component=%s position=%s was_R=%s by=%s",
            component_id, position_id, was_responsible, scope.get("user_id"),
        )
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_raci_cell failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# Risk Register PMBOK — G1 (vectraclip.risks)
# Doc: docs/EXECUCAO-G1-RISK-REGISTER-E-DAEDALUS.md §3
# Tabela criada pelo PR #149.
# =============================================================================

# Constants — não viraram catalog porque são enums PMBOK fechados (P6 do
# CODE-PATTERNS: máquina de estados local, não expansível por config de tenant).
# CHECK do DB rejeita inválidos com 23514; validamos antes pra mensagem em PT.
_RISK_VALID_CATEGORIES = {"technical", "external", "organizational", "project_mgmt"}
_RISK_VALID_STATUSES = {"identified", "analyzing", "planned", "monitoring", "occurred", "closed"}
_RISK_VALID_RESPONSE_STRATEGIES = {"avoid", "transfer", "mitigate", "accept", "escalate"}
_RISK_WRITE_BLOCKED_ROLES = _SIPOC_EDIT_BLOCKED_ROLES  # mesma política do RACI


class NewRiskInput(BaseModel):
    """Input para POST /api/risks. Pelo menos 1 vínculo (goal/workflow/process/component) é
    recomendado mas não obrigatório (risco pode ser company-wide)."""
    name: str
    category: str
    probability: float
    impact: float
    description: Optional[str] = None
    response_strategy: Optional[str] = None
    mitigation_actions: Optional[str] = None
    contingency_plan: Optional[str] = None
    owner_position_id: Optional[str] = None
    status: Optional[str] = "identified"
    linked_goal_id: Optional[str] = None
    linked_workflow_id: Optional[str] = None
    linked_sipoc_process_id: Optional[str] = None
    linked_sipoc_component_id: Optional[str] = None
    detected_by_athena: Optional[bool] = False
    athena_recommendation_id: Optional[str] = None

    class Config:
        extra = "ignore"


class UpdateRiskInput(BaseModel):
    """Input para PATCH /api/risks/{id}. Tudo opcional — partial update."""
    name: Optional[str] = None
    category: Optional[str] = None
    probability: Optional[float] = None
    impact: Optional[float] = None
    description: Optional[str] = None
    response_strategy: Optional[str] = None
    mitigation_actions: Optional[str] = None
    contingency_plan: Optional[str] = None
    owner_position_id: Optional[str] = None
    status: Optional[str] = None
    linked_goal_id: Optional[str] = None
    linked_workflow_id: Optional[str] = None
    linked_sipoc_process_id: Optional[str] = None
    linked_sipoc_component_id: Optional[str] = None

    class Config:
        extra = "ignore"


def _validate_risk_payload(payload: Dict[str, Any], *, partial: bool = False) -> None:
    """Validação pré-DB (mensagens em PT). CHECK do DB é o último guardião."""
    if "category" in payload and payload["category"] is not None:
        if payload["category"] not in _RISK_VALID_CATEGORIES:
            raise HTTPException(
                400,
                f"Risk: category '{payload['category']}' inválida. "
                f"Esperado: {sorted(_RISK_VALID_CATEGORIES)}.",
            )
    elif not partial:
        raise HTTPException(400, "Risk: campo 'category' é obrigatório.")

    if "probability" in payload and payload["probability"] is not None:
        try:
            p = float(payload["probability"])
        except (TypeError, ValueError):
            raise HTTPException(400, "Risk: 'probability' deve ser número entre 0 e 1.")
        if p < 0 or p > 1:
            raise HTTPException(
                400,
                f"Risk: 'probability' deve estar entre 0 e 1 (recebido {p}).",
            )
    elif not partial:
        raise HTTPException(400, "Risk: campo 'probability' é obrigatório.")

    if "impact" in payload and payload["impact"] is not None:
        try:
            i = float(payload["impact"])
        except (TypeError, ValueError):
            raise HTTPException(400, "Risk: 'impact' deve ser número entre 1 e 10.")
        if i < 1 or i > 10:
            raise HTTPException(
                400,
                f"Risk: 'impact' deve estar entre 1 e 10 (recebido {i}).",
            )
    elif not partial:
        raise HTTPException(400, "Risk: campo 'impact' é obrigatório.")

    if "status" in payload and payload["status"] is not None:
        if payload["status"] not in _RISK_VALID_STATUSES:
            raise HTTPException(
                400,
                f"Risk: status '{payload['status']}' inválido. "
                f"Esperado: {sorted(_RISK_VALID_STATUSES)}.",
            )

    if "response_strategy" in payload and payload["response_strategy"]:
        if payload["response_strategy"] not in _RISK_VALID_RESPONSE_STRATEGIES:
            raise HTTPException(
                400,
                f"Risk: response_strategy '{payload['response_strategy']}' inválido. "
                f"Esperado: {sorted(_RISK_VALID_RESPONSE_STRATEGIES)}.",
            )

    if "name" in payload and payload["name"] is not None:
        name = str(payload["name"]).strip()
        if len(name) < 3:
            raise HTTPException(400, "Risk: 'name' deve ter ao menos 3 caracteres.")
        if len(name) > 200:
            raise HTTPException(400, "Risk: 'name' não pode passar de 200 caracteres.")


@app.post("/api/risks")
async def create_risk(request: Request, payload: NewRiskInput):
    """Cria risco novo. company_id vem do JWT (tenant scope)."""
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    scope = get_user_scope(request.state.token)
    require_role_not(scope, _RISK_WRITE_BLOCKED_ROLES, "criar riscos")

    company_id = _resolve_company_id(request)
    if not company_id:
        raise HTTPException(400, "company_id_required (JWT sem tenant scope)")

    data = payload.model_dump(exclude_none=True)
    _validate_risk_payload(data)
    data["company_id"] = company_id

    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("risks").insert(data).execute()
        if not res.data:
            raise HTTPException(500, "Risk: insert returned empty")
        risk_id = res.data[0].get("id")
        logger.info(
            "Risk created id=%s name=%r category=%s prob=%s impact=%s by=%s",
            risk_id, data.get("name"), data.get("category"),
            data.get("probability"), data.get("impact"), scope.get("user_id"),
        )
        # G1.1 audit log (best-effort, service_role)
        from src.services.audit import audit_log
        audit_log(
            supabase,
            company_id=str(company_id),
            actor_type="human",
            actor_id=str(scope.get("user_id") or "unknown"),
            action="risk.create",
            target=f"risk:{risk_id}",
            payload={
                "name": data.get("name"),
                "category": data.get("category"),
                "probability": data.get("probability"),
                "impact": data.get("impact"),
                "linked_goal_id": data.get("linked_goal_id"),
                "linked_sipoc_process_id": data.get("linked_sipoc_process_id"),
            },
        )
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_risk failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/companies/{company_id}/risks")
async def list_company_risks(
    request: Request,
    company_id: UUID,
    status: Optional[str] = None,
    category: Optional[str] = None,
    min_score: Optional[float] = None,
):
    """Lista riscos de uma company. Filtros opcionais: status, category, min_score.
    Ordena por risk_score DESC (mais críticos primeiro)."""
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        q = client.table("risks").select("*").eq("company_id", str(company_id))
        if status:
            if status not in _RISK_VALID_STATUSES:
                raise HTTPException(400, f"status inválido: {status}")
            q = q.eq("status", status)
        if category:
            if category not in _RISK_VALID_CATEGORIES:
                raise HTTPException(400, f"category inválida: {category}")
            q = q.eq("category", category)
        if min_score is not None:
            q = q.gte("risk_score", min_score)
        res = q.order("risk_score", desc=True).execute()
        return res.data or []
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"list_company_risks failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/risks/{risk_id}")
async def get_risk(request: Request, risk_id: UUID):
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("risks").select("*").eq("id", str(risk_id)).limit(1).execute()
        if not res.data:
            raise HTTPException(404, "risk_not_found")
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_risk failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/risks/{risk_id}")
async def patch_risk(request: Request, risk_id: UUID, payload: UpdateRiskInput):
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    scope = get_user_scope(request.state.token)
    require_role_not(scope, _RISK_WRITE_BLOCKED_ROLES, "editar riscos")

    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "no_valid_fields")
    _validate_risk_payload(data, partial=True)

    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("risks").update(data).eq("id", str(risk_id)).execute()
        if not res.data:
            raise HTTPException(404, "risk_not_found")
        logger.info(
            "Risk patched id=%s fields=%s by=%s",
            risk_id, list(data.keys()), scope.get("user_id"),
        )
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_risk failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/risks/{risk_id}")
async def delete_risk(request: Request, risk_id: UUID):
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    scope = get_user_scope(request.state.token)
    require_role_not(scope, _RISK_WRITE_BLOCKED_ROLES, "remover riscos")
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("risks").delete().eq("id", str(risk_id)).execute()
        # supabase delete não retorna data se RLS falhar — verificar GET antes? Mantém simples.
        logger.info("Risk deleted id=%s by=%s", risk_id, scope.get("user_id"))
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_risk failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/goals/{goal_id}/risks")
async def list_goal_risks(request: Request, goal_id: UUID):
    """Riscos vinculados a um goal específico."""
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("risks").select("*")
            .eq("linked_goal_id", str(goal_id))
            .order("risk_score", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"list_goal_risks failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sipoc/processes/{process_id}/risks")
async def list_sipoc_process_risks(request: Request, process_id: UUID):
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("risks").select("*")
            .eq("linked_sipoc_process_id", str(process_id))
            .order("risk_score", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"list_sipoc_process_risks failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sipoc/components/{component_id}/risks")
async def list_sipoc_component_risks(request: Request, component_id: UUID):
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("risks").select("*")
            .eq("linked_sipoc_component_id", str(component_id))
            .order("risk_score", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"list_sipoc_component_risks failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# (fim Risk Register)
# =============================================================================


# =============================================================================
# Daedalus BPMN Diagrams — bpmn_diagrams + bpmn_diagram_versions
# Doc: docs/EXECUCAO-G1-RISK-REGISTER-E-DAEDALUS.md §2.5
# Tabelas criadas pelo PR #154.
# Engine própria (NÃO BPMN 2.0 XML — diagram_json é shape @xyflow/react).
# =============================================================================

_BPMN_VALID_GENERATED_BY = {"manual", "athena", "daedalus", "imported"}
_BPMN_WRITE_BLOCKED_ROLES = _SIPOC_EDIT_BLOCKED_ROLES  # mesma política do RACI/risks


class NewBpmnDiagramInput(BaseModel):
    """Input para POST /api/bpmn/diagrams. company_id vem do JWT."""
    name: str
    diagram_json: Dict[str, Any]
    description: Optional[str] = None
    generated_by: Optional[str] = "manual"
    generated_by_task_id: Optional[str] = None
    linked_sipoc_process_id: Optional[str] = None
    linked_workflow_id: Optional[str] = None
    linked_goal_id: Optional[str] = None

    class Config:
        extra = "ignore"


class UpdateBpmnDiagramInput(BaseModel):
    """Input para PATCH /api/bpmn/diagrams/{id}. Tudo opcional."""
    name: Optional[str] = None
    description: Optional[str] = None
    diagram_json: Optional[Dict[str, Any]] = None
    linked_sipoc_process_id: Optional[str] = None
    linked_workflow_id: Optional[str] = None
    linked_goal_id: Optional[str] = None

    class Config:
        extra = "ignore"


def _validate_bpmn_diagram_json(diagram_json: Any) -> None:
    """Validação mínima do shape — handler Daedalus (PR G) fará validação BPMN
    rules (nó start único, gateways com ≥2 saídas, etc.)."""
    if not isinstance(diagram_json, dict):
        raise HTTPException(400, "BPMN: diagram_json deve ser objeto JSON.")
    nodes = diagram_json.get("nodes")
    if nodes is None or not isinstance(nodes, list):
        raise HTTPException(400, "BPMN: diagram_json.nodes deve ser lista (pode ser vazia).")
    edges = diagram_json.get("edges")
    if edges is None or not isinstance(edges, list):
        raise HTTPException(400, "BPMN: diagram_json.edges deve ser lista (pode ser vazia).")


def _validate_bpmn_name(name: Any) -> str:
    if not isinstance(name, str):
        raise HTTPException(400, "BPMN: 'name' obrigatório (string).")
    n = name.strip()
    if len(n) < 3:
        raise HTTPException(400, "BPMN: 'name' deve ter ao menos 3 caracteres.")
    if len(n) > 200:
        raise HTTPException(400, "BPMN: 'name' não pode passar de 200 caracteres.")
    return n


@app.post("/api/bpmn/diagrams")
async def create_bpmn_diagram(request: Request, payload: NewBpmnDiagramInput):
    """Cria diagrama BPMN. company_id vem do JWT (tenant scope)."""
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    scope = get_user_scope(request.state.token)
    require_role_not(scope, _BPMN_WRITE_BLOCKED_ROLES, "criar diagramas BPMN")

    company_id = _resolve_company_id(request)
    if not company_id:
        raise HTTPException(400, "company_id_required (JWT sem tenant scope)")

    data = payload.model_dump(exclude_none=True)
    data["name"] = _validate_bpmn_name(data.get("name"))
    _validate_bpmn_diagram_json(data.get("diagram_json"))
    gen_by = data.get("generated_by", "manual")
    if gen_by not in _BPMN_VALID_GENERATED_BY:
        raise HTTPException(
            400,
            f"BPMN: generated_by '{gen_by}' inválido. Esperado: {sorted(_BPMN_VALID_GENERATED_BY)}.",
        )
    data["generated_by"] = gen_by
    data["company_id"] = company_id

    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("bpmn_diagrams").insert(data).execute()
        if not res.data:
            raise HTTPException(500, "BPMN: insert returned empty")
        logger.info(
            "BPMN diagram created id=%s name=%r generated_by=%s by=%s",
            res.data[0].get("id"), data.get("name"), gen_by, scope.get("user_id"),
        )
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_bpmn_diagram failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/companies/{company_id}/bpmn/diagrams")
async def list_company_bpmn_diagrams(
    request: Request,
    company_id: UUID,
    linked_sipoc_process_id: Optional[UUID] = None,
    linked_workflow_id: Optional[UUID] = None,
    linked_goal_id: Optional[UUID] = None,
    generated_by: Optional[str] = None,
):
    """Lista diagramas BPMN da company com filtros opcionais por vínculo/origem.
    Ordena por updated_at DESC (mais recentes primeiro)."""
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        q = client.table("bpmn_diagrams").select("*").eq("company_id", str(company_id))
        if linked_sipoc_process_id:
            q = q.eq("linked_sipoc_process_id", str(linked_sipoc_process_id))
        if linked_workflow_id:
            q = q.eq("linked_workflow_id", str(linked_workflow_id))
        if linked_goal_id:
            q = q.eq("linked_goal_id", str(linked_goal_id))
        if generated_by:
            if generated_by not in _BPMN_VALID_GENERATED_BY:
                raise HTTPException(400, f"generated_by inválido: {generated_by}")
            q = q.eq("generated_by", generated_by)
        res = q.order("updated_at", desc=True).execute()
        return res.data or []
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"list_company_bpmn_diagrams failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bpmn/diagrams/{diagram_id}")
async def get_bpmn_diagram(request: Request, diagram_id: UUID):
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("bpmn_diagrams").select("*").eq("id", str(diagram_id)).limit(1).execute()
        if not res.data:
            raise HTTPException(404, "bpmn_diagram_not_found")
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_bpmn_diagram failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/bpmn/diagrams/{diagram_id}")
async def patch_bpmn_diagram(request: Request, diagram_id: UUID, payload: UpdateBpmnDiagramInput):
    """Edita diagrama. Mudança em diagram_json dispara snapshot da versão
    anterior em bpmn_diagram_versions (trigger DB). Mudança só de metadata
    não snapshota."""
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    scope = get_user_scope(request.state.token)
    require_role_not(scope, _BPMN_WRITE_BLOCKED_ROLES, "editar diagramas BPMN")

    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "no_valid_fields")
    if "name" in data:
        data["name"] = _validate_bpmn_name(data["name"])
    if "diagram_json" in data:
        _validate_bpmn_diagram_json(data["diagram_json"])

    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("bpmn_diagrams").update(data).eq("id", str(diagram_id)).execute()
        if not res.data:
            raise HTTPException(404, "bpmn_diagram_not_found")
        logger.info(
            "BPMN diagram patched id=%s fields=%s new_version=%s by=%s",
            diagram_id, list(data.keys()), res.data[0].get("version"), scope.get("user_id"),
        )
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_bpmn_diagram failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/bpmn/diagrams/{diagram_id}")
async def delete_bpmn_diagram(request: Request, diagram_id: UUID):
    """Remove diagrama. CASCADE deleta também todas as versões em bpmn_diagram_versions."""
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    scope = get_user_scope(request.state.token)
    require_role_not(scope, _BPMN_WRITE_BLOCKED_ROLES, "remover diagramas BPMN")
    try:
        client = get_authenticated_client(request.state.token)
        client.table("bpmn_diagrams").delete().eq("id", str(diagram_id)).execute()
        logger.info("BPMN diagram deleted id=%s by=%s", diagram_id, scope.get("user_id"))
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_bpmn_diagram failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/bpmn/diagrams/{diagram_id}/duplicate")
async def duplicate_bpmn_diagram(request: Request, diagram_id: UUID, payload: Optional[Dict[str, Any]] = None):
    """Clona um diagrama existente. Novo registro com version=1 e generated_by='manual'
    (mesmo que o original tenha vindo de athena/daedalus — o clone é trabalho humano).
    Opcional: payload {name: '...'} para sobrescrever o nome do clone (default: '<original> (cópia)')."""
    if not supabase:
        raise HTTPException(503, "supabase_unavailable")
    scope = get_user_scope(request.state.token)
    require_role_not(scope, _BPMN_WRITE_BLOCKED_ROLES, "duplicar diagramas BPMN")

    try:
        client = get_authenticated_client(request.state.token)
        orig_res = client.table("bpmn_diagrams").select("*").eq("id", str(diagram_id)).limit(1).execute()
        if not orig_res.data:
            raise HTTPException(404, "bpmn_diagram_not_found")
        original = orig_res.data[0]

        override_name = (payload or {}).get("name") if isinstance(payload, dict) else None
        new_name = _validate_bpmn_name(override_name) if override_name else f"{original.get('name', 'Diagrama')} (cópia)"

        clone = {
            "company_id": original["company_id"],
            "name": new_name,
            "description": original.get("description"),
            "diagram_json": original["diagram_json"],
            "linked_sipoc_process_id": original.get("linked_sipoc_process_id"),
            "linked_workflow_id": original.get("linked_workflow_id"),
            "linked_goal_id": original.get("linked_goal_id"),
            "generated_by": "manual",
        }

        res = client.table("bpmn_diagrams").insert(clone).execute()
        if not res.data:
            raise HTTPException(500, "BPMN duplicate: insert returned empty")
        logger.info(
            "BPMN diagram duplicated source=%s clone=%s by=%s",
            diagram_id, res.data[0].get("id"), scope.get("user_id"),
        )
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"duplicate_bpmn_diagram failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/bpmn/diagrams/{diagram_id}/versions")
async def list_bpmn_diagram_versions(request: Request, diagram_id: UUID):
    """Histórico append-only de versões do diagrama. Ordem: mais recente primeiro.
    Não inclui a versão atual (que vive em bpmn_diagrams.diagram_json) —
    versions tem apenas as anteriores que foram snapshotadas pelo trigger."""
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("bpmn_diagram_versions")
            .select("*")
            .eq("diagram_id", str(diagram_id))
            .order("version", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"list_bpmn_diagram_versions failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# (fim Daedalus BPMN)
# =============================================================================


@app.get("/api/sipoc/templates")
async def list_templates():
    return get_templates_list()

@app.get("/api/sipoc/templates/{template_id}")
async def get_template(template_id: str):
    return get_template_detail(template_id)

@app.post("/api/sipoc/templates/{template_id}/clone")
async def clone_template_to_process(request: Request, template_id: str, payload: Dict[str, Any]):
    if not supabase:
        return {"success": False}
    try:
        client = get_authenticated_client(request.state.token)
        template = get_template_detail(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
            
        sector_id = payload.get("sector_id")
        process_name = payload.get("name", template["name"])
        
        # 1. Criar o novo processo
        proc_res = client.table("sipoc_processes").insert({
            "sector_id": sector_id,
            "name": process_name,
            "description": template["description"],
            "status": "rascunho"
        }).execute()
        
        if not proc_res.data:
             raise HTTPException(status_code=500, detail="Failed to create process")
             
        new_process = proc_res.data[0]
        
        # 2. Inserir componentes do template
        for i, comp in enumerate(template["components"]):
            client.table("sipoc_components").insert({
                "process_id": new_process["id"],
                "type": comp["type"],
                "content": comp["content"],
                "order": i
            }).execute()
            
        return {"success": True, "process_id": new_process["id"]}
    except Exception as e:
        logger.error(f"clone_template failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sipoc/analytics")
async def get_sipoc_analytics(request: Request):
    if not supabase:
        return {}
    try:
        client = get_authenticated_client(request.state.token)
        procs = client.table("sipoc_processes").select("*").execute()
        comps = client.table("sipoc_components").select("*").execute()
        
        return calculate_sipoc_kpis(procs.data or [], comps.data or [])
    except Exception as e:
        logger.error(f"get_sipoc_analytics failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sipoc/processes/{process_id}/approve")
async def approve_process(request: Request, process_id: UUID, payload: Dict[str, Any]):
    if not supabase:
        return {"success": False}
    try:
        client = get_authenticated_client(request.state.token)
        action = payload.get("action", "submit")
        
        # 1. Buscar status atual
        proc = client.table("sipoc_processes").select("status").eq("id", process_id).single().execute()
        current_status = proc.data.get('status', 'rascunho')
        
        # 2. Calcular novo status
        new_status = handle_status_transition(current_status, action)
        
        # 3. Atualizar
        client.table("sipoc_processes").update({"status": new_status}).eq("id", process_id).execute()
        
        return {"success": True, "new_status": new_status}
    except Exception as e:
        logger.error(f"approve_process failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sipoc/diagnose")
async def diagnose_activity(payload: Dict[str, Any]):
    text = payload.get("text", "")
    if not text:
        return {"findings": []}
    
    findings = run_diagnostic(text)
    return {"findings": findings}

@app.get("/api/sipoc/processes/{process_id}/edges")
async def list_sipoc_edges(request: Request, process_id: UUID):
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("sipoc_edges").select("*").eq("process_id", process_id).execute()
        return res.data or []
    except Exception as e:
        logger.error(f"list_sipoc_edges failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/sipoc/processes/{process_id}/edges")
async def save_sipoc_edges(request: Request, process_id: UUID, payload: List[Dict[str, Any]]):
    if not supabase:
        return {"success": False}
    try:
        client = get_authenticated_client(request.state.token)
        # 1. Limpar edges antigas
        client.table("sipoc_edges").delete().eq("process_id", process_id).execute()
        # 2. Inserir novas
        if payload:
            for edge in payload:
                edge["process_id"] = str(process_id)
            client.table("sipoc_edges").insert(payload).execute()
        return {"success": True}
    except Exception as e:
        logger.error(f"save_sipoc_edges failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# === Morpheus Dispatcher Scheduler ===

async def morpheus_scheduler(interval_s: int):
    logger.info(f"[morpheus] scheduler started interval={interval_s}s")
    while True:
        try:
            if supabase:
                dispatcher = MorpheusDispatcher(supabase)
                dispatched = dispatcher.dispatch()
                if dispatched:
                    logger.info(f"[morpheus] {dispatched} task(s) dispatched this cycle")
            else:
                logger.debug("[morpheus] skip tick: no supabase client")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[morpheus] scheduler error: {e}")
        await asyncio.sleep(interval_s)

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
    app.state.doctor_task = asyncio.create_task(doctor_scheduler(interval_s=30))
    app.state.morpheus_task = asyncio.create_task(morpheus_scheduler(interval_s=10))

@app.on_event("shutdown")
async def shutdown_event():
    for task_attr in ("doctor_task", "morpheus_task"):
        task = getattr(app.state, task_attr, None)
        if task:
            task.cancel()
            try:
                await task
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
    "companyId": "8487648a-b4db-482d-a541-898c4d249882",
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
    "companyId": "8487648a-b4db-482d-a541-898c4d249882",
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
    "companyId": "8487648a-b4db-482d-a541-898c4d249882",
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
    "companyId": "8487648a-b4db-482d-a541-898c4d249882",
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
    "companyId": "8487648a-b4db-482d-a541-898c4d249882",
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
    "companyId": "8487648a-b4db-482d-a541-898c4d249882",
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
    "companyId": "8487648a-b4db-482d-a541-898c4d249882",
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
    "companyId": "8487648a-b4db-482d-a541-898c4d249882",
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
    "companyId": "8487648a-b4db-482d-a541-898c4d249882",
    "parentGoalId": None,
    "title": "Clear 50 Containers",
    "metric": "clearances",
    "target": 50,
    "current": 12
}]

MOCK_COMPANIES = [{
    "id": "8487648a-b4db-482d-a541-898c4d249882",
    "name": "Vectra Cargo",
    "mission": "Logística Aduaneira Autônoma",
    "ownerUserId": "40000000-0000-4000-8000-000000000001",
    "slug": "vectra-cargo",
    "members": [{"userId": "40000000-0000-4000-8000-000000000001", "role": "admin", "joinedAt": "2026-04-19T00:00:00Z"}],
    "createdAt": "2026-04-19T00:00:00Z"
}]

MOCK_ROUTINES = [
    {
        "id": "rot00000-0000-4000-8000-000000000001",
        "companyId": "8487648a-b4db-482d-a541-898c4d249882",
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
        "companyId": "8487648a-b4db-482d-a541-898c4d249882",
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
        "companyId": "8487648a-b4db-482d-a541-898c4d249882",
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

_REAL_COMPANY_ID = "01b9b40e-2fc4-4cc5-a91e-cb95385d2aa2"
# IDs abaixo são apenas para modo mock (supabase=None). No DB real os UUIDs são gerados pelo gen_random_uuid().

MOCK_ADAPTERS = [
    {
        "id": "adp00000-0000-4000-8000-000000000001",
        "companyId": _REAL_COMPANY_ID,
        "slug": "claude_code",
        "displayName": "Claude Code",
        "provider": "anthropic",
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
    {
        "id": "adp00000-0000-4000-8000-000000000002",
        "companyId": _REAL_COMPANY_ID,
        "slug": "codex",
        "displayName": "Codex",
        "provider": "openai",
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
    {
        "id": "adp00000-0000-4000-8000-000000000003",
        "companyId": _REAL_COMPANY_ID,
        "slug": "mcp-imap",
        "displayName": "IMAP E-mail (MCP)",
        "provider": "imap",
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
    {
        "id": "adp00000-0000-4000-8000-000000000004",
        "companyId": _REAL_COMPANY_ID,
        "slug": "mcp-gmail",
        "displayName": "Google Gmail (MCP)",
        "provider": "google",
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
    {
        "id": "adp00000-0000-4000-8000-000000000005",
        "companyId": _REAL_COMPANY_ID,
        "slug": "mcp-slack",
        "displayName": "Slack Connect (MCP)",
        "provider": "slack",
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
    {
        "id": "adp00000-0000-4000-8000-000000000006",
        "companyId": _REAL_COMPANY_ID,
        "slug": "mcp-github",
        "displayName": "GitHub Ops (MCP)",
        "provider": "github",
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
]

MOCK_ADAPTER_FIELDS = [
    # claude_code: modelo + temperatura
    {
        "id": "fld00000-0000-4000-8000-000000000001",
        "companyId": _REAL_COMPANY_ID,
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
        "companyId": _REAL_COMPANY_ID,
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
    # mcp-imap: credenciais de acesso ao servidor de e-mail
    {
        "id": "fld00000-0000-4000-8000-000000000010",
        "companyId": _REAL_COMPANY_ID,
        "adapterId": "adp00000-0000-4000-8000-000000000003",
        "fieldKey": "imap_host",
        "fieldLabel": "Servidor IMAP",
        "fieldType": "text",
        "isRequired": True,
        "optionsJson": None,
        "triggerCondition": None,
        "sortOrder": 10,
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
    {
        "id": "fld00000-0000-4000-8000-000000000011",
        "companyId": _REAL_COMPANY_ID,
        "adapterId": "adp00000-0000-4000-8000-000000000003",
        "fieldKey": "imap_port",
        "fieldLabel": "Porta IMAP",
        "fieldType": "number",
        "isRequired": True,
        "optionsJson": None,
        "triggerCondition": None,
        "sortOrder": 20,
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
    {
        "id": "fld00000-0000-4000-8000-000000000012",
        "companyId": _REAL_COMPANY_ID,
        "adapterId": "adp00000-0000-4000-8000-000000000003",
        "fieldKey": "email",
        "fieldLabel": "Endereço de E-mail",
        "fieldType": "text",
        "isRequired": True,
        "optionsJson": None,
        "triggerCondition": None,
        "sortOrder": 30,
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
    {
        "id": "fld00000-0000-4000-8000-000000000013",
        "companyId": _REAL_COMPANY_ID,
        "adapterId": "adp00000-0000-4000-8000-000000000003",
        "fieldKey": "password",
        "fieldLabel": "Senha / App Password",
        "fieldType": "secret",
        "isRequired": True,
        "optionsJson": None,
        "triggerCondition": None,
        "sortOrder": 40,
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
]

MOCK_AGENT_ADAPTER_CONFIGS = [
    {
        "id": "cfg00000-0000-4000-8000-000000000001",
        "companyId": _REAL_COMPANY_ID,
        "agentId": "a0000000-0000-4000-8000-000000000001",
        "adapterId": "adp00000-0000-4000-8000-000000000001",
        "fieldValuesJson": {
            "model_id": "claude-opus-4-7-thinking-high",
            "temperature": 0.2,
        },
        "isActive": True,
        "createdAt": "2026-04-19T00:00:00Z",
        "updatedAt": "2026-04-19T00:00:00Z",
    },
]

MOCK_AGENT_EXECUTION_CONFIGS = [
    {
        "id": "exe00000-0000-4000-8000-000000000001",
        "companyId": "8487648a-b4db-482d-a541-898c4d249882",
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

MOCK_AGENT_SPECIALTY_CONFIGS: list = []

MOCK_AUDIT = [{
    "id": "7a5c0000-0000-4000-8000-000000000001",
    "company_id": "8487648a-b4db-482d-a541-898c4d249882",
    "actor_type": "system",
    "actor_id": "system-1",
    "action": "boot",
    "target": "system",
    "payload": {},
    "created_at": "2026-04-19T00:00:00Z"
}]

MOCK_APPROVAL = [{
    "id": "7a5c0000-0000-4000-8000-000000000001",
    "company_id": "8487648a-b4db-482d-a541-898c4d249882",
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
    if not supabase_auth:
        logger.error("Login abortado: supabase_auth não inicializado (verifique .env)")
        raise HTTPException(status_code=503, detail="Serviço de autenticação indisponível")
    
    try:
        logger.info(f"Tentativa de login para: {payload.email}")
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

        # Mapeamento robusto (VEC-194)
        logger.info("Mapeando metadados do usuário...")
        user_meta = getattr(res.user, "user_metadata", {}) or {}
        app_meta = getattr(res.user, "app_metadata", {}) or {}
        vc = app_meta.get("vectraclip", {})
        if not isinstance(vc, dict): vc = {}

        logger.info(f"Extraindo Role e Company (app_meta: {app_meta})")
        raw_role = vc.get("role") or user_meta.get("role") or app_meta.get("role") or "admin"
        company_id = vc.get("company_id") or app_meta.get("company_id") or user_meta.get("company_id")

        # Se não veio nos metadados do JWT, busca em app_users (fonte de verdade)
        if not company_id and supabase:
            try:
                lookup = supabase.table("app_users").select("company_id,role").eq("id", str(res.user.id)).execute()
                if lookup.data:
                    company_id = lookup.data[0].get("company_id")
                    raw_role = lookup.data[0].get("role") or raw_role
                    logger.info(f"company_id resolvido via app_users: {company_id}")
            except Exception as lu_err:
                logger.warning(f"Falha ao buscar app_users: {lu_err}")

        if not company_id:
            company_id = MOCK_USER["companyId"]
            logger.warning(f"company_id não encontrado para {res.user.id}, usando fallback mock")
        
        display_name = (
            user_meta.get("full_name")
            or user_meta.get("name")
            or (res.user.email.split("@")[0] if res.user.email else "User")
        )

        logger.info("Construindo objeto User...")
        user_data = User(
            id=str(res.user.id),
            name=str(display_name),
            email=str(res.user.email or ""),
            role=_zod_user_role(str(raw_role)),
            company_id=str(company_id),
            avatar_url=user_meta.get("avatar_url"),
            created_at=_user_created_at_to_utc(getattr(res.user, "created_at", None)),
        )

        logger.info("Construindo objeto AuthSession...")
        session = AuthSession(
            access_token=str(res.session.access_token),
            refresh_token=str(res.session.refresh_token),
            expires_at=_session_expires_to_utc(getattr(res.session, "expires_at", None)),
            user=user_data
        )

        logger.info("Login bem-sucedido, serializando resposta.")
        return session.to_zod_dict()

    except HTTPException:
        raise
    except Exception as e:
        err_msg = str(e).lower()
        # Captura erros comuns de autenticação do GoTrue/Supabase
        if "invalid login credentials" in err_msg or "invalid_credentials" in err_msg:
             logger.warning(f"Tentativa de login falhou (credenciais): {payload.email}")
             raise HTTPException(status_code=401, detail="E-mail ou senha incorretos")
             
        logger.error(f"Login CRITICAL FAILURE: {type(e).__name__} - {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Erro interno de autenticação: {str(e)}")

@app.get("/auth/me")
@app.get("/api/auth/me")
async def auth_me(request: Request):
    if not supabase:
        return MOCK_USER
    
    # Busca usuário real na tabela app_users do Supabase usando RLS
    try:
        token = request.state.token
        user_id = request.state.user_id
        
        if not token or not user_id:
             return MOCK_USER

        client = get_authenticated_client(token)
        res = client.table("app_users").select("*").eq("id", user_id).execute()
        
        if not res.data:
            logger.info(f"Usuário {user_id} não encontrado em app_users, usando fallback MOCK")
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
        logger.error(f"Erro em auth_me: {e}")
        # Em caso de erro catastrófico, retorna 401 para forçar re-login em vez de 500
        raise HTTPException(status_code=401, detail=f"Session error: {str(e)}")

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

        # Task #2 — fetch specialty_ids (lista, N:1) via lookup separado.
        # Bug anterior: `specialty_map[agent_id] = sc[specialty_id]` SOBRESCREVIA
        # quando havia múltiplas specialties por agente (Oracle hoje tem 3:
        # oracle-extract, oracle-rag, etc.). Agora acumula em lista.
        agent_ids = [r["id"] for r in res.data]
        specialty_map: Dict[str, List[str]] = {}
        if agent_ids:
            try:
                sc_res = client.table("agent_specialty_configs").select("agent_id,specialty_id").in_("agent_id", agent_ids).execute()
                for sc in sc_res.data:
                    agent_id = sc["agent_id"]
                    specialty_map.setdefault(agent_id, []).append(sc["specialty_id"])
            except Exception as sc_err:
                logger.warning(f"specialty_configs lookup failed (non-fatal): {sc_err}")

        rows = []
        for row in res.data:
            ids = specialty_map.get(row["id"], [])
            row["specialty_ids"] = ids
            # Backcompat: campo singular = primeira da lista (None se vazio)
            row["specialty_id"] = ids[0] if ids else None
            rows.append(Agent(**row).to_zod_dict())
        return rows
    except Exception as e:
        logger.error(f"get_agents failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

class NewAgentInput(BaseModel):
    name: str
    role: str
    adapterType: str
    tokenBudget: int
    systemPrompt: Optional[str] = None
    requiresApproval: bool = False
    platformUrl: Optional[str] = None

    class Config:
        extra = "ignore"

@app.post("/api/companies/{company_id}/agents")
@app.post("/companies/{company_id}/agents")
async def create_agent(company_id: str, payload: NewAgentInput):
    # DB CHECK constraint allows only claude_code|cursor|bot.
    # Map frontend enum values to DB-accepted values.
    _to_db = {"claude_code": "claude_code", "codex": "cursor", "shell": "bot", "webhook": "bot"}
    adapter_type = _to_db.get(payload.adapterType, "claude_code")

    row: Dict[str, Any] = {
        "company_id": company_id,
        "name": payload.name,
        "role": payload.role,
        "reports_to_id": None,
        "status": AgentStatus.IDLE,
        "token_budget": payload.tokenBudget,
        "current_burn_rate": 0,
        "adapter_type": adapter_type,
        "system_prompt": payload.systemPrompt,
        "requires_approval": payload.requiresApproval,
        "platform_url": payload.platformUrl or None,
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
        new_agent["specialtyId"] = None
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
        raise HTTPException(status_code=500, detail=str(e))

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
        out = []
        for row in res.data:
            try:
                out.append(Task(**row).to_zod_dict())
            except Exception as row_err:
                logger.warning(f"get_tasks: skipping invalid row id={row.get('id')}: {row_err}")
        return out
    except Exception as e:
        logger.error(f"get_tasks failed: {e}")
        return []

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
    inputJson: Optional[Dict[str, Any]] = None

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
        Literal[
            "backlog",
            "queued",
            "in_progress",
            "review",
            "done",
            "blocked",
            "skipped",
        ]
    ] = None
    operation_type: Optional[str] = Field(default=None, alias="operationType")
    budget_limit: Optional[int] = Field(default=None, alias="budgetLimit")
    spent: Optional[float] = None
    cost_usd: Optional[float] = Field(default=None, alias="costUsd")
    assigned_to_agent_id: Optional[str] = Field(
        default=None, alias="assignedToAgentId"
    )
    parent_task_id: Optional[str] = Field(default=None, alias="parentTaskId")
    goal_id: Optional[str] = Field(default=None, alias="goalId")
    output_json: Optional[Dict[str, Any]] = Field(default=None, alias="outputJson")
    input_json: Optional[Dict[str, Any]] = Field(default=None, alias="inputJson")

    class Config:
        populate_by_name = True
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
        "output_json": "outputJson",
        "input_json": "inputJson",
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
    validate_jwt_company_id(request.state.token, company_id)
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
    if payload.inputJson is not None:
        insert_row["input_json"] = payload.inputJson

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
    validate_jwt_company_id(request.state.token, company_id)
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
            err_str = str(e)
            if "row-level security" in err_str.lower() or "42501" in err_str or "insufficient_privilege" in err_str.lower():
                raise HTTPException(status_code=403, detail="Acesso negado pela política RLS — verifique app_metadata.vectraclip.company_id no JWT")
            logger.error(f"create_goal DB failed: {e}")
            raise HTTPException(status_code=500, detail=err_str)
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
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/companies")
@app.get("/companies")
async def get_companies(request: Request):
    if not supabase:
        return MOCK_COMPANIES

    try:
        q = supabase.table("companies").select("company_id,name,updated_at,tier,owner_user_id")
        caller_company = getattr(request.state, "company_id", None)
        if caller_company:
            q = q.eq("company_id", caller_company)
        res = q.order("name", desc=False).execute()

        # Resolve ownerUserId e members por company via app_users.
        owner_map: Dict[str, str] = {}
        members_map: Dict[str, List[Dict[str, Any]]] = {}
        company_ids = [str(r.get("company_id")) for r in (res.data or []) if r.get("company_id")]
        if company_ids:
            try:
                users_res = (
                    supabase.table("app_users")
                    .select("id,company_id,role,created_at")
                    .in_("company_id", company_ids)
                    .order("created_at", desc=False)
                    .execute()
                )
                for u in (users_res.data or []):
                    cid = str(u.get("company_id") or "")
                    uid = str(u.get("id") or "")
                    if not cid or not uid:
                        continue
                    role = str(u.get("role") or "member").lower()
                    joined = str(u.get("created_at") or "").replace("+00:00", "Z") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    members_map.setdefault(cid, []).append({
                        "userId": uid,
                        "role": role,
                        "joinedAt": joined,
                    })
                    if cid not in owner_map:
                        owner_map[cid] = uid
                    if role == "admin":
                        owner_map[cid] = uid
            except Exception as owner_err:
                logger.warning(f"owner resolution fallback in get_companies: {owner_err}")

        import re as _re
        def _slugify(name: str) -> str:
            return _re.sub(r"-{2,}", "-", _re.sub(r"[^a-z0-9]+", "-", (name or "").lower())).strip("-") or "company"

        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        out: List[Dict[str, Any]] = []
        for row in (res.data or []):
            cid = company_row_public_id(row)
            name = row.get("name") or ""
            owner_id = row.get("owner_user_id") or owner_map.get(str(cid)) or getattr(request.state, "user_id", None) or MOCK_USER["id"]
            created_raw = row.get("updated_at") or now_iso
            created_iso = str(created_raw).replace("+00:00", "Z")
            out.append({
                "id": cid,
                "name": name,
                "mission": row.get("mission") or "",
                "ownerUserId": owner_id,
                "slug": _slugify(name),
                "members": members_map.get(str(cid)) or [{"userId": owner_id, "role": "admin", "joinedAt": created_iso}],
                "createdAt": created_iso,
            })
        return out
    except Exception as e:
        logger.error(f"get_companies DB failed: {e}")
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
    # Schema vectraclip.companies: company_id (PK), name, tier, created_at, updated_at
    # — resposta HTTP mantém `id` (alias) para compat com frontend (fase 1 multi-tenant).
    # (sem mission/owner_user_id). Mantemos `mission` no contrato de resposta para
    # compatibilidade com o frontend.
    row: Dict[str, Any] = {
        "name": payload.name,
        "tier": "trial",
        "owner_user_id": getattr(request.state, "user_id", None) or MOCK_USER["id"],
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
        cid = company_row_public_id(created)
        return {
            "id": cid,
            "name": created["name"],
            "mission": payload.mission,
            "ownerUserId": created.get("owner_user_id") or getattr(request.state, "user_id", None) or MOCK_USER["id"],
            "createdAt": str(created.get("created_at", now)).replace("+00:00", "Z"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_company failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/companies/{company_id}")
@app.patch("/companies/{company_id}")
async def patch_company(request: Request, company_id: str, patch: UpdateCompanyInput):
    validate_jwt_company_id(request.state.token, company_id)
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
        # G2.1 (PR #168): GRANT UPDATE + policy companies_update_admin ampliada
        # (admin, platform_admin, consultant, company_admin). RLS protege tenant
        # no DB; antes este endpoint usava service_role (bypass).
        client = get_authenticated_client(request.state.token)
        res = client.table("companies").update(payload).eq("company_id", company_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="company_not_found")
        row = res.data[0]
        rid = company_row_public_id(row)
        return {
            "id": rid,
            "name": row["name"],
            "mission": "",
            "ownerUserId": getattr(request.state, "user_id", None) or MOCK_USER["id"],
            "createdAt": str(row.get("created_at")).replace("+00:00", "Z"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_company failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        check = supabase.table("companies").select("company_id").eq("company_id", company_id).execute()
        if not check.data:
            raise HTTPException(status_code=404, detail="company_not_found")
        # ACCEPTED bypass: DELETE company é operação plataforma (apagar tenant
        # inteiro tem risco maior que UPDATE). Sem GRANT DELETE pra authenticated
        # de propósito — só plataforma faz via service_role + RBAC platform_admin
        # checado em camada superior (validate_jwt_company_id acima protege
        # cross-tenant). G2.1 (PR #168) documentou esta decisão.
        supabase.table("companies").delete().eq("company_id", company_id).execute()
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_company failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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


async def _emit_heartbeat_internal(
    payload: NewHeartbeatInput,
    supabase_client=None,
    ws_manager_inst=None,
) -> Dict[str, Any]:
    """
    Núcleo de persistência + WS emit do heartbeat. Sem dependência de FastAPI Request.

    Chamado por:
    - POST /api/heartbeats (endpoint público — agentes externos)
    - src.managed_agents.router após execução CMA — fechamento sintético
      (heartbeat com status=idle/error e tokens consumidos pela inferência)

    Calcula custo, faz insert em vectraclip.heartbeats, emite WS `heartbeat`,
    acumula task cost. Args opcionais permitem injetar clientes em testes;
    default usa os globais do módulo.
    """
    now = datetime.now(timezone.utc).isoformat()
    _validate_active_model_id(payload.modelId)
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

    sb = supabase_client if supabase_client is not None else supabase
    wm = ws_manager_inst if ws_manager_inst is not None else ws_manager

    if sb:
        try:
            agent_res = sb.table("agents").select("company_id").eq("id", payload.agentId).execute()
            if agent_res.data:
                row["company_id"] = agent_res.data[0]["company_id"]
            res = sb.table("heartbeats").insert(row).execute()
            if res.data:
                hb_dict = Heartbeat(**res.data[0]).to_zod_dict()
                company_id = row.get("company_id")
                _accumulate_task_cost(payload.taskId, heartbeat_cost)
                if company_id and wm:
                    await wm.emit_heartbeat(company_id, hb_dict)
                return hb_dict
        except Exception as e:
            logger.error(f"_emit_heartbeat_internal DB failed: {e}")

    return {
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


@app.post("/api/heartbeats")
async def post_heartbeat(request: Request, payload: NewHeartbeatInput):
    """Agente reporta heartbeat; Claw persiste e emite WS `heartbeat`."""
    return await _emit_heartbeat_internal(payload)


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

# === Projects ===

@app.get("/api/companies/{company_id}/projects")
@app.get("/companies/{company_id}/projects")
@app.get("/api/projects")
async def get_projects(request: Request, company_id: str = None):
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        query = client.table("projects").select("*").order("created_at", desc=True)
        if company_id:
            query = query.eq("company_id", company_id)
        res = query.execute()
        return [Project(**row).to_zod_dict() for row in res.data]
    except PostgrestAPIError as e:
        if e.code == "PGRST205":
            logger.warning("vectraclip.projects missing; returning empty list")
            return []
        raise
    except Exception as e:
        logger.error(f"get_projects failed: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/companies/{company_id}/projects")
@app.post("/companies/{company_id}/projects")
async def create_project(company_id: str, request: Request):
    body = await request.json()
    payload = {
        "company_id": company_id,
        "name": body["name"],
        "mission": body.get("mission", ""),
        "status": body.get("status", "backlog"),
        "lead_agent_id": body.get("leadAgentId"),
        "target_date": body.get("targetDate"),
        "issue_completion_pct": body.get("issueCompletionPct", 0),
    }
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("projects").insert(payload).execute()
        return Project(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"create_project failed: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/projects/{project_id}")
@app.get("/projects/{project_id}")
async def get_project(project_id: str, request: Request):
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("projects").select("*").eq("id", project_id).single().execute()
        return Project(**res.data).to_zod_dict()
    except Exception as e:
        logger.error(f"get_project failed: {e}")
        raise HTTPException(404, "Project not found")


@app.patch("/api/projects/{project_id}")
@app.patch("/projects/{project_id}")
async def update_project(project_id: str, request: Request):
    body = await request.json()
    patch = {}
    for k, v in body.items():
        snake = "".join(["_" + c.lower() if c.isupper() else c for c in k]).lstrip("_")
        patch[snake] = v
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("projects").update(patch).eq("id", project_id).execute()
        return Project(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"update_project failed: {e}")
        raise HTTPException(500, str(e))


@app.delete("/api/projects/{project_id}")
@app.delete("/projects/{project_id}")
async def delete_project(project_id: str, request: Request):
    try:
        client = get_authenticated_client(request.state.token)
        client.table("projects").delete().eq("id", project_id).execute()
        return Response(status_code=204)
    except Exception as e:
        logger.error(f"delete_project failed: {e}")
        raise HTTPException(500, str(e))


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
# Runs & Transcripts (VEC-320)
# -----------------------------------------------------------------------------

@app.get("/api/companies/{company_id}/runs")
@app.get("/companies/{company_id}/runs")
async def list_runs(request: Request, company_id: str, agentId: Optional[str] = None, since: Optional[str] = None):
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        query = (
            client.table("runs")
            .select("*")
            .eq("company_id", company_id)
            .order("started_at", desc=True)
            .limit(100)
        )
        if agentId:
            query = query.eq("agent_id", agentId)
        if since:
            query = query.gte("started_at", since)
        res = query.execute()
        return [Run(**row).to_zod_dict() for row in res.data]
    except PostgrestAPIError as e:
        if e.code == "PGRST205":
            logger.warning("vectraclip.runs missing; returning empty list")
            return []
        raise
    except Exception as e:
        logger.error(f"list_runs failed: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/runs/{run_id}")
@app.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str):
    if not supabase:
        raise HTTPException(404, "run not found")
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("runs").select("*").eq("id", run_id).single().execute()
        return Run(**res.data).to_zod_dict()
    except Exception as e:
        logger.error(f"get_run failed: {e}")
        raise HTTPException(404, "run not found")


@app.get("/api/runs/{run_id}/transcript")
@app.get("/runs/{run_id}/transcript")
async def get_run_transcript(request: Request, run_id: str):
    if not supabase:
        return {"runId": run_id, "entries": []}
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("run_transcript_entries")
            .select("*")
            .eq("run_id", run_id)
            .order("created_at", desc=False)
            .execute()
        )
        entries = [RunTranscriptEntry(**row).to_zod_dict() for row in res.data]
        return {"runId": run_id, "entries": entries}
    except PostgrestAPIError as e:
        if e.code == "PGRST205":
            return {"runId": run_id, "entries": []}
        raise
    except Exception as e:
        logger.error(f"get_run_transcript failed: {e}")
        raise HTTPException(500, str(e))


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
    fieldType: Literal["text", "textarea", "number", "boolean", "select", "multiselect", "file_upload", "secret", "url"]
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
        caller_company = _resolve_company_id(request)
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
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/companies/{company_id}/adapters")
@app.post("/companies/{company_id}/adapters")
async def create_adapter(request: Request, company_id: str, payload: NewAdapterInput):
    validate_jwt_company_id(request.state.token, company_id)
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
        raise HTTPException(status_code=500, detail=str(e))


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
        caller_company = _resolve_company_id(request)
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
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/adapters/{adapter_id}/fields")
@app.post("/adapters/{adapter_id}/fields")
async def create_adapter_field(request: Request, adapter_id: str, payload: NewAdapterFieldInput):
    # Precisamos saber o company_id do adapter
    if not supabase:
        adapter = next((a for a in MOCK_ADAPTERS if a["id"] == adapter_id), None)
        company_id = adapter["companyId"] if adapter else "8487648a-b4db-482d-a541-898c4d249882"
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
        return [_routine_wire_dict(row) for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_routines failed: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/companies/{company_id}/routines")
@app.post("/companies/{company_id}/routines")
async def create_routine(request: Request, company_id: str, payload: Dict[str, Any]):
    validate_jwt_company_id(request.state.token, company_id)
    # Payload raw para flexibilidade de triggers
    row = {
        "company_id": company_id,
        "name": payload.get("name"),
        "status": payload.get("status") or "active",
        "schedule": payload.get("schedule"),
        "agent_id": payload.get("agentId"),
        "prompt_template": payload.get("promptTemplate"),
        "operation_type": payload.get("operationType"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    merged_metadata = _merge_routine_execution_params_payload(payload)
    if merged_metadata is not None:
        row["metadata"] = merged_metadata

    if not supabase:
        new_rot = row.copy()
        new_rot["id"] = f"rot_tmp_{int(datetime.now().timestamp())}"
        new_rot["companyId"] = new_rot.pop("company_id")
        new_rot["createdAt"] = new_rot.pop("created_at")
        MOCK_ROUTINES.append(new_rot)
        return new_rot

    try:
        res = supabase.table("routines").insert(row).execute()
        return _routine_wire_dict(res.data[0])
    except Exception as e:
        logger.error(f"create_routine failed: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/routines/{routine_id}")
@app.get("/routines/{routine_id}")
async def get_routine(request: Request, routine_id: str):
    if not supabase:
        row = next((r for r in MOCK_ROUTINES if r.get("id") == routine_id), None)
        if not row:
            raise HTTPException(404, "routine_not_found")
        return row
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("routines").select("*").eq("id", routine_id).limit(1).execute()
        if not res.data:
            raise HTTPException(404, "routine_not_found")
        return _routine_wire_dict(res.data[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_routine failed: {e}")
        raise HTTPException(500, str(e))


@app.patch("/api/routines/{routine_id}")
@app.patch("/routines/{routine_id}")
async def patch_routine(request: Request, routine_id: str, payload: Dict[str, Any]):
    if not supabase:
        row = next((r for r in MOCK_ROUTINES if r.get("id") == routine_id), None)
        if not row:
            raise HTTPException(404, "routine_not_found")
        row.update(payload)
        return row
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("routines").select("id,metadata").eq("id", routine_id).limit(1).execute()
        if not res.data:
            raise HTTPException(404, "routine_not_found")
        current_metadata = res.data[0].get("metadata")

        # Normalise camelCase keys from the frontend to snake_case for DB
        CAMEL_TO_SNAKE = {
            "agentId": "agent_id",
            "promptTemplate": "prompt_template",
            "nextRunAt": "next_run_at",
            "operationType": "operation_type",
        }
        normalised = {CAMEL_TO_SNAKE.get(k, k): v for k, v in payload.items()}

        ALLOWED = {
            "name",
            "status",
            "schedule",
            "agent_id",
            "prompt_template",
            "metadata",
            "next_run_at",
            "operation_type",
        }
        update_data = {k: v for k, v in normalised.items() if k in ALLOWED}
        if payload.get("executionParams") is not None or payload.get("metadata") is not None:
            merged_metadata = _merge_routine_execution_params_payload(
                payload,
                current_metadata if isinstance(current_metadata, dict) else None,
            )
            if merged_metadata is not None:
                update_data["metadata"] = merged_metadata
        # Evita apagar agendamento da próxima execução quando o front envia null por omissão.
        for nullable_ts in ("next_run_at",):
            if nullable_ts in update_data and update_data[nullable_ts] is None:
                update_data.pop(nullable_ts)
        if not update_data:
            raise HTTPException(400, "no_valid_fields")

        updated = client.table("routines").update(update_data).eq("id", routine_id).execute()
        return _routine_wire_dict(updated.data[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_routine failed: {e}")
        raise HTTPException(500, str(e))


@app.delete("/api/routines/{routine_id}")
@app.delete("/routines/{routine_id}")
async def delete_routine(request: Request, routine_id: str):
    if not supabase:
        before = len(MOCK_ROUTINES)
        MOCK_ROUTINES[:] = [r for r in MOCK_ROUTINES if r.get("id") != routine_id]
        if len(MOCK_ROUTINES) == before:
            raise HTTPException(404, "routine_not_found")
        return Response(status_code=204)
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("routines").select("id").eq("id", routine_id).limit(1).execute()
        if not res.data:
            raise HTTPException(404, "routine_not_found")
        client.table("routines").delete().eq("id", routine_id).execute()
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_routine failed: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/agents/{agent_id}/routines")
@app.get("/agents/{agent_id}/routines")
async def list_agent_routines(request: Request, agent_id: str):
    if not supabase:
        return [r for r in MOCK_ROUTINES if r.get("agentId") == agent_id]
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("routines").select("*").eq("agent_id", agent_id).execute()
        return [_routine_wire_dict(row) for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_agent_routines failed: {e}")
        raise HTTPException(500, str(e))


KRONOS_AGENT_ID = "9c8d7e6f-5a4b-4321-9876-543210fedcba"
_KRONOS_ROUTINE_OPERATIONS = (
    "financial-audit",
    "financial-bookkeeping",
    "conciliacao-backlog",
    "planner-import-ofx",
    "planner-categorize-pendings",
)


def _routine_wire_dict(row: dict) -> dict:
    from src.agents.kronos import extract_routine_execution_params

    wire = Routine(**row).to_zod_dict()
    params = extract_routine_execution_params(row.get("metadata"))
    if params:
        wire["executionParams"] = params
    return wire


def _merge_routine_execution_params_payload(
    payload: Dict[str, Any],
    current_metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    from src.agents.kronos import merge_routine_execution_params

    execution_params = payload.get("executionParams")
    metadata = payload.get("metadata")
    if execution_params is None and metadata is None:
        return current_metadata
    return merge_routine_execution_params(
        metadata if isinstance(metadata, dict) else current_metadata,
        execution_params if isinstance(execution_params, dict) else None,
    )


def _resolve_routine_operation_type(routine_row: dict) -> str:
    explicit = str(routine_row.get("operation_type") or "").strip()
    if explicit and explicit != "email_lead":
        return explicit
    agent_id = str(routine_row.get("agent_id") or "")
    if agent_id == KRONOS_AGENT_ID:
        return "financial-bookkeeping"
    return explicit or "email_lead"


@app.post("/api/routines/{routine_id}/run-now")
@app.post("/routines/{routine_id}/run-now")
async def run_routine_now(request: Request, routine_id: str):
    if not supabase:
        row = next((r for r in MOCK_ROUTINES if r.get("id") == routine_id), None)
        if not row:
            raise HTTPException(404, "routine_not_found")
        return {"triggered": True, "routineId": routine_id}
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("routines").select("*").eq("id", routine_id).limit(1).execute()
        if not res.data:
            raise HTTPException(404, "routine_not_found")
        routine_row = res.data[0]
        now_utc = datetime.now(timezone.utc)
        now_iso = now_utc.isoformat()
        schedule = routine_row.get("schedule") or {}
        cron_expr = (
            routine_row.get("cron_expression")
            or (schedule.get("cron") if isinstance(schedule, dict) else None)
            or ""
        )
        tz_name = (schedule.get("timezone") if isinstance(schedule, dict) else None) or "UTC"
        next_run_iso = _compute_next_run_at(now_utc, cron_expr, tz_name)

        # Mark current run and pre-compute next run so UI/daemon stay in sync.
        routine_update = {"last_run_at": now_iso}
        if next_run_iso:
            routine_update["next_run_at"] = next_run_iso
        client.table("routines").update(routine_update).eq("id", routine_id).execute()

        # Create a Task record with status=queued so the daemon picks it up
        prompt_template = routine_row.get("prompt_template") or ""
        description = prompt_template \
            .replace("{{now}}", now_iso) \
            .replace("{{lastRun}}", routine_row.get("last_run_at") or "nunca")
        operation_type = _resolve_routine_operation_type(routine_row)
        input_json = None
        if operation_type in _KRONOS_ROUTINE_OPERATIONS:
            from src.agents.kronos import build_kronos_input_json

            metadata = routine_row.get("metadata")
            input_json = build_kronos_input_json(
                description=description,
                metadata=metadata if isinstance(metadata, dict) else None,
            )
            input_json = dict(input_json)
            input_json["routine_id"] = routine_id
        task_payload = {
            "company_id": routine_row.get("company_id"),
            "assigned_to_agent_id": routine_row.get("agent_id"),
            "title": f"[Rotina] {routine_row.get('name', 'Rotina')}",
            "description": description,
            "status": "queued",
            "operation_type": operation_type,
            "output_json": (
                {"hermes_leads": []}
                if operation_type == "email_lead"
                else {}
            ),
            "budget_limit": 0,
            "spent": 0,
            "cost_usd": 0,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        if input_json is not None:
            task_payload["input_json"] = input_json

        # Task #43 — Se routine está vinculada a um workflow_definition,
        # MATERIALIZA a árvore inteira via TaskFactory.materialize_workflow.
        # Substitui o INSERT single (task standalone). Resultado:
        #   • Parent task (status=in_progress, operation_type=orchestration)
        #   • N child tasks, primeira queued (entrypoint), demais backlog
        #   • Cada child com workflow_step_id + assigned_to_agent_id resolvido
        #     via step.specialty_slug (TaskFactory usa MorpheusDispatcher
        #     pra _find_agent pelo specialty).
        #   • dependency_step_codes / successor_step_codes alimentam
        #     TaskFactory.promote_successors_after_completion → avança DAG
        #     quando uma child termina.
        # Acordo arquitetural: "nada hardcoded". Handoff Kronos → Hermes
        # Reporter agora é Step 3 do workflow, não constante em código.
        wf_def_id = routine_row.get("workflow_definition_id")
        if wf_def_id:
            try:
                wf_slug_res = (
                    supabase.table("workflow_definitions")
                    .select("slug")
                    .eq("id", wf_def_id)
                    .limit(1)
                    .execute()
                )
                wf_slug = (
                    (wf_slug_res.data or [{}])[0].get("slug")
                    if wf_slug_res.data else None
                )
                if wf_slug:
                    from src.services.task_factory import TaskFactory, TaskFactoryError
                    from src.models import TaskBlueprint

                    blueprint = TaskBlueprint(
                        title=f"[Rotina] {routine_row.get('name', 'Rotina')}",
                        description=description,
                        budget_limit=0,
                    )
                    factory = TaskFactory(supabase)
                    try:
                        materialized = factory.materialize_workflow(
                            company_id=routine_row.get("company_id"),
                            workflow_slug=wf_slug,
                            parent_input=blueprint,
                            step_inputs={
                                # Aplica o input_json normalizado em todos os
                                # steps (cada handler escolhe quais chaves usa).
                                # Granularidade por step pode entrar em PR futuro.
                                "import-ofx": input_json or {},
                                "categorize-pendings": input_json or {},
                                "hermes-report": {"recipient_default": True},
                            },
                        )
                        parent_task = materialized.parent
                        subtasks = materialized.subtasks
                        # Marca routine.last_run_at já que materialize não fez.
                        # Não precisamos task_payload singular daqui em diante —
                        # o materialize criou tudo.
                        logger.info(
                            "run_routine_now: materialized workflow=%s parent=%s subtasks=%d",
                            wf_slug, parent_task.id, len(subtasks),
                        )
                        return {
                            "triggered": True,
                            "routineId": routine_id,
                            "parentTaskId": parent_task.id,
                            "subtaskIds": [t.id for t in subtasks],
                            "workflowSlug": wf_slug,
                        }
                    except TaskFactoryError as tf_err:
                        logger.error(
                            "run_routine_now: materialize_workflow falhou (%s) — "
                            "fallback para task standalone",
                            tf_err,
                        )
                        # Continua para o fluxo legado (INSERT single)
                else:
                    logger.warning(
                        "run_routine_now: workflow_definition_id=%s sem slug "
                        "— fallback standalone",
                        wf_def_id,
                    )
            except Exception as wf_err:
                logger.warning(
                    "run_routine_now: materialize_workflow erro inesperado (%s) "
                    "— fallback standalone",
                    wf_err,
                )
        task_id = None
        task_err_msg = None
        try:
            # Use service_role client to bypass RLS on tasks insert
            task_res = supabase.table("tasks").insert(task_payload).execute()
            if task_res.data:
                task_id = task_res.data[0].get("id")
                logger.info(f"run_routine_now: task created id={task_id}")
                # Push real-time update so the board refreshes instantly
                try:
                    task_obj = Task(**task_res.data[0])
                    company_id_for_ws = routine_row.get("company_id")
                    if company_id_for_ws:
                        asyncio.create_task(
                            ws_manager.emit_task_updated(company_id_for_ws, task_obj.to_zod_dict())
                        )
                except Exception as ws_err:
                    logger.debug(f"run_routine_now: ws emit skipped: {ws_err}")
        except Exception as task_err:
            task_err_msg = str(task_err)
            logger.error(f"run_routine_now: task creation failed: {task_err}")

        return {"triggered": True, "routineId": routine_id, "taskId": task_id, "taskError": task_err_msg}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"run_routine_now failed: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/routines/{routine_id}/reset-ofx-cursor")
@app.post("/routines/{routine_id}/reset-ofx-cursor")
async def reset_routine_ofx_cursor(request: Request, routine_id: str):
    """VEC-415: limpa `metadata.lastProcessedOfx` da rotina, preservando demais campos.

    Permite forçar reprocessamento do começo da pasta. Retorna o metadata atualizado
    + o valor que foi removido (se havia).
    """
    if not supabase:
        raise HTTPException(503, "supabase indisponível")
    try:
        from src.agents.kronos import (
            _OFX_CURSOR_METADATA_KEY,
            clear_routine_ofx_cursor,
            get_routine_ofx_cursor,
        )

        client = get_authenticated_client(request.state.token)
        previous = get_routine_ofx_cursor(client, routine_id)
        merged = clear_routine_ofx_cursor(client, routine_id)
        return {
            "routineId": routine_id,
            "previousCursor": previous,
            "cursorCleared": previous is not None,
            "metadata": merged,
        }
    except ValueError as exc:
        msg = str(exc)
        if "não encontrada" in msg:
            raise HTTPException(404, "routine_not_found")
        raise HTTPException(400, msg)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"reset_routine_ofx_cursor failed: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/companies/{company_id}/workflow-steps")
@app.get("/companies/{company_id}/workflow-steps")
async def list_workflow_steps(request: Request, company_id: str):
    """Returns SIPOC-like workflow steps mapped from workflow_definitions/workflow_steps."""
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        # postgrest-py 0.13.2 não expõe .or_(); union manual de 2 queries.
        defs_co = (
            client.table("workflow_definitions")
            .select("id, company_id, slug, name")
            .eq("company_id", company_id)
            .eq("is_active", True)
            .execute()
        )
        defs_global = (
            client.table("workflow_definitions")
            .select("id, company_id, slug, name")
            .is_("company_id", "null")
            .eq("is_active", True)
            .execute()
        )
        seen_ids: set[str] = set()
        wf_defs: list[dict[str, Any]] = []
        for d in list(defs_co.data or []) + list(defs_global.data or []):
            did = str(d.get("id") or "")
            if did and did not in seen_ids:
                seen_ids.add(did)
                wf_defs.append(d)
        if not wf_defs:
            return []

        def_by_id = {d.get("id"): d for d in wf_defs if d.get("id")}
        wf_ids = [d["id"] for d in wf_defs if d.get("id")]
        if not wf_ids:
            return []
        steps_res = (
            client.table("workflow_steps")
            .select("*")
            .in_("workflow_id", wf_ids)
            .order("step_order")
            .execute()
        )
        rows = steps_res.data or []

        # Build id -> step_code to resolve "proximo"
        id_to_code = {
            r.get("id"): f"{(r.get('slug') or 'step').upper()}-{int(r.get('step_order') or 0)}"
            for r in rows
        }

        mapped = []
        for r in rows:
            wf = def_by_id.get(r.get("workflow_id")) or {}
            step_code = f"{(r.get('slug') or 'step').upper()}-{int(r.get('step_order') or 0)}"
            requires_approval = bool(r.get("requires_approval"))
            next_id = r.get("on_success_step_id")
            mapped.append(
                {
                    "id": r.get("id"),
                    "companyId": company_id,
                    "stepCode": step_code,
                    "nome": r.get("name") or r.get("slug") or "Etapa",
                    "descricao": (
                        f"Workflow '{wf.get('name') or wf.get('slug') or 'pipeline'}' — "
                        f"step {int(r.get('step_order') or 0)}"
                    ),
                    "responsavel": "humano" if requires_approval else "agente",
                    "setor": "Pipeline",
                    "ferramentas": [r.get("specialty_slug")] if r.get("specialty_slug") else [],
                    "slaHoras": None,
                    "alertas": [],
                    "proximo": [id_to_code.get(next_id)] if next_id and id_to_code.get(next_id) else [],
                    "suppliers": [
                        {
                            "nome": "Etapa anterior",
                            "tipo": "etapa_anterior",
                            "referencia": wf.get("slug") or "workflow",
                        }
                    ],
                    "inputs": [
                        {
                            "nome": "task.output_json",
                            "tipo": "dado_estruturado",
                            "formato": "jsonb",
                            "obrigatorio": True,
                            "canal": "database",
                        }
                    ],
                    "outputs": [
                        {
                            "nome": "task.output_json",
                            "tipo": "dado_estruturado",
                            "formato": "jsonb",
                            "destino": r.get("specialty_slug") or "pipeline",
                            "canal": "database",
                        }
                    ],
                    "customers": [
                        {
                            "nome": "Próxima etapa",
                            "tipo": "etapa_seguinte",
                            "referencia": id_to_code.get(next_id) if next_id else None,
                        }
                    ],
                    "decisions": [
                        {
                            "condicao": "sucesso",
                            "acao": "avança para próxima etapa",
                            "proximoStep": id_to_code.get(next_id) if next_id else None,
                        },
                        {
                            "condicao": "falha",
                            "acao": f"on_failure_action={r.get('on_failure_action') or 'block'}",
                        },
                    ],
                    "createdAt": r.get("created_at") or datetime.now(timezone.utc).isoformat(),
                }
            )
        return mapped
    except Exception as e:
        logger.warning(f"list_workflow_steps failed: {e}")
        return []


# ── helpers shared by POST / PUT ──────────────────────────────────────────────
import re as _re_wf
import json as _json_wf


async def _call_llm_sipoc_element(element: str, step_context: dict, locked: dict) -> list:
    """Chama Claude Haiku para sugerir itens de um elemento SIPOC."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    # Constrói contexto acumulado
    five = step_context.get("fiveW2H", {})
    ctx_lines = [
        f"Step: {step_context.get('nome', '')}",
        f"Descrição: {step_context.get('descricao', '')}",
        f"O quê (what): {five.get('what', '')}",
        f"Por quê (why): {five.get('why', '')}",
        f"Quem (who): {five.get('who', '')}",
        f"Onde (where): {five.get('where', '')}",
        f"Quando (when): {five.get('when', '')}",
        f"Como (how): {five.get('how', '')}",
    ]
    if locked.get("suppliers"):
        ctx_lines.append(f"Fornecedores aceitos: {_json_wf.dumps(locked['suppliers'], ensure_ascii=False)}")
    if locked.get("inputs"):
        ctx_lines.append(f"Entradas aceitas: {_json_wf.dumps(locked['inputs'], ensure_ascii=False)}")
    if locked.get("outputs"):
        ctx_lines.append(f"Saídas aceitas: {_json_wf.dumps(locked['outputs'], ensure_ascii=False)}")

    element_instructions = {
        "suppliers": "Sugira os FORNECEDORES (S do SIPOC): quem ou o que fornece insumos para este step. Retorne JSON array com objetos {nome, tipo ('agente'|'humano'|'sistema_externo'|'etapa_anterior'), referencia}.",
        "inputs": "Sugira as ENTRADAS (I do SIPOC): dados, arquivos ou eventos que chegam neste step. Retorne JSON array com objetos {nome, tipo ('arquivo'|'dado_estruturado'|'evento'|'confirmacao_humana'), formato, obrigatorio (bool), canal ('database'|'email'|'api'|'webhook'|'filesystem'|'upload'|'manual'|'whatsapp'|'ui'|'siscomex'), canalDetalhe}.",
        "outputs": "Sugira as SAÍDAS (O do SIPOC): o que este step produz. Retorne JSON array com objetos {nome, tipo ('arquivo'|'dado_estruturado'|'notificacao'|'confirmacao'), formato, destino, canal, canalDetalhe}.",
        "customers": "Sugira os CLIENTES (C do SIPOC): quem ou o que consome as saídas deste step. Retorne JSON array com objetos {nome, tipo ('etapa_seguinte'|'humano'|'sistema_externo'|'cliente_final'), referencia, canalAprovacao}.",
    }

    system = "Você é um especialista em SIPOC (Suppliers, Inputs, Process, Outputs, Customers) para processos de automação empresarial. Responda SOMENTE com JSON válido, sem markdown, sem explicações."
    user_msg = "\n".join(ctx_lines) + "\n\n" + element_instructions.get(element, "")

    try:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1024,
                    "system": system,
                    "messages": [{"role": "user", "content": user_msg}],
                },
                timeout=30.0,
            )
        if resp.status_code != 200:
            logger.error(f"suggest_sipoc_element LLM error: {resp.text}")
            return []
        content = resp.json()["content"][0]["text"].strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.rsplit("```", 1)[0].strip()
        return _json_wf.loads(content)
    except Exception as e:
        logger.error(f"suggest_sipoc_element failed: {e}")
        return []


def _wf_slugify(name: str) -> str:
    return _re_wf.sub(r"-{2,}", "-", _re_wf.sub(r"[^a-z0-9]+", "-", (name or "").lower())).strip("-") or "step"


def _normalize_5w2h_payload(body: dict) -> dict:
    """Normalise incoming payload so sipoc_meta always has a canonical fiveW2H dict.

    Rules:
    - If body already has ``fiveW2H`` (dict), use it as the base.
    - Otherwise collect flat fields: what, why, who, where, when, how.
    - howMuch: string → {"description": str}; dict → as-is; absent → {}
      Also handles snake_case ``how_much`` as fallback when ``howMuch`` is absent.
    - Returns a shallow copy of body with ``fiveW2H`` set (flat fields kept for
      backward-compatibility during the transition window).
    """
    result = dict(body)

    existing = body.get("fiveW2H")
    if isinstance(existing, dict):
        five = dict(existing)
    else:
        five = {
            "what": body.get("what") or "",
            "why": body.get("why") or "",
            "who": body.get("who") or "",
            "where": body.get("where") or "",
            "when": body.get("when") or "",
            "how": body.get("how") or "",
        }

    # Normalise howMuch -------------------------------------------------------
    # Priority: fiveW2H.howMuch > flat howMuch > flat how_much
    inner_how_much = five.get("howMuch")
    flat_how_much = body.get("howMuch") or body.get("how_much")

    if inner_how_much is None:
        if isinstance(flat_how_much, dict):
            five["howMuch"] = flat_how_much
        elif isinstance(flat_how_much, str) and flat_how_much:
            five["howMuch"] = {"description": flat_how_much}
        else:
            five["howMuch"] = {}
    elif isinstance(inner_how_much, str):
        # Coerce string inside fiveW2H to canonical dict form
        five["howMuch"] = {"description": inner_how_much} if inner_how_much else {}
    # else: already a dict — keep as-is

    result["fiveW2H"] = five
    return result


def _coerce_sipoc_responsavel(meta: dict) -> None:
    """UI pode enviar `agente:<uuid>` para fixar o agente; contrato canônico e CHECK
    em `workflow_steps.responsavel` aceitam só `agente` | `humano` | `sistema`.
    Normaliza in-place: grava `responsibleAgentId` e redefine `responsavel` para o enum."""
    raw = meta.get("responsavel")
    if not isinstance(raw, str):
        return
    if raw in ("agente", "humano", "sistema"):
        return
    if raw.startswith("agente:"):
        tail = raw.split(":", 1)[1].strip()
        if tail:
            meta["responsibleAgentId"] = tail
        meta["responsavel"] = "agente"
    elif raw.startswith("humano:"):
        meta["responsavel"] = "humano"
    elif raw.startswith("sistema:"):
        meta["responsavel"] = "sistema"


def _validate_5w2h(normalized: dict) -> dict:
    """Validate required 5W2H fields and return a status + error list (never blocks save).

    Returns:
        {"status": "verde"|"amarelo"|"vermelho", "errors": [{"field": str, "message": str}]}

    Rules:
    - Required fields: why, how, who, when  (howMuch is NOT validated)
    - verde    = all 4 filled
    - amarelo  = 1, 2 or 3 of the 4 filled
    - vermelho = none of the 4 filled
    """
    five = normalized.get("fiveW2H") or {}
    required = ["why", "how", "who", "when"]
    missing = [f for f in required if not five.get(f, "").strip()]

    if len(missing) == 0:
        status = "verde"
    elif len(missing) == 4:
        status = "vermelho"
    else:
        status = "amarelo"

    errors = [
        {"field": f, "message": "Campo 5W2H obrigatório não preenchido"}
        for f in missing
    ]
    return {"status": status, "errors": errors}


def _sipoc_step_to_dict(r: dict, company_id: str, id_to_code: dict) -> dict:
    """Map a workflow_steps DB row → frontend SIPOC dict, preferring sipoc_meta when present."""
    meta: dict = r.get("sipoc_meta") or {}
    step_code = f"{(r.get('slug') or 'step').upper()}-{int(r.get('step_order') or 0)}"
    next_id = r.get("on_success_step_id")
    requires_approval = bool(r.get("requires_approval"))
    if meta:
        five = meta.get("fiveW2H") or {}
        w_what  = five.get("what")  or meta.get("what")  or ""
        w_why   = five.get("why")   or meta.get("why")   or ""
        w_who   = five.get("who")   or meta.get("who")   or ""
        w_where = five.get("where") or meta.get("where") or ""
        w_when  = five.get("when")  or meta.get("when")  or ""
        w_how   = five.get("how")   or meta.get("how")   or ""
        raw_hm  = five.get("howMuch") or meta.get("howMuch") or {}
        w_how_much = raw_hm if isinstance(raw_hm, dict) else ({"description": raw_hm} if raw_hm else {})
        return {
            "id": r.get("id"),
            "companyId": company_id,
            "stepCode": step_code,
            "nome": meta.get("nome") or r.get("name") or "Etapa",
            "descricao": meta.get("descricao") or "",
            "responsavel": meta.get("responsavel") or ("humano" if requires_approval else "agente"),
            "setor": meta.get("setor") or "Pipeline",
            "ferramentas": meta.get("ferramentas") or ([r.get("specialty_slug")] if r.get("specialty_slug") else []),
            "slaHoras": meta.get("slaHoras"),
            "alertas": meta.get("alertas") or [],
            "proximo": meta.get("proximo") or ([id_to_code.get(next_id)] if next_id and id_to_code.get(next_id) else []),
            "suppliers": meta.get("suppliers") or [],
            "inputs": meta.get("inputs") or [],
            "outputs": meta.get("outputs") or [],
            "customers": meta.get("customers") or [],
            "decisions": meta.get("decisions") or "",
            # flat legacy fields (kept for backward-compat)
            "why": w_why,
            "who": w_who,
            "where": w_where,
            "when": w_when,
            "how": w_how,
            "howMuch": w_how_much,
            # canonical nested object
            "fiveW2H": {
                "what": w_what,
                "why": w_why,
                "who": w_who,
                "where": w_where,
                "when": w_when,
                "how": w_how,
                "howMuch": w_how_much,
            },
            "validationStatus": r.get("validation_status") or "verde",
            "validationErrors": r.get("validation_errors") or [],
            "contractVersion": r.get("contract_version") or "v1",
            "createdAt": r.get("created_at") or datetime.now(timezone.utc).isoformat(),
        }
    # legacy row without sipoc_meta
    return {
        "id": r.get("id"),
        "companyId": company_id,
        "stepCode": step_code,
        "nome": r.get("name") or r.get("slug") or "Etapa",
        "descricao": "",
        "responsavel": "humano" if requires_approval else "agente",
        "setor": "Pipeline",
        "ferramentas": [r.get("specialty_slug")] if r.get("specialty_slug") else [],
        "slaHoras": None,
        "alertas": [],
        "proximo": [id_to_code.get(next_id)] if next_id and id_to_code.get(next_id) else [],
        "suppliers": [],
        "inputs": [],
        "outputs": [],
        "customers": [],
        "decisions": "",
        "fiveW2H": {"what": "", "why": "", "who": "", "where": "", "when": "", "how": "", "howMuch": {}},
        "validationStatus": r.get("validation_status") or "verde",
        "validationErrors": r.get("validation_errors") or [],
        "contractVersion": r.get("contract_version") or "v1",
        "createdAt": r.get("created_at") or datetime.now(timezone.utc).isoformat(),
    }


def _ensure_sipoc_workflow(client, company_id: str) -> str:
    """Find or create a company-owned workflow_definition for SIPOC steps. Returns its id."""
    res = (
        client.table("workflow_definitions")
        .select("id")
        .eq("company_id", company_id)
        .eq("slug", "sipoc-customizado")
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]["id"]
    ins = client.table("workflow_definitions").insert({
        "company_id": company_id,
        "name": "SIPOC Customizado",
        "slug": "sipoc-customizado",
        "description": "Etapas SIPOC definidas pela empresa",
        "is_active": True,
    }).execute()
    return ins.data[0]["id"]


@app.post("/api/companies/{company_id}/workflow-steps")
@app.post("/companies/{company_id}/workflow-steps")
async def create_workflow_step(company_id: str, request: Request):
    body = await request.json()
    if not supabase:
        raise HTTPException(503, "Database unavailable")
    try:
        client = get_authenticated_client(request.state.token)
        wf_id = _ensure_sipoc_workflow(client, company_id)

        max_res = (
            client.table("workflow_steps")
            .select("step_order")
            .eq("workflow_id", wf_id)
            .order("step_order", desc=True)
            .limit(1)
            .execute()
        )
        next_order = (max_res.data[0]["step_order"] + 1) if max_res.data else 1

        normalized = _normalize_5w2h_payload(body)
        _coerce_sipoc_responsavel(normalized)
        validation = _validate_5w2h(normalized)
        nome = normalized.get("nome") or "Etapa"
        slug = _wf_slugify(nome)
        requires_approval = normalized.get("responsavel") == "humano"
        specialty_slug = (normalized.get("ferramentas") or [None])[0]

        row = client.table("workflow_steps").insert({
            "workflow_id": wf_id,
            "step_order": next_order,
            "name": nome,
            "slug": slug,
            "specialty_slug": specialty_slug,
            "requires_approval": requires_approval,
            "responsavel": normalized.get("responsavel"),
            "sipoc_meta": normalized,
            "contract_version": "v2",
            "validation_status": validation["status"],
            "validation_errors": validation["errors"],
        }).execute().data[0]

        return _sipoc_step_to_dict(row, company_id, {})
    except Exception as e:
        logger.error(f"create_workflow_step failed: {e}")
        raise HTTPException(500, str(e))


@app.put("/api/workflow-steps/{step_id}")
@app.put("/workflow-steps/{step_id}")
@app.patch("/api/workflow-steps/{step_id}")
@app.patch("/workflow-steps/{step_id}")
async def update_workflow_step(step_id: str, request: Request):
    body = await request.json()
    if not supabase:
        raise HTTPException(503, "Database unavailable")
    try:
        client = get_authenticated_client(request.state.token)
        existing = client.table("workflow_steps").select("*").eq("id", step_id).single().execute()
        row = existing.data
        if not row:
            raise HTTPException(404, "Workflow step not found")

        normalized = _normalize_5w2h_payload(body)
        _coerce_sipoc_responsavel(normalized)
        validation = _validate_5w2h(normalized)
        nome = normalized.get("nome") or row.get("name") or "Etapa"
        requires_approval = normalized.get("responsavel") == "humano"
        specialty_slug = (normalized.get("ferramentas") or [None])[0]

        updated = client.table("workflow_steps").update({
            "name": nome,
            "slug": _wf_slugify(nome),
            "specialty_slug": specialty_slug,
            "requires_approval": requires_approval,
            "responsavel": normalized.get("responsavel"),
            "sipoc_meta": normalized,
            "contract_version": "v2",
            "validation_status": validation["status"],
            "validation_errors": validation["errors"],
        }).eq("id", step_id).execute().data[0]

        return _sipoc_step_to_dict(updated, body.get("companyId") or "", {})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"update_workflow_step failed: {e}")
        raise HTTPException(500, str(e))


@app.delete("/api/workflow-steps/{step_id}")
@app.delete("/workflow-steps/{step_id}")
async def delete_workflow_step(step_id: str, request: Request):
    if not supabase:
        raise HTTPException(503, "Database unavailable")
    try:
        client = get_authenticated_client(request.state.token)
        client.table("workflow_steps").delete().eq("id", step_id).execute()
        return Response(status_code=204)
    except Exception as e:
        logger.error(f"delete_workflow_step failed: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/workflow-steps/suggest-sipoc-element")
@app.post("/workflow-steps/suggest-sipoc-element")
async def suggest_sipoc_element(request: Request):
    body = await request.json()
    element = body.get("element")
    if element not in ("suppliers", "inputs", "outputs", "customers"):
        raise HTTPException(400, "element must be suppliers|inputs|outputs|customers")
    step_context = body.get("step_context", {})
    locked = body.get("locked", {})
    suggestions = await _call_llm_sipoc_element(element, step_context, locked)
    return {"element": element, "suggestions": suggestions}


@app.get("/api/companies/{company_id}/hermes/whitelist")
@app.get("/companies/{company_id}/hermes/whitelist")
async def list_hermes_whitelist(request: Request, company_id: str):
    """Returns all sender whitelist entries for the company."""
    if not supabase:
        return []
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("hermes_sender_whitelist")
            .select("*")
            .eq("company_id", company_id)
            .order("created_at")
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"list_hermes_whitelist failed: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/companies/{company_id}/hermes/whitelist")
@app.post("/companies/{company_id}/hermes/whitelist")
async def create_hermes_whitelist_entry(request: Request, company_id: str):
    """Adds an email address to the Hermes sender whitelist."""
    if not supabase:
        raise HTTPException(501, "mock_not_supported")
    try:
        body = await request.json()
        email = (body.get("email") or "").strip().lower()
        if not email:
            raise HTTPException(400, "email_required")
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("hermes_sender_whitelist")
            .insert({
                "company_id": company_id,
                "email": email,
                "label": body.get("label") or None,
                "is_active": body.get("isActive", True),
            })
            .execute()
        )
        if not res.data:
            raise HTTPException(500, "insert_failed")
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_hermes_whitelist_entry failed: {e}")
        raise HTTPException(500, str(e))


@app.patch("/api/companies/{company_id}/hermes/whitelist/{entry_id}")
@app.patch("/companies/{company_id}/hermes/whitelist/{entry_id}")
async def update_hermes_whitelist_entry(request: Request, company_id: str, entry_id: str):
    """Updates label or is_active for a whitelist entry."""
    if not supabase:
        raise HTTPException(501, "mock_not_supported")
    try:
        body = await request.json()
        updates: dict = {}
        if "label" in body:
            updates["label"] = body["label"]
        if "isActive" in body:
            updates["is_active"] = body["isActive"]
        if not updates:
            raise HTTPException(400, "no_fields_to_update")
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("hermes_sender_whitelist")
            .update(updates)
            .eq("id", entry_id)
            .eq("company_id", company_id)
            .execute()
        )
        if not res.data:
            raise HTTPException(404, "entry_not_found")
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"update_hermes_whitelist_entry failed: {e}")
        raise HTTPException(500, str(e))


@app.delete("/api/companies/{company_id}/hermes/whitelist/{entry_id}")
@app.delete("/companies/{company_id}/hermes/whitelist/{entry_id}")
async def delete_hermes_whitelist_entry(request: Request, company_id: str, entry_id: str):
    """Removes an email address from the whitelist."""
    if not supabase:
        raise HTTPException(501, "mock_not_supported")
    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("hermes_sender_whitelist")
            .delete()
            .eq("id", entry_id)
            .eq("company_id", company_id)
            .execute()
        )
        if not res.data:
            raise HTTPException(404, "entry_not_found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_hermes_whitelist_entry failed: {e}")
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
        caller_company = _resolve_company_id(request)
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("agent_adapter_configs")
            .select("*")
            .eq("agent_id", agent_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            return None
        row = res.data[0]
        if caller_company and row.get("company_id") and row.get("company_id") != caller_company:
            raise HTTPException(status_code=403, detail="cross_company_forbidden")
        return AgentAdapterConfig(**row).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_agent_adapter_config failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        caller_company = _resolve_company_id(request)
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
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Company Secrets (Vault)
# ---------------------------------------------------------------------------

class CompanySecretInput(BaseModel):
    name: str
    value: str
    description: Optional[str] = None

    class Config:
        extra = "ignore"


@app.get("/api/companies/{company_id}/secrets")
@app.get("/companies/{company_id}/secrets")
async def list_company_secrets(request: Request, company_id: str):
    """List secret names (never values) for a company."""
    if not supabase:
        return []
    try:
        caller_company = _resolve_company_id(request)
        if caller_company and caller_company != company_id:
            raise HTTPException(status_code=403, detail="cross_company_forbidden")
        res = (
            supabase.table("company_secrets")
            .select("id,name,description,created_at,updated_at")
            .eq("company_id", company_id)
            .order("name")
            .execute()
        )
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "description": r.get("description"),
                "createdAt": r["created_at"],
                "updatedAt": r["updated_at"],
            }
            for r in res.data
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"list_company_secrets failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/companies/{company_id}/secrets")
@app.post("/companies/{company_id}/secrets")
async def upsert_company_secret(request: Request, company_id: str, payload: CompanySecretInput):
    """Create or update a named secret in Vault (stored encrypted)."""
    if not supabase:
        return {"name": payload.name, "created": True}
    try:
        caller_company = _resolve_company_id(request)
        if caller_company and caller_company != company_id:
            raise HTTPException(status_code=403, detail="cross_company_forbidden")
        res = supabase.rpc(
            "upsert_company_secret",
            {
                "p_company_id": company_id,
                "p_name": payload.name,
                "p_value": payload.value,
                "p_description": payload.description,
            },
        ).execute()
        return {"name": payload.name, "vaultSecretId": res.data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"upsert_company_secret failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Cache TTL curto pra evitar round-trip por PUT mas refletir mudanças
# no catalog em <60s sem restart. Idempotente — ignorado se supabase=None.
_EXECUTION_MODE_CACHE: Dict[str, Any] = {"ids": None, "default": None, "fetched_at": 0.0}
_EXECUTION_MODE_CACHE_TTL_S = 60.0


def _load_execution_mode_ids() -> set:
    """Lê IDs ativos de agent_execution_modes (cacheado 60s).
    Retorna set vazio se supabase indisponível (skip validation — FK do DB
    pega depois). Catalog-driven: nada hardcoded."""
    import time
    now = time.time()
    cached = _EXECUTION_MODE_CACHE.get("ids")
    if cached is not None and (now - _EXECUTION_MODE_CACHE.get("fetched_at", 0.0)) < _EXECUTION_MODE_CACHE_TTL_S:
        return cached
    if not supabase:
        return set()
    try:
        res = (
            supabase.table("agent_execution_modes")
            .select("id,display_order,is_active")
            .eq("is_active", True)
            .order("display_order")
            .execute()
        )
        rows = res.data or []
        ids = {str(r["id"]) for r in rows if r.get("id")}
        default = str(rows[0]["id"]) if rows else None
        # G2.2: log explícito quando cache é re-fetched (visibilidade pra
        # debug de mode novo rejeitado em janela <60s do deploy do catalog)
        previous = _EXECUTION_MODE_CACHE.get("ids")
        if previous is None:
            logger.info("execution_mode cache primed: ids=%s default=%s", sorted(ids), default)
        elif previous != ids:
            added = ids - previous
            removed = previous - ids
            logger.warning(
                "execution_mode cache changed: added=%s removed=%s default_now=%s",
                sorted(added), sorted(removed), default,
            )
        _EXECUTION_MODE_CACHE["ids"] = ids
        _EXECUTION_MODE_CACHE["default"] = default
        _EXECUTION_MODE_CACHE["fetched_at"] = now
        return ids
    except Exception as e:
        logger.warning(f"_load_execution_mode_ids fallback (empty set): {e}")
        return set()


def _default_execution_mode() -> str:
    """Default = primeiro mode ativo do catalog por display_order.
    Fallback duro 'REALTIME' só se catalog vazio E supabase indisponível
    (boot offline). Documentado: NÃO é constante semântica, é degenerado."""
    _load_execution_mode_ids()  # populates cache
    return _EXECUTION_MODE_CACHE.get("default") or "REALTIME"


class AgentExecutionSetupInput(BaseModel):
    # str + validator que normaliza UPPER + valida contra catalog
    # `vectraclip.agent_execution_modes`. Sem Literal — o catalog cresce
    # sem deploy (ex.: futuro QUEUE_EVENT, WEBSUB) e a UI já leva via GET.
    executionMode: str
    triggerConfig: Dict[str, Any] = Field(default_factory=dict)
    functionUrl: Optional[str] = None
    authSecretRef: Optional[str] = None
    authHeaderName: Optional[str] = None
    isActive: Optional[bool] = True

    class Config:
        populate_by_name = True
        extra = "ignore"

    @validator("functionUrl", "authSecretRef", "authHeaderName", pre=True)
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v

    @validator("executionMode", pre=True)
    def normalize_and_validate_mode(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError("executionMode_required")
        v = str(v).strip().upper()
        valid = _load_execution_mode_ids()
        if valid and v not in valid:
            raise ValueError(
                f"unknown_execution_mode: '{v}' (válidos: {sorted(valid)})"
            )
        return v


class TaskDispatchInput(BaseModel):
    taskId: str
    idempotencyKey: Optional[str] = None
    attempt: int = 1

    class Config:
        populate_by_name = True
        extra = "ignore"


def _default_execution_config_payload(agent_id: str, company_id: Optional[str]) -> Dict[str, Any]:
    """Default REALTIME ativo para agentes sem row em agent_execution_configs.
    Formato espelha AgentExecutionConfig.to_zod_dict() (camelCase, ISO Z).
    O `id` começa com 'default-' como sentinela — frontend só lê os campos
    de config, então não precisa distinguir, mas a marcação é útil em logs."""
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "id": f"default-{agent_id}",
        "companyId": company_id or "",
        "agentId": agent_id,
        "executionMode": _default_execution_mode(),
        "triggerConfig": {},
        "functionUrl": None,
        "authSecretRef": None,
        "authHeaderName": None,
        "isActive": True,
        "createdAt": now_iso,
        "updatedAt": now_iso,
    }


@app.get("/api/agents/{agent_id}/execution-config")
@app.get("/agents/{agent_id}/execution-config")
async def get_agent_execution_config(request: Request, agent_id: str):
    """Retorna a config de execução do agent. Quando a row ainda não existe,
    devolve um default REALTIME ativo em vez de 404 — frontend renderiza
    o form em estado limpo e o save subsequente cria a row. Migration
    20260510120000 já fez backfill dos agentes sistema (Mnemos, Morpheus,
    HermesReporter, Kronos), mas o default protege contra agentes futuros
    criados fora de _persist_agent_atomic (seeds, manual inserts)."""
    if not supabase:
        row = next((r for r in MOCK_AGENT_EXECUTION_CONFIGS if r.get("agentId") == agent_id), None)
        if row:
            return row
        return _default_execution_config_payload(agent_id, company_id=None)

    try:
        caller_company = _resolve_company_id(request)
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("agent_execution_configs")
            .select("*")
            .eq("agent_id", agent_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            return _default_execution_config_payload(agent_id, company_id=caller_company)
        row = res.data[0]
        if caller_company and row.get("company_id") and row.get("company_id") != caller_company:
            raise HTTPException(status_code=403, detail="cross_company_forbidden")
        return AgentExecutionConfig(**row).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_agent_execution_config failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agents/{agent_id}/specialty-config")
@app.get("/agents/{agent_id}/specialty-config")
async def get_agent_specialty_config(request: Request, agent_id: str):
    if not supabase:
        row = next((r for r in MOCK_AGENT_SPECIALTY_CONFIGS if r.get("agentId") == agent_id), None)
        if not row:
            return Response(status_code=204)
        return row

    try:
        caller_company = _resolve_company_id(request)
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("agent_specialty_configs")
            .select("*")
            .eq("agent_id", agent_id)
            .execute()
        )
        if not res.data:
            return []
        
        configs = res.data
        if caller_company:
            # Filtragem básica de segurança se o RLS não for suficiente
            configs = [c for c in configs if str(c.get("company_id")) == str(caller_company)]
            
        return [AgentSpecialtyConfig(**row).to_zod_dict() for row in configs]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_agent_specialty_config failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SaveAgentSpecialtyConfigInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    specialty_id: str = Field(
        validation_alias=AliasChoices("specialtyId", "specialty_id"),
    )
    values: Dict[str, Any] = Field(default_factory=dict)


@app.put("/api/agents/{agent_id}/specialty-config")
@app.put("/agents/{agent_id}/specialty-config")
async def put_agent_specialty_config(request: Request, agent_id: str, payload: SaveAgentSpecialtyConfigInput):
    now_iso = datetime.now(timezone.utc).isoformat()
    if not supabase:
        global MOCK_AGENT_SPECIALTY_CONFIGS
        existing = next((r for r in MOCK_AGENT_SPECIALTY_CONFIGS if r.get("agentId") == agent_id), None)
        if existing:
            existing["specialtyId"] = payload.specialty_id
            existing["values"] = payload.values
            existing["updatedAt"] = now_iso.replace("+00:00", "Z")
            return existing
        new_row = {
            "id": f"asc_tmp_{int(datetime.now().timestamp())}",
            "agentId": agent_id,
            "specialtyId": payload.specialty_id,
            "values": payload.values,
            "updatedAt": now_iso.replace("+00:00", "Z"),
        }
        MOCK_AGENT_SPECIALTY_CONFIGS.append(new_row)
        return new_row

    try:
        caller_company = _resolve_company_id(request)
        agent_row = supabase.table("agents").select("id,company_id").eq("id", agent_id).limit(1).execute()
        if not agent_row.data:
            raise HTTPException(status_code=404, detail="agent_not_found")
        
        agent_company = agent_row.data[0]["company_id"]
        if caller_company and str(agent_company) != str(caller_company):
            raise HTTPException(status_code=403, detail="cross_company_forbidden")

        row_payload = {
            "company_id": agent_company,
            "agent_id": agent_id,
            "specialty_id": payload.specialty_id,
            "values": payload.values,
            "updated_at": now_iso,
        }
        
        res = (
            supabase.table("agent_specialty_configs")
            .upsert(row_payload, on_conflict="agent_id,specialty_id")
            .execute()
        )
        
        if not res.data:
            logger.error(f"put_agent_specialty_config: upsert returned no data for agent {agent_id}")
            raise HTTPException(status_code=500, detail="database_upsert_failed")
            
        return AgentSpecialtyConfig(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"put_agent_specialty_config failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agents/{agent_id}/shared-config")
@app.get("/agents/{agent_id}/shared-config")
async def get_agent_shared_config(request: Request, agent_id: str):
    """Modelo C — PR-B: campos compartilhados entre specialties do agente.

    Retorna a row de `agent_shared_config` para (company_id, agent_id). Se
    a row ainda não existe, devolve estrutura vazia com `schema=[]` e
    `values={}` — frontend renderiza o form em branco e o save subsequente
    cria a row.
    """
    if not supabase:
        # Mock dev: vazio
        return {
            "id": "",
            "companyId": "",
            "agentId": agent_id,
            "values": {},
            "schema": [],
            "createdAt": None,
            "updatedAt": None,
        }

    try:
        caller_company = _resolve_company_id(request)
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("agent_shared_config")
            .select("*")
            .eq("agent_id", agent_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            return {
                "id": "",
                "companyId": caller_company or "",
                "agentId": agent_id,
                "values": {},
                "schema": [],
                "createdAt": None,
                "updatedAt": None,
            }
        row = res.data[0]
        if caller_company and row.get("company_id") and str(row["company_id"]) != str(caller_company):
            raise HTTPException(status_code=403, detail="cross_company_forbidden")
        return AgentSharedConfig(**row).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_agent_shared_config failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SaveAgentSharedConfigInput(BaseModel):
    """PUT payload: usuário envia apenas `values` (preenchimento do form).
    Schema é seedado por migration e não editável pela UI (read-only)."""

    model_config = ConfigDict(populate_by_name=True)
    values: Dict[str, Any] = Field(default_factory=dict)


@app.put("/api/agents/{agent_id}/shared-config")
@app.put("/agents/{agent_id}/shared-config")
async def put_agent_shared_config(
    request: Request, agent_id: str, payload: SaveAgentSharedConfigInput
):
    """Upsert de `values` na agent_shared_config. Schema é read-only
    (definido por migration). Se a row não existir, cria com schema=[]
    e values=payload — pra evitar quebrar, o ideal é que a migration
    PR-A já tenha seedado a row com schema vazio se for um agent novo.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    if not supabase:
        return {
            "id": "tmp",
            "companyId": "",
            "agentId": agent_id,
            "values": payload.values,
            "schema": [],
            "createdAt": now_iso,
            "updatedAt": now_iso,
        }

    try:
        caller_company = _resolve_company_id(request)
        agent_row = supabase.table("agents").select("id,company_id").eq("id", agent_id).limit(1).execute()
        if not agent_row.data:
            raise HTTPException(status_code=404, detail="agent_not_found")

        agent_company = agent_row.data[0]["company_id"]
        if caller_company and str(agent_company) != str(caller_company):
            raise HTTPException(status_code=403, detail="cross_company_forbidden")

        # Upsert preservando schema existente (não toca schema via PUT — só values)
        row_payload = {
            "company_id": agent_company,
            "agent_id": agent_id,
            "values": payload.values,
            "updated_at": now_iso,
        }

        res = (
            supabase.table("agent_shared_config")
            .upsert(row_payload, on_conflict="company_id,agent_id")
            .execute()
        )

        if not res.data:
            logger.error(f"put_agent_shared_config: upsert returned no data for agent {agent_id}")
            raise HTTPException(status_code=500, detail="database_upsert_failed")

        return AgentSharedConfig(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"put_agent_shared_config failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/agents/{agent_id}/specialty-config/{specialty_id}")
@app.delete("/agents/{agent_id}/specialty-config/{specialty_id}")
async def delete_agent_specialty_config(request: Request, agent_id: str, specialty_id: str):
    if not supabase:
        global MOCK_AGENT_SPECIALTY_CONFIGS
        MOCK_AGENT_SPECIALTY_CONFIGS[:] = [
            r for r in MOCK_AGENT_SPECIALTY_CONFIGS 
            if not (r.get("agentId") == agent_id and r.get("specialtyId") == specialty_id)
        ]
        return Response(status_code=204)

    try:
        caller_company = _resolve_company_id(request)
        client = get_authenticated_client(request.state.token)
        
        # Validação de tenant
        check = client.table("agent_specialty_configs").select("company_id").eq("agent_id", agent_id).eq("specialty_id", specialty_id).limit(1).execute()
        if not check.data:
            raise HTTPException(status_code=404, detail="specialty_config_not_found")
        
        if caller_company and str(check.data[0]["company_id"]) != str(caller_company):
            raise HTTPException(status_code=403, detail="cross_company_forbidden")

        client.table("agent_specialty_configs").delete().eq("agent_id", agent_id).eq("specialty_id", specialty_id).execute()
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_agent_specialty_config failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Inbox endpoint — IMAP fetch + heuristic classification
# ---------------------------------------------------------------------------

import imaplib
import email as email_lib
from email.header import decode_header as _decode_header
import html
import re as _re

def _decode_mime_words(s: str) -> str:
    parts = _decode_header(s)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            try:
                decoded.append(part.decode(enc or "utf-8", errors="replace"))
            except LookupError:
                # Some providers send invalid labels like "unknown-8bit".
                decoded.append(part.decode("utf-8", errors="replace"))
            except Exception:
                decoded.append(part.decode("latin-1", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)

def _safe_charset(enc: str | None) -> str:
    """Normalizes invalid charset labels emitted by some providers."""
    enc_norm = (enc or "utf-8").strip().lower()
    if enc_norm in {"unknown-8bit", "unknown_8bit", "x-unknown"}:
        return "utf-8"
    return enc_norm

def _strip_html(text: str) -> str:
    text = html.unescape(text)
    text = _re.sub(r"<[^>]+>", " ", text)
    text = _re.sub(r"\s+", " ", text).strip()
    return text

def _classify_email(subject: str, from_: str, body: str) -> tuple[str, bool, bool]:
    """Returns (category, isQuote, isSpam)."""
    subj_low = subject.lower()
    from_low = from_.lower()

    # Spam heuristics
    spam_signals = ["oferta", "desconto", "grátis", "gratis", "promoção", "promocao",
                    "!!!", "cadastre-se já", "xyz", "click here", "unsubscribe"]
    is_spam = any(sig in subj_low or sig in from_low for sig in spam_signals)
    if is_spam:
        return "spam", False, True

    # Quote / cotação
    quote_signals = ["cotação", "cotacao", "proposta", "orçamento", "orcamento",
                     "quote", "proposal", "frete", "tarifa"]
    is_quote = any(sig in subj_low for sig in quote_signals)

    # Category
    urgent_signals = ["urgente", "confirmad", "confirmação", "os #", "coleta", "entrega",
                      "prazo", "vence", "atraso", "atrasad"]
    action_signals = ["re:", "fwd:", "aprovação", "aprovacao", "pagamento", "nf-e",
                      "invoice", "pedido", "contrato"]
    info_signals = ["newsletter", "digest", "tendência", "notícia", "boletim",
                    "informe", "comunicado", "aviso"]

    if any(sig in subj_low for sig in urgent_signals):
        return "urgente", is_quote, False
    if any(sig in subj_low for sig in action_signals) or is_quote:
        return "ação", is_quote, False
    if any(sig in subj_low or sig in from_low for sig in info_signals):
        return "informativo", is_quote, False
    return "ação", is_quote, False

def _fetch_imap_emails(host: str, port: int, username: str, password: str, limit: int = 20) -> list[dict]:
    """Synchronous IMAP fetch — must be run in a thread executor."""
    mail = imaplib.IMAP4_SSL(host, int(port))
    try:
        mail.login(username, password)
        mail.select("INBOX", readonly=True)
        _, msg_ids = mail.search(None, "ALL")
        ids = (msg_ids[0] or b"").split()
        ids = ids[-limit:][::-1]  # most recent first
        results = []
        for uid in ids:
            _, data = mail.fetch(uid, "(RFC822)")
            raw = data[0][1] if data and data[0] else None
            if not raw:
                continue
            msg = email_lib.message_from_bytes(raw)
            subject = _decode_mime_words(msg.get("Subject", "(sem assunto)"))
            from_ = _decode_mime_words(msg.get("From", ""))
            date_str = msg.get("Date", "")
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(date_str)
                received_at = dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            except Exception:
                received_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

            # Extract plain text body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ct = part.get_content_type()
                    if ct == "text/plain" and not part.get("Content-Disposition"):
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode(_safe_charset(part.get_content_charset()), errors="replace")
                            break
                    elif ct == "text/html" and not body:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = _strip_html(payload.decode(_safe_charset(part.get_content_charset()), errors="replace"))
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    ct = msg.get_content_type()
                    raw_body = payload.decode(_safe_charset(msg.get_content_charset()), errors="replace")
                    body = _strip_html(raw_body) if ct == "text/html" else raw_body

            excerpt = body[:200].strip()
            category, is_quote, is_spam = _classify_email(subject, from_, body)
            results.append({
                "id": uid.decode(),
                "from": from_,
                "subject": subject,
                "excerpt": excerpt,
                "receivedAt": received_at,
                "category": category,
                "isQuote": is_quote,
                "isSpam": is_spam,
            })
        return results
    finally:
        try:
            mail.logout()
        except Exception:
            pass

def _resolve_vault_secret(company_id: str, name: str) -> str:
    """Reads a decrypted vault secret via read_company_secret RPC (service role)."""
    if not supabase:
        return ""
    try:
        res = supabase.rpc(
            "read_company_secret",
            {"p_company_id": company_id, "p_name": name},
        ).execute()
        return res.data or ""
    except Exception as e:
        logger.warning(f"[vault] failed to resolve secret {name!r} for company {company_id}: {e}")
        return ""


def _resolve_field_value(value: str, company_id: str) -> str:
    """If value is a 'secret:NAME' reference, resolves it from vault; otherwise returns as-is."""
    if value and value.startswith("secret:"):
        name = value[len("secret:"):].strip()
        return _resolve_vault_secret(company_id, name)
    return value


def _resolve_imap_field(field_values: dict, *keys: str, default: str = "") -> str:
    """Returns the first non-empty value found among the given key aliases."""
    for k in keys:
        v = field_values.get(k)
        if v and str(v).strip():
            return str(v).strip()
    return default


def _resolve_imap_port(field_values: dict) -> int:
    raw = field_values.get("imap_port") or field_values.get("inbox_imap_port")
    try:
        return int(raw) if raw is not None else 993
    except (ValueError, TypeError):
        logger.warning(f"[inbox] invalid imap_port value {raw!r}, falling back to 993")
        return 993


def _compute_next_run_at(now_utc: datetime, cron_expr: str, tz_name: str) -> Optional[str]:
    """
    Computes next execution timestamp (UTC ISO) for a narrow cron subset:
    - `M H * * *` (daily)
    - `*/N * * * *` (every N minutes)
    Returns None for unsupported/invalid expressions.
    """
    if not cron_expr:
        return None
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return None

    minute_part, hour_part, day_part, month_part, weekday_part = parts
    if day_part != "*" or month_part != "*" or weekday_part != "*":
        return None

    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        tz = timezone.utc

    local_now = now_utc.astimezone(tz)

    # Pattern: */N * * * *
    if minute_part.startswith("*/") and hour_part == "*":
        try:
            step = int(minute_part[2:])
            if step <= 0:
                return None
            minute_bucket = (local_now.minute // step + 1) * step
            next_local = local_now.replace(second=0, microsecond=0)
            if minute_bucket >= 60:
                next_local = (next_local + timedelta(hours=1)).replace(minute=0)
            else:
                next_local = next_local.replace(minute=minute_bucket)
            return next_local.astimezone(timezone.utc).isoformat()
        except Exception:
            return None

    # Pattern: M H * * *
    try:
        minute = int(minute_part)
        hour = int(hour_part)
    except Exception:
        return None
    if not (0 <= minute <= 59 and 0 <= hour <= 23):
        return None

    next_local = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_local <= local_now:
        next_local = next_local + timedelta(days=1)
    return next_local.astimezone(timezone.utc).isoformat()


@app.get("/api/agents/{agent_id}/inbox")
@app.get("/agents/{agent_id}/inbox")
async def get_agent_inbox(request: Request, agent_id: str, limit: int = 20):
    """Fetches recent emails via IMAP using the agent's adapter config.
    Returns [] when no IMAP credentials are configured."""
    try:
        company_id: str = ""
        if supabase:
            client = get_authenticated_client(request.state.token)
            res = (
                client.table("agent_adapter_configs")
                .select("field_values_json, company_id")
                .eq("agent_id", agent_id)
                .limit(1)
                .execute()
            )
            if not res.data:
                logger.debug(f"[inbox] no adapter config for agent {agent_id}")
                return []
            field_values = res.data[0].get("field_values_json") or {}
            company_id = res.data[0].get("company_id", "")
        else:
            cfg = next(
                (c for c in MOCK_AGENT_ADAPTER_CONFIGS if c.get("agentId") == agent_id),
                None,
            )
            if not cfg:
                logger.debug(f"[inbox] no mock config for agent {agent_id}")
                return []
            field_values = cfg.get("fieldValuesJson") or {}
            company_id = cfg.get("companyId", "")

        # Accept both schema naming conventions: imap_* (adapter) and inbox_imap_* (specialty)
        host = _resolve_imap_field(field_values, "imap_host", "inbox_imap_host")
        port = _resolve_imap_port(field_values)
        username = _resolve_imap_field(field_values, "email", "inbox_email")
        raw_password = _resolve_imap_field(field_values, "password", "inbox_password")
        password = _resolve_field_value(raw_password, company_id)

        if not host:
            logger.debug(f"[inbox] agent {agent_id} has no IMAP host — not an email agent")
            return []
        if not username or not password:
            logger.warning(f"[inbox] agent {agent_id} has IMAP host but missing email/password")
            return []

        loop = asyncio.get_event_loop()
        emails = await loop.run_in_executor(
            None,
            lambda: _fetch_imap_emails(host, port, username, password, limit),
        )
        return emails
    except imaplib.IMAP4.error as e:
        logger.warning(f"[inbox] IMAP protocol error for agent {agent_id}: {e}")
        return []
    except Exception as e:
        logger.error(f"[inbox] unexpected error for agent {agent_id}: {type(e).__name__}: {e}")
        return []


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
        caller_company = _resolve_company_id(request)
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
        raise HTTPException(status_code=500, detail=str(e))


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
    caller_company = _resolve_company_id(request)

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
            .select("id,company_id,assigned_to_agent_id,title,status,budget_limit,cost_usd,approved_at,approved_by_user_id")
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
        _enforce_task_execution_gates(task, source="dispatch")

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
        execution_mode = str(
            (exec_row or {}).get("execution_mode") or _default_execution_mode()
        ).upper()
        function_url = (exec_row or {}).get("function_url")
        if not function_url:
            # Modes consumidos por poller local (REALTIME) não precisam de
            # function_url. A semântica "precisa de URL?" deveria virar
            # propriedade no catalog (config_schema marca function_url como
            # required:true em CRON/TRIGGER, false/ausente em REALTIME).
            # Por ora mantemos check pela ID conhecida — TODO migrar para
            # consulta a `agent_execution_modes.config_schema`.
            if execution_mode == "REALTIME":
                duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
                _chronos_log_dispatch_event(
                    {
                        "event": "dispatch.realtime_noop",
                        "reason": "realtime_poller",
                        "companyId": task_company,
                        "agentId": agent_id,
                        "taskId": payload.taskId,
                        "durationMs": duration_ms,
                    }
                )
                response = {
                    "ok": True,
                    "dispatched": True,
                    "mode": execution_mode,
                    "reason": "realtime_poller",
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
        raise HTTPException(status_code=500, detail=str(e))

def _assert_not_system_agent(client, agent_id: str) -> None:
    """Raises 403 if the agent is a protected system agent."""
    try:
        res = client.table("agents").select("is_system").eq("id", agent_id).limit(1).execute()
        if res.data and res.data[0].get("is_system"):
            raise HTTPException(status_code=403, detail="system_agent_immutable")
    except HTTPException:
        raise
    except Exception:
        pass  # on DB error, let the main operation surface its own error


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
    if supabase:
        _assert_not_system_agent(get_authenticated_client(request.state.token), agent_id)
    return await supabase_update_agent_status(request.state.token, agent_id, AgentStatus.PAUSED)


@app.post("/api/agents/{agent_id}/resume")
@app.post("/agents/{agent_id}/resume")
async def resume_agent(agent_id: str, request: Request):
    if supabase:
        _assert_not_system_agent(get_authenticated_client(request.state.token), agent_id)
    return await supabase_update_agent_status(request.state.token, agent_id, AgentStatus.IDLE)


@app.post("/api/agents/{agent_id}/kill")
@app.post("/agents/{agent_id}/kill")
async def kill_agent(agent_id: str, request: Request):
    if supabase:
        _assert_not_system_agent(get_authenticated_client(request.state.token), agent_id)
    return await supabase_update_agent_status(request.state.token, agent_id, AgentStatus.OFFLINE)


@app.post("/api/agents/{agent_id}/abort-task")
@app.post("/agents/{agent_id}/abort-task")
async def abort_agent_task(agent_id: str, request: Request):
    """Cancela a task in_progress do agente sem matar o agente."""
    if not supabase:
        return {"aborted": 0, "agentId": agent_id}

    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("tasks")
            .update({"status": "blocked"})
            .eq("agent_id", agent_id)
            .eq("status", "in_progress")
            .execute()
        )
        aborted = res.data or []
        for row in aborted:
            company_id = row.get("company_id")
            if company_id:
                await ws_manager.emit_task_updated(company_id, Task(**row).to_zod_dict())
        logger.info(f"abort-task: {len(aborted)} task(s) abortada(s) para agente {agent_id}")
        return {"aborted": len(aborted), "agentId": agent_id, "tasks": [t["id"] for t in aborted]}
    except Exception as e:
        logger.error(f"abort_agent_task failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/agents/{agent_id}")
@app.patch("/agents/{agent_id}")
async def patch_agent(agent_id: str, patch: AgentPatch, request: Request):
    # Só envia o que o cliente mandou (partial update verdadeiro).
    payload = patch.dict(by_alias=False, exclude_none=True)
    if not payload:
        raise HTTPException(status_code=400, detail="empty_patch")
    
    if not supabase:
        return await supabase_update_agent_status(request.state.token, agent_id, payload)

    try:
        client = get_authenticated_client(request.state.token)
        _assert_not_system_agent(client, agent_id)
        res = client.table("agents").update(payload).eq("id", agent_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Target Agent Not Found")
        agent_dict = Agent(**res.data[0]).to_zod_dict()
        company_id = res.data[0].get("company_id")
        if company_id:
            await ws_manager.emit_agent_updated(company_id, agent_dict)
        return agent_dict
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_agent failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        check = client.table("agents").select("id,company_id,is_system").eq("id", agent_id).execute()
        if not check.data:
            raise HTTPException(status_code=404, detail="Target Agent Not Found")
        if check.data[0].get("is_system"):
            raise HTTPException(status_code=403, detail="system_agent_immutable")
        company_id = check.data[0].get("company_id")
        client.table("agents").delete().eq("id", agent_id).execute()
        if company_id:
            await ws_manager.emit_agent_updated(company_id, {"id": agent_id, "deleted": True})
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_agent failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tasks/{task_id}/claim")
async def claim_task(request: Request, task_id: str):
    if not supabase: return MOCK_TASKS[0]
    try:
        client = get_authenticated_client(request.state.token)
        current = (
            client.table("tasks")
            .select("id,company_id,assigned_to_agent_id,status,budget_limit,cost_usd,approved_at,approved_by_user_id")
            .eq("id", task_id)
            .limit(1)
            .execute()
        )
        if not current.data:
            raise HTTPException(404, "Target Task Not Found")
        _enforce_task_execution_gates(current.data[0], source="claim")
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

        # Fetch first so we can act on request_type after updating
        fetch_res = client.table("approvals").select("*").eq("id", approval_id).limit(1).execute()
        if not fetch_res.data:
            raise HTTPException(404, "Target Approval Not Found")
        approval_row = fetch_res.data[0]

        res = client.table("approvals").update(patch).eq("id", approval_id).execute()
        if not res.data:
            raise HTTPException(404, "Target Approval Not Found")

        # Auto-create agent when a hire_agent approval is approved
        if status == "approved" and approval_row.get("request_type") == "hire_agent":
            _auto_create_agent_from_approval(approval_row)

        # G1.1 audit log (best-effort) — compliance trail de quem aprovou/rejeitou o quê
        try:
            scope = get_user_scope(request.state.token)
            actor_id = str(scope.get("user_id") or "unknown")
        except Exception:
            actor_id = "unknown"
        from src.services.audit import audit_log
        audit_log(
            supabase,
            company_id=str(approval_row.get("company_id") or ""),
            actor_type="human",
            actor_id=actor_id,
            action=f"approval.{status}",  # approval.approved | approval.rejected
            target=f"approval:{approval_id}",
            payload={
                "request_type": approval_row.get("request_type"),
                "previous_status": approval_row.get("status"),
                "new_status": status,
                "auto_created_agent": (status == "approved" and approval_row.get("request_type") == "hire_agent"),
            },
        )

        return CouncilApproval(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except PostgrestAPIError as e:
        if e.code == "PGRST205":
            logger.debug("vectraclip.approvals missing on update; using mock approvals")
            return _mock_set_approval_status(approval_id, status)
        raise HTTPException(500, str(e))
    except Exception as e:
        logger.error(f"set_approval_status failed: {e}")
        return _mock_set_approval_status(approval_id, status)


def _auto_create_agent_from_approval(approval_row: dict) -> None:
    """Creates an agent row when a hire_agent approval is approved. Non-fatal."""
    try:
        p = approval_row.get("payload") or {}
        company_id = approval_row.get("company_id")
        if not company_id:
            return
        _to_db = {"claude_code": "claude_code", "codex": "cursor", "shell": "bot", "webhook": "bot"}
        adapter_type = _to_db.get(str(p.get("adapterType", "claude_code")), "claude_code")
        row: Dict[str, Any] = {
            "company_id": company_id,
            "name": str(p.get("name", "Unnamed Agent")),
            "role": str(p.get("role", "Agent")),
            "reports_to_id": p.get("reportsToId") or None,
            "status": "idle",
            "token_budget": int(p.get("tokenBudget", 50000)),
            "current_burn_rate": 0,
            "adapter_type": adapter_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        supabase.table("agents").insert(row).execute()
        logger.info(f"auto_create_agent_from_approval: created agent '{row['name']}' for company {company_id}")
    except Exception as e:
        logger.error(f"auto_create_agent_from_approval failed (non-fatal): {e}")


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
    await websocket.accept()

    # --- Auth ---
    if token:
        try:
            claims = validate_supabase_jwt(token)
            if claims:
                token_company = (
                    claims.get("company_id")
                    or claims.get("user_metadata", {}).get("company_id")
                    or claims.get("app_metadata", {})
                    .get("vectraclip", {})
                    .get("company_id")
                )
            else:
                # Fallback local para evitar falso-negativo de WS quando houver
                # oscilação na validação via JWKS. Mantém guard de company.
                token_company = (_extract_vectraclip_claims(token) or {}).get("company_id")
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
        from fastapi.responses import PlainTextResponse  # pyright: ignore[reportMissingImports]
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
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("extract_bl_pl endpoint error")
        raise HTTPException(status_code=500, detail=str(exc))


# =====================================================================
# LLM Models + Agent Specialties (VEC-241)
# =====================================================================

@app.get("/api/llm-models")
@app.get("/llm-models")
async def list_llm_models(request: Request, active: Optional[str] = None):
    active_only = active != "false"
    if not supabase:
        rows = MOCK_LLM_MODELS if active_only else MOCK_LLM_MODELS
        return [LlmModel(**r).to_zod_dict() for r in rows if not active_only or r["is_active"]]
    try:
        q = supabase.table("llm_models").select("id,provider,display_name,input_cost_per_1m,output_cost_per_1m,cache_read_cost_per_1m,context_window_k,is_active,effective_from")
        if active_only:
            q = q.eq("is_active", True)
        res = q.order("display_name").execute()
        return [LlmModel(**row).to_zod_dict() for row in (res.data or [])]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"list_llm_models failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class LlmModelInput(BaseModel):
    provider: str
    displayName: str
    inputCostPer1M: float
    outputCostPer1M: float
    cacheReadCostPer1M: float = 0.0
    contextWindowK: int
    effectiveFrom: str
    isActive: Optional[bool] = True


@app.post("/api/llm-models")
@app.post("/llm-models")
async def create_llm_model(request: Request, payload: LlmModelInput):
    now_iso = datetime.now(timezone.utc).isoformat()
    row = {
        "id": f"llm_{int(datetime.now().timestamp())}",
        "provider": payload.provider,
        "display_name": payload.displayName,
        "input_cost_per_1m": payload.inputCostPer1M,
        "output_cost_per_1m": payload.outputCostPer1M,
        "cache_read_cost_per_1m": payload.cacheReadCostPer1M,
        "context_window_k": payload.contextWindowK,
        "is_active": payload.isActive if payload.isActive is not None else True,
        "effective_from": payload.effectiveFrom,
        "created_at": now_iso,
    }
    if not supabase:
        mock_row = {k: v for k, v in row.items()}
        MOCK_LLM_MODELS.append(mock_row)
        return LlmModel(**mock_row).to_zod_dict()
    try:
        res = supabase.table("llm_models").insert(row).execute()
        return LlmModel(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"create_llm_model failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/llm-models/{model_id}")
@app.patch("/llm-models/{model_id}")
async def patch_llm_model(request: Request, model_id: str, payload: Dict[str, Any]):
    if not supabase:
        m = next((r for r in MOCK_LLM_MODELS if r["id"] == model_id), None)
        if not m:
            raise HTTPException(status_code=404, detail="llm_model_not_found")
        m.update(payload)
        return LlmModel(**m).to_zod_dict()
    try:
        field_map = {
            "provider": "provider",
            "displayName": "display_name",
            "inputCostPer1M": "input_cost_per_1m",
            "outputCostPer1M": "output_cost_per_1m",
            "cacheReadCostPer1M": "cache_read_cost_per_1m",
            "contextWindowK": "context_window_k",
            "isActive": "is_active",
            "effectiveFrom": "effective_from",
        }
        update_data = {field_map[k]: v for k, v in payload.items() if k in field_map}
        if not update_data:
            raise HTTPException(status_code=400, detail="no_fields_to_update")
        # ACCEPTED bypass: llm_models é catalog CROSS-TENANT (não tem company_id).
        # G2.1 (PR #168) criou policy WRITE platform_admin no DB, mas Marcelo
        # (tenant admin) NÃO é platform_admin — UI tenant não consegue gerenciar.
        # Mantém service_role aqui; UI de gerência futura via admin console de
        # plataforma quando RBAC platform_admin estiver implementado.
        res = supabase.table("llm_models").update(update_data).eq("id", model_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="llm_model_not_found")
        return LlmModel(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_llm_model failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/llm-models/{model_id}")
@app.delete("/llm-models/{model_id}")
async def delete_llm_model(request: Request, model_id: str):
    if not supabase:
        m = next((r for r in MOCK_LLM_MODELS if r["id"] == model_id), None)
        if not m:
            raise HTTPException(status_code=404, detail="llm_model_not_found")
        m["is_active"] = False
        return Response(status_code=204)
    try:
        supabase.table("llm_models").update({"is_active": False}).eq("id", model_id).execute()
        return Response(status_code=204)
    except Exception as e:
        logger.error(f"delete_llm_model failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agent-domains")
@app.get("/agent-domains")
async def list_agent_domains(request: Request):
    """PR-DB — catálogo canônico de domínios (substitui texto livre).

    Lido pela tab Skills (agrupar specialties por domínio) e pelo NAV ADMIN
    (filtros + dropdowns nos formulários de specialty). Retorna apenas
    domains ativos, ordenados por `display_order`.
    """
    if not supabase:
        # Mock fallback: lista vazia em dev sem Supabase
        return []
    try:
        res = (
            supabase.table("agent_domains")
            .select("id,name,description,icon,color,display_order,is_active")
            .eq("is_active", True)
            .order("display_order")
            .execute()
        )
        return [AgentDomain(**row).to_zod_dict() for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_agent_domains failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/operation-types")
@app.get("/operation-types")
async def list_operation_types(request: Request):
    """Task #52 — catálogo canônico dos operation_types.

    Substitui enum hardcoded no Zod schema do frontend. Espelha o
    Literal[...] do Pydantic Task com metadata rica (name, description,
    category, icon, color, primary_agent_id, default_specialty_slug).

    Read-only para usuário autenticado. Mutações via migration.
    """
    if not supabase:
        return []
    try:
        res = (
            supabase.table("operation_types_catalog")
            .select(
                "id,name,description,category,icon,color,display_order,"
                "primary_agent_id,default_specialty_slug,is_active"
            )
            .eq("is_active", True)
            .order("display_order")
            .execute()
        )
        return [OperationType(**row).to_zod_dict() for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_operation_types failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/workflow-logic-patterns")
@app.get("/workflow-logic-patterns")
async def list_workflow_logic_patterns(request: Request):
    """Task #49 — catálogo canônico de logic_patterns para workflow_steps.

    Espelha os 8 patterns (7 do FlowLogic.tsx + SIMPLE default) que
    alimentam: tela /flow-logic (catálogo educativo), Tab Orquestração no
    form Nova Etapa (#48 frontend) e FK em workflow_steps.logic_pattern.

    Read-only para todos; mutações via migration apenas. Retorna patterns
    ativos ordenados por `display_order`.
    """
    if not supabase:
        return []
    try:
        res = (
            supabase.table("workflow_logic_patterns")
            .select(
                "id,category,taxonomy,name,description,heuristics,icon,color,"
                "display_order,json_skeleton,engine_handler,is_active"
            )
            .eq("is_active", True)
            .order("display_order")
            .execute()
        )
        return [
            WorkflowLogicPattern(**row).to_zod_dict() for row in (res.data or [])
        ]
    except Exception as e:
        logger.error(f"list_workflow_logic_patterns failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/workflow-trigger-types")
@app.get("/workflow-trigger-types")
async def list_workflow_trigger_types(request: Request):
    """PR-T1 — catálogo canônico de trigger types para workflow_definitions.

    Define COMO um workflow é disparado (manual/cron/webhook/event). FK em
    workflow_definitions.trigger_type. Lido pelo /workflow frontend para
    renderizar dropdown/chips + form da aba Trigger.

    Read-only para autenticado. Mutações por migration.
    """
    if not supabase:
        return []
    try:
        res = (
            supabase.table("workflow_trigger_types")
            .select("slug,name,description,icon,display_order,is_active")
            .eq("is_active", True)
            .order("display_order")
            .execute()
        )
        return [WorkflowTriggerType(**row).to_zod_dict() for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_workflow_trigger_types failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agent-execution-modes")
@app.get("/agent-execution-modes")
async def list_agent_execution_modes(request: Request):
    """PR-EB — catálogo canônico de modos de execução.

    Substitui CHECK hardcoded ('REALTIME','CRON','TRIGGER') por tabela com
    config_schema declarado por modo. Frontend da tab Configuration usa
    para popular o dropdown de Modo e renderizar form condicional dos
    campos filhos quando o usuário seleciona um modo. Retorna apenas modos
    ativos, ordenados por `display_order`.
    """
    if not supabase:
        return []
    try:
        res = (
            supabase.table("agent_execution_modes")
            .select(
                "id,name,description,icon,color,display_order,config_schema,is_active"
            )
            .eq("is_active", True)
            .order("display_order")
            .execute()
        )
        return [AgentExecutionMode(**row).to_zod_dict() for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_agent_execution_modes failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agent-specialties")
@app.get("/agent-specialties")
async def list_agent_specialties(request: Request):
    if not supabase:
        return [AgentSpecialty(**r).to_zod_dict() for r in MOCK_AGENT_SPECIALTIES if r["is_active"]]
    try:
        res = (
            supabase.table("agent_specialties")
            .select("id,name,slug,domain,description,compatible_roles,system_prompt_template,config_schema,is_active")
            .eq("is_active", True)
            .order("name")
            .execute()
        )
        return [AgentSpecialty(**row).to_zod_dict() for row in (res.data or [])]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"list_agent_specialties failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class AgentSpecialtyInput(BaseModel):
    name: str
    slug: str
    domain: str
    description: str = ""
    compatibleRoles: List[str] = Field(default_factory=list)
    systemPromptTemplate: str = ""
    configSchema: Optional[Dict[str, Any]] = None


@app.post("/api/agent-specialties")
@app.post("/agent-specialties")
async def create_agent_specialty(request: Request, payload: AgentSpecialtyInput):
    now_iso = datetime.now(timezone.utc).isoformat()
    if not supabase:
        new_sp = {
            "id": f"sp_{int(datetime.now().timestamp())}",
            "name": payload.name,
            "slug": payload.slug,
            "domain": payload.domain,
            "description": payload.description,
            "compatible_roles": payload.compatibleRoles,
            "system_prompt_template": payload.systemPromptTemplate,
            "config_schema": payload.configSchema,
            "is_active": True,
        }
        MOCK_AGENT_SPECIALTIES.append(new_sp)
        return AgentSpecialty(**new_sp).to_zod_dict()

    try:
        row = {
            "id": f"sp_{int(datetime.now().timestamp())}",
            "name": payload.name,
            "slug": payload.slug,
            "domain": payload.domain,
            "description": payload.description,
            "compatible_roles": payload.compatibleRoles,
            "system_prompt_template": payload.systemPromptTemplate,
            "config_schema": payload.configSchema,
            "is_active": True,
            "created_at": now_iso,
        }
        res = supabase.table("agent_specialties").insert(row).execute()
        return AgentSpecialty(**res.data[0]).to_zod_dict()
    except Exception as e:
        logger.error(f"create_agent_specialty failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/agent-specialties/{specialty_id}")
@app.patch("/agent-specialties/{specialty_id}")
async def patch_agent_specialty(request: Request, specialty_id: str, payload: Dict[str, Any]):
    if not supabase:
        sp = next((s for s in MOCK_AGENT_SPECIALTIES if s["id"] == specialty_id), None)
        if not sp:
            raise HTTPException(status_code=404, detail="specialty_not_found")
        sp.update(payload)
        return AgentSpecialty(**sp).to_zod_dict()

    try:
        update_data: Dict[str, Any] = {}
        if "name" in payload: update_data["name"] = payload["name"]
        if "slug" in payload: update_data["slug"] = payload["slug"]
        if "domain" in payload: update_data["domain"] = payload["domain"]
        if "description" in payload: update_data["description"] = payload["description"]
        if "compatibleRoles" in payload: update_data["compatible_roles"] = payload["compatibleRoles"]
        if "systemPromptTemplate" in payload: update_data["system_prompt_template"] = payload["systemPromptTemplate"]
        if "configSchema" in payload: update_data["config_schema"] = payload["configSchema"]
        if "isActive" in payload: update_data["is_active"] = payload["isActive"]
        if not update_data:
            raise HTTPException(status_code=400, detail="no_fields_to_update")
        res = supabase.table("agent_specialties").update(update_data).eq("id", specialty_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="specialty_not_found")
        return AgentSpecialty(**res.data[0]).to_zod_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_agent_specialty failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/agent-specialties/{specialty_id}")
@app.delete("/agent-specialties/{specialty_id}")
async def delete_agent_specialty(request: Request, specialty_id: str):
    if not supabase:
        global MOCK_AGENT_SPECIALTIES
        MOCK_AGENT_SPECIALTIES = [s for s in MOCK_AGENT_SPECIALTIES if s["id"] != specialty_id]
        return Response(status_code=204)

    try:
        supabase.table("agent_specialties").update({"is_active": False}).eq("id", specialty_id).execute()
        return Response(status_code=204)
    except Exception as e:
        logger.error(f"delete_agent_specialty failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================================
# Claude Managed Agents (CMA) — Task Execution Endpoint
# =====================================================================

class ExecuteTaskRequest(BaseModel):
    force_mode: Optional[Literal["managed_agent", "harness", "auto"]] = None


@app.post("/api/tasks/{task_id}/execute")
@app.post("/tasks/{task_id}/execute")
async def execute_task_endpoint(task_id: str, body: ExecuteTaskRequest, request: Request):
    """
    Executa uma task imediatamente via CMA ou Harness.
    force_mode="auto" (padrão) usa o Decision Engine para escolher.
    """
    from src.managed_agents.router import route_task_execution

    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase não disponível")

    # Busca task
    try:
        res = (
            supabase.table("tasks")
            .select("id,title,description,operation_type,budget_limit,cost_usd,approved_at,approved_by_user_id,company_id,assigned_to_agent_id,status,executor_type")
            .eq("id", task_id)
            .single()
            .execute()
        )
        task = res.data
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Task não encontrada: {e}")

    if not task:
        raise HTTPException(status_code=404, detail="Task não encontrada")

    if task.get("status") == "in_progress":
        raise HTTPException(status_code=409, detail="Task já está em execução")
    _enforce_task_execution_gates(task, source="execute")

    try:
        result = await route_task_execution(
            task=task,
            force_mode=body.force_mode,
            supabase_client=supabase,
            ws_manager=ws_manager,
        )
        return result
    except Exception as e:
        logger.error(f"execute_task_endpoint error task_id={task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# VEC-237-G  Plutus approval gate
# ─────────────────────────────────────────────────────────────────────────────

class ApproveTaskBody(BaseModel):
    approved_by_user_id: Optional[str] = None


@app.post("/api/tasks/{task_id}/approve")
async def approve_task(task_id: str, request: Request, body: ApproveTaskBody = ApproveTaskBody()):
    """
    Sets approved_at + approved_by_user_id on a task in status=review.
    Plutus daemon picks it up on the next tick and executes step 3 (insert_quote).
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase não disponível")

    try:
        res = (
            supabase.table("tasks")
            .select("id, status, company_id, operation_type, output_json")
            .eq("id", task_id)
            .single()
            .execute()
        )
        task = res.data
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Task não encontrada: {e}")

    if task.get("status") not in ("review", "blocked"):
        raise HTTPException(
            status_code=409,
            detail=f"Task não está em review. Status atual: {task.get('status')}",
        )

    user_payload = getattr(request.state, "user", {}) or {}
    approver_id = (
        body.approved_by_user_id
        or user_payload.get("sub")
        or user_payload.get("id")
    )
    now_iso = datetime.now(timezone.utc).isoformat()

    operation_type = task.get("operation_type") or ""
    output_json = task.get("output_json") or {}
    update_payload = {
        "approved_at": now_iso,
        "approved_by_user_id": approver_id,
        "status": "queued",  # default behavior keeps existing Plutus flow
        "updated_at": now_iso,
    }

    # Mercator gate: human approves truck suggestion, then routes to Hodos stage.
    if operation_type == "freight-quotation-approval":
        briefing = (output_json.get("briefing") or {}) if isinstance(output_json, dict) else {}
        suggestion = (briefing.get("vehicle_suggestion") or {}) if isinstance(briefing, dict) else {}
        if isinstance(suggestion, dict):
            suggestion["approval_status"] = "approved"
            suggestion["approved_at"] = now_iso
            suggestion["approved_by_user_id"] = approver_id
            briefing["vehicle_suggestion"] = suggestion
            output_json["briefing"] = briefing
        update_payload.update(
            {
                "status": "review",
                "operation_type": "route-cost-calculation",
                "output_json": output_json,
            }
        )

    try:
        updated = (
            supabase.table("tasks")
            .update(update_payload)
            .eq("id", task_id)
            .execute()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao aprovar task: {e}")

    company_id = task.get("company_id", "")
    try:
        from src.models import Task as TaskModel
        task_payload = TaskModel(**updated.data[0]).to_zod_dict()
        ws_manager.broadcast_nowait(
            company_id,
            {"type": "task_updated", "payload": task_payload},
        )
    except Exception:
        pass

    return {"approved": True, "task_id": task_id, "approved_by": approver_id}


# ─────────────────────────────────────────────────────────────────────────────
# VEC-237-I  Workflow CRUD
# ─────────────────────────────────────────────────────────────────────────────
#
# Task #45 (consolidação): `GET /api/companies/{company_id}/workflows` foi
# movido para src/api_routes/workflows.py (versão canônica do submodule),
# que mescla os 2 comportamentos divergentes: visibility company+global,
# is_active filter, steps_count enrichment e JWT validation.


@app.get("/api/workflows/{workflow_id}/steps")
async def list_workflow_steps(workflow_id: str, request: Request):
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase não disponível")
    res = (
        supabase.table("workflow_steps")
        .select("*")
        .eq("workflow_id", workflow_id)
        .order("step_order")
        .execute()
    )
    return res.data or []


if __name__ == "__main__":
    import uvicorn  # pyright: ignore[reportMissingImports]
    uvicorn.run(app, host="0.0.0.0", port=3000)



@app.post("/api/workflow/run-orchestrator")
async def run_flow_orchestrator(request: Request):
    try:
        from src.services.flow_orchestrator import build_orchestrator
        from langchain_core.messages import HumanMessage  # pyright: ignore[reportMissingImports]
    except ImportError:
        raise HTTPException(status_code=500, detail="LangGraph engine not installed or built.")
        
    data = await request.json()
    prompt = data.get("prompt", "Inicie o fluxo base.")
    
    app_orchestrator = build_orchestrator()
    initial_state = {
        "messages": [HumanMessage(content=prompt)],
        "context_data": {},
        "iteration_count": 0,
        "current_node": "supervisor"
    }
    
    async def event_generator():
        # Transmite os eventos passo a passo usando Server-Sent Events (SSE)
        for output in app_orchestrator.stream(initial_state):
            for key, value in output.items():
                event_data = {"node": key, "message": f"Nó Concluído: {key}"}
                yield f"data: {_json_wf.dumps(event_data)}\n\n"
                await asyncio.sleep(0.5)
        yield "data: {\"node\": \"END\", \"message\": \"Fluxo Finalizado\"}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ─────────────────────────────────────────────────────────────────────────────
# Constants compartilhadas com src/api_routes/* (importadas lazy nos submodules)
# ─────────────────────────────────────────────────────────────────────────────
_ORACLE_AGENT_ID = "00000000-0000-0000-0000-000000000002"
HERMES_REPORTER_AGENT_ID = "360a96cb-b1c3-4b65-b9fa-2b9cbb59dac1"


# ─────────────────────────────────────────────────────────────────────────────
# Routers extraídos para src/api_routes/<feature>.py (Step 8 split progressivo)
# ─────────────────────────────────────────────────────────────────────────────
from src.api_routes import prospects as _prospects_routes  # noqa: E402
from src.api_routes import research_templates as _research_templates_routes  # noqa: E402
from src.api_routes import workflows as _workflows_routes  # noqa: E402
from src.api_routes import system as _system_routes  # noqa: E402
from src.api_routes import kronos_rules as _kronos_rules_routes  # noqa: E402
from src.api_routes import tasks_workflow as _tasks_workflow_routes  # noqa: E402
from src.api_routes import companies_extras as _companies_extras_routes  # noqa: E402
from src.api_routes import oracle_chat as _oracle_chat_routes  # noqa: E402
from src.api_routes import rag as _rag_routes  # noqa: E402
from src.api_routes import athena as _athena_routes  # noqa: E402
from src.api_routes import sipoc_taxonomy as _sipoc_taxonomy_routes  # noqa: E402
from src.api_routes import admin as _admin_routes  # noqa: E402
from src.api_routes import sipoc_diagnose as _sipoc_diagnose_routes  # noqa: E402

app.include_router(_prospects_routes.router)
app.include_router(_research_templates_routes.router)
app.include_router(_workflows_routes.router)
app.include_router(_system_routes.router)
app.include_router(_kronos_rules_routes.router)
app.include_router(_tasks_workflow_routes.router)
app.include_router(_companies_extras_routes.router)
app.include_router(_oracle_chat_routes.router)
app.include_router(_rag_routes.router)
app.include_router(_athena_routes.router)
app.include_router(_sipoc_taxonomy_routes.router)
app.include_router(_admin_routes.router)
app.include_router(_sipoc_diagnose_routes.router)

