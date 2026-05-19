"""src.api_routes.sipoc_diagnose — Athena diagnose agregador por setor (PR9 Fase A).

Endpoint que roda diagnóstico estruturado de um setor SIPOC: agrega activities,
calcula coverage de 5W2H + RACI, identifica candidatos a automação e gaps,
e persiste em athena_recommendations.

Endpoint:
- POST /api/sipoc/diagnose/{sector_id}        diagnose_sector

Bloqueia sector_responsible/viewer (ação consultiva/strategic).

LLM enrichment via Gemini é **opcional** — endpoint funciona sem LLM (calcula
métricas estatísticas do snapshot do DB). Quando Gemini voltar (issue
project_gemini_403_permission_denied_2026-05-16), o helper `_enrich_with_llm`
pode ser ativado e popular o campo `llm_analysis`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

logger = logging.getLogger("api.sipoc_diagnose")
router = APIRouter(tags=["sipoc-diagnose"])

# Roles que NÃO podem disparar diagnóstico (ação consultiva).
_DIAGNOSE_BLOCKED_ROLES = ["sector_responsible", "viewer"]

# PR2.2 autopilot 2026-05-19: chaves + coverage agora vêm do SSOT
# (`src.services.sipoc_5w2h_keys`). A ordem aqui mantida via re-export pra
# compat com qualquer call-site que importe _5W2H_KEYS deste módulo.
from src.services.sipoc_5w2h_keys import CANONICAL_KEYS as _5W2H_KEYS, coverage_5w2h


def _activity_5w2h_coverage(content: Optional[Dict[str, Any]]) -> float:
    """Retorna 0.0–1.0 de cobertura 5W2H da activity.

    Delega ao SSOT `coverage_5w2h` que aceita `howMuch` legado mapeado pra
    `how_much` automaticamente — então documents jsonb antigos não zeram
    silenciosamente a coluna how_much.
    """
    if not isinstance(content, dict):
        return 0.0
    return coverage_5w2h(content)


def _activity_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    """Sumário enxuto da activity (pra retornar no diagnóstico)."""
    content = row.get("content") or {}
    if not isinstance(content, dict):
        content = {}
    return {
        "id": row["id"],
        "name": content.get("name") or content.get("title") or "(sem nome)",
        "coverage5w2h": round(_activity_5w2h_coverage(content), 2),
        "automationStatus": row.get("automation_status") or "undefined",
        "suggestedOperationType": row.get("suggested_operation_type"),
        "responsiblePositionId": row.get("responsible_position_id"),
    }


def _compute_diagnose(
    sector: Dict[str, Any],
    processes: List[Dict[str, Any]],
    activities: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Agregação estatística pura — sem LLM. Calcula KPIs + identifica gaps e
    candidatos a automação a partir do snapshot do DB.
    """
    total_activities = len(activities)
    total_processes = len(processes)

    if total_activities == 0:
        return {
            "sector": {"id": sector["id"], "name": sector.get("name")},
            "kpis": {
                "totalProcesses": total_processes,
                "totalActivities": 0,
                "coverage5w2hPct": 0.0,
                "responsibleCoveragePct": 0.0,
            },
            "automationStatusCounts": {"undefined": 0, "manual": 0, "hybrid": 0, "automated": 0},
            "operationTypeCounts": {},
            "automationCandidates": [],
            "gaps5w2h": [],
            "gapsResponsible": [],
            "hireSuggestions": [],
            "warning": "Setor sem activities mapeadas. Rode o SipocWizard ou importe templates do marketplace pra começar.",
        }

    coverage_sum = 0.0
    with_responsible = 0
    status_counts: Dict[str, int] = {"undefined": 0, "manual": 0, "hybrid": 0, "automated": 0}
    op_type_counts: Dict[str, int] = {}
    gaps_5w2h: List[Dict[str, Any]] = []
    gaps_responsible: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []

    for a in activities:
        content = a.get("content") or {}
        if not isinstance(content, dict):
            content = {}
        cov = _activity_5w2h_coverage(content)
        coverage_sum += cov
        status = a.get("automation_status") or "undefined"
        status_counts[status] = status_counts.get(status, 0) + 1

        op = a.get("suggested_operation_type")
        if op:
            op_type_counts[op] = op_type_counts.get(op, 0) + 1

        if a.get("responsible_position_id"):
            with_responsible += 1
        else:
            gaps_responsible.append(_activity_summary(a))

        if cov < 0.5:
            gaps_5w2h.append(_activity_summary(a))

        # Candidato a automação: 5W2H >= 70% + operation_type sugerido + status hybrid/automated
        if cov >= 0.7 and op and status in ("hybrid", "automated"):
            candidates.append(_activity_summary(a))

    coverage_pct = round((coverage_sum / total_activities) * 100, 1)
    responsible_pct = round((with_responsible / total_activities) * 100, 1)

    # Hire suggestions: agrupa por operation_type, ordena por count desc
    hire_suggestions = [
        {"operationType": op, "activitiesCount": cnt, "rationale": f"{cnt} atividade(s) sugerem o agent que executa '{op}'."}
        for op, cnt in sorted(op_type_counts.items(), key=lambda x: -x[1])
        if cnt >= 1
    ]

    return {
        "sector": {"id": sector["id"], "name": sector.get("name")},
        "kpis": {
            "totalProcesses": total_processes,
            "totalActivities": total_activities,
            "coverage5w2hPct": coverage_pct,
            "responsibleCoveragePct": responsible_pct,
        },
        "automationStatusCounts": status_counts,
        "operationTypeCounts": op_type_counts,
        "automationCandidates": candidates,
        "gaps5w2h": gaps_5w2h,
        "gapsResponsible": gaps_responsible,
        "hireSuggestions": hire_suggestions,
    }


