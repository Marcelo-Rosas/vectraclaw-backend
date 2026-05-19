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

from fastapi import APIRouter, Body, HTTPException, Path, Request

logger = logging.getLogger("api.agent_mcp_bindings")

router = APIRouter(tags=["mcp-bindings"])


def _resolve_company(request: Request) -> str:
    company_id = getattr(request.state, "company_id", None)
    if not company_id:
        raise HTTPException(status_code=401, detail="unauthenticated")
    return str(company_id)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _server_to_camel(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "description": row.get("description"),
        "transport": row.get("transport"),
        "endpointUrlTemplate": row.get("endpoint_url_template"),
        "authType": row.get("auth_type"),
        "fieldDefinitions": row.get("field_definitions") or [],
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

def _do_handshake(binding_row: Dict[str, Any], server_row: Dict[str, Any], company_id: str) -> List[Dict[str, Any]]:
    """Conecta no MCP server + lista tools. Suporta http + api_key/bearer/none.
    oauth2/stdio levantam 502 (N7 auth resolver pendente)."""
    from src.api import resolve_secret_ref
    from src.services.mcp_client import McpClient

    transport = server_row.get("transport")
    auth_type = server_row.get("auth_type")
    if transport != "http":
        raise HTTPException(status_code=502, detail=f"handshake_transport_unsupported:{transport}_needs_N7")
    if auth_type in ("oauth2_client_credentials",):
        raise HTTPException(status_code=502, detail="handshake_oauth2_needs_N7_auth_resolver")

    field_values = binding_row.get("field_values_json") or {}
    # Resolve endpoint a partir do template + field_values
    endpoint = server_row.get("endpoint_url_template") or ""
    for k, v in field_values.items():
        endpoint = endpoint.replace("{" + k + "}", str(v))
    if "{" in endpoint:
        raise HTTPException(status_code=422, detail=f"endpoint_template_unresolved:{endpoint}")

    # Resolve token/key (pode ser vault:// ref)
    api_key: Optional[str] = None
    for cand in ("access_token", "api_key", "token", "password"):
        if cand in field_values:
            api_key = resolve_secret_ref(field_values[cand], company_id)
            break

    client = McpClient(endpoint, api_key=api_key)
    tools = client.list_tools()
    return tools


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
            tools = _do_handshake(b, server.data[0], company_id)
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
