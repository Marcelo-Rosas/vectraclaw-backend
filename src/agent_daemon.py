import os
import subprocess
import sys
import time
import logging
import traceback
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone  # noqa: F401 — used in _save_company_context

from src.agent_ids import ORACLE_AGENT_ID

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
    _LOCK_DIR = Path(__file__).parent.parent / ".daemon_locks"

    def __init__(self, polling_interval: Optional[int] = None):
        self.polling_interval = polling_interval or int(os.getenv("DAEMON_POLLING_INTERVAL_SECONDS", "5"))
        self.agent_id = os.getenv("AGENT_ID")
        self.is_running = False
        self._supabase = None
        self._agent_config: Dict[str, Any] = {}  # carregado no startup
        self._lock_file: Optional[Path] = None
        # VEC-377 — idle heartbeat tick: garante visibilidade de "Live" no dashboard
        # mesmo quando daemon está polando sem tasks. Configurável via env.
        self._idle_heartbeat_interval = int(os.getenv("DAEMON_IDLE_HEARTBEAT_SECONDS", "30"))
        self._last_heartbeat_at: Optional[datetime] = None

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """Verifica se um PID está ativo sem depender de psutil."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True,
            )
            return str(pid) in result.stdout
        except Exception:
            return False

    def _acquire_lock(self) -> bool:
        """
        Cria um PID file em .daemon_locks/<agent_id>.lock.
        Retorna False se já existir um processo vivo com o mesmo AGENT_ID.
        """
        if not self.agent_id:
            return True  # sem agent_id, não trava

        self._LOCK_DIR.mkdir(exist_ok=True)
        self._lock_file = self._LOCK_DIR / f"{self.agent_id}.lock"

        if self._lock_file.exists():
            try:
                existing_pid = int(self._lock_file.read_text().strip())
                if self._pid_alive(existing_pid):
                    logger.error(
                        "Daemon já está rodando para AGENT_ID=%s (PID %d). Abortando.",
                        self.agent_id, existing_pid,
                    )
                    return False
                logger.warning("Lock stale (PID %d morto). Sobrescrevendo.", existing_pid)
            except ValueError:
                pass  # arquivo corrompido — sobrescreve

        self._lock_file.write_text(str(os.getpid()))
        logger.info("Lock adquirido: %s (PID %d)", self._lock_file.name, os.getpid())
        return True

    def _release_lock(self) -> None:
        if self._lock_file and self._lock_file.exists():
            try:
                self._lock_file.unlink()
                logger.info("Lock liberado: %s", self._lock_file.name)
            except Exception as e:
                logger.warning("Falha ao liberar lock: %s", e)

    def _get_supabase(self):
        if self._supabase is not None:
            return self._supabase
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            return None
        try:
            from supabase import create_client, ClientOptions
            schema = os.getenv("SUPABASE_SCHEMA", "vectraclip")
            self._supabase = create_client(url, key, options=ClientOptions(schema=schema, persist_session=False))
        except Exception as e:
            logger.error(f"Daemon Supabase init failed: {e}")
        return self._supabase

    def _load_agent_config(self) -> None:
        """Carrega system_prompt e model_id do banco para este agente."""
        client = self._get_supabase()
        if not client or not self.agent_id:
            return

        # system_prompt da tabela agents
        try:
            res = (
                client.table("agents")
                .select("system_prompt")
                .eq("id", self.agent_id)
                .maybe_single()
                .execute()
            )
            if res.data:
                self._agent_config["system_prompt"] = res.data.get("system_prompt") or ""
        except Exception as e:
            logger.warning(f"_load_agent_config: agents lookup failed: {e}")

        # model_id via agent_adapter_configs.field_values_json
        try:
            res = (
                client.table("agent_adapter_configs")
                .select("field_values_json")
                .eq("agent_id", self.agent_id)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            if res.data:
                fv = res.data[0].get("field_values_json") or {}
                self._agent_config["model_id"] = fv.get("model_id", "")
        except Exception as e:
            logger.warning(f"_load_agent_config: adapter_configs lookup failed: {e}")

        logger.info(
            "agent_config loaded: model_id=%s system_prompt=%s",
            self._agent_config.get("model_id") or "(default)",
            "yes" if self._agent_config.get("system_prompt") else "no",
        )

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
                .select(
                    "id,company_id,title,description,operation_type,budget_limit,"
                    "executor_type,input_json,parent_task_id"
                )
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

    def _get_matching_specialty_id(self, operation_type: str) -> Optional[str]:
        """
        VEC-326: Resolve qual especialidade do agente deve ser usada para esta task.
        Busca uma specialty cujo slug ou ID dê match com o operation_type da task.
        """
        client = self._get_supabase()
        if not client or not self.agent_id or not operation_type:
            return None
        
        try:
            # Busca todas as especialidades configuradas para este agente
            res = (
                client.table("agent_specialty_configs")
                .select("specialty_id, agent_specialties(slug)")
                .eq("agent_id", self.agent_id)
                .execute()
            )
            
            for row in res.data:
                spec_id = row.get("specialty_id")
                # agent_specialties é um join (lista ou objeto dependendo do postgrest)
                spec_data = row.get("agent_specialties")
                spec_slug = spec_data.get("slug") if spec_data else None
                
                # Match exato por ID ou Slug
                if operation_type in [spec_id, spec_slug]:
                    return spec_id
            
            return None
        except Exception as e:
            logger.warning(f"_get_matching_specialty_id failed: {e}")
            return None

    def _claim_task(self, task_id: str) -> bool:
        """Marca a task como in_progress atomicamente e popula claimed_at (VEC-392).

        Antes da VEC-392 só atualizava `status`, deixando `claimed_at` NULL —
        afetava todos os 10 daemons. Frontend precisava derivar `claimedAt`
        client-side pra mostrar 'reivindicado há X min'. Agora o backend popula.
        """
        client = self._get_supabase()
        if not client:
            return False
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            res = (
                client.table("tasks")
                .update({"status": "in_progress", "claimed_at": now_iso})
                .eq("id", task_id)
                .eq("status", "queued")  # guard: só transiciona se ainda queued
                .execute()
            )
            return bool(res.data)
        except Exception as e:
            logger.warning(f"_claim_task failed task={task_id}: {e}")
            return False

    def _emit_task_lifecycle_heartbeat(
        self,
        task_id: str,
        status: str,
        *,
        company_id: Optional[str] = None,
        operation_type: Optional[str] = None,
        log_excerpt: Optional[str] = None,
        cost_usd: float = 0.0,
    ) -> None:
        """VEC-429 Fase 1 — emite heartbeat ligado a `task_id` para todos os daemons.

        Antes desta função, apenas o Oracle emitia heartbeat com task_id (via
        `_emit_oracle_records`); os demais daemons só emitiam heartbeats
        `idle` (task_id=NULL) através de `_emit_idle_heartbeat`. Consequência:
        o dashboard não conseguia indicar visualmente que o agente X estava
        executando a task Y, e o handoff (Kronos→HermesReporter) ficava
        invisível durante a janela ativa.

        Chamada em dois pontos:
        - logo após `_claim_task` retornar True (status='working').
        - dentro de `_complete_task` (status='succeeded' | 'error').

        Falha silenciosa — heartbeat é best-effort.
        """
        if not self.agent_id or not task_id:
            return
        client = self._get_supabase()
        if not client:
            return

        resolved_company = company_id or self._agent_config.get("company_id")
        if not resolved_company:
            try:
                ag = (
                    client.table("agents")
                    .select("company_id")
                    .eq("id", self.agent_id)
                    .maybe_single()
                    .execute()
                )
                if ag and ag.data:
                    resolved_company = ag.data.get("company_id")
                    self._agent_config["company_id"] = resolved_company
            except Exception:
                pass

        if not log_excerpt:
            if operation_type:
                log_excerpt = f"task {status}: {operation_type}"
            else:
                log_excerpt = f"task lifecycle: {status}"

        now = datetime.now(timezone.utc).isoformat()
        row: Dict[str, Any] = {
            "agent_id": self.agent_id,
            "task_id": task_id,
            "status": status,
            "tokens_used": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "model_id": None,
            "cost_usd": round(float(cost_usd or 0.0), 8),
            "log_excerpt": log_excerpt,
            "created_at": now,
            "updated_at": now,
        }
        if resolved_company:
            row["company_id"] = resolved_company

        try:
            client.table("heartbeats").insert(row).execute()
        except Exception as e:
            logger.warning(
                "_emit_task_lifecycle_heartbeat failed task=%s status=%s: %s",
                task_id, status, e,
            )

    def _complete_task(
        self,
        task_id: str,
        success: bool,
        cost_usd: float = 0.0,
        output_json: Optional[Dict[str, Any]] = None,
        status_override: Optional[str] = None,
        task_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        client = self._get_supabase()
        if not client:
            return
        try:
            status = status_override or ("done" if success else "blocked")
            patch: dict = {"status": status}
            if cost_usd:
                patch["cost_usd"] = cost_usd
            if output_json is not None:
                patch["output_json"] = output_json
            client.table("tasks").update(patch).eq("id", task_id).execute()
            # VEC-334 — promote workflow children + rollup parent (DAG snapshot columns)
            try:
                from src.services.task_factory import TaskFactory

                TaskFactory(client).promote_successors_after_completion(task_id)
            except Exception as promo_err:
                logger.warning("_complete_task promotion failed task=%s: %s", task_id, promo_err)
            # VEC-429 Fase 1 — heartbeat terminal ligado à task (visível no dashboard).
            # `heartbeats.status` CHECK aceita: working|idle|paused|errored|offline.
            # Sucesso → 'working' (mesmo padrão de `_emit_oracle_records`);
            # falha → 'errored'. Distinção fim vs claim fica em `log_excerpt`.
            hb_status = "working" if (success and status != "blocked") else "errored"
            self._emit_task_lifecycle_heartbeat(
                task_id=task_id,
                status=hb_status,
                company_id=(task_meta or {}).get("company_id"),
                operation_type=(task_meta or {}).get("operation_type"),
                log_excerpt=(
                    f"task {status}"
                    + (f": {task_meta.get('operation_type')}" if task_meta and task_meta.get("operation_type") else "")
                ),
                cost_usd=cost_usd,
            )
        except Exception as e:
            logger.warning(f"_complete_task failed task={task_id}: {e}")

    def _populate_resolved_specialty(self, task: Dict[str, Any]) -> None:
        """PR3 + PR-C — Anexa specialty + configs (specialty + shared) em `task`.

        Atribui três campos para os handlers consultarem:
        - `task["_resolved_specialty"]`: ResolvedSpecialty | None
        - `task["_resolved_config"]`:    dict (agent_specialty_configs.values)
        - `task["_resolved_shared"]`:    dict (agent_shared_config.values — PR-C)

        Match da specialty: slug == operation_type da task. Shared NÃO depende
        de match — é populado mesmo sem specialty match (defaults do agente
        independentes do skill).

        Falha silenciosa — handler que não encontre `_resolved_*` segue com
        fallback legado (`task.description` em KEY=VALUE).
        """
        if not self.agent_id:
            return

        client = self._get_supabase()
        if not client:
            return

        company_id = task.get("company_id") or self._agent_config.get("company_id")

        # 1. Shared config sempre populado (defaults do agente)
        try:
            from src.services.specialty_resolver import resolve_shared_config

            shared = resolve_shared_config(client, self.agent_id, company_id=company_id)
            task["_resolved_shared"] = shared
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "_populate_resolved_specialty: shared lookup failed task=%s: %s",
                task.get("id"),
                exc,
            )

        # 2. Specialty + values só quando há match por op_type
        op_type = task.get("operation_type")
        if not op_type:
            return

        try:
            from src.services.specialty_resolver import (
                resolve_config,
                resolve_specialty,
            )

            spec = resolve_specialty(client, self.agent_id, op_type)
            if spec is None:
                return

            values = resolve_config(
                client, self.agent_id, spec.id, company_id=company_id
            )

            task["_resolved_specialty"] = spec
            task["_resolved_config"] = values
            logger.info(
                "specialty resolved task=%s op=%s slug=%s config_keys=%s shared_keys=%s",
                task.get("id"),
                op_type,
                spec.slug,
                list(values.keys()),
                list((task.get("_resolved_shared") or {}).keys()),
            )
        except Exception as exc:  # noqa: BLE001 — fail-quiet por design
            logger.warning(
                "_populate_resolved_specialty failed task=%s: %s",
                task.get("id"),
                exc,
            )

    def _maybe_reply_to_connector_session(self, task: dict, raw_output: str) -> None:
        """W7 P0-11 — Se a task veio de um connector inbound (webhook Meta etc),
        envia o output como reply pela mesma sessão.

        Detecção: `task.input_json.session_id` (gravado pelo
        `_dispatch_inbound_task` em src/api_routes/connectors.py após P0-9).
        Tasks normais (sem session_id) são noop silencioso.

        Extração do texto da reply (PR3 fix 2026-05-18):
        Handlers modernos (Mercator W13, Athena, Morpheus, Kronos, Mnemos,
        Daedalus) retornam dict estruturado `{status, output_text, output_json}`
        — `raw_output` é o JSON serializado dessa estrutura. Pra esses, extrai
        `output_text`. Fallback graceful pra handler legacy `claude -p` que
        retorna texto cru (DEPRECATED branch).

        Handler moderno SEM `output_text` (oracle, athena de hoje) cai no
        fallback de JSON cru — log WARNING explícito pra observabilidade
        (auditor P1.1 2026-05-18). Se algum fluxo futuro colocar `session_id`
        em task de oracle/athena, o WARNING vai sinalizar a falta de
        `output_text` antes de mandar JSON pro WhatsApp.

        Best-effort: qualquer falha (lookup, reply HTTP) é logada como warning
        e propaga `Exception` pro caller que silencia. Não bloqueia
        `_complete_task` (no `finally:` do loop processor).
        """
        import json as _json_local

        input_json = task.get("input_json") or {}  # guard contra None (Regra auditor)
        session_id = input_json.get("session_id") if isinstance(input_json, dict) else None
        if not session_id:
            return  # task normal sem origem em connector — noop

        client = self._get_supabase()
        if not client:
            logger.warning("connector reply: supabase indisponível task=%s", task.get("id"))
            return

        try:
            res = (
                client.table("connector_sessions")
                .select("*")
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
        except Exception as e:
            logger.warning("connector reply: SELECT session falhou id=%s: %s", session_id, e)
            return
        if not res.data:
            logger.warning("connector reply: session_id=%s não encontrada", session_id)
            return
        session = res.data[0]

        # PR3 (2026-05-18) — extração estruturada de output_text
        reply_text: str
        try:
            parsed = _json_local.loads(raw_output)
            if isinstance(parsed, dict):
                candidate = parsed.get("output_text")
                if not candidate and isinstance(parsed.get("output_json"), dict):
                    # Extensibilidade NAVI-style — não usado por handlers
                    # atuais mas reserva pro caso de absorção do nina-orchestrator
                    candidate = parsed["output_json"].get("message_to_client")
                if candidate:
                    reply_text = str(candidate).strip()
                else:
                    # Handler moderno sem output_text — observabilidade obrigatória
                    # (auditor P1.1) pra detectar dict serializado vazando pro Meta
                    logger.warning(
                        "connector reply: handler moderno sem output_text — usando JSON cru "
                        "como fallback (visível pro cliente!). task=%s op=%s keys=%s",
                        task.get("id"), task.get("operation_type"), list(parsed.keys()),
                    )
                    reply_text = (raw_output or "").strip()
            else:
                # Lista/string/número solto serializado — improvável mas defensivo
                reply_text = (raw_output or "").strip()
        except (ValueError, TypeError):
            # Handler legacy claude -p devolve texto cru, não JSON
            reply_text = (raw_output or "").strip()

        if not reply_text:
            logger.info("connector reply: output vazio task=%s — skip", task.get("id"))
            return

        try:
            from src.services import connector_bus  # lazy: evita circular
            import asyncio as _aio
            _aio.run(connector_bus.reply(session, reply_text))
            logger.info(
                "connector reply sent task=%s session=%s channel=%s len=%d",
                task.get("id"), session_id, session.get("channel"), len(reply_text),
            )
        except Exception as e:
            logger.warning(
                "connector reply failed task=%s session=%s: %s",
                task.get("id"), session_id, e,
            )

    def execute_task(self, task: dict) -> str:
        import asyncio
        import json as _json

        op_type = task.get("operation_type", "other")
        task_id = task.get("id", "?")
        logger.info("execute_task: id=%s op_type=%s", task_id, op_type)

        # VEC-XXX PR3 — resolve specialty + config antes do dispatch.
        # Handlers que ignorarem `task["_resolved_*"]` seguem funcionando
        # com seu fluxo legado (backcompat 100%).
        self._populate_resolved_specialty(task)

        # Deterministic branches for native Python agents
        # W9 (2026-05-18) — Morpheus inbound triage. Sem LLM, puro matching
        # data-driven via vectraclip.inbound_intent_rules. Cria task filha
        # com op_type + agent corretos (catalog-driven via ADR-VEC-INBOUND-INTENT-CLASSIFIER).
        if op_type == "inbound-triage":
            from src.agents.morpheus_inbound_triage import entrypoint as triage_entry
            result = triage_entry(task, self._get_supabase())
            return _json.dumps(result)

        # W13 MVP (2026-05-18) — Mercator freight-quotation humano-in-loop.
        # Handler escala pro time comercial via resposta estruturada (4 dados:
        # origem/destino/peso/valor). NÃO calcula valor — depende de price_tables
        # CFN não absorvidas ainda. Fix Bug #1 do handoff CONNECTOR-SESSIONS-AGENT-DISPATCH
        # (5 tasks freight-quotation status=blocked desde 2026-05-18). Memory
        # `project_session_2026-05-16_fase_a_5prs` afirmou W7 P0-10 criou o arquivo
        # mercator.py, mas nunca existiu em prod — só agora.
        if op_type == "freight-quotation":
            from src.agents.mercator import handle_freight_quotation
            result = handle_freight_quotation(task, self._get_supabase())
            return _json.dumps(result)

        if op_type == "financial-audit":
            from src.agents.kronos import entrypoint as kronos_entry
            result = kronos_entry(task, self._get_supabase())
            return _json.dumps(result)

        if op_type in ("conciliacao-backlog", "financial-bookkeeping"):
            from src.agents.kronos import entrypoint_backlog
            result = entrypoint_backlog(task, self._get_supabase())
            return _json.dumps(result)

        if op_type == "planner-import-ofx":
            from src.agents.kronos_planner import entrypoint_planner_import
            result = entrypoint_planner_import(task, self._get_supabase())
            return _json.dumps(result)

        if op_type == "planner-categorize-pendings":
            from src.agents.kronos_planner import entrypoint_categorize_pendings
            result = entrypoint_categorize_pendings(task, self._get_supabase())
            return _json.dumps(result)

        # Task #18 (sessão 2026-05-14): workflow kronos-audit-historico
        if op_type == "kronos-audit-historico":
            from src.agents.kronos_audit import entrypoint_kronos_audit
            result = entrypoint_kronos_audit(task, self._get_supabase())
            return _json.dumps(result)

        if op_type == "planner-apply-corrections":
            from src.agents.kronos_apply_corrections import entrypoint_apply_corrections
            result = entrypoint_apply_corrections(task, self._get_supabase())
            return _json.dumps(result)

        # audit-review NÃO tem handler que executa lógica — ao ser pegada
        # da fila, transiciona a task pra `review` (o endpoint POST
        # /api/tasks/{id}/approve em api.py:6888 só aceita status='review'
        # ou 'blocked'). Quando user aprova, endpoint promove pra `queued`
        # e o sucessor planner-apply-corrections roda via promote_successors.
        if op_type == "audit-review":
            return _json.dumps({
                "status": "review",
                "output_json": {
                    "info": "task aguarda aprovação humana — POST /api/tasks/{id}/approve",
                    "approval_endpoint": "/api/tasks/{task_id}/approve",
                },
            })

        if op_type == "oracle-report":
            from src.agents.hermes_reporter import entrypoint as hr_entry
            result = hr_entry(task)
            return _json.dumps(result)

        if op_type == "rag-ingest":
            from src.agents.mnemos import entrypoint as mnemos_entry
            result = mnemos_entry(task, self._get_supabase())
            return _json.dumps(result)

        # VEC-388 PR1 - Athena (9o daemon, PMOia Heldman/PMBOK)
        # Branch DEVE vir antes de oracle- para garantir matching exato
        # mesmo que algum prefixo futuro coincida.
        if op_type.startswith("athena-"):
            from src.agents.athena import execute_specialty as athena_execute
            result = asyncio.run(athena_execute(task, self._get_supabase()))
            return _json.dumps(result)

        # Daedalus (PR G+H — modelador BPMN, fallback estatístico sem LLM)
        if op_type.startswith("bpmn-"):
            from src.agents.daedalus import execute_specialty as daedalus_execute
            result = asyncio.run(daedalus_execute(task, self._get_supabase()))
            return _json.dumps(result)

        if op_type.startswith("oracle-"):
            from src.agents.oracle import execute_specialty
            result = asyncio.run(execute_specialty(task, self._get_supabase()))
            self._emit_oracle_records(task, result)
            if op_type == "oracle-research":
                self._send_oracle_research_email(task, result)
            return _json.dumps(result)

        if op_type == "dispatch-research":
            result = self._dispatch_research(task)
            return _json.dumps(result)

        if op_type == "rag-ingest":
            from src.agents.mnemos import entrypoint as mnemos_entry
            result = mnemos_entry(task, self._get_supabase())
            return _json.dumps(result)

        # Default: forward to claude -p
        # TODO(W8): remover este caminho após todos agentes terem adapter
        # configurado. Caminho catalog-driven correto: task com executor_type=auto
        # → decision_engine → router → ClaudeCodeCliAgentClient (slug=claude_code_cli,
        # provider=claude_cli_subscription). Memory `claude-p-must-be-adapter`.
        # Auditor 2026-05-18: este branch é gambiarra pré-MVP, log warning antes.
        logger.warning(
            "DEPRECATED claude -p default path | task=%s op=%s agent=%s — "
            "agente sem adapter claude_code_cli configurado em agent_adapter_configs. "
            "Path catalog-driven correto: provisionar via /admin/connectors > Preencher Valores.",
            task.get("id"), op_type, task.get("assigned_to_agent_id"),
        )
        prompt = f"[{op_type}] {task.get('title', '')}\n\n{task.get('description', '')}"
        logger.info("claude -p prompt: %s", prompt[:120])

        model_id = self._agent_config.get("model_id", "")
        system_prompt = self._agent_config.get("system_prompt", "")

        args = ["claude", "-p", prompt]
        if model_id:
            args += ["--model", model_id]
        if system_prompt:
            args += ["--system-prompt", system_prompt]

        timeout = int(os.getenv("DAEMON_MAX_TURNS", "3")) * 60

        # Remove ANTHROPIC_API_KEY para forçar autenticação OAuth (Claude Code MAX)
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            if result.returncode != 0:
                logger.error("claude CLI error (rc=%d): %s", result.returncode, result.stderr[:400])
                raise RuntimeError(f"claude CLI exited {result.returncode}")

            output = result.stdout.strip()
            logger.info("Tarefa processada com sucesso. Output: %s", output[:200])
            return output

        except subprocess.TimeoutExpired:
            logger.error("claude CLI timeout (%ds)", timeout)
            raise
        except Exception:
            logger.error("Erro na execução da task. Stack: %s", traceback.format_exc())
            raise

    def check_and_trigger_routines(self):
        """VEC-242: Verifica se há rotinas agendadas para agora."""
        pass

    def _recover_stale_tasks(self) -> None:
        """Na inicialização, reseta tasks in_progress deixadas por crashes anteriores.
        Exclui oracle-research — podem ter interaction_id ativo."""
        client = self._get_supabase()
        if not client or not self.agent_id:
            return
        try:
            res = (
                client.table("tasks")
                .update({"status": "queued"})
                .eq("assigned_to_agent_id", self.agent_id)
                .eq("status", "in_progress")
                .neq("operation_type", "oracle-research")
                .execute()
            )
            recovered = len(res.data or [])
            if recovered:
                logger.warning(f"Recovery: {recovered} task(s) in_progress resetada(s) para queued")
        except Exception as e:
            logger.warning(f"_recover_stale_tasks failed: {e}")

    def _save_company_context(
        self,
        company_id: str,
        text: str,
        citations: list,
        company_name: str,
    ) -> None:
        client = self._get_supabase()
        if not client:
            return
        try:
            context = {
                "research_summary": text,
                "citations": citations[:20],
                "research_date": datetime.now(timezone.utc).isoformat(),
                "company_name": company_name,
            }
            client.table("companies").update({"context_json": context}).eq("company_id", company_id).execute()
            logger.info("company_context saved company_id=%s", company_id)
        except Exception as e:
            logger.warning(f"_save_company_context failed: {e}")

    # Tracks consecutive poll failures per interaction_id — key is interaction_id, value is count.
    # After _POLL_FAILURE_THRESHOLD failures the task falls back to sync research.
    _poll_failure_counts: dict = {}
    _POLL_FAILURE_THRESHOLD = 5

    def _poll_research_tasks(self) -> None:
        """Verifica oracle-research tasks em in_progress e finaliza quando o Deep Research completa."""
        if self.agent_id != ORACLE_AGENT_ID:
            return

        import asyncio as _aio
        from src.services.gemini_interactions import get_research_status  # _calc_cost dropped — unused import
        from src.agents.oracle import (
            persist_prospect_from_oracle_research,
            _normalize_research_output_format,
        )

        client = self._get_supabase()
        if not client:
            return
        try:
            res = (
                client.table("tasks")
                .select("id,company_id,operation_type,input_json,output_json")
                .eq("assigned_to_agent_id", self.agent_id)
                .eq("status", "in_progress")
                .eq("operation_type", "oracle-research")
                .execute()
            )
            tasks = res.data or []
        except Exception as e:
            logger.warning(f"_poll_research_tasks fetch failed: {e}")
            return

        for task in tasks:
            output = task.get("output_json") or {}
            metadata = output.get("metadata") or {}
            interaction_id = metadata.get("interaction_id")
            if not interaction_id:
                continue

            try:
                poll_result = _aio.run(get_research_status(interaction_id))
                # Reset failure counter on success
                self._poll_failure_counts.pop(interaction_id, None)
            except Exception as e:
                failures = self._poll_failure_counts.get(interaction_id, 0) + 1
                self._poll_failure_counts[interaction_id] = failures
                logger.warning(
                    "get_research_status failed interaction=%s failures=%d/%d: %s",
                    interaction_id, failures, self._POLL_FAILURE_THRESHOLD, e,
                )
                if failures < self._POLL_FAILURE_THRESHOLD:
                    continue
                # Threshold reached — treat as failed and fall through to sync fallback
                logger.warning(
                    "oracle-research poll threshold reached interaction=%s task=%s — forcing sync fallback",
                    interaction_id, task["id"],
                )
                self._poll_failure_counts.pop(interaction_id, None)
                poll_result = {"status": "failed", "error": f"poll failed {failures}x: {e}"}

            if poll_result["status"] == "completed":
                text = poll_result.get("text", "")
                citations = poll_result.get("citations", [])
                tokens = poll_result.get("tokens", {})
                cost_usd = poll_result.get("cost_usd", 0.0)

                # Deep Research returned empty or sources-only — fall back to sync research
                _stripped = (text or "").strip()
                _is_sources_only = _stripped.startswith("**Sources:**") or _stripped.startswith("\n\n**Sources:**")
                if not _stripped or len(_stripped) < 200 or _is_sources_only:
                    logger.warning(
                        "deep_research returned empty text task=%s interaction=%s — triggering sync fallback",
                        task["id"], interaction_id,
                    )
                    input_json_inner = task.get("input_json") or {}
                    prompt_inner = input_json_inner.get("prompt") or ""
                    if prompt_inner:
                        try:
                            from src.agents.oracle import _handle_research_sync
                            sync_result = _aio.run(_handle_research_sync(prompt_inner, {
                                **input_json_inner,
                                "_supabase": client,
                                "_task_id": task["id"],
                                "_company_id": task.get("company_id"),
                            }))
                            sync_meta = sync_result.get("metadata") or {}
                            final_sync_output = {
                                **sync_result,
                                "metadata": {
                                    **metadata,
                                    **sync_meta,
                                    "status": "completed",
                                    "deep_research_fallback": True,
                                },
                            }
                            require_review = bool(input_json_inner.get("require_human_review"))
                            status_ov = "review" if require_review else None
                            self._complete_task(task["id"], True, output_json=final_sync_output, status_override=status_ov)
                            logger.info("oracle-research sync fallback completed task=%s review=%s", task["id"], require_review)
                        except Exception as _ex:
                            logger.error("oracle-research sync fallback failed task=%s: %s", task["id"], _ex)
                    continue  # Never save empty Deep Research result

                input_json = task.get("input_json") or {}

                structured_data: dict = {}
                if text and len(text) > 200 and task.get("company_id"):
                    try:
                        structured_data = _aio.run(
                            persist_prospect_from_oracle_research(
                                client,
                                task["company_id"],
                                task["id"],
                                text,
                                input_json,
                                citations,
                            )
                        ) or {}
                    except Exception as _ex:
                        logger.warning("prospect persist failed task=%s: %s", task["id"], _ex)

                final_output = {
                    "report_markdown": text,
                    "structured_data": structured_data or None,
                    "citations": citations,
                    "metadata": {
                        **metadata,
                        "status": "completed",
                        "tokens": tokens,
                        "research_output_format": _normalize_research_output_format(input_json.get("output_format")),
                    },
                }
                if input_json.get("save_to_company_context") and task.get("company_id"):
                    self._save_company_context(
                        task["company_id"], text, citations,
                        input_json.get("company_name", ""),
                    )

                self._complete_task(task["id"], True, cost_usd=cost_usd, output_json=final_output)
                logger.info(
                    "oracle-research completed task=%s tokens=%s cost=%.6f prospect_saved=%s",
                    task["id"], tokens.get("total", 0), cost_usd,
                    bool(structured_data),
                )

            elif poll_result["status"] == "failed":
                fail_reason = poll_result.get("error", "")
                logger.warning(
                    "deep_research failed task=%s reason=%s — trying sync fallback",
                    task["id"], fail_reason[:120],
                )
                input_json_f = task.get("input_json") or {}
                prompt_f = input_json_f.get("prompt") or ""
                if prompt_f:
                    try:
                        from src.agents.oracle import _handle_research_sync
                        sync_result = _aio.run(_handle_research_sync(prompt_f, {
                            **input_json_f,
                            "_supabase": client,
                            "_task_id": task["id"],
                            "_company_id": task.get("company_id"),
                        }))
                        sync_meta = sync_result.get("metadata") or {}
                        final_sync_output = {
                            **sync_result,
                            "metadata": {
                                **metadata,
                                **sync_meta,
                                "status": "completed",
                                "deep_research_fallback": True,
                                "deep_research_failure": fail_reason[:200],
                            },
                        }
                        require_review_f = bool(input_json_f.get("require_human_review"))
                        status_ov_f = "review" if require_review_f else None
                        self._complete_task(task["id"], True, output_json=final_sync_output, status_override=status_ov_f)
                        logger.info("oracle-research sync fallback (after failure) completed task=%s review=%s", task["id"], require_review_f)
                        continue
                    except Exception as _ex:
                        logger.error("oracle-research sync fallback failed task=%s: %s", task["id"], _ex)
                # Sync also failed — mark blocked
                error_output = {
                    "error_detail": {"code": "research_failed", "message": fail_reason},
                    "metadata": metadata,
                }
                self._complete_task(task["id"], False, output_json=error_output)
                logger.warning("oracle-research blocked (all fallbacks failed) task=%s", task["id"])

    def _emit_oracle_records(self, task: dict, result: dict) -> None:
        """Inserts a heartbeat and a run record after each Oracle Gemini execution."""
        client = self._get_supabase()
        if not client:
            return

        meta = (result.get("output_json") or {}).get("metadata") or {}
        tokens = meta.get("tokens") or {}
        # F2 GSD (2026-05-17): drop chain elif hardcoded de model normalization.
        # Handler agora resolve model_id via catalog (`_resolve_model(input_data)`)
        # e seta `metadata.model_used = resolved_model` antes do return — trust direto.
        # Cost calc usa lookup em llm_models (id é PK), aceita string vazia fail-safe.
        # Se aparecer suffix legacy (deep-research-*), fica como historic raw — não
        # tentar normalizar em allowlist hardcoded (era violação Regra Ouro #2).
        model_id = meta.get("model_used") or ""

        cost_usd = round(float(result.get("cost_usd") or 0.0), 8)
        company_id = task.get("company_id")
        task_id = task.get("id")
        op_type = task.get("operation_type", "oracle")
        now = datetime.now(timezone.utc).isoformat()
        tokens_in = int(tokens.get("input") or 0)
        tokens_out = int(tokens.get("output") or 0)
        tokens_total = int(tokens.get("total") or 0) or (tokens_in + tokens_out)
        duration_ms = int(meta.get("duration_ms") or 0)

        hb_row = {
            "company_id": company_id,
            "agent_id": ORACLE_AGENT_ID,
            "task_id": task_id,
            "status": "working",
            "tokens_used": tokens_total,
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "cache_read_tokens": 0,
            "model_id": model_id,
            "cost_usd": cost_usd,
            "log_excerpt": f"{op_type} completed via Gemini ({tokens_total} tokens)",
            "created_at": now,
            "updated_at": now,
        }
        try:
            client.table("heartbeats").insert(hb_row).execute()
            logger.info(
                "oracle heartbeat emitted task=%s model=%s tokens=%s cost=%.6f",
                task_id, model_id, tokens_total, cost_usd,
            )
        except Exception as e:
            logger.warning("_emit_oracle_records heartbeat failed task=%s: %s", task_id, e)

        run_row = {
            "company_id": company_id,
            "agent_id": ORACLE_AGENT_ID,
            "task_id": task_id,
            "status": "succeeded",
            "finished_at": now,
            "duration_ms": duration_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
        }
        try:
            client.table("runs").insert(run_row).execute()
            logger.info(
                "oracle run record inserted task=%s cost=%.6f duration_ms=%d",
                task_id, cost_usd, duration_ms,
            )
        except Exception as e:
            logger.warning("_emit_oracle_records run failed task=%s: %s", task_id, e)

        # Accumulate current_burn_rate with this run's tokens so the AgentCard
        # badge shows cumulative Oracle consumption even when status is idle.
        if tokens_total > 0:
            try:
                existing_res = client.table("agents").select("current_burn_rate").eq(
                    "id", ORACLE_AGENT_ID
                ).execute()
                existing = int((existing_res.data[0].get("current_burn_rate") or 0) if existing_res.data else 0)
                client.table("agents").update({
                    "current_burn_rate": existing + tokens_total,
                    "updated_at": now,
                }).eq("id", ORACLE_AGENT_ID).execute()
            except Exception as e:
                logger.warning("_emit_oracle_records agent update failed: %s", e)

    def _send_oracle_research_email(self, task: dict, result: dict) -> None:
        """
        Envia o relatório oracle-research por e-mail via HermesReporter.
        Destinatário: ORACLE_REPORT_EMAIL env var (fallback: marcelo.rosas@vectracargo.com.br).
        """
        try:
            output_json = result.get("output_json") or {}
            report_md = (output_json.get("report_markdown") or "").strip()
            if not report_md:
                logger.info("_send_oracle_research_email: sem report_markdown, skip")
                return

            recipient = os.getenv("ORACLE_REPORT_EMAIL", "marcelo.rosas@vectracargo.com.br").strip()
            title = (task.get("title") or "Oracle Research").strip()
            input_data = task.get("input_json") or {}
            company_name = (input_data.get("company_name") or "").strip()
            subject = f"Oracle Research — {company_name or title}"

            from src.agents.hermes_reporter import render_html, send_smtp
            html_body = render_html(
                report_md,
                subject,
                header_title="Vectra Cargo — Oracle Research",
                footer_text="Relatório gerado automaticamente pelo Oracle • Vectra Claw",
            )
            msg_id = send_smtp(subject, html_body, [recipient])
            logger.info(
                "_send_oracle_research_email: enviado msg_id=%s recipient=%s task=%s",
                msg_id, recipient, task.get("id"),
            )
        except Exception as e:
            logger.warning("_send_oracle_research_email failed task=%s: %s", task.get("id"), e)

    def _dispatch_research(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Morpheus cria uma sub-task oracle-research e delega ao Oracle.
        input_json esperado:
          prompt        — texto da pesquisa (obrigatório)
          company_name  — nome da empresa (opcional, para título)
          website_url   — URL do site (opcional)
          save_to_company_context — bool (opcional, default False)
          require_human_review    — bool (opcional, default False)
        """
        client = self._get_supabase()
        if not client:
            return {"output_json": {"error_detail": {"code": "no_db", "message": "Supabase indisponível"}}, "cost_usd": 0.0}

        input_data: Dict[str, Any] = task.get("input_json") or {}
        prompt = (input_data.get("prompt") or task.get("description") or task.get("title") or "").strip()
        if not prompt:
            return {"output_json": {"error_detail": {"code": "missing_prompt", "message": "input_json.prompt é obrigatório"}}, "cost_usd": 0.0}

        company_name = input_data.get("company_name") or "empresa"
        try:
            from src.models import TaskBlueprint
            from src.services.task_factory import TaskFactory, TaskFactoryError

            factory = TaskFactory(client)
            bp = TaskBlueprint(
                title=task.get("title") or "Dispatch research",
                description=task.get("description") or "",
                budget_limit=int(task.get("budget_limit") or 200_000),
                goal_id=task.get("goal_id"),
            )
            step_payload = {
                "prompt": prompt,
                "company_name": company_name,
                "website_url": input_data.get("website_url", ""),
                "save_to_company_context": bool(input_data.get("save_to_company_context", False)),
                "require_human_review": bool(input_data.get("require_human_review", False)),
                "documents": input_data.get("documents") or [],
            }
            mw = factory.materialize_workflow(
                str(task.get("company_id")),
                "oracle-research-pipeline",
                bp,
                step_inputs={"oracle-research": step_payload},
                existing_parent_task_id=str(task.get("id")),
            )
            sub_id = mw.subtasks[0].id if mw.subtasks else "?"
            logger.info("dispatch_research: materialized workflow sub-task id=%s parent=%s", sub_id, task.get("id"))
            return {
                "output_json": {
                    "report_markdown": f"Pesquisa sobre **{company_name}** despachada para o Oracle.\n\nSub-task ID: `{sub_id}`",
                    "metadata": {"oracle_task_id": sub_id},
                },
                "cost_usd": 0.0,
            }
        except TaskFactoryError as fe:
            logger.error("dispatch_research TaskFactoryError: %s", fe)
            return {"output_json": {"error_detail": {"code": "workflow_error", "message": str(fe)}}, "cost_usd": 0.0}
        except Exception as e:
            logger.error("dispatch_research failed: %s", e)
            return {"output_json": {"error_detail": {"code": "insert_failed", "message": str(e)}}, "cost_usd": 0.0}

    def _emit_idle_heartbeat(self) -> None:
        """VEC-377 — emite heartbeat 'idle' periódico durante polling sem task.

        Rate-limited por self._idle_heartbeat_interval (default 30s).
        Beneficia visibilidade do daemon no dashboard ("Live" + burn rate)
        mesmo sem processar tasks. Falha silenciosa: erro de heartbeat
        nunca derruba o polling loop.
        """
        if not self.agent_id:
            return
        now = datetime.now(timezone.utc)
        if self._last_heartbeat_at is not None:
            elapsed = (now - self._last_heartbeat_at).total_seconds()
            if elapsed < self._idle_heartbeat_interval:
                return  # rate-limited

        client = self._get_supabase()
        if not client:
            return
        try:
            # company_id derivado do agente (cache em _agent_config se disponível)
            company_id = self._agent_config.get("company_id")
            if not company_id:
                ag = client.table("agents").select("company_id").eq("id", self.agent_id).maybe_single().execute()
                if ag.data:
                    company_id = ag.data.get("company_id")
                    self._agent_config["company_id"] = company_id

            row = {
                "agent_id": self.agent_id,
                "status": "idle",
                "tokens_used": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0,
                "log_excerpt": "daemon polling, sem tasks pendentes",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
            if company_id:
                row["company_id"] = company_id

            client.table("heartbeats").insert(row).execute()
            self._last_heartbeat_at = now
        except Exception as e:
            # Não polui logs com warning a cada 30s; só debug.
            logger.debug("idle heartbeat skipped: %s", e)

    def run_forever(self):
        if not self._acquire_lock():
            sys.exit(1)

        try:
            self.is_running = True
            logger.info("=== Inicializando Vectra Claw Agent Engine ===")
            logger.info(f"agent_id={self.agent_id or 'não configurado'} polling={self.polling_interval}s")
            self._recover_stale_tasks()
            self._load_agent_config()

            while self.is_running:
                try:
                    task = self.fetch_next_task()
                    if task:
                        task_id = task["id"]

                        if self._claim_task(task_id):
                            # VEC-429 Fase 1 — heartbeat 'working' ligado à task
                            # logo após claim. Permite dashboard exibir agente
                            # como executando em vez de só 'idle'.
                            self._emit_task_lifecycle_heartbeat(
                                task_id=task_id,
                                status="working",
                                company_id=task.get("company_id"),
                                operation_type=task.get("operation_type"),
                                log_excerpt=(
                                    f"executing {task.get('operation_type', 'task')}"
                                ),
                            )
                            success = False
                            cost_usd = 0.0
                            output_json = None
                            status_override = None
                            try:
                                raw = self.execute_task(task)
                                success = True
                                try:
                                    import json as _j
                                    parsed = _j.loads(raw)
                                    cost_usd = float(parsed.get("cost_usd", 0) or 0)
                                    output_json = parsed.get("output_json")
                                    status_override = parsed.get("status_override")
                                    if parsed.get("status") == "errored":
                                        success = False
                                        if output_json is None:
                                            output_json = {
                                                "error_detail": {
                                                    "message": parsed.get("error") or "errored",
                                                }
                                            }
                                except Exception:
                                    pass
                                # W7 P0-11 — Reply pós-output pra connector_session
                                # se a task veio de webhook inbound (Meta etc).
                                # Auditor 2026-05-18: GO, escopo cirúrgico, best-effort.
                                if success:
                                    try:
                                        self._maybe_reply_to_connector_session(task, raw)
                                    except Exception as e:
                                        logger.warning("connector reply hook non-fatal: %s", e)
                            finally:
                                self._complete_task(
                                    task_id, success, cost_usd,
                                    output_json=output_json,
                                    status_override=status_override,
                                    task_meta={
                                        "company_id": task.get("company_id"),
                                        "operation_type": task.get("operation_type"),
                                    },
                                )
                        else:
                            logger.debug(f"task {task_id} já foi claimed por outro worker")

                    self.check_and_trigger_routines()
                    self._poll_research_tasks()
                    # VEC-377 — emite heartbeat idle periodicamente (rate-limited)
                    self._emit_idle_heartbeat()
                    time.sleep(self.polling_interval)

                except KeyboardInterrupt:
                    logger.info("Sinal KeyboardInterrupt recebido. Desligando com segurança...")
                    self.is_running = False

                except Exception as e:
                    logger.error(f"Erro fatal não tratado no poller principal: {e}")
                    logger.warning(f"Reinicializando ciclo em {int(os.getenv('DAEMON_RESTART_DELAY_SECONDS','5'))}s...")
                    time.sleep(int(os.getenv("DAEMON_RESTART_DELAY_SECONDS", "5")))

        finally:
            self._release_lock()

if __name__ == "__main__":
    daemon = ResilientHarnessDaemon()
    daemon.run_forever()
