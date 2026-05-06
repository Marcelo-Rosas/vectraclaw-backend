"""
src.api_routes.kronos_rules — CRUD de regras de categorização do Kronos.

Endpoints:
- GET    /api/kronos/rules                      list (filtros: type, active_only)
- POST   /api/kronos/rules                      create (valida regex)
- PUT    /api/kronos/rules/{rule_id}            update parcial
- DELETE /api/kronos/rules/{rule_id}            soft-delete (is_active=false)

A tabela `vectraclip.kronos_rules` armazena regex → categoria/subcategoria
usadas pelo daemon Kronos para classificar lançamentos OFX/Planner.
"""
from __future__ import annotations

import logging
import re as _re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("api.kronos_rules")
router = APIRouter(tags=["kronos_rules"])


class KronosRuleInput(BaseModel):
    type: str = Field(..., pattern="^(expense|revenue)$")
    pattern: str
    category: str
    subcategory: Optional[str] = None
    confidence: float = Field(..., ge=0, le=1)
    priority: Optional[int] = 100
    notes: Optional[str] = None


@router.get("/api/kronos/rules")
async def list_kronos_rules(
    type: Optional[str] = Query(None, pattern="^(expense|revenue)$"),
    active_only: bool = Query(True),
):
    from src.api import supabase

    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_required")
    try:
        q = supabase.table("kronos_rules").select("*").order("priority")
        if type:
            q = q.eq("type", type)
        if active_only:
            q = q.eq("is_active", True)
        return q.execute().data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/kronos/rules", status_code=201)
async def create_kronos_rule(payload: KronosRuleInput):
    from src.api import supabase

    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_required")
    try:
        _re.compile(payload.pattern, _re.I | _re.UNICODE)
    except _re.error as e:
        raise HTTPException(status_code=422, detail=f"Regex inválido: {e}")
    row = payload.model_dump()
    row["is_active"] = True
    try:
        res = supabase.table("kronos_rules").insert(row).execute()
        return res.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/kronos/rules/{rule_id}")
async def update_kronos_rule(rule_id: str, payload: dict):
    from src.api import supabase

    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_required")
    if "pattern" in payload:
        try:
            _re.compile(payload["pattern"], _re.I | _re.UNICODE)
        except _re.error as e:
            raise HTTPException(status_code=422, detail=f"Regex inválido: {e}")
    try:
        res = supabase.table("kronos_rules").update(payload).eq("id", rule_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="rule_not_found")
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/kronos/rules/{rule_id}")
async def deactivate_kronos_rule(rule_id: str):
    """Soft-delete: marca is_active=false."""
    from src.api import supabase

    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_required")
    try:
        res = (
            supabase.table("kronos_rules")
            .update({"is_active": False})
            .eq("id", rule_id)
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="rule_not_found")
        return {"deleted": True, "id": rule_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
