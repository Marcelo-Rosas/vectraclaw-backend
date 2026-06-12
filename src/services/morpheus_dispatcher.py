import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("MorpheusDispatcher")

from src.agent_ids import MORPHEUS_AGENT_ID  # SSOT — ver src/agent_ids.py

# Fallback quando não há linha em workflow_steps (legado / bootstrap).
OPERATION_SEQUENCE: dict[str, str] = {
    "email_lead": "freight-quotation",
}

# Tipos que o Morpheus jamais deve disparar como predecessores de novas tasks.
# Adicionar aqui operation_types que têm seu próprio orquestrador ou
# que não devem gerar filhos automáticos.
MORPHEUS_EXCLUDED_TYPES: frozenset[str] = frozenset({
    "workflow-orchestrator",
    "followup-dispatcher",
    "route-cost-calculation",
})


class MorpheusDispatcher:
    def __init__(self, supabase_client):
        self.client = supabase_client

    # ------------------------------------------------------------------
    # Routing rules from DB (VEC-318 workflow_steps)
    # ------------------------------------------------------------------

    def _load_routing_rules(self) -> List[Dict[str, Any]]:
        """Returns workflow_steps rows enriched with workflow company_id."""
        try:
            res = (
                self.client.table("workflow_steps")
                .select(
                    "current_operation_type,next_operation_type,specialty_slug,workflow_id,active"
                )
                .execute()
            )
        except Exception as e:
            logger.error("[morpheus] load routing rules failed: %s", e)
            return []

        rows = [
            r
            for r in (res.data or [])
            if r.get("active", True) and r.get("current_operation_type")
        ]
        out: List[Dict[str, Any]] = []
        for r in rows:
            try:
                wf = (
                    self.client.table("workflow_definitions")
                    .select("company_id")
                    .eq("id", r["workflow_id"])
                    .limit(1)
                    .execute()
                )
                wc = (wf.data or [None])[0]
                r = dict(r)
                r["_workflow_company_id"] = wc.get("company_id") if wc else None
                out.append(r)
            except Exception as exc:
                logger.warning("[morpheus] skip rule workflow_id=%s: %s", r.get("workflow_id"), exc)
        return out

    # ------------------------------------------------------------------
    # Fila de entrada
    # ------------------------------------------------------------------

    def _match_rule(
        self, rules: List[Dict[str, Any]], company_id: str, completed_op: str
    ) -> Optional[Dict[str, Any]]:
        for r in rules:
            if r.get("current_operation_type") != completed_op:
                continue
            wfc = r.get("_workflow_company_id")
            if wfc is not None and str(wfc) != str(company_id):
                continue
            if r.get("next_operation_type"):
                return r
        return None

    def _pending_tasks(self, rules: Optional[List[Dict[str, Any]]] = None) -> list[dict]:
        """
        Tasks done whose operation_type matches workflow_steps.current_operation_type
        (company-scoped or global template) and sem filho com mesmo next_operation_type.
        """
        rules = rules or self._load_routing_rules()
        monitored_types = {r["current_operation_type"] for r in rules}
        monitored_types |= set(OPERATION_SEQUENCE.keys())
        monitored_types -= MORPHEUS_EXCLUDED_TYPES

        try:
            done_res = (
                self.client.table("tasks")
                .select("id,company_id,title,description,operation_type,goal_id,parent_task_id")
                .eq("status", "done")
                .in_("operation_type", list(monitored_types))
                .execute()
            )
            candidates = done_res.data or []
        except Exception as e:
            logger.error("[morpheus] pending_tasks query failed: %s", e)
            return []

        if not candidates:
            return []

        company_ids = list({t["company_id"] for t in candidates})
        try:
            all_child_res = (
                self.client.table("tasks")
                .select("title,parent_task_id,company_id,operation_type")
                .in_("company_id", company_ids)
                .execute()
            )
            existing_children = all_child_res.data or []
        except Exception as e:
            logger.warning("[morpheus] child_tasks fetch failed: %s", e)
            existing_children = []

        children_by_parent: Dict[str, set] = {}
        for ch in existing_children:
            pid = ch.get("parent_task_id")
            if not pid:
                continue
            children_by_parent.setdefault(pid, set()).add(ch.get("operation_type"))

        pending = []
        for task in candidates:
            company_id = str(task["company_id"])
            rule = self._match_rule(rules, company_id, task["operation_type"])
            # Workflow-steps rules only apply to tasks that are part of a chain
            # (have parent_task_id set). Standalone tasks (no parent) must not
            # trigger the dispatch chain to avoid spurious cascades.
            if rule and not task.get("parent_task_id"):
                continue
            next_type = rule["next_operation_type"] if rule else OPERATION_SEQUENCE.get(task["operation_type"])

            if not next_type:
                continue

            if next_type in MORPHEUS_EXCLUDED_TYPES:
                continue

            already = children_by_parent.get(task["id"], set())
            if next_type in already:
                continue

            expected_title = f"[Morpheus→{next_type}] {task['title']}"
            legacy_title_match = any(
                ch.get("parent_task_id") == task["id"] and ch.get("title") == expected_title
                for ch in existing_children
            )
            if legacy_title_match:
                continue

            pending.append(task)

        return pending

    # ------------------------------------------------------------------
    # Resolução de agente
    # ------------------------------------------------------------------

    def _find_agent(
        self,
        company_id: str,
        specialty_slug: str,
        *,
        operation_type: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve um agente para a specialty.

        Hardening:
        - Determinístico: evita `LIMIT 1` sem `ORDER BY`.
        - Não depende de `idle`: materialização de workflow deve conseguir
          atribuir um agente mesmo quando todos estão `working` (a task fica em
          backlog/queued e será consumida depois).
        - Quando `operation_type` é informado, prefere `primary_agent_id` do
          `operation_types_catalog` se ele estiver configurado para a specialty.
        """
        try:
            sp_res = (
                self.client.table("agent_specialties")
                .select("id")
                .eq("slug", specialty_slug)
                .limit(1)
                .execute()
            )
            sp = (sp_res.data or [None])[0]
            if not sp:
                logger.warning("[morpheus] specialty não encontrada: %r", specialty_slug)
                return None

            cfg_res = (
                self.client.table("agent_specialty_configs")
                .select("agent_id")
                .eq("specialty_id", sp["id"])
                .execute()
            )
            agent_ids = [r["agent_id"] for r in (cfg_res.data or [])]
            if not agent_ids:
                return None

            # Preferência canônica quando o op_type declara um primary_agent_id.
            if operation_type:
                try:
                    op_res = (
                        self.client.table("operation_types_catalog")
                        .select("primary_agent_id")
                        .eq("id", operation_type)
                        .limit(1)
                        .execute()
                    )
                    op_row = (op_res.data or [None])[0]
                    primary = (op_row or {}).get("primary_agent_id")
                    if primary and primary in agent_ids:
                        agp = (
                            self.client.table("agents")
                            .select("id,status")
                            .eq("company_id", company_id)
                            .eq("id", primary)
                            .limit(1)
                            .execute()
                        )
                        rowp = (agp.data or [None])[0]
                        if rowp and rowp.get("status") != "offline":
                            return rowp["id"]
                except Exception as exc:
                    logger.debug(
                        "[morpheus] primary_agent lookup failed op_type=%r: %s",
                        operation_type,
                        exc,
                    )

            # Fallback determinístico por prioridade de status.
            ag_res = (
                self.client.table("agents")
                .select("id,status")
                .eq("company_id", company_id)
                .in_("id", agent_ids)
                .execute()
            )
            candidates = list(ag_res.data or [])
            if not candidates:
                return None

            def _rank(status: Optional[str]) -> int:
                s = (status or "").strip().lower()
                if s == "idle":
                    return 0
                if s == "working":
                    return 1
                if s == "paused":
                    return 2
                if s == "offline":
                    return 9
                return 5

            candidates.sort(key=lambda r: (_rank(r.get("status")), str(r.get("id"))))
            best = candidates[0]
            return str(best.get("id")) if best.get("id") else None
        except Exception as e:
            logger.warning("[morpheus] find_agent failed specialty=%r: %s", specialty_slug, e)
            return None

    # ------------------------------------------------------------------
    # Criação do task filho
    # ------------------------------------------------------------------

    def _create_child_task(self, parent: dict, next_type: str, agent_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "id": str(uuid.uuid4()),
            "company_id": parent["company_id"],
            "parent_task_id": parent["id"],
            "assigned_to_agent_id": agent_id,
            "goal_id": parent.get("goal_id"),
            "title": f"[Morpheus→{next_type}] {parent['title']}",
            "description": parent.get("description") or "",
            "status": "queued",
            "operation_type": next_type,
            "budget_limit": 0,
            "spent": 0,
            "cost_usd": 0,
            "created_at": now,
            "updated_at": now,
        }
        try:
            self.client.table("tasks").insert(row).execute()
            logger.info(
                "[morpheus] dispatched parent=%s op=%r → %r agent=%s",
                parent["id"],
                parent["operation_type"],
                next_type,
                agent_id,
            )
            return True
        except Exception as e:
            logger.error("[morpheus] create_child_task failed parent=%s: %s", parent["id"], e)
            return False

    # ------------------------------------------------------------------
    # Ponto de entrada público
    # ------------------------------------------------------------------

    def dispatch(self) -> tuple[int, int]:
        rules_cache = self._load_routing_rules()
        pending = self._pending_tasks(rules_cache)
        if not pending:
            return 0, 0

        dispatched = 0
        for task in pending:
            rule = self._match_rule(rules_cache, str(task["company_id"]), task["operation_type"])
            if rule:
                next_type = rule["next_operation_type"]
                spec_slug = rule.get("specialty_slug") or next_type
            else:
                next_type = OPERATION_SEQUENCE.get(task["operation_type"])
                spec_slug = next_type
            if not next_type:
                continue
            agent_id = self._find_agent(task["company_id"], spec_slug or next_type)
            if not agent_id:
                logger.warning(
                    "[morpheus] nenhum agente idle para op=%r task=%s",
                    next_type,
                    task["id"],
                )
                continue
            if self._create_child_task(task, next_type, agent_id):
                dispatched += 1

        return len(pending), dispatched
