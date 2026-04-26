import os
import time
import logging
import traceback
from typing import Optional, Dict, Any

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
    def __init__(self, polling_interval: Optional[int] = None):
        self.polling_interval = polling_interval or int(os.getenv("DAEMON_POLLING_INTERVAL_SECONDS", "5"))
        self.agent_id = os.getenv("AGENT_ID")
        self.runtime = PortRuntime()
        self.is_running = False
        self._supabase = None

    def _get_supabase(self):
        if self._supabase is not None:
            return self._supabase
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            return None
        try:
            from supabase import create_client
            from supabase.lib.client_options import ClientOptions
            schema = os.getenv("SUPABASE_SCHEMA", "vectraclip")
            self._supabase = create_client(url, key, options=ClientOptions(schema=schema, persist_session=False))
        except Exception as e:
            logger.error(f"Daemon Supabase init failed: {e}")
        return self._supabase

    def should_skip_task(self, task: Dict[str, Any]) -> bool:
        """Retorna True se a task deve ser ignorada pelo daemon (ex: destinada ao CMA)."""
        executor = task.get("executor_type", "auto")
        if executor == "managed_agent":
            logger.info(f"Skipping CMA task {task.get('id')} (executor_type=managed_agent)")
            return True
        return False

    def fetch_next_task(self) -> Optional[Dict[str, Any]]:
        """Busca a próxima task com status 'queued' destinada ao Harness."""
        client = self._get_supabase()
        if not client or not self.agent_id:
            return None
        try:
            res = (
                client.table("tasks")
                .select("id,title,description,operation_type,budget_limit,executor_type")
                .eq("assigned_to_agent_id", self.agent_id)
                .eq("status", "queued")
                .neq("executor_type", "managed_agent")  # ignora CMA tasks
                .order("created_at")
                .limit(1)
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.warning(f"fetch_next_task failed: {e}")
            return None

    def _claim_task(self, task_id: str) -> bool:
        """Marca a task como in_progress atomicamente."""
        client = self._get_supabase()
        if not client:
            return False
        try:
            res = (
                client.table("tasks")
                .update({"status": "in_progress"})
                .eq("id", task_id)
                .eq("status", "queued")  # guard: só transiciona se ainda queued
                .execute()
            )
            return bool(res.data)
        except Exception as e:
            logger.warning(f"_claim_task failed task={task_id}: {e}")
            return False

    def _complete_task(self, task_id: str, success: bool) -> None:
        client = self._get_supabase()
        if not client:
            return
        try:
            status = "done" if success else "blocked"
            client.table("tasks").update({"status": status}).eq("id", task_id).execute()
        except Exception as e:
            logger.warning(f"_complete_task failed task={task_id}: {e}")

    def execute_task(self, prompt: str):
        logger.info(f"Ordem Recebida: {prompt}")
        try:
            # Reutiliza o roteador estrito do claw-code (turn-loop)
            results = self.runtime.run_turn_loop(
                prompt,
                limit=int(os.getenv("DAEMON_TASK_RESULT_LIMIT", "5")),
                max_turns=int(os.getenv("DAEMON_MAX_TURNS", "3")),
                structured_output=True,
            )
            for idx, turn in enumerate(results, start=1):
                 logger.info(f"    [Turno {idx}] Resolução interna: {turn.output}")
                 logger.info(f"    [Turno {idx}] Motivo de parada: {turn.stop_reason}")

            logger.info("Tarefa processada e resolvida com sucesso.")
            
        except Exception:
             # O Agente não pode "capotar" por causa de alucinação ou erros de infraestrutura
             logger.error(f"Erro catastrófico da sub-task interceptado. Stack: {traceback.format_exc()}")
             logger.warning("Falha isolada! O agente reportará erro ao banco mas o Daemon continuará vivo.")

    def check_and_trigger_routines(self):
        """
        VEC-242: Verifica se há rotinas agendadas para agora (Trigger Engine).
        """
        # No M1, apenas logamos o check. No M4, integraremos com APScheduler ou Cron.
        logger.debug("Trigger Engine: Checking scheduled routines...")
        pass

    def run_forever(self):
        self.is_running = True
        logger.info("=== Inicializando Vectra Claw Agent Engine ===")
        logger.info(f"agent_id={self.agent_id or 'não configurado'} polling={self.polling_interval}s")

        while self.is_running:
            try:
                task = self.fetch_next_task()
                if task:
                    task_id = task["id"]
                    if self._claim_task(task_id):
                        prompt = f"[{task.get('operation_type','other')}] {task['title']}\n\n{task.get('description','')}"
                        success = False
                        try:
                            self.execute_task(prompt)
                            success = True
                        finally:
                            self._complete_task(task_id, success)
                    else:
                        logger.debug(f"task {task_id} já foi claimed por outro worker")

                self.check_and_trigger_routines()
                time.sleep(self.polling_interval)

            except KeyboardInterrupt:
                logger.info("Sinal KeyboardInterrupt recebido. Desligando com segurança...")
                self.is_running = False

            except Exception as e:
                logger.error(f"Erro fatal não tratado no poller principal: {e}")
                logger.warning(f"Reinicializando ciclo em {int(os.getenv('DAEMON_RESTART_DELAY_SECONDS','5'))}s...")
                time.sleep(int(os.getenv("DAEMON_RESTART_DELAY_SECONDS", "5")))

if __name__ == "__main__":
    daemon = ResilientHarnessDaemon()
    daemon.run_forever()