def _build_rationale_text(diagnose: Dict[str, Any]) -> str:
    """Render textual do diagnóstico pra salvar em athena_recommendations.rationale."""
    k = diagnose["kpis"]
    parts = [
        f"Setor: {diagnose['sector'].get('name')}",
        f"Processos: {k['totalProcesses']} | Atividades: {k['totalActivities']}",
        f"Cobertura 5W2H: {k['coverage5w2hPct']}% | RACI: {k['responsibleCoveragePct']}%",
    ]
    status = diagnose["automationStatusCounts"]
    parts.append(
        f"Automação: {status['automated']} automated, {status['hybrid']} hybrid, "
        f"{status['manual']} manual, {status['undefined']} undefined"
    )
    if diagnose["automationCandidates"]:
        parts.append(f"{len(diagnose['automationCandidates'])} candidato(s) a automação imediata.")
    if diagnose["gaps5w2h"]:
        parts.append(f"{len(diagnose['gaps5w2h'])} atividade(s) com 5W2H incompleto (<50%).")
    if diagnose["gapsResponsible"]:
        parts.append(f"{len(diagnose['gapsResponsible'])} atividade(s) sem responsável atribuído.")
    if diagnose["hireSuggestions"]:
        top = diagnose["hireSuggestions"][:3]
        parts.append("Top sugestões de contratação: " + ", ".join(f"{s['operationType']} ({s['activitiesCount']}x)" for s in top))
    return " | ".join(parts)


@router.post("/api/sipoc/diagnose/{sector_id}")
@router.post("/sipoc/diagnose/{sector_id}")
async def diagnose_sector(request: Request, sector_id: str):
    """Roda diagnóstico agregado de um setor SIPOC.

    Retorna:
      {
        sector: {id, name},
        kpis: {totalProcesses, totalActivities, coverage5w2hPct, responsibleCoveragePct},
        automationStatusCounts: {undefined, manual, hybrid, automated},
        operationTypeCounts: {<slug>: <count>, ...},
        automationCandidates: [activity_summary, ...],
        gaps5w2h: [activity_summary, ...],
        gapsResponsible: [activity_summary, ...],
        hireSuggestions: [{operationType, activitiesCount, rationale}, ...],
        recommendation: {id, status, rationale}  # row persistida em athena_recommendations
      }

    Roles bloqueados: sector_responsible, viewer (diagnóstico é ação consultiva/admin).
    """
    from src.api import supabase, get_authenticated_client, get_user_scope, require_role_not

    if not supabase:
        raise HTTPException(503, "supabase_unavailable")

    scope = get_user_scope(request.state.token)
    require_role_not(scope, _DIAGNOSE_BLOCKED_ROLES, "disparar diagnóstico de setor")

    try:
        client = get_authenticated_client(request.state.token)

        # 1. Sector
        sres = (
            client.table("sipoc_sectors")
            .select("id, name, company_id")
            .eq("id", sector_id)
            .limit(1)
            .execute()
        )
        if not sres.data:
            raise HTTPException(404, "sector_not_found_or_not_accessible")
        sector = sres.data[0]
        company_id = sector["company_id"]

        # 2. Processes do sector
        pres = (
            client.table("sipoc_processes")
            .select("id, name")
            .eq("sector_id", sector_id)
            .execute()
        )
        processes = pres.data or []
        process_ids = [p["id"] for p in processes]

        # 3. Activities (sipoc_components type=activity) dos processes
        activities: List[Dict[str, Any]] = []
        if process_ids:
            ares = (
                client.table("sipoc_components")
                .select("id, process_id, type, content, automation_status, suggested_operation_type, responsible_position_id")
                .in_("process_id", process_ids)
                .eq("type", "activity")
                .execute()
            )
            activities = ares.data or []

        # 4. Agregação
        diagnose = _compute_diagnose(sector, processes, activities)

        # 5. Persiste em athena_recommendations (kind=diagnose_gap)
        rationale = _build_rationale_text(diagnose)
        rec_row = {
            "company_id": company_id,
            "kind": "diagnose_gap",
            "title": f"Diagnóstico SIPOC — {sector.get('name')}",
            "rationale": rationale,
            "proposed_changes_json": diagnose,
            "citations": [],
            "confidence": 0.8,  # snapshot-based (sem LLM), high confidence em metrics
            "estimated_effort": "M",  # CHECK aceita S|M|L|XL
            "status": "pending",
        }
        # service_role pra evitar problemas de GRANT em UPDATE/INSERT (mesmo padrão do hotfix PR7)
        ires = supabase.table("athena_recommendations").insert(rec_row).execute()
        rec_id = ires.data[0]["id"] if ires.data else None

        diagnose["recommendation"] = {
            "id": rec_id,
            "status": "pending",
            "rationale": rationale,
        }

        logger.info(
            "diagnose_sector sector=%s processes=%d activities=%d coverage5w2h=%.1f%% recommendation=%s",
            sector_id, len(processes), len(activities),
            diagnose["kpis"]["coverage5w2hPct"], rec_id,
        )
        return diagnose
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"diagnose_sector failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


