"""Morpheus standalone dispatcher worker.

Roteia tasks `backlog` -> `queued` (atribui agente por specialty/disponibilidade)
chamando MorpheusDispatcher.dispatch() em loop.

Roda como processo SEPARADO (docker-compose service `morpheus`), espelhando o
padrão do Harness daemon (src/agent_daemon.py). Decoplado do app HTTP de
propósito: o scheduler asyncio in-app (api.py::morpheus_scheduler) morre quando
o Cloud Run escala a zero, deixando tasks presas em `backlog` pra sempre. Aqui o
loop vive num container always-on.

O scheduler in-app continua existindo, mas agora guardado atrás de
MORPHEUS_IN_APP (default off) pra evitar dispatcher duplo/corrida quando este
worker está rodando.

Env:
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY   (obrigatórios)
  SUPABASE_SCHEMA                           (default "vectraclip")
  MORPHEUS_INTERVAL_SECONDS                 (default 10)
  LOG_LEVEL                                 (default INFO)
"""
import logging
import os
import signal
import time

from src.services.morpheus_dispatcher import MorpheusDispatcher

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("MorpheusDaemon")

_DEFAULT_INTERVAL = 10
_MAX_BACKOFF_SECONDS = 60
_running = True


def _load_dotenv(path: str = ".env") -> None:
    """Best-effort: injeta .env quando rodado fora do compose (sem dependência)."""
    if not os.path.exists(path):
        return
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError as exc:  # pragma: no cover - leitura de .env é best-effort
        logger.warning("falha lendo %s (ignorando): %s", path, exc)


def _build_supabase():
    """Client service_role schema vectraclip — mesmo padrão de
    agent_daemon._get_supabase. Retorna None se faltar credencial."""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        logger.error(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY ausentes — Morpheus não pode iniciar"
        )
        return None
    from supabase import create_client, ClientOptions

    schema = os.getenv("SUPABASE_SCHEMA", "vectraclip")
    return create_client(
        url, key, options=ClientOptions(schema=schema, persist_session=False)
    )


def _handle_signal(signum, _frame) -> None:
    global _running
    logger.info("sinal %s recebido — encerrando após o ciclo atual", signum)
    _running = False


def _sleep_interruptible(seconds: float) -> None:
    """Dorme em fatias de 1s pra reagir rápido a SIGTERM (docker stop)."""
    slept = 0.0
    while _running and slept < seconds:
        time.sleep(min(1.0, seconds - slept))
        slept += 1.0


def run_forever() -> int:
    _load_dotenv()
    interval = int(os.getenv("MORPHEUS_INTERVAL_SECONDS", str(_DEFAULT_INTERVAL)))
    schema = os.getenv("SUPABASE_SCHEMA", "vectraclip")

    supabase = _build_supabase()
    if supabase is None:
        return 1

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("[morpheus] daemon iniciado interval=%ss schema=%s", interval, schema)
    consecutive_errors = 0
    while _running:
        try:
            pending, dispatched = MorpheusDispatcher(supabase).dispatch()
            if dispatched:
                logger.info(
                    "[morpheus] %s/%s task(s) despachada(s) neste ciclo", dispatched, pending
                )
            consecutive_errors = 0
            _sleep_interruptible(interval)
        except Exception as exc:  # noqa: BLE001 - loop precisa sobreviver a tudo
            consecutive_errors += 1
            backoff = min(interval * (2 ** min(consecutive_errors, 3)), _MAX_BACKOFF_SECONDS)
            logger.error(
                "[morpheus] erro no ciclo (%s consecutivos): %s — backoff %ss",
                consecutive_errors, exc, backoff,
            )
            _sleep_interruptible(backoff)

    logger.info("[morpheus] daemon encerrado")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_forever())
