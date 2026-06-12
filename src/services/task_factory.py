"""
Materialize workflow_definitions + workflow_steps into parent + child tasks.

Uses workflow_graph (networkx) for validation, topological generations and critical path.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.agent_ids import ORACLE_AGENT_ID  # SSOT — ver src/agent_ids.py
from src.models import MaterializedWorkflow, Task, TaskBlueprint
from src.services import workflow_graph
from src.services.morpheus_dispatcher import MORPHEUS_AGENT_ID, MorpheusDispatcher

logger = logging.getLogger("TaskFactory")


class TaskFactoryError(ValueError):
    """Invalid workflow definition or graph validation failure."""


class TaskFactory:
    def __init__(self, client: Any) -> None:
        self.client = client
        self._dispatcher = MorpheusDispatcher(client)

    # ------------------------------------------------------------------
    # Workflow resolution
    # ------------------------------------------------------------------

    def resolve_workflow_definition(
        self, company_id: str, slug: str
    ) -> Optional[Dict[str, Any]]:
        res = self.client.table("workflow_definitions").select("*").eq("slug", slug).execute()
        rows = res.data or []
        if not rows:
            return None
        company_match = next((r for r in rows if r.get("company_id") == company_id), None)
        if company_match:
            return company_match
        return next((r for r in rows if r.get("company_id") is None), None)

    def fetch_workflow_steps(self, workflow_id: str) -> List[Dict[str, Any]]:
        res = (
            self.client.table("workflow_steps")
            .select("*")
            .eq("workflow_id", workflow_id)
            .eq("active", True)
            .order("step_order")
            .execute()
        )
        return list(res.data or [])

    def rows_to_graph_steps(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize DB rows → dicts consumed by workflow_graph."""
        mutable: List[Dict[str, Any]] = []
        for r in rows:
            slug = (r.get("slug") or "").strip()
            if not slug:
                continue
            entry = dict(r)
            prox = r.get("proximo_step_codes")
            if isinstance(prox, str):
                prox = [prox] if prox else []
            elif prox is None:
                prox = []
            entry["step_code"] = slug
            entry["slug"] = slug
            entry["proximo_step_codes"] = list(prox)
            entry["proximo"] = list(prox)
            entry["sla_horas"] = r.get("sla_horas")
            entry["slaHoras"] = r.get("sla_horas")
            mutable.append(entry)

        workflow_graph.enrich_steps_with_legacy_edges(mutable)
        for e in mutable:
            e["proximo"] = workflow_graph.proximo_list(e)
        return mutable

    # ------------------------------------------------------------------
    # Materialize
    # ------------------------------------------------------------------

    def _resolve_assigned_agent_id(
        self, company_id: str, row: Dict[str, Any], operation_type: str
    ) -> Optional[str]:
        """Resolve assigned_to_agent_id para um step.

        Ordem:
        0) `assigned_to_agent_id` (override explícito declarado no step)
        1) `agent_specialty_config_id` (override por specialty config)
        2) `specialty_slug` via MorpheusDispatcher (determinístico)
        3) fallback Oracle para `oracle-*` (exceto op_types de e-mail)
        """
        explicit_agent_id = (row.get("assigned_to_agent_id") or "").strip()
        if explicit_agent_id:
            return str(explicit_agent_id)

        cfg_id = (row.get("agent_specialty_config_id") or "").strip()
        if cfg_id:
            try:
                cfg = (
                    self.client.table("agent_specialty_configs")
                    .select("agent_id")
                    .eq("id", cfg_id)
                    .eq("company_id", company_id)
                    .limit(1)
                    .execute()
                )
                cfg_row = (cfg.data or [None])[0]
                agent_id = (cfg_row or {}).get("agent_id")
                if agent_id:
                    return str(agent_id)
            except Exception as exc:
                logger.warning(
                    "_resolve_assigned_agent_id: config_id lookup failed (%s): %s",
                    cfg_id,
                    exc,
                )

        spec_slug = (row.get("specialty_slug") or "").strip()
        if spec_slug:
            agent_id = self._dispatcher._find_agent(
                company_id, spec_slug, operation_type=operation_type
            )
            if agent_id:
                return str(agent_id)

        op = str(operation_type or "")
        if op.startswith("oracle-") and op not in (
            "oracle-report",
            "responsavel-pelo-disparo-de-e-mails",
        ):
            return ORACLE_AGENT_ID

        return None

    def materialize_workflow(
        self,
        company_id: str,
        workflow_slug: str,
        parent_input: TaskBlueprint,
        step_inputs: Optional[Dict[str, Dict[str, Any]]] = None,
        *,
        existing_parent_task_id: Optional[str] = None,
    ) -> MaterializedWorkflow:
        wf = self.resolve_workflow_definition(company_id, workflow_slug)
        if not wf:
            raise TaskFactoryError(f"workflow not found: {workflow_slug!r}")

        rows = self.fetch_workflow_steps(str(wf["id"]))
        graph_steps = self.rows_to_graph_steps(rows)
        errs = workflow_graph.validate_workflow_steps(graph_steps)
        if errs:
            raise TaskFactoryError("; ".join(errs))

        G = workflow_graph.build_graph(graph_steps)
        generations = workflow_graph.topological_generations_with_meta(G)
        critical, sla_total = workflow_graph.critical_path(G)
        critical_set = set(critical)

        now = datetime.now(timezone.utc).isoformat()
        step_inputs = step_inputs or {}
        slug_to_row = {(r.get("slug") or "").strip(): r for r in rows}

        workflow_meta = {
            "workflowSlug": workflow_slug,
            "workflowDefinitionId": str(wf["id"]),
            "estimatedSlaHours": sla_total,
            "criticalPath": critical,
            "topologicalGenerations": generations,
            "entrypoints": generations[0] if generations else [],
        }

        if existing_parent_task_id:
            pres = (
                self.client.table("tasks")
                .select("*")
                .eq("id", existing_parent_task_id)
                .limit(1)
                .execute()
            )
            if not pres.data:
                raise TaskFactoryError(f"parent task not found: {existing_parent_task_id}")
            parent_dict = pres.data[0]
            parent_id = existing_parent_task_id
            merged_input = dict(parent_dict.get("input_json") or {})
            merged_input.update(workflow_meta)
            self.client.table("tasks").update({"input_json": merged_input, "updated_at": now}).eq(
                "id", parent_id
            ).execute()
            parent_dict = {**parent_dict, "input_json": merged_input}
        else:
            parent_row = {
                "company_id": company_id,
                "title": parent_input.title,
                "description": parent_input.description,
                "budget_limit": parent_input.budget_limit,
                "goal_id": parent_input.goal_id,
                "workflow_definition_id": wf.get("id") if wf else None,
                "operation_type": "orchestration",
                "status": "in_progress",
                "spent": 0,
                "cost_usd": 0,
                "input_json": workflow_meta,
                # Parent orchestration tem como responsável o Morpheus —
                # convenção do team (ver agents/CLAUDE.md). Sem isso, o
                # backfill setava com agent_id do primeiro step (ex: Kronos),
                # quebrando a kanban.
                "assigned_to_agent_id": MORPHEUS_AGENT_ID,
                "created_at": now,
                "updated_at": now,
            }
            pres = self.client.table("tasks").insert(parent_row).execute()
            if not pres.data:
                raise TaskFactoryError("failed to insert parent task")
            parent_dict = pres.data[0]
            parent_id = parent_dict["id"]

        subtasks_raw: List[Dict[str, Any]] = []
        insert_failures: List[Dict[str, Any]] = []
        expected_step_count = sum(
            1 for gen in generations for step_code in gen if step_code in slug_to_row
        )

        for gen_idx, gen in enumerate(generations):
            for step_code in gen:
                row = slug_to_row.get(step_code)
                if not row:
                    logger.warning("materialize: missing row for step %s", step_code)
                    continue
                preds = list(G.predecessors(step_code))
                succs = list(G.successors(step_code))
                op_type = (
                    row.get("default_operation_type")
                    or row.get("next_operation_type")
                    or row.get("current_operation_type")
                    or "other"
                )
                spec_slug = row.get("specialty_slug")
                agent_id = self._resolve_assigned_agent_id(company_id, row, op_type)

                merged_child_input = dict(step_inputs.get(step_code, {}) or {})
                merged_child_input["workflowStepSlug"] = step_code
                merged_child_input["workflowSlug"] = workflow_slug

                child = {
                    "company_id": company_id,
                    "parent_task_id": parent_id,
                    "workflow_step_id": row["id"],
                    "workflow_definition_id": wf.get("id") if wf else None,
                    "title": f"[{workflow_slug}] {row.get('name') or step_code}",
                    "description": str(row.get("description") or "")[:2000],
                    "operation_type": op_type,
                    "status": "queued" if gen_idx == 0 else "backlog",
                    "budget_limit": parent_input.budget_limit,
                    "spent": 0,
                    "cost_usd": 0,
                    "goal_id": parent_input.goal_id,
                    "assigned_to_agent_id": agent_id,
                    "dependency_step_codes": preds,
                    "successor_step_codes": succs,
                    "is_critical_path": step_code in critical_set,
                    "input_json": merged_child_input,
                    "created_at": now,
                    "updated_at": now,
                }
                try:
                    cres = self.client.table("tasks").insert(child).execute()
                except Exception as exc:
                    logger.error(
                        "materialize: insert raised for step=%s workflow=%s parent=%s: %s",
                        step_code, workflow_slug, parent_id, exc,
                    )
                    insert_failures.append({"step": step_code, "error": str(exc)})
                    continue
                if cres.data:
                    subtasks_raw.append(cres.data[0])
                else:
                    err_detail = getattr(cres, "error", None) or getattr(cres, "status_code", None)
                    logger.error(
                        "materialize: empty insert response for step=%s workflow=%s parent=%s detail=%s",
                        step_code, workflow_slug, parent_id, err_detail,
                    )
                    insert_failures.append({"step": step_code, "error": f"empty response ({err_detail})"})

        if expected_step_count and not subtasks_raw:
            # Nada foi materializado — pai órfã. Reverte para evitar in_progress eterno.
            logger.error(
                "materialize: zero subtasks created for workflow=%s parent=%s failures=%s",
                workflow_slug, parent_id, insert_failures,
            )
            try:
                if existing_parent_task_id:
                    self.client.table("tasks").update(
                        {
                            "status": "blocked",
                            "updated_at": now,
                            "output_json": {
                                "error_detail": {
                                    "code": "materialize_failed",
                                    "message": "no subtasks created",
                                    "failures": insert_failures,
                                }
                            },
                        }
                    ).eq("id", parent_id).execute()
                else:
                    self.client.table("tasks").delete().eq("id", parent_id).execute()
            except Exception as cleanup_exc:
                logger.error("materialize: rollback of parent %s failed: %s", parent_id, cleanup_exc)
            raise TaskFactoryError(
                f"materialize_workflow {workflow_slug!r}: 0/{expected_step_count} subtasks created; failures={insert_failures}"
            )

        try:
            self.client.table("workflow_definitions").update({"last_run_at": now}).eq(
                "id", wf["id"]
            ).execute()
        except Exception as exc:
            logger.warning("task_factory: last_run_at update failed: %s", exc)

        return MaterializedWorkflow(
            parent=Task(**parent_dict),
            subtasks=[Task(**t) for t in subtasks_raw],
        )

    # ------------------------------------------------------------------
    # Promotion + rollup (called from agent_daemon)
    # ------------------------------------------------------------------

    def promote_successors_after_completion(self, completed_task_id: str) -> None:
        tres = (
            self.client.table("tasks")
            .select("*")
            .eq("id", completed_task_id)
            .limit(1)
            .execute()
        )
        if not tres.data:
            return
        completed_task = tres.data[0]
        parent_id = completed_task.get("parent_task_id")
        if not parent_id:
            return

        final_status = completed_task.get("status")
        # Wave 1A: workflow só avança a partir de DONE. Tasks erroradas BLOQUEIAM
        # o successor (humano precisa intervir/aprovar) — antes `skipped` deixava
        # passar silenciosamente. Mais seguro.
        if final_status != "done":
            return

        succs = completed_task.get("successor_step_codes") or []
        if isinstance(succs, str):
            succs = [succs]

        sib = (
            self.client.table("tasks")
            .select("id,status,input_json,dependency_step_codes")
            .eq("parent_task_id", parent_id)
            .execute()
        )
        siblings = sib.data or []

        slug_status: Dict[str, str] = {}
        for t in siblings:
            slug = (t.get("input_json") or {}).get("workflowStepSlug")
            if slug:
                slug_status[str(slug)] = str(t.get("status") or "")

        now = datetime.now(timezone.utc).isoformat()

        for t in siblings:
            slug = (t.get("input_json") or {}).get("workflowStepSlug")
            if not slug or slug not in succs:
                continue
            if str(t.get("status") or "") != "backlog":
                continue
            deps = t.get("dependency_step_codes") or []
            if isinstance(deps, str):
                deps = [deps]
            # Wave 1A: dep deve estar DONE (era done|skipped). Erro bloqueia successor.
            ok = all(slug_status.get(str(d)) == "done" for d in deps)
            if ok:
                logger.info(
                    "promote_successors: completed=%s → promoting sibling id=%s slug=%s",
                    completed_task_id, t["id"], slug,
                )
                self.client.table("tasks").update({"status": "queued", "updated_at": now}).eq(
                    "id", t["id"]
                ).execute()

        self.rollup_parent(str(parent_id))

    def rollup_parent(self, parent_id: str) -> None:
        sib = (
            self.client.table("tasks")
            .select("id,status")
            .eq("parent_task_id", parent_id)
            .execute()
        )
        children = sib.data or []
        if not children:
            return

        total = len(children)
        done = sum(1 for c in children if c.get("status") == "done")
        blocked_or_errored = sum(1 for c in children if c.get("status") in ("blocked", "errored"))

        if total == 0:
            return

        now = datetime.now(timezone.utc).isoformat()
        patch: Dict[str, Any] = {"updated_at": now}

        if done == total:
            patch["status"] = "done"
        elif blocked_or_errored > 0:
            patch["status"] = "blocked"
        else:
            return

        self.client.table("tasks").update(patch).eq("id", parent_id).execute()

