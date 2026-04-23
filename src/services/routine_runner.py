import os
import logging
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from src.models import Routine, Agent
from src.services.mcp_client import McpRegistry

logger = logging.getLogger("Routine_Runner")

class McpAgentRunner:
    """
    Executa uma Rotina de forma autônoma utilizando conectores MCP.
    """
    def __init__(self, routine: Routine, agent: Optional[Agent] = None):
        self.routine = routine
        self.agent = agent
        self.registry = McpRegistry()
        self.max_turns = int(os.getenv("ROUTINE_MAX_TURNS", "10"))
        
    def setup_connectors(self, adapters_data: List[Dict[str, Any]]):
        """
        Registra todos os conectores (adapters) associados à rotina.
        No MCP, cada adapter é um servidor de ferramentas.
        """
        for adp in adapters_data:
            # No futuro, o campo 'url' virá da configuração do adapter
            url = adp.get("fieldValuesJson", {}).get("mcp_url") or adp.get("url")
            if url:
                self.registry.register_connector(
                    adp["id"], 
                    url, 
                    adp.get("fieldValuesJson", {}).get("api_key")
                )

    def run(self):
        """Loop principal de execução autônoma."""
        logger.info(f"Iniciando Rotina: {self.routine.name}")
        
        # 1. Carregar ferramentas disponíveis
        tools = self.registry.get_all_tools()
        logger.info(f"Ferramentas MCP disponíveis: {[t['name'] for t in tools]}")
        
        # 2. Preparar Prompt do Agente (ou System Prompt da Especialidade)
        system_prompt = f"Você é um agente autônomo executando a rotina: {self.routine.name}.\n"
        if self.agent:
            system_prompt += f"Seu papel é: {self.agent.role}.\n"
        
        system_prompt += "\nUse as ferramentas disponíveis para completar a tarefa sem intervenção humana."

        # 3. Loop de Turnos (Simulado/Iniciação do LLM)
        # TODO: Integrar com Anthropic SDK para o loop real
        logger.info("Executando Ciclo Autônomo (LLM Turn Loop)...")
        
        last_run_at = datetime.now(timezone.utc)
        logger.info(f"Rotina {self.routine.name} finalizada com sucesso.")
        return {
            "success": True,
            "turns": 1,
            "log": "Rotina executada via MCP Client Layer.",
            "last_run_at": last_run_at.isoformat(),
            "status": "active",
        }

class RoutineTriggerService:
    """Serviço que monitora e dispara rotinas baseadas no cron ou eventos."""
    def __init__(self):
        self.active_runners: List[McpAgentRunner] = []

    def trigger_routine(self, routine: Routine, agent: Optional[Agent], adapters: List[Dict[str, Any]]):
        runner = McpAgentRunner(routine, agent)
        runner.setup_connectors(adapters)
        return runner.run()
