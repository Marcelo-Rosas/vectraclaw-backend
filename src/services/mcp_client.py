"""MCP Client — wrapper para Model Context Protocol servers.

N7 refactor (Plan §11.5): adiciona
- resolve_mcp_auth(): auth resolver por auth_type (oauth2_client_credentials /
  bearer / api_key / none) + resolução de template de endpoint + vault:// refs.
- McpClient.health_check(): teste on-demand de conexão.
- list_tools(): tenta MCP JSON-RPC 2.0 (tools/list) com fallback pro GET legacy.

Backward-compat: McpClient(server_url, api_key=None) e McpRegistry preservados
(routine_runner.McpAgentRunner depende). stdio + background health loop ficam
explicitamente NotImplemented — sem consumidor runtime hoje (todos os MCP
servers seedados são transport=http). Levantam erro claro quando acionados.
"""
import json
import logging
from typing import List, Dict, Any, Optional, Tuple, Callable

import requests

logger = logging.getLogger("MCP_Client")

# Configuração padrão de servidores MCP locais (stdio — ainda não suportado).
DEFAULT_MCP_CONFIG: Dict[str, Any] = {
    "mcpServers": {
        "chrome-devtools": {
            "command": "npx",
            "args": ["-y", "chrome-devtools-mcp@latest"],
        }
    }
}


# ─────────────────────────────────────────────────────────────────────────────
# Auth resolver (N7) — antes era o 502 "needs_N7" do handshake N6
# ─────────────────────────────────────────────────────────────────────────────

class McpAuthError(Exception):
    """Falha resolvendo auth/endpoint de um MCP server."""


def _fill_template(template: str, values: Dict[str, Any]) -> str:
    out = template or ""
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def resolve_mcp_auth(
    server: Dict[str, Any],
    field_values: Dict[str, Any],
    secret_resolver: Optional[Callable[[Any], Optional[str]]] = None,
) -> Tuple[str, Dict[str, str]]:
    """Resolve (endpoint, headers) a partir do server catalog + field_values do binding.

    server: row de mcp_server_catalog (transport, auth_type, endpoint_url_template).
    field_values: agent_mcp_bindings.field_values_json (pode conter vault:// refs).
    secret_resolver: fn(value) -> texto claro (resolve vault://). Identity se None.

    Levanta McpAuthError em transport não-http ou template não resolvido.
    """
    resolve = secret_resolver or (lambda v: v)

    transport = server.get("transport")
    if transport == "stdio":
        raise McpAuthError("stdio_transport_not_implemented")
    if transport not in ("http", "sse"):
        raise McpAuthError(f"transport_unsupported:{transport}")

    endpoint = _fill_template(server.get("endpoint_url_template") or "", field_values)
    if "{" in endpoint:
        raise McpAuthError(f"endpoint_template_unresolved:{endpoint}")

    auth_type = server.get("auth_type") or "none"
    headers: Dict[str, str] = {}

    if auth_type == "none":
        pass

    elif auth_type == "api_key":
        key = None
        for cand in ("api_key", "access_token", "token", "password"):
            if cand in field_values:
                key = resolve(field_values[cand])
                break
        if not key:
            raise McpAuthError("api_key_missing")
        headers["Authorization"] = f"Bearer {key}"

    elif auth_type == "bearer":
        token = None
        for cand in ("access_token", "token", "bearer_token"):
            if cand in field_values:
                token = resolve(field_values[cand])
                break
        if not token:
            raise McpAuthError("bearer_token_missing")
        headers["Authorization"] = f"Bearer {token}"

    elif auth_type == "oauth2_client_credentials":
        token_url = field_values.get("oauth_token_url") or field_values.get("token_url")
        client_id = field_values.get("client_id")
        client_secret = resolve(field_values.get("client_secret")) if field_values.get("client_secret") else None
        if not (token_url and client_id and client_secret):
            raise McpAuthError("oauth2_fields_missing:need_oauth_token_url+client_id+client_secret")
        try:
            resp = requests.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    # audience opcional (Camunda usa); só envia se presente
                    **({"audience": field_values["audience"]} if field_values.get("audience") else {}),
                },
                timeout=15,
            )
            resp.raise_for_status()
            access_token = resp.json().get("access_token")
            if not access_token:
                raise McpAuthError("oauth2_no_access_token_in_response")
            headers["Authorization"] = f"Bearer {access_token}"
        except McpAuthError:
            raise
        except Exception as e:
            raise McpAuthError(f"oauth2_token_exchange_failed:{e}")

    else:
        raise McpAuthError(f"auth_type_unsupported:{auth_type}")

    return endpoint, headers


