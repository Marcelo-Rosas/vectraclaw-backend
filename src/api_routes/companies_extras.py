"""
src.api_routes.companies_extras — endpoints adicionais por company.

Reúne 2 endpoints novos por enquanto. Conforme outros forem extraídos
no futuro, podem migrar para cá ou subdividir mais.

Endpoints:
- POST /api/companies/{company_id}/qualify         dispara oracle-research
- POST /api/companies/{company_id}/lookup-cnpj     consulta BrasilAPI
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, Request

logger = logging.getLogger("api.companies_extras")
router = APIRouter(tags=["companies_extras"])


_QUALIFY_PROMPT_TEMPLATE = (
    "Pesquise o perfil operacional da empresa '{name}' no Brasil.\n"
    "Foco em:\n"
    "- Modais de transporte utilizados (rodoviário, aéreo, marítimo, ferroviário, intermodal)\n"
    "- Regiões e estados de atuação\n"
    "- Tipos de carga transportada (paletizada, granel, refrigerada, perigosa, etc.)\n"
    "- Porte da frota (própria e terceirizada)\n"
    "- Mercados e segmentos atendidos (varejo, indústria, e-commerce, saúde, etc.)\n"
    "- Diferenciais competitivos e posicionamento de mercado\n\n"
    "Retorne um relatório estruturado em PT-BR com seções claras e fontes citadas."
)


@router.post("/api/companies/{company_id}/qualify")
@router.post("/companies/{company_id}/qualify")
async def qualify_company(request: Request, company_id: str):
    """Dispara um oracle-research para construir o perfil operacional da empresa.

    O resultado é salvo em `companies.context_json` após conclusão pelo daemon
    (handler `save_to_company_context` no Oracle).
    """
    from src.api import supabase, validate_jwt_company_id, _ORACLE_AGENT_ID

    validate_jwt_company_id(request.state.token, company_id)

    if not supabase:
        raise HTTPException(status_code=503, detail="supabase_unavailable")

    try:
        company_res = (
            supabase.table("companies")
            .select("name")
            .eq("company_id", company_id)
            .maybe_single()
            .execute()
        )
        if not company_res.data:
            raise HTTPException(status_code=404, detail="company_not_found")
        company_name = company_res.data.get("name", company_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    prompt = _QUALIFY_PROMPT_TEMPLATE.format(name=company_name)
    task_row = {
        "company_id": company_id,
        "title": f"Qualificação operacional: {company_name}",
        "description": prompt,
        "operation_type": "oracle-research",
        "status": "queued",
        "budget_limit": 200_000,
        "executor_type": "auto",
        "assigned_to_agent_id": _ORACLE_AGENT_ID,
        "input_json": {
            "prompt": prompt,
            "company_name": company_name,
            "save_to_company_context": True,
        },
    }

    try:
        res = supabase.table("tasks").insert(task_row).execute()
        if not res.data:
            raise HTTPException(status_code=500, detail="task_creation_failed")
        task = res.data[0]
        logger.info("qualify_company task created id=%s company=%s", task.get("id"), company_id)
        return {"ok": True, "task_id": task.get("id"), "company_name": company_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"qualify_company failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/companies/{company_id}/lookup-cnpj")
@router.post("/companies/{company_id}/lookup-cnpj")
async def lookup_cnpj_endpoint(
    request: Request,
    company_id: str,
    body: Dict[str, Any] = Body(default_factory=dict),
):
    """Consulta cartão CNPJ na BrasilAPI e devolve shape normalizado.

    Body: `{"cnpj": "00000000000100"}` — dígitos puros ou com formatação.
    Retorna razão social, fantasia, endereço, CNAE, situação cadastral, QSA, capital.
    """
    from src.api import validate_jwt_company_id
    from src.services.cnpj_lookup import lookup_cnpj, CnpjLookupError

    validate_jwt_company_id(request.state.token, company_id)

    raw_cnpj = (body.get("cnpj") or "").strip() if isinstance(body, dict) else ""
    if not raw_cnpj:
        raise HTTPException(400, "cnpj_required")

    try:
        result = await lookup_cnpj(raw_cnpj)
    except CnpjLookupError as e:
        if e.code == CnpjLookupError.CODE_INVALID:
            raise HTTPException(400, str(e))
        if e.code == CnpjLookupError.CODE_NOT_FOUND:
            raise HTTPException(404, str(e))
        if e.code == CnpjLookupError.CODE_NETWORK:
            raise HTTPException(504, str(e))
        raise HTTPException(502, str(e))
    except Exception as e:
        logger.error(f"lookup_cnpj_endpoint failed: {e}")
        raise HTTPException(500, str(e))

    return result.model_dump()
