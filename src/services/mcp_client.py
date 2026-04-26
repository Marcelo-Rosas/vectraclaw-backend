import json
import logging
import requests
from typing import List, Dict, Any, Optional

logger = logging.getLogger("MCP_Client")

# Configuração padrão de servidores MCP locais.
DEFAULT_MCP_CONFIG: Dict[str, Any] = {
    "mcpServers": {
        "chrome-devtools": {
            "command": "npx",
            "args": ["-y", "chrome-devtools-mcp@latest"],
        }
    }
}

class McpClient:
    """
    Cliente básico para o protocolo MCP (Model Context Protocol).
    Suporta descoberta de ferramentas (tools) e execução via SSE/HTTP.
    """
    def __init__(self, server_url: str, api_key: Optional[str] = None):
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json",
            "X-MCP-Version": "2024-11-05"
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def list_tools(self) -> List[Dict[str, Any]]:
        """Lista ferramentas disponíveis no servidor MCP."""
        try:
            response = requests.get(f"{self.server_url}/tools", headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("tools", [])
        except Exception as e:
            logger.error(f"Erro ao listar ferramentas MCP de {self.server_url}: {e}")
            return []

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Executa uma ferramenta no servidor MCP."""
        try:
            payload = {
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
            response = requests.post(
                f"{self.server_url}/tools/call", 
                headers=self.headers, 
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Erro ao chamar ferramenta {tool_name} em {self.server_url}: {e}")
            return {"isError": True, "content": [{"type": "text", "text": str(e)}]}

class McpRegistry:
    """Gerenciador de múltiplos servidores MCP (Connectors)."""
    def __init__(self):
        self.clients: Dict[str, McpClient] = {}
        self.tool_map: Dict[str, str] = {} # tool_name -> connector_id

    def register_connector(self, connector_id: str, url: str, api_key: Optional[str] = None):
        client = McpClient(url, api_key)
        self.clients[connector_id] = client
        
        # Refresh tools
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
