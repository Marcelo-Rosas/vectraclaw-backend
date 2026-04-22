import time
import logging
import traceback
from typing import Optional

from .runtime import PortRuntime

# Configura o Logger nativo para o Daemon
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - [VECTRA CLAW] - %(levelname)s - %(message)s'
)
logger = logging.getLogger('HarnessDaemon')

class ResilientHarnessDaemon:
    """
    Loop Base do Agente Resiliente (M1)
    Garante que a thread do agente nunca morra devido a falhas em chamadas de tools (API/Banco)
    e fique aguardando ordens ativamente.
    """
    def __init__(self, polling_interval: int = 5):
        self.polling_interval = polling_interval
        self.runtime = PortRuntime()
        self.is_running = False

    def fetch_next_task(self) -> Optional[str]:
        # TODO (Ticket do Banco): Substituir por fetch no Supabase (GET /api/tasks ou socket realtime)
        # Mocking empty queue no M1
        return None

    def execute_task(self, prompt: str):
        logger.info(f"Ordem Recebida: {prompt}")
        try:
            # Reutiliza o roteador estrito do claw-code (turn-loop)
            results = self.runtime.run_turn_loop(
                prompt, 
                limit=5, 
                max_turns=3, 
                structured_output=True
            )
            for idx, turn in enumerate(results, start=1):
                 logger.info(f"    [Turno {idx}] Resolução interna: {turn.output}")
                 logger.info(f"    [Turno {idx}] Motivo de parada: {turn.stop_reason}")

            logger.info("Tarefa processada e resolvida com sucesso.")
            
        except Exception:
             # O Agente não pode "capotar" por causa de alucinação ou erros de infraestrutura
             logger.error(f"Erro catastrófico da sub-task interceptado. Stack: {traceback.format_exc()}")
             logger.warning("Falha isolada! O agente reportará erro ao banco mas o Daemon continuará vivo.")

    def run_forever(self):
        self.is_running = True
        logger.info("=== Inicializando Vectra Claw Agent Engine ===")
        logger.info("Harness em modo IDLE. Aguardando payloads de Logística...")
        
        while self.is_running:
            try:
                task = self.fetch_next_task()
                if task:
                    self.execute_task(task)
                else:
                    time.sleep(self.polling_interval)
                    
            except KeyboardInterrupt:
                logger.info("Sinal KeyboardInterrupt recebido. Desligando com segurança...")
                self.is_running = False
                
            except Exception as e:
                # O loop Mestre da Thread nunca quebra. Proteção máxima de Failover (M4 Setup Base).
                logger.error(f"Erro fatal não tratado no poller principal: {e}")
                logger.warning("Reinicializando ciclo de fetching em 5 segundos...")
                time.sleep(5)

if __name__ == "__main__":
    daemon = ResilientHarnessDaemon(polling_interval=3)
    daemon.run_forever()
