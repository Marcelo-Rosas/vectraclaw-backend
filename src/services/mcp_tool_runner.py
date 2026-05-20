"""MCP Tool Runner — "o dedo" que executa uma tool MCP em runtime (frente b).

Dado um nome prefixado (mcp__<server>__<tool>) + argumentos, resolve o binding
do agente + credenciais effective (company_mcp_values PRIMARY + override) +
chama McpClient.call_tool. Respeita whitelist allowed_tools.

Primitiva reusável: o loop tool_use dos providers (managed_agents) chama
execute_mcp_tool quando o LLM pede uma tool com prefixo mcp__.

NÃO faz o loop LLM em si — só a execução de UMA tool. Integração no loop
autônomo (injetar tools no request + rotear tool_use) é a próxima camada.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("MCP_Tool_Runner")

PREFIX = "mcp__"


def parse_prefixed_tool(name: str) -> Optional[tuple[str, str]]:
    """mcp__<server_id_underscored>__<tool> → (server_id_underscored, tool_name).
    Retorna None se não for prefixado. server_id volta com underscores (igual
    catalog id com hífens vira underscore na injeção do prompt — N7.5)."""
    if not name or not name.startswith(PREFIX):
        return None
    rest = name[len(PREFIX):]
    sep = rest.find("__")
    if sep < 0:
        return None
    return rest[:sep], rest[sep + 2:]


def list_agent_mcp_tools(supabase: Any, agent_id: str) -> List[Dict[str, Any]]:
    """Tools MCP disponíveis pro agente (de bindings ativos, tools_cache),
    já prefixadas + filtradas por allowed_tools. Formato pronto pra injetar
    no tools[] do provider (name/description/input_schema)."""
    out: List[Dict[str, Any]] = []
    try:
        binds = (
            supabase.table("agent_mcp_bindings")
            .select("mcp_server_id, allowed_tools, tools_cache")
            .eq("agent_id", agent_id)
            .eq("is_active", True)
            .execute()
        )
    except Exception as e:
        logger.warning(f"list_agent_mcp_tools lookup falhou: {e}")
        return out
    for b in (binds.data or []):
        server_id = b.get("mcp_server_id") or ""
        prefix = PREFIX + server_id.replace("-", "_") + "__"
        allowed = b.get("allowed_tools")
        for t in (b.get("tools_cache") or []):
            if not isinstance(t, dict):
                continue
            tname = t.get("name")
            if not tname or (allowed is not None and tname not in allowed):
                continue
            out.append({
                "name": prefix + tname,
                "description": t.get("description") or "",
                "input_schema": t.get("inputSchema") or t.get("input_schema") or {"type": "object"},
            })
    return out


def execute_mcp_tool(
    supabase: Any, company_id: str, agent_id: str, prefixed_name: str, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    """Executa UMA tool MCP. Resolve binding + creds effective (company PRIMARY +
    override) + whitelist + McpClient.call_tool. Retorna {success, result|error}."""
    from src.api import resolve_secret_ref
    from src.services.mcp_client import McpClient, McpAuthError
    from src.api_routes.agent_mcp_bindings import _resolve_effective_field_values

    parsed = parse_prefixed_tool(prefixed_name)
    if not parsed:
        return {"success": False, "error": f"not_mcp_tool:{prefixed_name}"}
    server_us, tool_name = parsed

    # bindings do agente; casa server por id-underscored == server_id.replace('-','_')
    try:
        binds = (
            supabase.table("agent_mcp_bindings")
            .select("mcp_server_id, allowed_tools, field_values_json")
            .eq("agent_id", agent_id)
            .eq("is_active", True)
            .execute()
        )
    except Exception as e:
        return {"success": False, "error": f"binding_lookup_failed:{e}"}

    match = None
    for b in (binds.data or []):
        if (b.get("mcp_server_id") or "").replace("-", "_") == server_us:
            match = b
            break
    if not match:
        return {"success": False, "error": f"no_active_binding_for_server:{server_us}"}

    server_id = match["mcp_server_id"]
    allowed = match.get("allowed_tools")
    if allowed is not None and tool_name not in allowed:
        return {"success": False, "error": f"tool_not_allowed:{tool_name}"}

    try:
        server = supabase.table("mcp_server_catalog").select("*").eq("id", server_id).limit(1).execute()
        if not server.data:
            return {"success": False, "error": "mcp_server_not_found"}
        effective = _resolve_effective_field_values(supabase, company_id, server_id, match.get("field_values_json"))
        resolver = lambda v: resolve_secret_ref(v, company_id)
        client = McpClient.from_binding(server.data[0], effective, secret_resolver=resolver)
        result = client.call_tool(tool_name, arguments or {})
        return {"success": True, "result": result}
    except McpAuthError as e:
        return {"success": False, "error": f"auth_failed:{e}"}
    except Exception as e:
        logger.error(f"execute_mcp_tool {prefixed_name} falhou: {e}")
        return {"success": False, "error": str(e)}
