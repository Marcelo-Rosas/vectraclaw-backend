"""
src.api_routes.gymsite — Rota pública para captação de leads do GymSite.

Endpoints:
- POST /api/gymsite/lead
"""
import uuid
import re
import logging
import asyncio
from typing import Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

logger = logging.getLogger("api.gymsite")
router = APIRouter(tags=["gymsite"])


class GymSiteLeadInput(BaseModel):
    nome: str
    cnpj: str
    email: EmailStr
    telefone: str


def clean_cnpj(cnpj: str) -> str:
    """Remove caracteres não numéricos do CNPJ."""
    return re.sub(r"[^0-9]", "", cnpj)


@router.post("/api/gymsite/lead", status_code=201)
async def create_gymsite_lead(lead: GymSiteLeadInput):
    """Captação de leads públicos do GymSite."""
    from src.api import supabase

    if not supabase:
        raise HTTPException(503, "Supabase connection is required")

    cnpj_clean = clean_cnpj(lead.cnpj)
    if len(cnpj_clean) != 14:
        raise HTTPException(422, "CNPJ inválido, deve conter 14 dígitos")

    access_code = str(uuid.uuid4())

    try:
        # Tenta inserir na tabela gymsite_leads
        lead_data = {
            "nome": lead.nome,
            "cnpj": cnpj_clean,
            "email": lead.email,
            "telefone": lead.telefone,
            "access_code": access_code,
            "status": "pending",
        }
        res = supabase.table("gymsite_leads").insert(lead_data).execute()
        if not res.data:
            raise HTTPException(500, "Falha ao gravar o lead")
    except Exception as e:
        error_msg = str(e)
        if "gymsite_leads_cnpj_unique" in error_msg or "duplicate key" in error_msg.lower():
            raise HTTPException(409, "CNPJ já cadastrado")
        logger.error(f"Erro ao inserir lead gymsite: {e}")
        raise HTTPException(500, "Erro interno ao processar o lead")

    # Cria a task para o Morpheus
    task_row: Dict[str, Any] = {
        "title": f"GymSite Lead - {lead.nome} ({cnpj_clean})",
        "description": lead.model_dump_json(),
        "operation_type": "gymsite_lead_intake",
        "status": "pending",
        "budget_limit": 50000,
        "input_json": lead.model_dump(),
        # O agente responsável será associado via trigger/routing_rules
    }
    
    try:
        task_res = supabase.table("tasks").insert(task_row).execute()
        if task_res.data:
            task_id = task_res.data[0]["id"]
            # Dispatch fire-and-forget
            from src.workflows import MorpheusDispatcher
            asyncio.create_task(MorpheusDispatcher().dispatch(task_id))
    except Exception as e:
        logger.warning(f"Aviso: Não foi possível despachar task para o lead {cnpj_clean}: {e}")

    return {
        "access_code": access_code,
        "message": "Lead recebido com sucesso"
    }