class McpClient:
    """Cliente MCP. transport=http. JSON-RPC 2.0 com fallback GET legacy."""

    def __init__(
        self,
        server_url: str,
        api_key: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json",
            "X-MCP-Version": "2024-11-05",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        if headers:
            self.headers.update(headers)

    @classmethod
    def from_binding(
        cls,
        server: Dict[str, Any],
        field_values: Dict[str, Any],
        secret_resolver: Optional[Callable[[Any], Optional[str]]] = None,
    ) -> "McpClient":
        """Constrói client resolvendo auth via resolve_mcp_auth."""
        endpoint, headers = resolve_mcp_auth(server, field_values, secret_resolver)
        return cls(endpoint, headers=headers)

    # MCP protocol version negociada no initialize
    MCP_PROTOCOL_VERSION = "2025-06-18"

    @staticmethod
    def _parse_rpc_body(resp: "requests.Response") -> Dict[str, Any]:
        """Streamable HTTP pode devolver JSON puro OU SSE (text/event-stream).
        Extrai o objeto JSON-RPC do data: ... do último frame SSE se for o caso."""
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "text/event-stream" in ctype:
            last: Dict[str, Any] = {}
            for line in resp.text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    chunk = line[len("data:"):].strip()
                    if chunk and chunk != "[DONE]":
                        try:
                            last = json.loads(chunk)
                        except Exception:
                            continue
            return last
        try:
            return resp.json()
        except Exception:
            return {}

    def _ensure_session(self, timeout: int = 15) -> None:
        """Handshake MCP obrigatório: initialize → notifications/initialized.
        Captura Mcp-Session-Id (Streamable HTTP) pra reusar nas chamadas seguintes."""
        if getattr(self, "_initialized", False):
            return
        self._session_id = getattr(self, "_session_id", None)
        self._id = 0
        init_headers = dict(self.headers)
        init_headers["Accept"] = "application/json, text/event-stream"
        self._id += 1
        init_payload = {
            "jsonrpc": "2.0", "id": self._id, "method": "initialize",
            "params": {
                "protocolVersion": self.MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "vectraclaw-mcp-client", "version": "1.0"},
            },
        }
        resp = requests.post(self.server_url, headers=init_headers, json=init_payload, timeout=timeout)
        resp.raise_for_status()
        sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
        # notifications/initialized (notification — sem id, sem resposta esperada)
        notif_headers = dict(init_headers)
        if self._session_id:
            notif_headers["Mcp-Session-Id"] = self._session_id
        try:
            requests.post(
                self.server_url, headers=notif_headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=timeout,
            )
        except Exception as e:
            logger.warning(f"notifications/initialized falhou (segue): {e}")
        self._initialized = True

    def _jsonrpc(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: int = 15) -> Optional[Dict[str, Any]]:
        """POST JSON-RPC 2.0 com handshake MCP + session + parse SSE."""
        self._ensure_session(timeout=timeout)
        headers = dict(self.headers)
        headers["Accept"] = "application/json, text/event-stream"
        if getattr(self, "_session_id", None):
            headers["Mcp-Session-Id"] = self._session_id
        self._id = getattr(self, "_id", 0) + 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        resp = requests.post(self.server_url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = self._parse_rpc_body(resp)
        if "error" in data:
            raise RuntimeError(f"mcp_jsonrpc_error:{data['error']}")
        return data.get("result")

    def list_tools(self) -> List[Dict[str, Any]]:
        """Lista tools via MCP tools/list (após initialize). Fallback GET /tools legacy."""
        try:
            result = self._jsonrpc("tools/list")
            if result and isinstance(result.get("tools"), list):
                return result["tools"]
        except Exception as e:
            logger.warning(f"tools/list MCP falhou em {self.server_url} ({e}); tentando GET legacy")
        try:
            response = requests.get(f"{self.server_url}/tools", headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json().get("tools", [])
        except Exception as e:
            logger.error(f"list_tools falhou em {self.server_url}: {e}")
            return []

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Executa tool via MCP tools/call (após initialize). Fallback POST legacy."""
        try:
            result = self._jsonrpc("tools/call", {"name": tool_name, "arguments": arguments}, timeout=30)
            if result is not None:
                return result
        except Exception as e:
            logger.warning(f"tools/call MCP falhou ({e}); tentando POST legacy")
        try:
            payload = {"method": "tools/call", "params": {"name": tool_name, "arguments": arguments}}
            response = requests.post(f"{self.server_url}/tools/call", headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"call_tool {tool_name} falhou em {self.server_url}: {e}")
            return {"isError": True, "content": [{"type": "text", "text": str(e)}]}

    def health_check(self) -> Tuple[bool, Optional[str]]:
        """Teste on-demand de conexão. Retorna (ok, error_msg)."""
        try:
            self.list_tools()
            return True, None
        except Exception as e:
            return False, str(e)


class McpRegistry:
    """Gerenciador de múltiplos servidores MCP (Connectors). Backward-compat."""

    def __init__(self):
        self.clients: Dict[str, McpClient] = {}
        self.tool_map: Dict[str, str] = {}  # tool_name -> connector_id

    def register_connector(self, connector_id: str, url: str, api_key: Optional[str] = None):
        client = McpClient(url, api_key)
        self.clients[connector_id] = client
        tools = client.list_tools()
        for t in tools:
            name = t.get("name")
            if name:
                self.tool_map[name] = connector_id
        logger.info(f"Conector {connector_id} registrado com {len(tools)} ferramentas.")

    def get_all_tools(self) -> List[Dict[str, Any]]:
        all_tools = []
        for client in self.clients.values():
            all_tools.extend(client.list_tools())
        return all_tools

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        connector_id = self.tool_map.get(tool_name)
        if not connector_id:
            raise ValueError(f"Ferramenta {tool_name} não encontrada em nenhum conector.")
        return self.clients[connector_id].call_tool(tool_name, arguments)
