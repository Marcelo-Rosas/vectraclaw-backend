"""
Athena — 9º daemon do VectraClaw.
Project Management Coach baseado em PMBOK / Kim Heldman.

VEC-388 PR1: skeleton com stubs. Handlers reais entram nos PRs 3-5:
  - PR3: athena-classify (real)
  - PR4: athena-charter + athena-stakeholder-map (real)
  - PR5: athena-risk-register + athena-evm (real)

VEC-389 (depois): athena-audit + athena-recommend
VEC-390 (depois): athena-prioritize
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger("Athena")

# ─────────────────────────────────────────────────────────────────────────────
# Identidade do agente
# ─────────────────────────────────────────────────────────────────────────────
# AGENT_ID fixo — substitui FK em tasks.assigned_to_agent_id.
# Gerado uma única vez via `python -c "import uuid; print(uuid.uuid4())"`.
# NUNCA alterar — quebraria a FK em milhares de tasks futuras.
ATHENA_AGENT_ID = "ad4fc1ad-7e2b-4bb6-8bc3-69016ea18b2d"

# Modelo Gemini default para Athena (handlers reais nos PRs 3-5 podem override por handler)
ATHENA_DEFAULT_MODEL = "gemini-2.5-pro"

# Versão dos schemas Pydantic de output (para validation.schema_version)
ATHENA_SCHEMA_VERSION = "v4.1"


# ─────────────────────────────────────────────────────────────────────────────
# Tabela de custos Gemini 2.5 Pro
# Fonte: https://ai.google.dev/gemini-api/docs/pricing
# Confirmar antes de cada commit em produção (preços mudam)
# ─────────────────────────────────────────────────────────────────────────────
_GEMINI_PRO_COST_PER_TOKEN = {
    "input": 1.25 / 1_000_000,
    "output": 10.00 / 1_000_000,
}


def _calc_cost(tokens: Dict[str, int]) -> float:
    """Calcula custo USD a partir do dict de tokens retornado pelo gemini_client."""
    return (
        tokens.get("input", 0) * _GEMINI_PRO_COST_PER_TOKEN["input"]
        + tokens.get("output", 0) * _GEMINI_PRO_COST_PER_TOKEN["output"]
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stub helper: padrão de output para handlers não-implementados
# Mantém o contrato I/T/O do PMBOK desde o PR1 — facilita debug do dispatch
# mesmo antes dos handlers reais existirem.
# ─────────────────────────────────────────────────────────────────────────────
def _stub_output(operation_type: str, task_id: str = "") -> Dict[str, Any]:
    """Output padrão de stub. Mantém schema I/T/O esperado pelo PMBOK."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "output_json": {
            "handler_name": operation_type,
            "execution_id": task_id,
            "execution_started_at": now,
            "execution_completed_at": now,
            "inputs_used": {"_stub": True},
            "tools_techniques_applied": ["expert_judgment"],
            "outputs": {
                "status": "not_implemented",
                "message": (
                    f"Handler '{operation_type}' será implementado em PR futuro. "
                    f"Veja VEC-388 (PRs 3-5) e VEC-389/VEC-390."
                ),
            },
            "validation": {
                "schema_version": ATHENA_SCHEMA_VERSION,
                "all_required_inputs_present": False,
                "confidence": 0.0,
                "warnings": ["handler em stub — implementação pendente"],
                "needs_human_review": False,
            },
            "citations": [],
            "metadata": {"tokens": {"input": 0, "output": 0, "total": 0}},
        },
        "cost_usd": 0.0,
        "status_override": "done",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stub handlers — todos retornam not_implemented no PR1
# Cada um vai ganhar implementação real nos PRs subsequentes
# ─────────────────────────────────────────────────────────────────────────────

