"""VEC-168 — Intelligence dashboard cross-company."""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from src.services.intelligence_dashboard import build_intelligence_dashboard

logger = logging.getLogger("api.intelligence")
router = APIRouter(tags=["intelligence"])


@router.get("/api/intelligence/dashboard")
@router.get("/intelligence/dashboard")
async def intelligence_dashboard(request: Request, weeks: int = 8) -> Dict[str, Any]:
    """
    KPIs e gráficos agregados cross-company.
    Roles: platform_admin, consultant, admin.
    """
    from src.api import get_authenticated_client, supabase

    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_unavailable")

    token = getattr(request.state, "token", None)
    if not token:
        raise HTTPException(status_code=401, detail="unauthenticated")

    role = getattr(request.state, "role", None)
    caller_company = getattr(request.state, "company_id", None)

    try:
        client = get_authenticated_client(token)
        return build_intelligence_dashboard(
            client,
            caller_role=role,
            caller_company_id=str(caller_company) if caller_company else None,
            weeks=weeks,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("intelligence_dashboard failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e
