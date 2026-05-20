"""Service que materializa SIPOC do chat Oracle em vectraclip.sipoc_* tables.

PR2.3 autopilot 2026-05-19 (F-006/F-008). Opção B: aceita estado completo no
body em vez de ler in-memory state vazio do Oracle chat.

Pipeline:
  1. Resolve company_id via JOIN sector_id → sipoc_sectors (defense vs leak)
  2. INSERT sipoc_processes (status='rascunho' default — FK guard PR2.1)
  3. Loop INSERT sipoc_components (5W2H normalizado via SSOT PR2.2; FK soft
     validation pra responsible_position_id + suggested_operation_type)
  4. Loop INSERT sipoc_raci (soft skip + warning em FK violation)
  5. Retorna SipocCommitResult com process_id + counts + warnings

Convenções:
- service_role client (cross-table validation precisa bypassar RLS)
- defense-in-depth: company_id explicitly checked against sector.company_id
- best-effort em FKs opcionais (responsible_position_id, suggested_operation_type):
  inserir NULL + warning em vez de bloquear. Marcelo cravou: dado parcial > dado
  bloqueado quando o usuário tá no meio do mapeamento.
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.services.sipoc_5w2h_keys import normalize_5w2h_keys

logger = logging.getLogger("SipocCommit")

# RAG corpus: bucket + Mnemos (curador). O SIPOC commitado é a FONTE do fluxo —
# vira exemplo no RAG pro Oracle ancorar mapeamentos futuros (auto-loop).
_RAG_BUCKET = os.getenv("RAG_STORAGE_BUCKET", "rag-documents")
_MNEMOS_AGENT_ID = "00000000-0000-0000-0000-000000000003"

# Rótulos de raia SIPOC pra serialização markdown (snake_case → humano).
_SIPOC_TYPE_HEADINGS = {
    "supplier": "Suppliers (Fornecedores)",
    "input": "Inputs (Entradas)",
    "activity": "Process (Atividades)",
    "output": "Outputs (Saídas)",
    "customer": "Customers (Clientes)",
}
_5W2H_LABELS = {
    "what": "O quê", "why": "Por quê", "who": "Quem", "where": "Onde",
    "when": "Quando", "how": "Como", "how_much": "Quanto",
}


def _serialize_sipoc_markdown(
    *, process_name: str, sector_name: str, description: Optional[str],
    components: List[Dict[str, Any]],
) -> str:
    """Serializa o SIPOC commitado em markdown pro corpus RAG. Agrupado por raia
    (S→I→P→O→C); atividades expõem 5W2H. É o texto que o Oracle vai recuperar
    como exemplo de processo parecido."""
    lines: List[str] = [
        f"# SIPOC: {process_name}",
        f"Setor: {sector_name}",
    ]
    if description and description.strip():
        lines.append(f"Objetivo/Descrição: {description.strip()}")
    lines.append("")

    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for comp in components:
        by_type.setdefault((comp.get("type") or "").strip(), []).append(comp)

    for ctype in ("supplier", "input", "activity", "output", "customer"):
        items = by_type.get(ctype) or []
        if not items:
            continue
        lines.append(f"## {_SIPOC_TYPE_HEADINGS.get(ctype, ctype)}")
        for comp in items:
            content = comp.get("content") or {}
            name = (comp.get("name") or content.get("name") or content.get("title") or "").strip()
            lines.append(f"- **{name or '(sem nome)'}**")
            if ctype == "activity":
                norm = normalize_5w2h_keys(content if isinstance(content, dict) else {})
                for k, label in _5W2H_LABELS.items():
                    v = norm.get(k)
                    if v:
                        lines.append(f"  - {label}: {v}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def ingest_sipoc_to_rag(
    supabase, *, company_id: str, process_id: str, process_name: str,
    sector_name: str, description: Optional[str], components: List[Dict[str, Any]],
) -> Optional[str]:
    """Best-effort: serializa o SIPOC commitado e enfileira ingestão no RAG
    (Storage → rag_documents → task rag-ingest pro Mnemos, 768-dim). NUNCA
    levanta — o commit não pode falhar por causa do RAG. Retorna warning ou None."""
    try:
        md = _serialize_sipoc_markdown(
            process_name=process_name, sector_name=sector_name,
            description=description, components=components,
        )
        md_bytes = md.encode("utf-8")
        sha256 = hashlib.sha256(md_bytes).hexdigest()
        # .txt/text-plain: o extractor do RAG não suporta markdown; markdown como
        # texto puro é suficiente pro embedder (chunk + 768-dim).
        filename = f"SIPOC — {process_name}.txt"
        storage_path = f"{company_id}/sipoc-{process_id}.txt"

        supabase.storage.from_(_RAG_BUCKET).upload(
            storage_path, md_bytes,
            file_options={"content-type": "text/plain", "upsert": "true"},
        )
        now = _now_iso()
        doc = supabase.table("rag_documents").insert({
            "company_id": company_id,
            "filename": filename,
            "storage_path": storage_path,
            "sha256": sha256,
            "mime_type": "text/plain",
            "size_bytes": len(md_bytes),
            "status": "uploaded",
            "uploaded_at": now,
            # metadata = sinal de recuperação pro Oracle (filtra/rankeia por setor)
            "metadata": {
                "source": "sipoc_committed",
                "sector": sector_name,
                "process_id": process_id,
            },
        }).execute()
        if not doc.data:
            return "rag ingest: rag_documents insert vazio (SIPOC não entrou no corpus)"
        document_id = doc.data[0]["id"]

        supabase.table("tasks").insert({
            "company_id": company_id,
            "title": f"RAG ingest (SIPOC): {process_name}",
            "description": f"Ingestão do SIPOC commitado '{process_name}' no corpus (auto-loop).",
            "operation_type": "rag-ingest",
            "status": "queued",
            "budget_limit": 0, "spent": 0, "cost_usd": 0,
            "executor_type": "auto",
            "assigned_to_agent_id": _MNEMOS_AGENT_ID,
            "input_json": {"document_id": document_id, "filename": filename, "sha256": sha256},
            "created_at": now, "updated_at": now,
        }).execute()
        logger.info("sipoc_commit: SIPOC %s enfileirado no RAG (doc=%s)", process_id, document_id)
        return None
    except Exception as exc:
        logger.warning("ingest_sipoc_to_rag falhou process=%s (commit segue ok): %s", process_id, exc)
        return f"rag ingest falhou (SIPOC commitado mas não entrou no corpus): {exc!s}"


class SipocCommitError(Exception):
    """Erro fatal do commit. HTTP 400/403/404 dependendo do code."""

    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_sector(supabase, sector_id: str, user_company_id: str) -> Dict[str, Any]:
    """SELECT sipoc_sectors + verifica que sector.company_id == user company.

    Defense-in-depth contra leak cross-tenant. RLS já protege via JOIN policy
    (vide pg_policy em sipoc_processes), mas aqui validamos explicitly antes
    de qualquer write porque service_role bypassa RLS.
    """
    res = (
        supabase.table("sipoc_sectors")
        .select("id, company_id, name")
        .eq("id", sector_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise SipocCommitError("sector_not_found", f"sector_id {sector_id} não existe", 404)
    sector = res.data[0]
    if str(sector["company_id"]) != str(user_company_id):
        # Não vazar que existe em outra company — log + 404 (mesmo erro de "não existe")
        logger.warning(
            "sipoc_commit cross-tenant attempt: sector=%s belongs_to=%s, user_company=%s",
            sector_id, sector["company_id"], user_company_id,
        )
        raise SipocCommitError("sector_not_found", f"sector_id {sector_id} não existe", 404)
    return sector


def _validate_position(supabase, position_id: Optional[str], company_id: str) -> Optional[str]:
    """Retorna position_id se válido pra company, None se inválido. Não raise."""
    if not position_id:
        return None
    try:
        res = (
            supabase.table("sipoc_positions")
            .select("id")
            .eq("id", position_id)
            .eq("company_id", company_id)
            .limit(1)
            .execute()
        )
        return position_id if res.data else None
    except Exception as exc:
        logger.warning("sipoc_commit position validate failed id=%s: %s", position_id, exc)
        return None


def _validate_operation_type(supabase, op_slug: Optional[str]) -> Optional[str]:
    """Retorna op_slug se válido em operation_types_catalog, None caso contrário."""
    if not op_slug:
        return None
    try:
        # operation_types_catalog tem PK 'id' (text slug). Confirma existência.
        res = (
            supabase.table("operation_types_catalog")
            .select("id")
            .eq("id", op_slug)
            .limit(1)
            .execute()
        )
        return op_slug if res.data else None
    except Exception as exc:
        logger.warning("sipoc_commit op_type validate failed id=%s: %s", op_slug, exc)
        return None


def _insert_process(
    supabase,
    *,
    sector_id: str,
    name: str,
    description: Optional[str],
    owner_position_id: Optional[str],
) -> str:
    """INSERT sipoc_processes, retorna id."""
    now = _now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "sector_id": sector_id,
        "name": name.strip()[:200],
        "description": (description or "").strip()[:2000] or None,
        "status": "rascunho",  # FK guard PR2.1
        "version": 1,
        "position_id": owner_position_id,
        "metadata": {"committed_at": now, "source": "oracle_chat_commit"},
        "created_at": now,
        "updated_at": now,
    }
    res = supabase.table("sipoc_processes").insert(row).execute()
    if not res.data:
        raise SipocCommitError("process_insert_failed", "INSERT sipoc_processes retornou vazio", 500)
    return str(res.data[0]["id"])


def _insert_components(
    supabase,
    *,
    process_id: str,
    company_id: str,
    components: List[Dict[str, Any]],
    warnings: List[str],
) -> List[Tuple[int, str, str]]:
    """INSERT sipoc_components em batch best-effort.

    Returns list of (index, component_id, type) — usado pelo raci pra resolver
    component_index → component_id.
    """
    inserted: List[Tuple[int, str, str]] = []
    now = _now_iso()

    for idx, comp in enumerate(components):
        comp_type = (comp.get("type") or "").strip()
        if not comp_type:
            warnings.append(f"components[{idx}]: type vazio, ignorado")
            continue

        raw_content = comp.get("content") or {}
        if not isinstance(raw_content, dict):
            raw_content = {}

        # Normaliza 5W2H via SSOT (snake_case canonical)
        normalized = normalize_5w2h_keys(raw_content)

        # Garante name no content (UI lê de content.name ou content.title)
        name = (comp.get("name") or normalized.get("name") or "").strip()
        if name:
            normalized["name"] = name

        # FKs opcionais com soft validation
        resp_pos = _validate_position(supabase, comp.get("responsible_position_id"), company_id)
        if comp.get("responsible_position_id") and not resp_pos:
            warnings.append(
                f"components[{idx}]: responsible_position_id inválido pra company, gravado como NULL"
            )

        op_type = _validate_operation_type(supabase, comp.get("suggested_operation_type"))
        if comp.get("suggested_operation_type") and not op_type:
            warnings.append(
                f"components[{idx}]: suggested_operation_type '{comp.get('suggested_operation_type')}' não existe em operation_types_catalog, gravado como NULL"
            )

        row = {
            "id": str(uuid.uuid4()),
            "process_id": process_id,
            "type": comp_type,  # FK sipoc_component_types.slug (PR2.1 guard)
            "content": normalized,
            "order": int(comp.get("order") or idx),
            "responsible_position_id": resp_pos,
            "automation_status": comp.get("automation_status") or "undefined",
            "suggested_operation_type": op_type,
            "validation_status": None,
            "metadata": {"committed_via": "oracle_chat_commit"},
            "created_at": now,
            "updated_at": now,
        }
        try:
            res = supabase.table("sipoc_components").insert(row).execute()
            if res.data:
                inserted.append((idx, str(res.data[0]["id"]), comp_type))
            else:
                warnings.append(f"components[{idx}]: INSERT vazio")
        except Exception as exc:
            # FK type pode bater se vier 'event' ou outro slug não-canônico
            warnings.append(f"components[{idx}]: INSERT falhou ({exc!s})")
            logger.exception("sipoc_commit component insert failed idx=%d", idx)

    return inserted


def _insert_raci(
    supabase,
    *,
    process_id: str,
    company_id: str,
    raci: List[Dict[str, Any]],
    inserted_components: List[Tuple[int, str, str]],
    warnings: List[str],
) -> int:
    """INSERT sipoc_raci best-effort. Retorna quantos foram inseridos."""
    if not raci:
        return 0

    by_index = {idx: comp_id for idx, comp_id, _t in inserted_components}
    count = 0
    now = _now_iso()

    for r_idx, r in enumerate(raci):
        comp_index = r.get("component_index")
        if comp_index is None or comp_index not in by_index:
            warnings.append(f"raci[{r_idx}]: component_index {comp_index} não casa com nenhum component inserido")
            continue

        position_id = _validate_position(supabase, r.get("position_id"), company_id)
        if not position_id:
            warnings.append(f"raci[{r_idx}]: position_id inválido pra company, pulado")
            continue

        role = (r.get("role") or "").strip().lower()
        if not role:
            warnings.append(f"raci[{r_idx}]: role vazio, pulado")
            continue

        row = {
            "id": str(uuid.uuid4()),
            "process_id": process_id,
            "component_id": by_index[comp_index],
            "position_id": position_id,
            "role": role,
            "created_at": now,
            "updated_at": now,
        }
        try:
            supabase.table("sipoc_raci").insert(row).execute()
            count += 1
        except Exception as exc:
            warnings.append(f"raci[{r_idx}]: INSERT falhou ({exc!s})")
            logger.exception("sipoc_commit raci insert failed idx=%d", r_idx)

    return count


def commit_sipoc(
    supabase,
    *,
    user_company_id: str,
    session_id: Optional[str],
    sector_id: str,
    process_name: str,
    process_description: Optional[str] = None,
    owner_position_id: Optional[str] = None,
    components: Optional[List[Dict[str, Any]]] = None,
    raci: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Materializa SIPOC do payload em sipoc_processes + components + raci.

    Args:
        supabase: client (service_role — bypassa RLS, valida company explicitly).
        user_company_id: vem de request.state.company_id (middleware).
        session_id: opcional, só pra audit metadata.
        sector_id: FK sipoc_sectors. Validado contra user_company_id.
        process_name: nome do processo SIPOC sendo materializado.
        process_description: opcional.
        owner_position_id: position_id do dono (opcional).
        components: lista de dicts {type, name, content (5W2H), order,
                    responsible_position_id?, suggested_operation_type?,
                    automation_status?}.
        raci: lista opcional de {component_index, position_id, role}.

    Returns:
        dict com process_id, components_created, raci_created, warnings.

    Raises:
        SipocCommitError: pra erros fatais (sector inválido, process insert
            falha). Endpoint mapeia pra HTTP status.
    """
    if not user_company_id:
        raise SipocCommitError("missing_company", "company_id ausente no request", 403)
    if not sector_id:
        raise SipocCommitError("missing_sector_id", "sector_id é obrigatório", 400)
    if not process_name or not process_name.strip():
        raise SipocCommitError("missing_process_name", "process_name é obrigatório", 400)

    warnings: List[str] = []

    # 1) Resolve sector + valida tenant
    sector = _resolve_sector(supabase, sector_id, user_company_id)
    company_id = sector["company_id"]

    # 2) Owner position validation (soft — NULL se inválido)
    validated_owner = _validate_position(supabase, owner_position_id, company_id)
    if owner_position_id and not validated_owner:
        warnings.append(
            f"owner_position_id '{owner_position_id}' inválido pra company, gravado como NULL"
        )

    # 3) INSERT process
    process_id = _insert_process(
        supabase,
        sector_id=sector_id,
        name=process_name,
        description=process_description,
        owner_position_id=validated_owner,
    )

    # 4) INSERT components batch
    inserted_components = _insert_components(
        supabase,
        process_id=process_id,
        company_id=company_id,
        components=components or [],
        warnings=warnings,
    )

    # 5) INSERT raci batch
    raci_created = _insert_raci(
        supabase,
        process_id=process_id,
        company_id=company_id,
        raci=raci or [],
        inserted_components=inserted_components,
        warnings=warnings,
    )

    # 6) Auto-loop: SIPOC commitado vira exemplo no RAG (a FONTE realimenta o
    # corpus). Best-effort — não falha o commit se o RAG estiver indisponível.
    rag_warning = ingest_sipoc_to_rag(
        supabase,
        company_id=str(company_id),
        process_id=process_id,
        process_name=process_name,
        sector_name=sector.get("name") or "",
        description=process_description,
        components=components or [],
    )
    if rag_warning:
        warnings.append(rag_warning)

    result = {
        "process_id": process_id,
        "components_created": len(inserted_components),
        "raci_created": raci_created,
        "warnings": warnings,
        "session_id": session_id,
    }
    logger.info(
        "sipoc_commit done process=%s sector=%s components=%d raci=%d warnings=%d",
        process_id, sector_id, len(inserted_components), raci_created, len(warnings),
    )
    return result