async def _handle_classify_stub(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """PR3: classifica goal como project vs operation + SMART breakdown + business_case."""
    return _stub_output("athena-classify", input_data.get("_task_id", ""))


async def _handle_charter_stub(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """PR4: gera Project Charter com 5 elementos PMBOK + APO + selection_model."""
    return _stub_output("athena-charter", input_data.get("_task_id", ""))


async def _handle_stakeholder_map_stub(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """PR4: matriz Power × Interest + team_health_assessment + communication_plan."""
    return _stub_output("athena-stakeholder-map", input_data.get("_task_id", ""))


async def _handle_risk_register_stub(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """PR5: Risk Register com escala PMBOK 5ª (0.1-0.9 × 0.05-0.80) + secondary/residual/transfer."""
    return _stub_output("athena-risk-register", input_data.get("_task_id", ""))


async def _handle_evm_stub(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """PR5: EVM (Python calcula, Gemini narra) com VAC + TCPI + golden numbers."""
    return _stub_output("athena-evm", input_data.get("_task_id", ""))


async def _handle_audit_stub(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """VEC-389 PR2: audita quadro de agentes (read-only, gera relatório)."""
    return _stub_output("athena-audit", input_data.get("_task_id", ""))


async def _handle_recommend_stub(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """VEC-389 PR3: cria athena_recommendations status=pending (sem auto-apply)."""
    return _stub_output("athena-recommend", input_data.get("_task_id", ""))


async def _handle_rag_ingest(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """VEC-394 (real): ingest de PDFs Heldman/PMBOK em athena_documents/athena_chunks.

    Espelha o contrato Mnemos: lê `document_id` de input_data, baixa do
    Storage bucket `athena-rag`, extrai → chunka → embeda → bulk insert.

    Args:
        prompt: ignorado (handler é dirigido por document_id, não por prompt).
        input_data: dict com `_supabase`, `_task_id`, `document_id`, etc.

    Returns:
        Dict no contrato I/T/O PMBOK com `outputs.chunks_indexed`, mapeado
        do retorno do `entrypoint` em `src/services/athena_rag.py`.
    """
    from src.services.athena_rag import entrypoint as _ingest_entry

    supabase = input_data.get("_supabase")
    task = {
        "id": input_data.get("_task_id", ""),
        "company_id": input_data.get("_company_id"),
        "input_json": {
            "document_id": input_data.get("document_id"),
            "filename": input_data.get("filename"),
            "sha256": input_data.get("sha256"),
        },
    }
    result = _ingest_entry(task, supabase)

    now = datetime.now(timezone.utc).isoformat()
    if result.get("status") == "done":
        chunks_indexed = result.get("chunks_inserted", 0)
        outputs = {
            "status": "indexed",
            "chunks_indexed": chunks_indexed,
            "page_count": result.get("page_count"),
            "document_id": result.get("document_id"),
        }
        validation = {
            "schema_version": ATHENA_SCHEMA_VERSION,
            "all_required_inputs_present": True,
            "confidence": 1.0 if chunks_indexed > 0 else 0.5,
            "warnings": [] if chunks_indexed > 0 else ["documento vazio — 0 chunks"],
            "needs_human_review": False,
        }
        status_override = "done"
    else:
        outputs = {
            "status": "error",
            "code": "ingest_failed",
            "message": result.get("error", "unknown error"),
            "document_id": result.get("document_id"),
        }
        validation = {
            "schema_version": ATHENA_SCHEMA_VERSION,
            "all_required_inputs_present": bool(input_data.get("document_id")),
            "confidence": 0.0,
            "warnings": [],
            "needs_human_review": True,
        }
        status_override = "blocked"

    return {
        "output_json": {
            "handler_name": "athena-rag-ingest",
            "execution_id": task["id"],
            "execution_started_at": now,
            "execution_completed_at": now,
            "inputs_used": {"document_id": input_data.get("document_id")},
            "tools_techniques_applied": ["expert_judgment", "document_extraction", "chunking", "embedding"],
            "outputs": outputs,
            "validation": validation,
            "citations": [],
            "metadata": {"tokens": {"input": 0, "output": 0, "total": 0}},
        },
        "cost_usd": 0.0,
        "status_override": status_override,
    }


async def _handle_prioritize_stub(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """VEC-390: ranking ponderado entre múltiplos goals usando weighted_scoring."""
    return _stub_output("athena-prioritize", input_data.get("_task_id", ""))


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch table — mapeia operation_type → handler
# Todos stubs no PR1; substituídos por handlers reais nos PRs futuros.
# Roteamento real do daemon (src/agent_daemon.py) usa apenas o prefixo
# "athena-", então adicionar novo operation_type aqui é suficiente para
# o despacho funcionar — não precisa tocar em agent_daemon.py de novo.
# ─────────────────────────────────────────────────────────────────────────────
_SPECIALTY_DISPATCH = {
    # VEC-388 (Pipeline PMI — mandato 1)
    "athena-classify":         _handle_classify_stub,
    "athena-charter":          _handle_charter_stub,
    "athena-stakeholder-map":  _handle_stakeholder_map_stub,
    "athena-risk-register":    _handle_risk_register_stub,
    "athena-evm":              _handle_evm_stub,
    "athena-rag-ingest":       _handle_rag_ingest,
    # VEC-389 (Coverage Manager — mandato 2)
    "athena-audit":            _handle_audit_stub,
    "athena-recommend":        _handle_recommend_stub,
    # VEC-390 (Prioritizer — mandato 3)
    "athena-prioritize":       _handle_prioritize_stub,
}


# ─────────────────────────────────────────────────────────────────────────────
# Entry point para o agent_daemon
# Contrato igual ao Oracle (src/agents/oracle.py:855):
#   - Recebe task (dict) + supabase client
#   - Retorna {output_json, cost_usd, status_override}
# ─────────────────────────────────────────────────────────────────────────────
async def execute_specialty(task: Dict[str, Any], supabase: Any) -> Dict[str, Any]:
    """
    Entry point para o daemon. Despacha operation_type para o handler correto.

    Contrato (espelha src/agents/oracle.py:855):
        Args:
            task: dict com operation_type, input_json, company_id, id, etc.
            supabase: cliente Supabase (pode ser None em testes)
        Returns:
            {
                "output_json": dict,       # estrutura I/T/O do handler
                "cost_usd": float,         # custo calculado
                "status_override": str|None,  # "done" | "blocked" | None (valores válidos do CHECK constraint tasks_status_check)
            }
    """
    op_type = task.get("operation_type", "")
    input_data: Dict[str, Any] = task.get("input_json") or {}
    prompt = (
        input_data.get("prompt")
        or task.get("description")
        or task.get("title")
        or ""
    ).strip()

    logger.info(
        "athena.execute_specialty op=%s task=%s company=%s",
        op_type, task.get("id"), task.get("company_id"),
    )

    handler = _SPECIALTY_DISPATCH.get(op_type)
    if handler is None:
        logger.warning("athena.execute_specialty unknown op_type=%s", op_type)
        return {
            "output_json": {
                "handler_name": op_type,
                "execution_id": task.get("id", ""),
                "outputs": {
                    "status": "error",
                    "code": "unknown_operation_type",
                    "message": (
                        f"operation_type '{op_type}' não reconhecido pela Athena. "
                        f"Esperado um de: {sorted(_SPECIALTY_DISPATCH.keys())}"
                    ),
                },
                "validation": {
                    "schema_version": ATHENA_SCHEMA_VERSION,
                    "all_required_inputs_present": False,
                    "confidence": 0.0,
                    "warnings": [],
                    "needs_human_review": False,
                },
                "citations": [],
            },
            "cost_usd": 0.0,
            "status_override": "blocked",
        }

    # Enriquecimento do input com handles que os handlers reais (PR3+) vão precisar
    enriched_input = {
        **input_data,
        "_supabase": supabase,
        "_company_id": task.get("company_id"),
        "_task_id": task.get("id"),
        "_agent_id": ATHENA_AGENT_ID,
    }

    try:
        result = await handler(prompt, enriched_input)
    except Exception as exc:
        logger.error(
            "athena.execute_specialty handler error op=%s task=%s: %s",
            op_type, task.get("id"), exc, exc_info=True,
        )
        return {
            "output_json": {
                "handler_name": op_type,
                "execution_id": task.get("id", ""),
                "outputs": {
                    "status": "error",
                    "code": "execution_error",
                    "message": str(exc),
                },
                "validation": {
                    "schema_version": ATHENA_SCHEMA_VERSION,
                    "all_required_inputs_present": False,
                    "confidence": 0.0,
                    "warnings": [],
                    "needs_human_review": True,
                },
                "citations": [],
            },
            "cost_usd": 0.0,
            "status_override": "blocked",
        }

    # Log de sucesso (mesmo padrão do Oracle)
    output_json = result.get("output_json", {})
    tokens = (output_json.get("metadata") or {}).get("tokens", {}) or \
             (result.get("metadata") or {}).get("tokens", {})
    cost_usd = result.get("cost_usd")
    if cost_usd is None:
        cost_usd = _calc_cost(tokens)

    logger.info(
        "athena.execute_specialty done op=%s task=%s tokens=%s cost=%.6f",
        op_type, task.get("id"), tokens.get("total", 0), cost_usd,
    )

    return {
        "output_json": output_json,
        "cost_usd": cost_usd,
        "status_override": result.get("status_override", "done"),
    }