def _compute_diagnose_for_pdf(sector_id: str, client) -> Dict[str, Any]:
    """Mesma agregação do endpoint POST, mas SEM persistir em
    athena_recommendations (chamado pelo endpoint de PDF — leitura pura).
    """
    sres = (
        client.table("sipoc_sectors")
        .select("id, name, company_id")
        .eq("id", sector_id)
        .limit(1)
        .execute()
    )
    if not sres.data:
        raise HTTPException(404, "sector_not_found_or_not_accessible")
    sector = sres.data[0]

    pres = (
        client.table("sipoc_processes")
        .select("id, name")
        .eq("sector_id", sector_id)
        .execute()
    )
    processes = pres.data or []
    process_ids = [p["id"] for p in processes]

    activities: List[Dict[str, Any]] = []
    if process_ids:
        ares = (
            client.table("sipoc_components")
            .select("id, process_id, type, content, automation_status, suggested_operation_type, responsible_position_id")
            .in_("process_id", process_ids)
            .eq("type", "activity")
            .execute()
        )
        activities = ares.data or []

    diagnose = _compute_diagnose(sector, processes, activities)
    diagnose["recommendation"] = {
        "id": None,
        "status": "pdf_export",
        "rationale": _build_rationale_text(diagnose),
    }
    return diagnose


@router.get("/api/sipoc/diagnose/{sector_id}/pdf")
@router.get("/sipoc/diagnose/{sector_id}/pdf")
async def diagnose_sector_pdf(request: Request, sector_id: str):
    """Gera PDF executivo do diagnóstico de um setor (sem persistir).

    Usa o mesmo cálculo do POST mas:
    - NÃO insere row em athena_recommendations (read-only)
    - Retorna binário application/pdf com filename sugestivo

    Útil pra "Exportar diagnóstico" no SipocReport sem poluir o painel
    Athena com uma row a cada export.
    """
    from src.api import supabase, get_authenticated_client, get_user_scope, require_role_not
    from src.services.sipoc_diagnose_pdf import render_diagnose_pdf
    from datetime import datetime as _dt

    if not supabase:
        raise HTTPException(503, "supabase_unavailable")

    scope = get_user_scope(request.state.token)
    require_role_not(scope, _DIAGNOSE_BLOCKED_ROLES, "exportar PDF do diagnóstico")

    try:
        client = get_authenticated_client(request.state.token)
        diagnose = _compute_diagnose_for_pdf(sector_id, client)
        pdf_bytes = render_diagnose_pdf(diagnose)

        # Slug do nome pro filename
        sector_name = diagnose["sector"].get("name") or "setor"
        safe_name = "".join(c if c.isalnum() else "_" for c in sector_name).strip("_") or "setor"
        date_str = _dt.now().strftime("%Y%m%d")
        filename = f"diagnostico_sipoc_{safe_name}_{date_str}.pdf"

        logger.info(
            "diagnose_sector_pdf sector=%s bytes=%d filename=%s",
            sector_id, len(pdf_bytes), filename,
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                "Content-Length": str(len(pdf_bytes)),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"diagnose_sector_pdf failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))
