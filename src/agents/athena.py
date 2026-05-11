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

# Modelo Gemini default para Athena.
# VEC-399 smoke 2026-05-11: gemini-2.5-pro EXIGE thinking_config.thinking_budget>0
# e o wrapper gemini_client.generate força thinking_budget=0 ("custo mínimo em chat"),
# causando "Budget 0 is invalid. This model only works in thinking mode" no handler.
# Workaround: usar gemini-2.5-flash (aceita budget=0) para todos handlers Athena por
# enquanto. Fix robusto (parametrizar thinking_budget em gemini_client.generate)
# fica para PR follow-up — afeta TODOS os agents, escopo separado.
ATHENA_DEFAULT_MODEL = "gemini-2.5-flash"

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

async def _handle_classify(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """VEC-399 (real): classifica goal como project vs operation + SMART breakdown
    + business_case_strength + organizational_calibration via Gemini.

    Pipeline:
      1. SELECT goal de vectraclip.goals (lê title/metric/target/current/parent)
      2. SELECT companies.context_json (contexto organizacional)
      3. RAG athena_chunks: top-4 chunks Heldman sobre 'project vs operation'
      4. Gemini structured output (response_mime_type=application/json)
      5. Pydantic validation via athena_schemas.ClassifyOutput
      6. UPDATE goals SET kind/confidence/business_case_strength/pmoia_metadata/
         classified_at (SOMENTE essas 5 colunas — title/metric/target imutáveis)
      7. Retorna envelope I/T/O PMBOK

    Sem encadeamento automático para athena-charter (PR4) — handler real ainda
    não existe; field `next_handler` no output sinaliza intenção apenas.

    Args:
        prompt: ignorado (handler dirigido por goal_id, não por prompt livre).
        input_data: dict com `_supabase`, `_task_id`, `_company_id`, `goal_id`.
    """
    from datetime import datetime as _dt, timezone as _tz
    import json as _json

    from src.agents.athena_schemas import ClassifyOutput, ValidationBlock
    from src.services.gemini_client import generate as gemini_generate

    started_at = _dt.now(_tz.utc).isoformat()
    supabase = input_data.get("_supabase")
    task_id = input_data.get("_task_id", "")
    company_id = input_data.get("_company_id")
    goal_id = input_data.get("goal_id")

    # ─── Pré-validação de inputs obrigatórios ─────────────────────────────
    if not goal_id:
        return _classify_error_output(
            task_id, started_at, "missing_goal_id",
            "input_json.goal_id é obrigatório para athena-classify",
        )
    if supabase is None:
        return _classify_error_output(
            task_id, started_at, "missing_supabase",
            "Cliente Supabase não disponível (esperado via input_data['_supabase'])",
        )

    # ─── 1) Carrega goal ──────────────────────────────────────────────────
    try:
        goal_res = (
            supabase.table("goals")
            .select("id,company_id,parent_goal_id,title,metric,target,current,kind,confidence,business_case_strength")
            .eq("id", goal_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.exception("athena-classify select goal failed task=%s goal=%s", task_id, goal_id)
        return _classify_error_output(
            task_id, started_at, "goal_select_failed", str(exc),
        )
    if not goal_res.data:
        return _classify_error_output(
            task_id, started_at, "goal_not_found",
            f"vectraclip.goals not found: id={goal_id}",
        )
    goal = goal_res.data[0]
    # Defense-in-depth: confirma multi-tenancy (handler não classifica goal de outra company)
    if company_id and str(goal.get("company_id")) != str(company_id):
        return _classify_error_output(
            task_id, started_at, "company_mismatch",
            f"goal.company_id ({goal.get('company_id')}) != task.company_id ({company_id})",
        )

    # ─── 2) Contexto organizacional ───────────────────────────────────────
    company_context = _get_company_context(supabase, goal.get("company_id"))

    # ─── 3) RAG corpus Athena (best-effort, degrada graceful se vazio) ────
    rag_chunks: list = []
    rag_citations: list = []
    try:
        from src.services.athena_rag import query_top_k as _athena_query
        rag_results = await _athena_query(
            "PMBOK distinguir projeto temporário de operação contínua. SMART. business case.",
            company_id=goal.get("company_id"),
            k=4,
            min_score=0.3,
            supabase_client=supabase,
        )
        for r in rag_results:
            rag_chunks.append(
                f"[chunk {r.chunk_index} | score {r.score:.2f} | {r.document_filename or '?'}]\n{r.content[:1500]}"
            )
            rag_citations.append({
                "chunk_id": r.id,
                "page": r.page_number,
                "source": r.document_filename,
                "topic": "PMBOK classify",
            })
    except Exception as exc:
        # RAG falha não bloqueia classificação — apenas reduz qualidade.
        logger.warning("athena-classify RAG indisponível (degradando): %s", exc)

    # ─── 4) Gemini structured output ──────────────────────────────────────
    system_instruction = _CLASSIFY_SYSTEM_PROMPT
    user_prompt = _build_classify_prompt(goal, company_context, rag_chunks)

    try:
        text, metadata = await gemini_generate(
            ATHENA_DEFAULT_MODEL,
            user_prompt,
            system_instruction=system_instruction,
            response_mime_type="application/json",
        )
    except Exception as exc:
        logger.exception("athena-classify gemini call failed task=%s", task_id)
        return _classify_error_output(
            task_id, started_at, "gemini_call_failed", str(exc),
        )

    try:
        gemini_payload = _json.loads(text)
    except Exception as exc:
        return _classify_error_output(
            task_id, started_at, "gemini_invalid_json",
            f"Gemini não retornou JSON válido: {exc}. Raw[:200]={text[:200]!r}",
        )

    # ─── 5) Monta envelope I/T/O + Pydantic validation ────────────────────
    completed_at = _dt.now(_tz.utc).isoformat()
    tools_applied = ["expert_judgment", "smart_filter", "business_case_validation"]
    if rag_chunks:
        tools_applied.append("rag_retrieval")

    envelope = {
        "handler_name": "athena-classify",
        "execution_id": task_id,
        "execution_started_at": started_at,
        "execution_completed_at": completed_at,
        "inputs_used": {
            "goal_id": goal_id,
            "goal_title": goal.get("title"),
            "company_context_keys": list((company_context or {}).keys()),
            "rag_chunks_used": len(rag_chunks),
        },
        "tools_techniques_applied": tools_applied,
        "outputs": gemini_payload,
        "validation": ValidationBlock(
            all_required_inputs_present=True,
            confidence=float(gemini_payload.get("confidence", 0.0)),
            warnings=[],
            needs_human_review=False,
        ).model_dump(),
        "citations": rag_citations,
    }

    try:
        validated = ClassifyOutput.model_validate(envelope)
    except Exception as exc:
        logger.exception("athena-classify pydantic validation failed task=%s", task_id)
        return _classify_error_output(
            task_id, started_at, "pydantic_validation_failed",
            f"{exc}. envelope.outputs={envelope.get('outputs')}",
        )

    outputs_validated = validated.outputs

    # ─── 6) Persiste em goals (SÓ nas novas colunas; nunca title/metric/target) ─
    try:
        update_payload = {
            "kind": outputs_validated.kind,
            "confidence": float(outputs_validated.confidence),
            "business_case_strength": outputs_validated.business_case_strength,
            "pmoia_metadata": {
                "smart_breakdown": outputs_validated.smart_breakdown.model_dump(),
                "classification_rationale": outputs_validated.classification_rationale,
                "organizational_calibration": outputs_validated.organizational_calibration,
                "next_handler_suggested": outputs_validated.next_handler,
                "classified_by_task_id": task_id,
            },
            "classified_at": completed_at,
        }
        supabase.table("goals").update(update_payload).eq("id", goal_id).execute()
    except Exception as exc:
        # UPDATE falhou — não bloqueia retorno do handler (output_json registra),
        # mas marca needs_human_review para a UI alertar.
        logger.error("athena-classify goals UPDATE failed (non-fatal): %s", exc)
        envelope["validation"]["warnings"].append(f"goals_update_failed: {exc}")
        envelope["validation"]["needs_human_review"] = True

    # ─── 7) Cost (Gemini default rate; cota real virá em refator futuro) ──
    tokens = {
        "input": int(metadata.get("input_token_count") or 0),
        "output": int(metadata.get("output_token_count") or 0),
    }
    tokens["total"] = tokens["input"] + tokens["output"]
    envelope["metadata"] = {"tokens": tokens}
    cost_usd = _calc_cost(tokens)

    logger.info(
        "athena-classify done task=%s goal=%s kind=%s confidence=%.2f case=%s tokens=%d cost=%.6f",
        task_id, goal_id, outputs_validated.kind, outputs_validated.confidence,
        outputs_validated.business_case_strength, tokens["total"], cost_usd,
    )

    return {
        "output_json": envelope,
        "cost_usd": cost_usd,
        "status_override": "done",
    }


def _classify_error_output(
    task_id: str, started_at: str, code: str, message: str,
) -> Dict[str, Any]:
    """Envelope I/T/O minimal para erros do handler classify. status=blocked."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "output_json": {
            "handler_name": "athena-classify",
            "execution_id": task_id,
            "execution_started_at": started_at,
            "execution_completed_at": now,
            "inputs_used": {},
            "tools_techniques_applied": ["expert_judgment"],
            "outputs": {
                "status": "error",
                "code": code,
                "message": message,
            },
            "validation": {
                "schema_version": ATHENA_SCHEMA_VERSION,
                "all_required_inputs_present": False,
                "confidence": 0.0,
                "warnings": [code],
                "needs_human_review": True,
            },
            "citations": [],
            "metadata": {"tokens": {"input": 0, "output": 0, "total": 0}},
        },
        "cost_usd": 0.0,
        "status_override": "blocked",
    }


def _get_company_context(supabase: Any, company_id: Any) -> Dict[str, Any]:
    """Best-effort: lê companies.context_json para enriquecer o prompt do classify.
    Retorna {} se row não existir ou erro — degrada graceful."""
    if not company_id or supabase is None:
        return {}
    try:
        res = (
            supabase.table("companies")
            .select("context_json")
            .eq("company_id", company_id)
            .limit(1)
            .execute()
        )
        if res.data:
            ctx = res.data[0].get("context_json") or {}
            return ctx if isinstance(ctx, dict) else {}
    except Exception as exc:
        logger.warning("athena-classify company_context lookup failed: %s", exc)
    return {}


_CLASSIFY_SYSTEM_PROMPT = """Você é Athena, PMOia da Vectra Cargo, especialista em PMBOK 5ª edição (Kim Heldman).

Sua tarefa: classificar uma meta organizacional como PROJETO (esforço temporário com começo, meio e fim definidos, produto único) ou OPERAÇÃO (atividade recorrente, contínua, sem entrega única). Quando a evidência é ambígua, retornar 'undecided' e explicar por quê.

REGRAS HARD (não negociáveis):
1. Se SMART está incompleto (faltam specific/measurable/achievable/relevant/timebound), confidence ≤ 0.6 e kind=undecided.
2. Se business_case_strength=absent E kind=project, confidence ≤ 0.5 (sem business case não se aprova projeto pela rubrica PMBOK).
3. classification_rationale tem no mínimo 50 caracteres e cita pelo menos UM critério PMBOK (temporariedade, unicidade, esforço progressivo, restrição tripla, etc).
4. tools_techniques_applied no JSON de saída SEMPRE inclui 'expert_judgment'. Quando há RAG_CHUNKS, inclua também 'rag_retrieval'.

FORMATO DE SAÍDA — apenas JSON, sem markdown, exatamente o schema:
{
  "kind": "project" | "operation" | "undecided",
  "confidence": <float 0..1>,
  "classification_rationale": "<min 50 chars, cita critério PMBOK>",
  "smart_breakdown": {
    "specific": "<min 20 chars>",
    "measurable": "<min 10 chars>",
    "achievable": "<min 10 chars>",
    "relevant": "<min 10 chars>",
    "timebound": "<min 10 chars>"
  },
  "business_case_strength": "strong" | "adequate" | "weak" | "absent",
  "organizational_calibration": {
    "context_used": "<resumo curto do contexto da company aplicado>",
    "fit_score": <float 0..1>,
    "notes": "<observações sobre alinhamento estratégico>"
  },
  "next_handler": "athena-charter" | null
}

Defina next_handler='athena-charter' apenas quando kind=project E confidence ≥ 0.7 E business_case_strength em (strong, adequate). Caso contrário, null."""


def _build_classify_prompt(
    goal: Dict[str, Any],
    company_context: Dict[str, Any],
    rag_chunks: list,
) -> str:
    """Renderiza o prompt do user para o athena-classify."""
    import json as _json

    rag_block = (
        "\n\n--- TRECHOS DE HELDMAN/PMBOK (corpus Athena) ---\n"
        + "\n\n".join(rag_chunks)
        if rag_chunks else
        "\n\n(Nenhum trecho do corpus Athena disponível para esta classificação — opere apenas com expert_judgment.)"
    )

    return f"""META A CLASSIFICAR
==================
Título: {goal.get('title')}
Métrica: {goal.get('metric') or '(não definida)'}
Alvo: {goal.get('target')}
Atual: {goal.get('current')}
Goal pai (UUID): {goal.get('parent_goal_id') or '(sem pai)'}

CONTEXTO ORGANIZACIONAL (companies.context_json)
================================================
{_json.dumps(company_context, ensure_ascii=False, indent=2) if company_context else '(sem contexto registrado)'}
{rag_block}

INSTRUÇÃO
=========
Classifique a meta acima conforme PMBOK 5ª. Aplique as REGRAS HARD do system prompt.
Retorne APENAS o JSON conforme schema. Sem markdown, sem texto antes/depois."""


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
    # entrypoint é sync e chama asyncio.run() internamente (paridade Mnemos).
    # Como este handler é async (rodando dentro do event loop do agent_daemon),
    # chamar asyncio.run() aninhado lança "cannot be called from a running event
    # loop". Mnemos é despachado como função sync direto e não tem esse problema.
    # Solução: rodar em thread separada via asyncio.to_thread (libera o loop).
    result = await asyncio.to_thread(_ingest_entry, task, supabase)

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
    "athena-classify":         _handle_classify,
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
