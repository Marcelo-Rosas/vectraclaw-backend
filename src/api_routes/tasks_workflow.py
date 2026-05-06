"""
src.api_routes.tasks_workflow — endpoints de fluxo de aprovação/avaliação de tasks.

Cobre transições pós-execução: reject (review → blocked), evaluate
(score 1-5 + notes idempotente em qualquer status).

Endpoints:
- POST /api/tasks/{task_id}/reject       reject_task
- POST /api/tasks/{task_id}/evaluate     evaluate_task

⚠️ approve_task NÃO está aqui (versão antiga continua em api.py por enquanto;
a versão nova com review_notes vem na Step 8.8 cleanup).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("api.tasks_workflow")
router = APIRouter(tags=["tasks_workflow"])


class EvaluateTaskInput(BaseModel):
    """Body do POST /api/tasks/{task_id}/evaluate.

    `evaluated_by` espelha o CHECK do banco (vec_semana_2):
      - `agent`: auto-avaliação ao concluir a task.
      - `human`: revisão humana.
      - `auto`:  job batch de qualidade.
    """
    score: int = Field(ge=1, le=5, description="Score 1 (ruim) a 5 (excelente)")
    notes: Optional[str] = None
    evaluated_by: Literal["agent", "human", "auto"] = "agent"


@router.post("/api/tasks/{task_id}/reject")
async def reject_task(request: Request, task_id: UUID):
    """Marca task em status `review` como `blocked`. Emite WS task_updated."""
    from src.api import supabase, get_authenticated_client, ws_manager
    from src.models import Task

    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_required")
    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("tasks").update({
            "status": "blocked",
        }).eq("id", str(task_id)).eq("status", "review").execute()
        if not res.data:
            raise HTTPException(
                status_code=404,
                detail="Task não encontrada ou não está em status 'review'",
            )
        task_dict = Task(**res.data[0]).to_zod_dict()
        company_id = res.data[0].get("company_id")
        if company_id:
            await ws_manager.emit_task_updated(company_id, task_dict)
        return task_dict
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"reject_task failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/tasks/{task_id}/evaluate")
async def evaluate_task(request: Request, task_id: str, payload: EvaluateTaskInput):
    """Registra/atualiza avaliação de uma task.

    Idempotente: re-call sobrescreve score/notes/evaluated_by/evaluated_at.
    Funciona em qualquer status (não exige `review`) — permite auto-avaliação
    no momento de conclusão e reavaliação humana de tasks já encerradas.
    """
    from src.api import supabase, get_authenticated_client, ws_manager
    from src.models import Task

    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_required")
    try:
        client = get_authenticated_client(request.state.token)
        update: Dict[str, Any] = {
            "evaluation_score": payload.score,
            "evaluation_notes": payload.notes,
            "evaluated_by": payload.evaluated_by,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
        res = client.table("tasks").update(update).eq("id", str(task_id)).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Task não encontrada")
        task_dict = Task(**res.data[0]).to_zod_dict()
        company_id = res.data[0].get("company_id")
        if company_id:
            await ws_manager.emit_task_updated(company_id, task_dict)
        return task_dict
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"evaluate_task failed task_id={task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
