"""N6 — Endpoints MCP Server Catalog + Agent MCP Bindings.

Parte da separação tri-tabela (Plan §4 / docs/CONTRACTS-MCP-BINDINGS.md):
- mcp_server_catalog: catálogo cross-tenant de MCP servers (read-only via API)
- agent_mcp_bindings: binding per-tenant (agent × mcp_server)

Endpoints (CONTRACTS §3):
- GET    /api/mcp/servers                       lista catalog ativo
- GET    /api/mcp/servers/{server_id}           detalhe 1 server
- GET    /api/agents/{agent_id}/mcp-bindings     bindings do agente
- POST   /api/agents/{agent_id}/mcp-bindings     cria binding
- PATCH  /api/mcp-bindings/{binding_id}          edita binding
- DELETE /api/mcp-bindings/{binding_id}          remove binding
- POST   /api/mcp-bindings/{binding_id}/handshake     testa conexão + popula tools_cache
- POST   /api/mcp-bindings/{binding_id}/tools/refresh refresca tools_cache

Auth: middleware existente (request.state.company_id). Filtro company_id
EXPLÍCITO em toda query (api usa service_role; não confia só em RLS).

Limitação N6: handshake suporta transport=http com auth_type api_key/bearer/none.
oauth2_client_credentials (Camunda) precisa do auth resolver do N7 — retorna
502 com mensagem clara. stdio idem (N7).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Path, Query, Request

logger = logging.getLogger("api.agent_mcp_bindings")

router = APIRouter(tags=["mcp-bindings"])


def _resolve_company(request: Request) -> str:
    company_id = getattr(request.state, "company_id", None)
    if not company_id:
        raise HTTPException(status_code=401, detail="unauthenticated")
    return str(company_id)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _field_def_to_camel(d: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza um item de field_definitions (shape seed {key,label,type,required,...})
    pro shape camelCase que o frontend McpEmbeddedFieldDefinition espera
    ({fieldKey,fieldLabel,fieldType,isRequired,...}). Sem isso o filtro
    embeddedFieldsToAdapterFields(d.fieldKey) derruba todos os campos → form vazio."""
    if not isinstance(d, dict):
        return {}
    return {
        "fieldKey": d.get("fieldKey") or d.get("key"),
        "fieldLabel": d.get("fieldLabel") or d.get("label"),
        "fieldType": d.get("fieldType") or d.get("type") or "text",
        "isRequired": d.get("isRequired") if d.get("isRequired") is not None else bool(d.get("required", False)),
        "optionsJson": d.get("optionsJson") or d.get("options_json"),
        "sortOrder": d.get("sortOrder") or d.get("sort_order"),
        "defaultValue": d.get("defaultValue") if d.get("defaultValue") is not None else d.get("default"),
        "placeholder": d.get("placeholder"),
    }


