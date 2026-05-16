"""src.api_routes.admin — Admin endpoints (positions + app_users).

PR7 Fase A. Permite que admin/consultant/company_admin gerencie:
- Cargos no organograma SIPOC (PATCH, DELETE) — GET/POST já existem em api.py
- Usuários do tenant (listar, atribuir role + position_id)

Endpoints (todos bloqueiam role=viewer e role=sector_responsible):
- PATCH  /api/sipoc/positions/{position_id}      patch_position
- DELETE /api/sipoc/positions/{position_id}      delete_position
- GET    /api/companies/{company_id}/app_users   list_company_users
- PATCH  /api/app_users/{user_id}                patch_app_user

CHECK constraints relevantes (do PR2 #131):
- app_users.role ∈ (admin, platform_admin, consultant, company_admin,
                     sector_responsible, viewer)
- app_users.assigned_position_id FK → sipoc_positions(id) nullable

Bloqueio adicional: sector_responsible/viewer também não podem se
auto-promover (require_role_not aplicado em patch_app_user).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Request, Response
from pydantic import BaseModel

logger = logging.getLogger("api.admin")
router = APIRouter(tags=["admin"])

_VALID_ROLES = {
    "admin", "platform_admin", "consultant",
    "company_admin", "sector_responsible", "viewer",
}

# Roles que NÃO podem operar endpoints admin.
_ADMIN_BLOCKED_ROLES = ["sector_responsible", "viewer"]


class PatchPositionInput(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    sector_id: Optional[str] = None
    reports_to_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class PatchAppUserInput(BaseModel):
    role: Optional[str] = None
    assigned_position_id: Optional[str] = None
    name: Optional[str] = None


def _position_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize DB row → wire format (camelCase)."""
    return {
        "id": row["id"],
        "companyId": row.get("company_id"),
        "sectorId": row.get("sector_id"),
        "title": row.get("title"),
        "description": row.get("description"),
        "reportsToId": row.get("reports_to_id"),
        "metadata": row.get("metadata") or {},
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


def _user_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize app_users row → wire format (camelCase). Sem expor email
    completo se viewer (não aplica aqui — endpoints já são admin-only).
    """
    return {
        "id": row["id"],
        "email": row.get("email"),
        "name": row.get("name"),
        "role": row.get("role"),
        "companyId": row.get("company_id"),
        "assignedPositionId": row.get("assigned_position_id"),
        "avatarUrl": row.get("avatar_url"),
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


# -----------------------------------------------------------------------------
# Positions — PATCH + DELETE (GET/POST já em api.py)
# -----------------------------------------------------------------------------

@router.patch("/api/sipoc/positions/{position_id}")
@router.patch("/sipoc/positions/{position_id}")
async def patch_position(request: Request, position_id: str, payload: PatchPositionInput):
    """Edita um cargo do organograma SIPOC. Admin only."""
    from src.api import supabase, get_authenticated_client, get_user_scope, require_role_not

    if not supabase:
        raise HTTPException(503, "supabase_unavailable")

    scope = get_user_scope(request.state.token)
    require_role_not(scope, _ADMIN_BLOCKED_ROLES, "editar cargos do organograma")

    update_data = {k: v for k, v in payload.dict(exclude_unset=True).items() if v is not None}
    if not update_data:
        raise HTTPException(400, "no_valid_fields")

    try:
        client = get_authenticated_client(request.state.token)
        res = client.table("sipoc_positions").update(update_data).eq("id", position_id).execute()
        if not res.data:
            raise HTTPException(404, "position_not_found_or_not_accessible")
        logger.info("patch_position position=%s fields=%s by=%s",
                    position_id, list(update_data.keys()), scope.get("user_id"))
        return _position_to_dict(res.data[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_position failed: {e}")
        raise HTTPException(500, str(e))


@router.delete("/api/sipoc/positions/{position_id}")
@router.delete("/sipoc/positions/{position_id}")
async def delete_position(request: Request, position_id: str):
    """Remove um cargo do organograma. Admin only.

    Falha (409) se houver app_users com assigned_position_id apontando pra esse
    cargo OU se houver sipoc_components.responsible_position_id apontando.
    """
    from src.api import supabase, get_authenticated_client, get_user_scope, require_role_not

    if not supabase:
        raise HTTPException(503, "supabase_unavailable")

    scope = get_user_scope(request.state.token)
    require_role_not(scope, _ADMIN_BLOCKED_ROLES, "remover cargos do organograma")

    try:
        client = get_authenticated_client(request.state.token)

        # Pré-check: tem dependentes?
        users_ref = (
            client.table("app_users")
            .select("id", count="exact")
            .eq("assigned_position_id", position_id)
            .limit(1)
            .execute()
        )
        if users_ref.count and users_ref.count > 0:
            raise HTTPException(409, f"position_in_use: {users_ref.count} user(s) atribuídos — remova/realoque antes")

        comps_ref = (
            client.table("sipoc_components")
            .select("id", count="exact")
            .eq("responsible_position_id", position_id)
            .limit(1)
            .execute()
        )
        if comps_ref.count and comps_ref.count > 0:
            raise HTTPException(409, f"position_in_use: {comps_ref.count} atividade(s) atribuída(s) — realoque antes")

        # OK pra deletar
        res = client.table("sipoc_positions").delete().eq("id", position_id).execute()
        if not res.data:
            raise HTTPException(404, "position_not_found_or_not_accessible")
        logger.info("delete_position position=%s by=%s", position_id, scope.get("user_id"))
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delete_position failed: {e}")
        raise HTTPException(500, str(e))


# -----------------------------------------------------------------------------
# App users — GET list + PATCH (role/position assignment)
# -----------------------------------------------------------------------------

@router.get("/api/companies/{company_id}/app_users")
@router.get("/companies/{company_id}/app_users")
async def list_company_users(request: Request, company_id: str):
    """Lista usuários do tenant. Admin only."""
    from src.api import supabase, get_authenticated_client, get_user_scope, require_role_not, validate_jwt_company_id

    if not supabase:
        return []

    scope = get_user_scope(request.state.token)
    require_role_not(scope, _ADMIN_BLOCKED_ROLES, "listar usuários do tenant")
    validate_jwt_company_id(request.state.token, company_id)

    try:
        client = get_authenticated_client(request.state.token)
        res = (
            client.table("app_users")
            .select("*")
            .eq("company_id", company_id)
            .order("created_at")
            .execute()
        )
        return [_user_to_dict(row) for row in (res.data or [])]
    except Exception as e:
        logger.error(f"list_company_users failed: {e}")
        raise HTTPException(500, str(e))


@router.patch("/api/app_users/{user_id}")
@router.patch("/app_users/{user_id}")
async def patch_app_user(request: Request, user_id: str, payload: PatchAppUserInput):
    """Edita user (role e/ou assigned_position_id). Admin only.

    Salvaguardas:
    - Role deve ser um dos valores válidos do CHECK constraint
    - Bloqueia auto-edição (sector_responsible não pode se promover)
    - Não permite remover último admin/platform_admin do tenant (futuro;
      por agora confia na decisão do operador)
    """
    from src.api import supabase, get_authenticated_client, get_user_scope, require_role_not

    if not supabase:
        raise HTTPException(503, "supabase_unavailable")

    scope = get_user_scope(request.state.token)
    require_role_not(scope, _ADMIN_BLOCKED_ROLES, "editar dados de usuários")

    update_data: Dict[str, Any] = {}
    if payload.role is not None:
        if payload.role not in _VALID_ROLES:
            raise HTTPException(400, f"invalid_role: deve ser um de {sorted(_VALID_ROLES)}")
        update_data["role"] = payload.role
    if payload.assigned_position_id is not None:
        # Empty string → SET NULL (desatribuir cargo)
        update_data["assigned_position_id"] = payload.assigned_position_id or None
    if payload.name is not None:
        update_data["name"] = payload.name

    if not update_data:
        raise HTTPException(400, "no_valid_fields")

    try:
        # PR7 hotfix: vectraclip.app_users só tem GRANT SELECT pra authenticated
        # (não INSERT/UPDATE/DELETE). RLS policies admin existem, mas GRANT base
        # faltando bloqueia o UPDATE antes do RLS rodar — "permission denied for
        # table app_users". Solução cirúrgica: usar service_role aqui (já que
        # require_role_not acima garante RBAC em app-layer).
        # Tenant safety: query com filtro explícito de company_id derivado do scope.
        # Alternativa estrutural (futuro PR): GRANT INSERT/UPDATE/DELETE pra
        # authenticated; aí podemos voltar pra get_authenticated_client.
        if not supabase:
            raise HTTPException(503, "supabase_unavailable")
        # Read pelo client authenticated (GRANT SELECT existe, RLS filtra)
        read_client = get_authenticated_client(request.state.token)
        cur = (
            read_client.table("app_users")
            .select("id, company_id, role")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if not cur.data:
            raise HTTPException(404, "user_not_found_or_not_accessible")
        # Tenant safety: confirma que user pertence ao company_id do scope
        if scope.get("company_id") and cur.data[0].get("company_id") != scope.get("company_id"):
            raise HTTPException(403, "cross_tenant_update_blocked")

        # Update via service_role (bypassa GRANT faltante)
        res = supabase.table("app_users").update(update_data).eq("id", user_id).execute()
        if not res.data:
            raise HTTPException(500, "update_returned_empty")

        logger.info(
            "patch_app_user user=%s fields=%s by=%s",
            user_id, list(update_data.keys()), scope.get("user_id"),
        )

        # G1.1 audit log (best-effort) — compliance trail de mudança de role/position
        from src.services.audit import audit_log
        prev_role = cur.data[0].get("role")
        new_role = update_data.get("role")
        action_name = "user.role_change" if (new_role and new_role != prev_role) else "user.update"
        audit_log(
            supabase,
            company_id=str(scope.get("company_id") or cur.data[0].get("company_id") or ""),
            actor_type="human",
            actor_id=str(scope.get("user_id") or "unknown"),
            action=action_name,
            target=f"user:{user_id}",
            payload={
                "fields_changed": list(update_data.keys()),
                "previous_role": prev_role,
                "new_role": new_role,
                "assigned_position_id": update_data.get("assigned_position_id"),
            },
        )
        return _user_to_dict(res.data[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"patch_app_user failed: {e}")
        raise HTTPException(500, str(e))