def _server_to_camel(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "description": row.get("description"),
        "transport": row.get("transport"),
        "endpointUrlTemplate": row.get("endpoint_url_template"),
        "authType": row.get("auth_type"),
        "fieldDefinitions": [_field_def_to_camel(d) for d in (row.get("field_definitions") or [])],
        "category": row.get("category"),
        "icon": row.get("icon"),
        "color": row.get("color"),
        "displayOrder": row.get("display_order"),
        "isActive": row.get("is_active"),
        "documentationUrl": row.get("documentation_url"),
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


def _binding_to_camel(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "companyId": row.get("company_id"),
        "agentId": row.get("agent_id"),
        "mcpServerId": row.get("mcp_server_id"),
        "fieldValuesJson": row.get("field_values_json") or {},
        "allowedTools": row.get("allowed_tools"),
        "toolsCache": row.get("tools_cache"),
        "lastHealthAt": row.get("last_health_at"),
        "lastError": row.get("last_error"),
        "isActive": row.get("is_active"),
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Catalog (cross-tenant, read-only)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/mcp/servers")
@router.get("/mcp/servers")
async def list_mcp_servers(request: Request) -> List[Dict[str, Any]]:
    """Lista mcp_server_catalog ativo (cross-tenant)."""
    _resolve_company(request)
    from src.api import supabase
    if not supabase:
        return []
    try:
        res = (
            supabase.table("mcp_server_catalog")
            .select("*")
            .eq("is_active", True)
            .order("display_order")
            .execute()
        )
        return [_server_to_camel(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"list_mcp_servers failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/mcp/servers/{server_id}")
@router.get("/mcp/servers/{server_id}")
async def get_mcp_server(request: Request, server_id: str = Path(...)) -> Dict[str, Any]:
    _resolve_company(request)
    from src.api import supabase
    if not supabase:
        raise HTTPException(status_code=404, detail="server_not_found")
    try:
        res = (
            supabase.table("mcp_server_catalog")
            .select("*")
            .eq("id", server_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="server_not_found")
        return _server_to_camel(res.data[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_mcp_server failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Bindings (per-tenant)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/agents/{agent_id}/mcp-bindings")
@router.get("/agents/{agent_id}/mcp-bindings")
async def list_agent_mcp_bindings(request: Request, agent_id: str = Path(...)) -> List[Dict[str, Any]]:
    company_id = _resolve_company(request)
    from src.api import supabase
    if not supabase:
        return []
    try:
        res = (
            supabase.table("agent_mcp_bindings")
            .select("*")
            .eq("agent_id", agent_id)
            .eq("company_id", company_id)
            .execute()
        )
        return [_binding_to_camel(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"list_agent_mcp_bindings failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/agents/{agent_id}/mcp-bindings")
@router.post("/agents/{agent_id}/mcp-bindings")
async def create_agent_mcp_binding(
    request: Request,
    agent_id: str = Path(...),
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Cria binding (agent × mcp_server). Body: {mcpServerId, fieldValuesJson?, allowedTools?}."""
    company_id = _resolve_company(request)
    from src.api import supabase
    if not supabase:
        raise HTTPException(status_code=503, detail="db_unavailable")

    mcp_server_id = payload.get("mcpServerId") or payload.get("mcp_server_id")
    if not mcp_server_id:
        raise HTTPException(status_code=422, detail="mcpServerId_required")

    try:
        # Valida agente pertence à company
        agent_row = (
            supabase.table("agents").select("id,company_id").eq("id", agent_id).limit(1).execute()
        )
        if not agent_row.data:
            raise HTTPException(status_code=404, detail="agent_not_found")
        if str(agent_row.data[0].get("company_id")) != str(company_id):
            raise HTTPException(status_code=403, detail="cross_company_forbidden")

        # Valida server existe no catalog
        server_row = (
            supabase.table("mcp_server_catalog").select("id").eq("id", mcp_server_id).limit(1).execute()
        )
        if not server_row.data:
            raise HTTPException(status_code=404, detail="mcp_server_not_found")

        now = _now_iso()
        row = {
            "company_id": company_id,
            "agent_id": agent_id,
            "mcp_server_id": mcp_server_id,
            "field_values_json": payload.get("fieldValuesJson") or payload.get("field_values_json") or {},
            "allowed_tools": payload.get("allowedTools") or payload.get("allowed_tools"),
            "is_active": payload.get("isActive", True),
            "created_at": now,
            "updated_at": now,
        }
        res = supabase.table("agent_mcp_bindings").insert(row).execute()
        if not res.data:
            raise HTTPException(status_code=500, detail="insert_returned_empty")
        return _binding_to_camel(res.data[0])
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e)
        # UNIQUE (agent_id, mcp_server_id)
        if "uq_agent_mcp_bindings_agent_server" in msg or "duplicate key" in msg.lower():
            raise HTTPException(status_code=409, detail="binding_already_exists")
        logger.error(f"create_agent_mcp_binding failed: {e}")
        raise HTTPException(status_code=500, detail=msg)


@router.patch("/api/mcp-bindings/{binding_id}")
@router.patch("/mcp-bindings/{binding_id}")
async def patch_mcp_binding(
    request: Request,
    binding_id: str = Path(...),
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    company_id = _resolve_company(request)
    from src.api import supabase
    if not supabase:
        raise HTTPException(status_code=503, detail="db_unavailable")
    try:
        existing = (
            supabase.table("agent_mcp_bindings")
            .select("id,company_id")
            .eq("id", binding_id)
            .limit(1)
            .execute()
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="binding_not_found")
        if str(existing.data[0].get("company_id")) != str(company_id):
            raise HTTPException(status_code=403, detail="cross_company_forbidden")

        updates: Dict[str, Any] = {"updated_at": _now_iso()}
        if "fieldValuesJson" in payload or "field_values_json" in payload:
            updates["field_values_json"] = payload.get("fieldValuesJson") or payload.get("field_values_json") or {}
        if "allowedTools" in payload or "allowed_tools" in payload:
            updates["allowed_tools"] = payload.get("allowedTools") or payload.get("allowed_tools")
        if "isActive" in payload or "is_active" in payload:
            updates["is_active"] = payload.get("isActive", payload.get("is_active"))

        res = (
            supabase.table("agent_mcp_bindings")
            .update(updates)
            .eq("id", binding_id)
            .eq("company_id", company_id)
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=500, detail="update_returned_empty")
        return _binding_to_camel(res.data[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_mcp_binding failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/mcp-bindings/{binding_id}")
@router.delete("/mcp-bindings/{binding_id}")
async def delete_mcp_binding(request: Request, binding_id: str = Path(...)) -> Dict[str, Any]:
    company_id = _resolve_company(request)
    from src.api import supabase
    if not supabase:
        raise HTTPException(status_code=503, detail="db_unavailable")
    try:
        existing = (
            supabase.table("agent_mcp_bindings")
            .select("id,company_id")
            .eq("id", binding_id)
            .limit(1)
            .execute()
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="binding_not_found")
        if str(existing.data[0].get("company_id")) != str(company_id):
            raise HTTPException(status_code=403, detail="cross_company_forbidden")
        supabase.table("agent_mcp_bindings").delete().eq("id", binding_id).eq("company_id", company_id).execute()
        return {"deleted": True, "id": binding_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_mcp_binding failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Handshake + tools refresh
# ─────────────────────────────────────────────────────────────────────────────

def _company_mcp_value_to_camel(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "companyId": row.get("company_id"),
        "mcpServerId": row.get("mcp_server_id"),
        "profileKey": row.get("profile_key") or "default",
        "fieldValuesJson": row.get("field_values_json") or {},
        "allowedTools": row.get("allowed_tools"),
        "isActive": row.get("is_active"),
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


def _resolve_effective_field_values(
    supabase: Any,
    company_id: str,
    server_id: str,
    override: Optional[Dict[str, Any]] = None,
    profile_key: str = "default",
) -> Dict[str, Any]:
    """N11: credenciais MCP são PRIMARY no company_mcp_values (config em /admin/mcp).
    agent_mcp_bindings.field_values_json é override de exceção (W5 pattern).
    Resolve = company values (perfil) + override por cima."""
    effective: Dict[str, Any] = {}
    pk = (profile_key or "default").strip() or "default"
    try:
        q = (
            supabase.table("company_mcp_values")
            .select("field_values_json")
            .eq("company_id", company_id)
            .eq("mcp_server_id", server_id)
            .eq("is_active", True)
        )
        if pk != "default":
            q = q.eq("profile_key", pk)
        cv = q.limit(1).execute()
        if cv.data:
            effective.update(cv.data[0].get("field_values_json") or {})
        elif pk != "default":
            legacy = (
                supabase.table("company_mcp_values")
                .select("field_values_json")
                .eq("company_id", company_id)
                .eq("mcp_server_id", server_id)
                .eq("profile_key", "default")
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            if legacy.data:
                effective.update(legacy.data[0].get("field_values_json") or {})
    except Exception as e:
        logger.warning(f"_resolve_effective_field_values company lookup falhou: {e}")
    if override:
        effective.update({k: v for k, v in override.items() if v not in (None, "")})
    return effective


def _do_handshake(
    field_values: Dict[str, Any],
    server_row: Dict[str, Any],
    company_id: str,
) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Conecta no MCP server + lista tools, ou valida/autentica credential_only."""
    transport = (server_row.get("transport") or "").strip()
    if transport == "credential_only":
        from src.api import resolve_secret_ref
        from src.services.mcp_web_automation_probe import probe_planner_login

        resolver = lambda v: resolve_secret_ref(v, company_id)
        base = str(field_values.get("base_url") or field_values.get("url") or "").strip()
        user_raw = field_values.get("username") or field_values.get("email")
        pwd_raw = field_values.get("password")
        user = resolver(user_raw) if user_raw else ""
        pwd = resolver(pwd_raw) if pwd_raw else ""
        if not base or not str(user or "").strip() or not str(pwd or "").strip():
            raise HTTPException(
                status_code=422,
                detail="credential_only_incomplete:base_url,username,password",
            )
        login_url = str(field_values.get("login_url") or "").strip() or None
        probe = probe_planner_login(
            email=str(user).strip(),
            password=str(pwd).strip(),
            base_url=base.rstrip("/"),
            login_url=login_url,
        )
        if not probe.get("ok"):
            raise HTTPException(
                status_code=422,
                detail=f"planner_login_failed:{probe.get('message', 'unknown')}",
            )
        return [], probe

    from src.api import resolve_secret_ref
    from src.services.mcp_client import McpClient, McpAuthError

    resolver = lambda v: resolve_secret_ref(v, company_id)
    try:
        client = McpClient.from_binding(server_row, field_values or {}, secret_resolver=resolver)
    except McpAuthError as e:
        raise HTTPException(status_code=502, detail=f"handshake_auth_failed:{e}")
    return client.list_tools(), None


@router.post("/api/mcp-bindings/{binding_id}/handshake")
@router.post("/mcp-bindings/{binding_id}/handshake")
async def handshake_mcp_binding(request: Request, binding_id: str = Path(...)) -> Dict[str, Any]:
    company_id = _resolve_company(request)
    from src.api import supabase
    if not supabase:
        raise HTTPException(status_code=503, detail="db_unavailable")
    try:
        binding = (
            supabase.table("agent_mcp_bindings").select("*").eq("id", binding_id).limit(1).execute()
        )
        if not binding.data:
            raise HTTPException(status_code=404, detail="binding_not_found")
        b = binding.data[0]
        if str(b.get("company_id")) != str(company_id):
            raise HTTPException(status_code=403, detail="cross_company_forbidden")

        server = (
            supabase.table("mcp_server_catalog").select("*").eq("id", b.get("mcp_server_id")).limit(1).execute()
        )
        if not server.data:
            raise HTTPException(status_code=404, detail="mcp_server_not_found")

        now = _now_iso()
        try:
            # N11: creds PRIMARY de company_mcp_values + override do binding
            effective = _resolve_effective_field_values(
                supabase, company_id, b.get("mcp_server_id"), b.get("field_values_json")
            )
            tools, _probe = _do_handshake(effective, server.data[0], company_id)
            supabase.table("agent_mcp_bindings").update({
                "tools_cache": tools,
                "last_health_at": now,
                "last_error": None,
                "updated_at": now,
            }).eq("id", binding_id).execute()
            return {"tools": tools, "healthAt": now}
        except HTTPException as he:
            supabase.table("agent_mcp_bindings").update({
                "last_error": str(he.detail),
                "updated_at": now,
            }).eq("id", binding_id).execute()
            raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"handshake_mcp_binding failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/mcp-bindings/{binding_id}/tools/refresh")
@router.post("/mcp-bindings/{binding_id}/tools/refresh")
async def refresh_mcp_binding_tools(request: Request, binding_id: str = Path(...)) -> Dict[str, Any]:
    """Alias de handshake focado em refrescar tools_cache."""
    result = await handshake_mcp_binding(request, binding_id)
    return {"tools": result.get("tools", [])}


# ─────────────────────────────────────────────────────────────────────────────
# N11 — Company MCP credentials (PRIMARY; config em /admin/mcp)
# Secrets vão pro vault no frontend (useUpsertCompanySecret) ANTES do PUT;
# backend só persiste field_values_json com vault:// refs.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/companies/{company_id}/mcp-values")
@router.get("/companies/{company_id}/mcp-values")
async def list_company_mcp_values(request: Request, company_id: str = Path(...)) -> List[Dict[str, Any]]:
    caller = _resolve_company(request)
    if str(caller) != str(company_id):
        raise HTTPException(status_code=403, detail="cross_company_forbidden")
    from src.api import supabase
    if not supabase:
        return []
    try:
        res = (
            supabase.table("company_mcp_values")
            .select("*")
            .eq("company_id", company_id)
            .execute()
        )
        return [_company_mcp_value_to_camel(r) for r in (res.data or [])]
    except Exception as e:
        logger.error(f"list_company_mcp_values failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/companies/{company_id}/mcp-values/{server_id}")
@router.put("/companies/{company_id}/mcp-values/{server_id}")
async def upsert_company_mcp_value(
    request: Request,
    company_id: str = Path(...),
    server_id: str = Path(...),
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Upsert credenciais MCP da company. Body: {fieldValuesJson, allowedTools?, isActive?}.
    Secrets já devem vir como vault:// refs (frontend vaultou antes)."""
    caller = _resolve_company(request)
    if str(caller) != str(company_id):
        raise HTTPException(status_code=403, detail="cross_company_forbidden")
    from src.api import supabase
    if not supabase:
        raise HTTPException(status_code=503, detail="db_unavailable")
    try:
        server = supabase.table("mcp_server_catalog").select("id").eq("id", server_id).limit(1).execute()
        if not server.data:
            raise HTTPException(status_code=404, detail="mcp_server_not_found")
        now = _now_iso()
        pk = (
            payload.get("profileKey")
            or payload.get("profile_key")
            or "default"
        )
        pk = str(pk).strip() or "default"
        row = {
            "company_id": company_id,
            "mcp_server_id": server_id,
            "profile_key": pk,
            "field_values_json": payload.get("fieldValuesJson") or payload.get("field_values_json") or {},
            "allowed_tools": payload.get("allowedTools") or payload.get("allowed_tools"),
            "is_active": payload.get("isActive", True),
            "updated_at": now,
        }
        res = (
            supabase.table("company_mcp_values")
            .upsert(row, on_conflict="company_id,mcp_server_id,profile_key")
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=500, detail="upsert_returned_empty")
        return _company_mcp_value_to_camel(res.data[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"upsert_company_mcp_value failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/companies/{company_id}/mcp-values/{server_id}")
@router.delete("/companies/{company_id}/mcp-values/{server_id}")
async def delete_company_mcp_value(
    request: Request,
    company_id: str = Path(...),
    server_id: str = Path(...),
    profile_key: str = Query("default", alias="profileKey"),
) -> Dict[str, Any]:
    caller = _resolve_company(request)
    if str(caller) != str(company_id):
        raise HTTPException(status_code=403, detail="cross_company_forbidden")
    from src.api import supabase
    if not supabase:
        raise HTTPException(status_code=503, detail="db_unavailable")
    try:
        pk = (profile_key or "default").strip() or "default"
        supabase.table("company_mcp_values").delete().eq("company_id", company_id).eq(
            "mcp_server_id", server_id
        ).eq("profile_key", pk).execute()
        return {"deleted": True, "mcpServerId": server_id, "profileKey": pk}
    except Exception as e:
        logger.error(f"delete_company_mcp_value failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/agents/{agent_id}/mcp-tools")
@router.get("/agents/{agent_id}/mcp-tools")
async def list_agent_mcp_tools_route(request: Request, agent_id: str = Path(...)) -> List[Dict[str, Any]]:
    """Tools MCP disponíveis pro agente (prefixadas + whitelist), prontas pra
    injetar no loop do provider. Frente b."""
    _resolve_company(request)
    from src.api import supabase
    from src.services.mcp_tool_runner import list_agent_mcp_tools
    if not supabase:
        return []
    return list_agent_mcp_tools(supabase, agent_id)


@router.post("/api/agents/{agent_id}/mcp-tools/call")
@router.post("/agents/{agent_id}/mcp-tools/call")
async def call_agent_mcp_tool_route(
    request: Request, agent_id: str = Path(...), payload: Dict[str, Any] = Body(...)
) -> Dict[str, Any]:
    """Executa UMA tool MCP (o "dedo"). Body: {name: mcp__server__tool, arguments: {}}.
    Resolve binding + creds company + whitelist + call_tool."""
    company_id = _resolve_company(request)
    from src.api import supabase
    from src.services.mcp_tool_runner import execute_mcp_tool
    if not supabase:
        raise HTTPException(status_code=503, detail="db_unavailable")
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=422, detail="name_required")
    return execute_mcp_tool(supabase, company_id, agent_id, name, payload.get("arguments") or {})


@router.post("/api/companies/{company_id}/mcp-values/{server_id}/handshake")
@router.post("/companies/{company_id}/mcp-values/{server_id}/handshake")
async def handshake_company_mcp_value(
    request: Request,
    company_id: str = Path(...),
    server_id: str = Path(...),
    profile_key: str = Query("default", alias="profileKey"),
    payload: Dict[str, Any] = Body(default={}),
) -> Dict[str, Any]:
    """Testa credenciais company-level. Body opcional: {fieldValuesJson} do form (pré-save)."""
    caller = _resolve_company(request)
    if str(caller) != str(company_id):
        raise HTTPException(status_code=403, detail="cross_company_forbidden")
    from src.api import supabase
    if not supabase:
        raise HTTPException(status_code=503, detail="db_unavailable")
    try:
        server = supabase.table("mcp_server_catalog").select("*").eq("id", server_id).limit(1).execute()
        if not server.data:
            raise HTTPException(status_code=404, detail="mcp_server_not_found")
        pk = (profile_key or "default").strip() or "default"
        effective = _resolve_effective_field_values(
            supabase, company_id, server_id, None, profile_key=pk
        )
        override = payload.get("fieldValuesJson") or payload.get("field_values_json")
        if isinstance(override, dict) and override:
            effective.update({k: v for k, v in override.items() if v not in (None, "")})
        tools, probe = _do_handshake(effective, server.data[0], company_id)
        out: Dict[str, Any] = {"tools": tools, "healthAt": _now_iso()}
        if (server.data[0].get("transport") or "") == "credential_only":
            out["credentialOnly"] = True
            if probe:
                out["loginProbe"] = probe
        return out
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"handshake_company_mcp_value failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
