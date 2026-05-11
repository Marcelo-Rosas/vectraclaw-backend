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


async def _handle_charter(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """VEC-401 (real, output-only): gera Project Charter PMBOK no output_json.

    Pipeline:
      1. SELECT goal (com kind/confidence/business_case já populados pelo classify)
      2. Pré-validação: rejeita se goal.kind != 'project' ou confidence < 0.7
      3. SELECT companies.context_json (contexto organizacional)
      4. RAG athena_chunks: top-4 chunks Heldman sobre 'Project Charter, 5 elementos'
      5. Gemini Flash structured output (response_mime_type=application/json)
      6. Pydantic validation via CharterOutput
      7. Retorna envelope I/T/O PMBOK — sem INSERT em projects (PR4b)

    Sem persistência neste PR — fica para PR4b (INSERT em vectraclip.projects).
    Args:
        prompt: ignorado (handler dirigido por goal_id).
        input_data: dict com `_supabase`, `_task_id`, `_company_id`, `goal_id`.
    """
    from datetime import datetime as _dt, timezone as _tz
    import json as _json

    from src.agents.athena_schemas import CharterOutput, ValidationBlock
    from src.services.gemini_client import generate as gemini_generate

    started_at = _dt.now(_tz.utc).isoformat()
    supabase = input_data.get("_supabase")
    task_id = input_data.get("_task_id", "")
    company_id = input_data.get("_company_id")
    goal_id = input_data.get("goal_id")

    if not goal_id:
        return _charter_error_output(
            task_id, started_at, "missing_goal_id",
            "input_json.goal_id é obrigatório para athena-charter",
        )
    if supabase is None:
        return _charter_error_output(
            task_id, started_at, "missing_supabase",
            "Cliente Supabase não disponível (esperado via input_data['_supabase'])",
        )

    # 1) SELECT goal
    try:
        goal_res = (
            supabase.table("goals")
            .select("id,company_id,parent_goal_id,title,metric,target,current,kind,confidence,business_case_strength,pmoia_metadata")
            .eq("id", goal_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.exception("athena-charter select goal failed task=%s goal=%s", task_id, goal_id)
        return _charter_error_output(task_id, started_at, "goal_select_failed", str(exc))
    if not goal_res.data:
        return _charter_error_output(
            task_id, started_at, "goal_not_found",
            f"vectraclip.goals not found: id={goal_id}",
        )
    goal = goal_res.data[0]

    if company_id and str(goal.get("company_id")) != str(company_id):
        return _charter_error_output(
            task_id, started_at, "company_mismatch",
            f"goal.company_id ({goal.get('company_id')}) != task.company_id ({company_id})",
        )

    # 2) Pré-validação: charter exige goal classificado como project
    g_kind = goal.get("kind")
    g_conf = goal.get("confidence")
    if g_kind != "project":
        return _charter_error_output(
            task_id, started_at, "goal_not_classified_as_project",
            f"athena-charter exige goal.kind='project'. Atual: kind={g_kind!r}. "
            f"Rode athena-classify primeiro e confirme classificação como projeto.",
        )
    try:
        if g_conf is None or float(g_conf) < 0.7:
            return _charter_error_output(
                task_id, started_at, "low_classify_confidence",
                f"athena-charter exige goal.confidence >= 0.7. Atual: {g_conf}. "
                f"Re-classifique ou avalie human-in-the-loop.",
            )
    except (TypeError, ValueError):
        return _charter_error_output(
            task_id, started_at, "invalid_confidence",
            f"goal.confidence inválido: {g_conf!r}",
        )

    # 3) Contexto organizacional
    company_context = _get_company_context(supabase, goal.get("company_id"))

    # 4) RAG corpus Athena (best-effort)
    rag_chunks: list = []
    rag_citations: list = []
    try:
        from src.services.athena_rag import query_top_k as _athena_query
        rag_results = await _athena_query(
            "Project Charter PMBOK 5 elementos business_need scope strategic_alignment HR stakeholder risk tolerance",
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
                "topic": "PMBOK charter",
            })
    except Exception as exc:
        logger.warning("athena-charter RAG indisponível (degradando): %s", exc)

    # 5) Gemini
    user_prompt = _build_charter_prompt(goal, company_context, rag_chunks)
    try:
        text, metadata = await gemini_generate(
            ATHENA_DEFAULT_MODEL,
            user_prompt,
            system_instruction=_CHARTER_SYSTEM_PROMPT,
            response_mime_type="application/json",
        )
    except Exception as exc:
        logger.exception("athena-charter gemini call failed task=%s", task_id)
        return _charter_error_output(task_id, started_at, "gemini_call_failed", str(exc))

    try:
        gemini_payload = _json.loads(text)
    except Exception as exc:
        return _charter_error_output(
            task_id, started_at, "gemini_invalid_json",
            f"Gemini não retornou JSON válido: {exc}. Raw[:200]={text[:200]!r}",
        )

    # 6) Pydantic validation
    completed_at = _dt.now(_tz.utc).isoformat()
    tools_applied = ["expert_judgment", "smart_filter", "selection_methods"]
    if rag_chunks:
        tools_applied.append("rag_retrieval")

    envelope = {
        "handler_name": "athena-charter",
        "execution_id": task_id,
        "execution_started_at": started_at,
        "execution_completed_at": completed_at,
        "inputs_used": {
            "goal_id": goal_id,
            "goal_title": goal.get("title"),
            "goal_kind": g_kind,
            "goal_confidence": g_conf,
            "company_context_keys": list((company_context or {}).keys()),
            "rag_chunks_used": len(rag_chunks),
        },
        "tools_techniques_applied": tools_applied,
        "outputs": gemini_payload,
        "validation": ValidationBlock(
            all_required_inputs_present=True,
            confidence=float(gemini_payload.get("validation_confidence", g_conf or 0.7)),
            warnings=[],
            needs_human_review=False,
        ).model_dump(),
        "citations": rag_citations,
    }

    try:
        CharterOutput.model_validate(envelope)
    except Exception as exc:
        logger.exception("athena-charter pydantic validation failed task=%s", task_id)
        return _charter_error_output(
            task_id, started_at, "pydantic_validation_failed",
            f"{exc}. envelope.outputs={envelope.get('outputs')}",
        )

    # 7) Metadata + cost (VEC-400 trackeia tokens=0 em follow-up)
    tokens = {
        "input": int(metadata.get("input_token_count") or 0),
        "output": int(metadata.get("output_token_count") or 0),
    }
    tokens["total"] = tokens["input"] + tokens["output"]
    envelope["metadata"] = {"tokens": tokens}
    cost_usd = _calc_cost(tokens)

    logger.info(
        "athena-charter done task=%s goal=%s selection=%s tokens=%d cost=%.6f",
        task_id, goal_id, gemini_payload.get("selection_model"),
        tokens["total"], cost_usd,
    )

    return {
        "output_json": envelope,
        "cost_usd": cost_usd,
        "status_override": "done",
    }


def _charter_error_output(
    task_id: str, started_at: str, code: str, message: str,
) -> Dict[str, Any]:
    """Envelope I/T/O minimal para erros do handler charter. status=blocked.
    NOTA: usa schema HandlerOutputBase genérico aqui porque o CharterOutputs
    estrito exige campos preenchidos — em caso de erro, apenas reportamos.
    """
    now = datetime.now(timezone.utc).isoformat()
    return {
        "output_json": {
            "handler_name": "athena-charter",
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


_CHARTER_SYSTEM_PROMPT = """Você é Athena, PMOia da Vectra Cargo, especialista em PMBOK 5ª edição (Kim Heldman).

Sua tarefa: redigir um Project Charter completo para uma meta organizacional já classificada como PROJETO (kind=project) com confidence≥0.7. O charter formaliza o projeto e autoriza sua iniciação. Heldman é claro: SEM CHARTER, NÃO HÁ PROJETO.

REGRAS HARD (não negociáveis):
1. Os 5 elementos PMBOK são OBRIGATÓRIOS e cada um tem conteúdo substantivo:
   - business_need (≥50 chars): razão de negócio que motiva o projeto
   - scope_description (≥50 chars): O que está dentro/fora do escopo, entregáveis-chave
   - strategic_alignment (≥30 chars): conexão com objetivo estratégico da company
   - human_resources_assessment (≥30 chars): perfil de recursos humanos necessários e gap atual
   - stakeholder_risk_tolerance (≥30 chars): perfil de risco do(s) sponsor(s) e stakeholders-chave
2. charter_md (≥200 chars) é o documento legível para humanos consolidando os 5 elementos acima em markdown.
3. smart_goals deve ter pelo menos 1 entrada com TODOS os 5 atributos SMART preenchidos (≥10 chars cada).
4. selection_model é UM dos seguintes (Heldman cap.4):
   - npv (preferido quando há fluxo de caixa estimável)
   - payback (quando o critério é tempo de retorno)
   - weighted_scoring (múltiplos critérios qualitativos)
   - sacred_cow (projeto político/imposto sem ROI mensurável — sinalize red flag)
   - discounted_cash_flow (variante NPV com taxa de desconto explícita)
5. red_flags: liste explicitamente sinais de problema (escopo aberto, sponsor não engajado, RH crítico em falta, etc). Se NENHUM, retorne lista vazia [].
6. tools_techniques_applied DEVE incluir 'expert_judgment' e 'smart_filter'. Quando há RAG chunks, incluir 'rag_retrieval'.

FORMATO DE SAÍDA — apenas JSON, sem markdown, exatamente o schema:
{
  "charter_md": "<markdown completo do charter, ≥200 chars>",
  "business_need": "<≥50 chars>",
  "scope_description": "<≥50 chars>",
  "strategic_alignment": "<≥30 chars>",
  "human_resources_assessment": "<≥30 chars>",
  "stakeholder_risk_tolerance": "<≥30 chars>",
  "smart_goals": [
    {
      "goal": "<descrição da meta, ≥20 chars>",
      "specific": "<≥10>",
      "measurable": "<≥10>",
      "achievable": "<≥10>",
      "relevant": "<≥10>",
      "timebound": "<≥10>"
    }
  ],
  "red_flags": ["<sinal 1>", "<sinal 2>"],
  "selection_model": "npv" | "payback" | "weighted_scoring" | "sacred_cow" | "discounted_cash_flow",
  "next_steps": ["<próximo passo 1>", "<próximo passo 2>"]
}"""


def _build_charter_prompt(
    goal: Dict[str, Any],
    company_context: Dict[str, Any],
    rag_chunks: list,
) -> str:
    """Renderiza o prompt do user para o athena-charter."""
    import json as _json

    pmoia = goal.get("pmoia_metadata") or {}
    smart_already = pmoia.get("smart_breakdown") or {}
    rationale = pmoia.get("classification_rationale") or "(não disponível)"

    rag_block = (
        "\n\n--- TRECHOS DE HELDMAN/PMBOK (corpus Athena) ---\n"
        + "\n\n".join(rag_chunks)
        if rag_chunks else
        "\n\n(Nenhum trecho do corpus Athena disponível — opere com expert_judgment.)"
    )

    return f"""META JÁ CLASSIFICADA COMO PROJETO
==================================
Título: {goal.get('title')}
Métrica: {goal.get('metric') or '(não definida)'}
Alvo: {goal.get('target')}
Atual: {goal.get('current')}
Goal pai: {goal.get('parent_goal_id') or '(sem pai)'}

CLASSIFICAÇÃO PRÉVIA (athena-classify)
======================================
- kind: {goal.get('kind')}
- confidence: {goal.get('confidence')}
- business_case_strength: {goal.get('business_case_strength')}
- rationale: {rationale}
- SMART preliminar:
{_json.dumps(smart_already, ensure_ascii=False, indent=2)}

CONTEXTO ORGANIZACIONAL (companies.context_json)
================================================
{_json.dumps(company_context, ensure_ascii=False, indent=2) if company_context else '(sem contexto registrado)'}
{rag_block}

INSTRUÇÃO
=========
Redija o Project Charter completo conforme PMBOK 5ª (5 elementos obrigatórios + SMART + selection_model + red_flags + next_steps).
Aplique as REGRAS HARD do system prompt.
Retorne APENAS o JSON conforme schema. Sem markdown encapsulado, sem texto antes/depois."""


async def _handle_stakeholder_map(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """VEC-403 (real, output-only): gera mapa de stakeholders PMBOK no output_json.

    Pipeline (mesmo padrão VEC-401):
      1. SELECT goal (com kind/confidence/business_case já populados pelo classify)
      2. Pré-validação: rejeita se goal.kind != 'project' ou confidence < 0.7
      3. SELECT companies.context_json
      4. RAG: top-4 chunks Heldman sobre stakeholder register + Power×Interest grid
      5. Gemini Flash structured output
      6. Pydantic validation via StakeholderMapOutput
      7. Retorna envelope I/T/O sem tocar em tabelas (não existe tabela stakeholders)

    Args:
        prompt: ignorado.
        input_data: dict com `_supabase`, `_task_id`, `_company_id`, `goal_id`,
                    e opcionalmente `stakeholders_hint` (lista pré-conhecida).
    """
    from datetime import datetime as _dt, timezone as _tz
    import json as _json

    from src.agents.athena_schemas import StakeholderMapOutput, ValidationBlock
    from src.services.gemini_client import generate as gemini_generate

    started_at = _dt.now(_tz.utc).isoformat()
    supabase = input_data.get("_supabase")
    task_id = input_data.get("_task_id", "")
    company_id = input_data.get("_company_id")
    goal_id = input_data.get("goal_id")
    stakeholders_hint = input_data.get("stakeholders_hint") or []

    if not goal_id:
        return _stakeholder_map_error_output(
            task_id, started_at, "missing_goal_id",
            "input_json.goal_id é obrigatório para athena-stakeholder-map",
        )
    if supabase is None:
        return _stakeholder_map_error_output(
            task_id, started_at, "missing_supabase",
            "Cliente Supabase não disponível",
        )

    # 1) SELECT goal
    try:
        goal_res = (
            supabase.table("goals")
            .select("id,company_id,title,metric,target,kind,confidence,business_case_strength,pmoia_metadata")
            .eq("id", goal_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.exception("athena-stakeholder-map select goal failed task=%s goal=%s", task_id, goal_id)
        return _stakeholder_map_error_output(task_id, started_at, "goal_select_failed", str(exc))
    if not goal_res.data:
        return _stakeholder_map_error_output(
            task_id, started_at, "goal_not_found",
            f"vectraclip.goals not found: id={goal_id}",
        )
    goal = goal_res.data[0]

    if company_id and str(goal.get("company_id")) != str(company_id):
        return _stakeholder_map_error_output(
            task_id, started_at, "company_mismatch",
            f"goal.company_id != task.company_id",
        )

    # 2) Pré-validação
    g_kind = goal.get("kind")
    g_conf = goal.get("confidence")
    if g_kind != "project":
        return _stakeholder_map_error_output(
            task_id, started_at, "goal_not_classified_as_project",
            f"athena-stakeholder-map exige goal.kind='project'. Atual: kind={g_kind!r}",
        )
    try:
        if g_conf is None or float(g_conf) < 0.7:
            return _stakeholder_map_error_output(
                task_id, started_at, "low_classify_confidence",
                f"athena-stakeholder-map exige goal.confidence >= 0.7. Atual: {g_conf}",
            )
    except (TypeError, ValueError):
        return _stakeholder_map_error_output(
            task_id, started_at, "invalid_confidence",
            f"goal.confidence inválido: {g_conf!r}",
        )

    # 3) Contexto organizacional
    company_context = _get_company_context(supabase, goal.get("company_id"))

    # 4) RAG corpus Athena
    rag_chunks: list = []
    rag_citations: list = []
    try:
        from src.services.athena_rag import query_top_k as _athena_query
        rag_results = await _athena_query(
            "stakeholder register Power Interest grid Heldman communication plan team health",
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
                "topic": "PMBOK stakeholder map",
            })
    except Exception as exc:
        logger.warning("athena-stakeholder-map RAG indisponível (degradando): %s", exc)

    # 5) Gemini
    user_prompt = _build_stakeholder_map_prompt(goal, company_context, rag_chunks, stakeholders_hint)
    try:
        text, metadata = await gemini_generate(
            ATHENA_DEFAULT_MODEL,
            user_prompt,
            system_instruction=_STAKEHOLDER_MAP_SYSTEM_PROMPT,
            response_mime_type="application/json",
        )
    except Exception as exc:
        logger.exception("athena-stakeholder-map gemini call failed task=%s", task_id)
        return _stakeholder_map_error_output(task_id, started_at, "gemini_call_failed", str(exc))

    try:
        gemini_payload = _json.loads(text)
    except Exception as exc:
        return _stakeholder_map_error_output(
            task_id, started_at, "gemini_invalid_json",
            f"Gemini não retornou JSON válido: {exc}. Raw[:200]={text[:200]!r}",
        )

    # 6) Pydantic
    completed_at = _dt.now(_tz.utc).isoformat()
    tools_applied = ["expert_judgment", "stakeholder_analysis", "power_interest_grid"]
    if rag_chunks:
        tools_applied.append("rag_retrieval")

    envelope = {
        "handler_name": "athena-stakeholder-map",
        "execution_id": task_id,
        "execution_started_at": started_at,
        "execution_completed_at": completed_at,
        "inputs_used": {
            "goal_id": goal_id,
            "goal_title": goal.get("title"),
            "stakeholders_hint_count": len(stakeholders_hint),
            "rag_chunks_used": len(rag_chunks),
        },
        "tools_techniques_applied": tools_applied,
        "outputs": gemini_payload,
        "validation": ValidationBlock(
            all_required_inputs_present=True,
            confidence=float(gemini_payload.get("validation_confidence", g_conf or 0.7)),
            warnings=[],
            needs_human_review=False,
        ).model_dump(),
        "citations": rag_citations,
    }

    try:
        StakeholderMapOutput.model_validate(envelope)
    except Exception as exc:
        logger.exception("athena-stakeholder-map pydantic validation failed task=%s", task_id)
        return _stakeholder_map_error_output(
            task_id, started_at, "pydantic_validation_failed",
            f"{exc}. envelope.outputs={envelope.get('outputs')}",
        )

    # 7) Metadata + cost
    tokens = {
        "input": int(metadata.get("input_token_count") or 0),
        "output": int(metadata.get("output_token_count") or 0),
    }
    tokens["total"] = tokens["input"] + tokens["output"]
    envelope["metadata"] = {"tokens": tokens}
    cost_usd = _calc_cost(tokens)

    logger.info(
        "athena-stakeholder-map done task=%s goal=%s stakeholders=%d tokens=%d cost=%.6f",
        task_id, goal_id, len(gemini_payload.get("stakeholders", [])),
        tokens["total"], cost_usd,
    )

    return {
        "output_json": envelope,
        "cost_usd": cost_usd,
        "status_override": "done",
    }


def _stakeholder_map_error_output(
    task_id: str, started_at: str, code: str, message: str,
) -> Dict[str, Any]:
    """Envelope I/T/O minimal para erros do handler stakeholder-map. status=blocked."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "output_json": {
            "handler_name": "athena-stakeholder-map",
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


_STAKEHOLDER_MAP_SYSTEM_PROMPT = """Você é Athena, PMOia da Vectra Cargo, especialista em PMBOK 5ª (Kim Heldman, cap.13 Stakeholder Management).

Sua tarefa: gerar o Stakeholder Map de um projeto já com Charter, identificando todos os atores relevantes, classificando-os na matriz Power × Interest, e propondo communication_plan + team_health_assessment.

REGRAS HARD:
1. stakeholders DEVE ter pelo menos 1 entrada com nome real ou role (ex: "Diretor de TI", "Sponsor", "Líder Comercial"). NUNCA usar placeholders genéricos como "Stakeholder 1".
2. Cada stakeholder tem influence ∈ [0,1] e interest ∈ [0,1]. Pelo menos 1 com influence≥0.7 (sponsor) e 1 com interest≥0.7 (operacional).
3. matrix_power_interest DEVE classificar TODOS os stakeholders em UM dos 4 quadrantes:
   - high_power_high_interest (Manage Closely): influence≥0.5 E interest≥0.5
   - high_power_low_interest (Keep Satisfied): influence≥0.5 E interest<0.5
   - low_power_high_interest (Keep Informed): influence<0.5 E interest≥0.5
   - low_power_low_interest (Monitor): influence<0.5 E interest<0.5
4. communication_plan DEVE ter 1 entrada por stakeholder em "Manage Closely" e "Keep Satisfied" no mínimo. Frequência alinhada com criticality (Manage Closely=semanal/diário; Keep Satisfied=quinzenal/mensal).
5. team_health_assessment: maturity_level usando CMMI-like (initial/managed/defined/quantitatively_managed/optimizing). gaps e recommendations devem ser concretos para o contexto do goal.
6. risk_alerts: liste explicitamente sinais como "Sponsor desengajado", "Stakeholders críticos não identificados", "Conflito Power×Interest entre 2 sponsors". Lista vazia [] se nenhum.
7. tools_techniques_applied SEMPRE inclui 'expert_judgment', 'stakeholder_analysis', 'power_interest_grid'. Quando há RAG, incluir 'rag_retrieval'.

FORMATO DE SAÍDA — apenas JSON, sem markdown:
{
  "stakeholders": [
    {"name": "...", "role": "...", "influence": 0.8, "interest": 0.9, "expectations": "..."},
    ...
  ],
  "matrix_power_interest": {
    "high_power_high_interest": ["<nome1>", ...],
    "high_power_low_interest": [],
    "low_power_high_interest": [],
    "low_power_low_interest": []
  },
  "communication_plan": [
    {"stakeholder_name": "...", "channel": "email|whatsapp|1on1|reuniao|report|dashboard|outro",
     "frequency": "realtime|diario|semanal|quinzenal|mensal|trimestral|on_demand",
     "message_focus": "..."},
    ...
  ],
  "team_health_assessment": {
    "maturity_level": "initial|managed|defined|quantitatively_managed|optimizing",
    "gaps_identified": ["..."],
    "recommendations": ["..."]
  },
  "risk_alerts": ["..."]
}"""


def _build_stakeholder_map_prompt(
    goal: Dict[str, Any],
    company_context: Dict[str, Any],
    rag_chunks: list,
    stakeholders_hint: list,
) -> str:
    import json as _json

    pmoia = goal.get("pmoia_metadata") or {}
    rationale = pmoia.get("classification_rationale") or "(não disponível)"

    hint_block = (
        "\n\nSTAKEHOLDERS PRÉ-IDENTIFICADOS (input):\n" + _json.dumps(stakeholders_hint, ensure_ascii=False, indent=2)
        if stakeholders_hint else
        "\n\n(Sem stakeholders pré-identificados — deduza a partir do contexto do projeto e da company.)"
    )

    rag_block = (
        "\n\n--- TRECHOS DE HELDMAN/PMBOK (corpus Athena) ---\n"
        + "\n\n".join(rag_chunks)
        if rag_chunks else
        "\n\n(Nenhum trecho do corpus Athena — opere com expert_judgment.)"
    )

    return f"""PROJETO COM CHARTER (kind=project)
====================================
Título: {goal.get('title')}
Métrica: {goal.get('metric') or '(não definida)'}
Alvo: {goal.get('target')}

CLASSIFICAÇÃO PRÉVIA (athena-classify)
======================================
- confidence: {goal.get('confidence')}
- business_case_strength: {goal.get('business_case_strength')}
- rationale: {rationale}

CONTEXTO ORGANIZACIONAL (companies.context_json)
================================================
{_json.dumps(company_context, ensure_ascii=False, indent=2) if company_context else '(sem contexto registrado)'}
{hint_block}
{rag_block}

INSTRUÇÃO
=========
Gere o Stakeholder Map completo conforme PMBOK 5ª:
- Identifique stakeholders concretos (mínimo 3-5 papéis distintos)
- Classifique cada um na matriz Power × Interest
- Proponha communication_plan focado em criticality
- Avalie team_health (maturity + gaps + recommendations)
- Sinalize risk_alerts explícitos

Aplique as REGRAS HARD do system prompt.
Retorne APENAS o JSON conforme schema. Sem markdown, sem texto antes/depois."""


async def _handle_risk_register(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """VEC-404 (real, output-only): gera Risk Register PMBOK 5ª no output_json.

    Pipeline (mesmo padrão VEC-401/VEC-403):
      1. SELECT goal (com kind/confidence/business_case já populados pelo classify)
      2. Pré-validação: rejeita se goal.kind != 'project' ou confidence < 0.7
      3. SELECT companies.context_json
      4. RAG: top-4 chunks Heldman sobre RBS, riscos secundários, residuais, transfer
      5. Gemini Flash structured output
      6. Pydantic RiskRegisterOutput STRICT (escala PMBOK 5ª, consistência score=p*i,
         cor=classification, strategy compatible com nature, transfer_details
         obrigatório se strategy=transfer, ≥1 opportunity, ≥3 RBS categories)
      7. Retorna envelope I/T/O sem persistência (não existe tabela risks)

    Args:
        prompt: ignorado.
        input_data: dict com `_supabase`, `_task_id`, `_company_id`, `goal_id`.
    """
    from datetime import datetime as _dt, timezone as _tz
    import json as _json

    from src.agents.athena_schemas import RiskRegisterOutput, ValidationBlock
    from src.services.gemini_client import generate as gemini_generate

    started_at = _dt.now(_tz.utc).isoformat()
    supabase = input_data.get("_supabase")
    task_id = input_data.get("_task_id", "")
    company_id = input_data.get("_company_id")
    goal_id = input_data.get("goal_id")

    if not goal_id:
        return _risk_register_error_output(
            task_id, started_at, "missing_goal_id",
            "input_json.goal_id é obrigatório para athena-risk-register",
        )
    if supabase is None:
        return _risk_register_error_output(
            task_id, started_at, "missing_supabase",
            "Cliente Supabase não disponível",
        )

    # 1) SELECT goal
    try:
        goal_res = (
            supabase.table("goals")
            .select("id,company_id,title,metric,target,kind,confidence,business_case_strength,pmoia_metadata")
            .eq("id", goal_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.exception("athena-risk-register select goal failed task=%s goal=%s", task_id, goal_id)
        return _risk_register_error_output(task_id, started_at, "goal_select_failed", str(exc))
    if not goal_res.data:
        return _risk_register_error_output(
            task_id, started_at, "goal_not_found",
            f"vectraclip.goals not found: id={goal_id}",
        )
    goal = goal_res.data[0]

    if company_id and str(goal.get("company_id")) != str(company_id):
        return _risk_register_error_output(
            task_id, started_at, "company_mismatch",
            f"goal.company_id != task.company_id",
        )

    # 2) Pré-validação
    g_kind = goal.get("kind")
    g_conf = goal.get("confidence")
    if g_kind != "project":
        return _risk_register_error_output(
            task_id, started_at, "goal_not_classified_as_project",
            f"athena-risk-register exige goal.kind='project'. Atual: kind={g_kind!r}",
        )
    try:
        if g_conf is None or float(g_conf) < 0.7:
            return _risk_register_error_output(
                task_id, started_at, "low_classify_confidence",
                f"athena-risk-register exige goal.confidence >= 0.7. Atual: {g_conf}",
            )
    except (TypeError, ValueError):
        return _risk_register_error_output(
            task_id, started_at, "invalid_confidence",
            f"goal.confidence inválido: {g_conf!r}",
        )

    # 3) Contexto
    company_context = _get_company_context(supabase, goal.get("company_id"))

    # 4) RAG
    rag_chunks: list = []
    rag_citations: list = []
    try:
        from src.services.athena_rag import query_top_k as _athena_query
        rag_results = await _athena_query(
            "risk register RBS risk breakdown structure secondary residual transfer PMBOK Heldman",
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
                "topic": "PMBOK risk register",
            })
    except Exception as exc:
        logger.warning("athena-risk-register RAG indisponível (degradando): %s", exc)

    # 5) Gemini
    user_prompt = _build_risk_register_prompt(goal, company_context, rag_chunks)
    try:
        text, metadata = await gemini_generate(
            ATHENA_DEFAULT_MODEL,
            user_prompt,
            system_instruction=_RISK_REGISTER_SYSTEM_PROMPT,
            response_mime_type="application/json",
        )
    except Exception as exc:
        logger.exception("athena-risk-register gemini call failed task=%s", task_id)
        return _risk_register_error_output(task_id, started_at, "gemini_call_failed", str(exc))

    try:
        gemini_payload = _json.loads(text)
    except Exception as exc:
        return _risk_register_error_output(
            task_id, started_at, "gemini_invalid_json",
            f"Gemini não retornou JSON válido: {exc}. Raw[:200]={text[:200]!r}",
        )

    # 6) Pydantic STRICT
    completed_at = _dt.now(_tz.utc).isoformat()
    tools_applied = ["expert_judgment", "risk_analysis", "risk_breakdown_structure"]
    if rag_chunks:
        tools_applied.append("rag_retrieval")

    envelope = {
        "handler_name": "athena-risk-register",
        "execution_id": task_id,
        "execution_started_at": started_at,
        "execution_completed_at": completed_at,
        "inputs_used": {
            "goal_id": goal_id,
            "goal_title": goal.get("title"),
            "rag_chunks_used": len(rag_chunks),
        },
        "tools_techniques_applied": tools_applied,
        "outputs": gemini_payload,
        "validation": ValidationBlock(
            all_required_inputs_present=True,
            confidence=float(gemini_payload.get("validation_confidence", g_conf or 0.7)),
            warnings=[],
            needs_human_review=False,
        ).model_dump(),
        "citations": rag_citations,
    }

    try:
        RiskRegisterOutput.model_validate(envelope)
    except Exception as exc:
        logger.exception("athena-risk-register pydantic validation failed task=%s", task_id)
        return _risk_register_error_output(
            task_id, started_at, "pydantic_validation_failed",
            f"{exc}. envelope.outputs={envelope.get('outputs')}",
        )

    # 7) Metadata + cost
    tokens = {
        "input": int(metadata.get("input_token_count") or 0),
        "output": int(metadata.get("output_token_count") or 0),
    }
    tokens["total"] = tokens["input"] + tokens["output"]
    envelope["metadata"] = {"tokens": tokens}
    cost_usd = _calc_cost(tokens)

    risks_count = len(gemini_payload.get("risks", []))
    logger.info(
        "athena-risk-register done task=%s goal=%s risks=%d tokens=%d cost=%.6f",
        task_id, goal_id, risks_count, tokens["total"], cost_usd,
    )

    return {
        "output_json": envelope,
        "cost_usd": cost_usd,
        "status_override": "done",
    }


def _risk_register_error_output(
    task_id: str, started_at: str, code: str, message: str,
) -> Dict[str, Any]:
    """Envelope I/T/O minimal para erros do handler risk-register. status=blocked."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "output_json": {
            "handler_name": "athena-risk-register",
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


_RISK_REGISTER_SYSTEM_PROMPT = """Você é Athena, PMOia da Vectra Cargo, especialista em PMBOK 5ª (Kim Heldman, cap.11 Risk Management).

Sua tarefa: gerar Risk Register completo PMBOK 5ª para um projeto. Aplicar a ESCALA OFICIAL (não inventar números), classificar via probabilidade × impacto, atribuir cores semáforo, mapear estratégia compatível com a natureza (threat/opportunity), e SEMPRE incluir riscos secundários e residuais.

REGRAS HARD (não negociáveis — Pydantic strict valida e rejeita):

1. ESCALA DISCRETA OBRIGATÓRIA:
   - probability ∈ {0.1, 0.3, 0.5, 0.7, 0.9}
   - impact ∈ {0.05, 0.10, 0.20, 0.40, 0.80}
   Qualquer outro valor é REJEITADO.

2. SCORE = round(probability × impact, 4). Calcule corretamente. Ex: 0.7 × 0.40 = 0.2800.

3. CLASSIFICATION derivada de SCORE (4 níveis):
   - score ≤ 0.0900 → "Baixo"
   - score ≤ 0.1900 → "Moderado"
   - score ≤ 0.3500 → "Alto"
   - score > 0.3500 → "Crítico"

4. CLASSIFICATION_COLOR (emoji semáforo):
   - Baixo → 🟢
   - Moderado → 🟡
   - Alto → 🟠
   - Crítico → 🔴

5. NATURE ∈ {threat, opportunity}. Heldman é categórico: riscos têm efeito positivo OU negativo. Risk Register sem nenhum opportunity = viés cognitivo → REJEITADO.

6. STRATEGY compatível com NATURE:
   - threat → eliminate | mitigate | transfer | accept_active | accept_passive
   - opportunity → exploit | enhance | share | accept

7. TRANSFER_DETAILS obrigatório quando strategy=transfer (sem instrumento financeiro real, "transfer" é só papel — anti-padrão Athena):
   - transferred_to (≥5 chars), instrument (≥10 chars)
   - cost_of_transfer_brl_per_unit, expected_loss_brl_without_transfer (ambos ≥0)
   - net_savings_brl = expected_loss - cost (validado)
   - counterparty_capacity_validated (bool), counterparty_validation_method (≥10 chars)

8. SECONDARY_RISKS (lista, pode ser vazia): riscos que surgem como CONSEQUÊNCIA da response_plan. Mesma escala oficial. CADA ENTRADA TEM `id` OBRIGATÓRIO (use convenção R-XXX.SR-N — ex: R-001.SR-1).

9. RESIDUAL_RISK (obrigatório por risco): risco remanescente após mitigation. Mesma escala + campo `acceptance` (≥10 chars explicando por que foi aceito). SEM CAMPO `id` no residual_risk (apenas description, probability, impact, score, classification, acceptance).

10. RBS_CATEGORY ∈ {External, Organizational, Project Management, Technical}. Risk Register precisa cobrir pelo menos 3 das 4 categorias — senão Pydantic REJEITA.

11. RISKS DEVE TER ≥5 entradas total (Pydantic min_length=5).

12. RISK_SUMMARY: agregados consistentes com risks[]. any_critical_breached=true se há classification=Crítico.

13. tools_techniques_applied SEMPRE inclui 'expert_judgment', 'risk_analysis', 'risk_breakdown_structure'.

FORMATO DE SAÍDA — apenas JSON, sem markdown:
{
  "risks": [
    {
      "id": "R-001",
      "nature": "threat" | "opportunity",
      "rbs_category": "External" | "Organizational" | "Project Management" | "Technical",
      "rbs_subcategory": "...",
      "description": "<≥20 chars>",
      "probability": 0.1|0.3|0.5|0.7|0.9,
      "impact": 0.05|0.10|0.20|0.40|0.80,
      "score": <calculado>,
      "classification": "Baixo|Moderado|Alto|Crítico",
      "classification_color": "🟢|🟡|🟠|🔴",
      "strategy": "<conforme nature>",
      "response_plan": "<≥30 chars>",
      "owner_position_id": null,
      "trigger_indicators": ["..."],
      "secondary_risks": [
        {
          "id": "R-001.SR-1",
          "description": "<≥20 chars descrevendo risco que surge da response_plan>",
          "probability": 0.1|0.3|0.5|0.7|0.9,
          "impact": 0.05|0.10|0.20|0.40|0.80,
          "score": <prob × impact>,
          "classification": "Baixo|Moderado|Alto|Crítico"
        }
      ],
      "residual_risk": {
        "description": "<≥20 chars>",
        "probability": <escala>, "impact": <escala>, "score": <calc>,
        "classification": "...", "acceptance": "<≥10 chars>"
      },
      "transfer_details": null,
      "contingency_reserve_brl": 0.0,
      "review_frequency": "daily|weekly|biweekly|monthly|quarterly"
    },
    ... (pelo menos 5 ao todo, com ≥1 opportunity e ≥3 RBS categories)
  ],
  "rbs": {
    "External": ["R-XXX", ...],
    "Organizational": ["R-XXX", ...],
    "Project Management": [...],
    "Technical": [...]
  },
  "risk_summary": {
    "total_risks": N,
    "critical_count": ..., "high_count": ..., "moderate_count": ..., "low_count": ...,
    "threats": ..., "opportunities": ...,
    "highest_score_risk_id": "R-XXX",
    "any_critical_breached": true|false
  },
  "team_health_assessment": null
}"""


def _build_risk_register_prompt(
    goal: Dict[str, Any],
    company_context: Dict[str, Any],
    rag_chunks: list,
) -> str:
    import json as _json

    pmoia = goal.get("pmoia_metadata") or {}
    rationale = pmoia.get("classification_rationale") or "(não disponível)"

    rag_block = (
        "\n\n--- TRECHOS DE HELDMAN/PMBOK (corpus Athena) ---\n"
        + "\n\n".join(rag_chunks)
        if rag_chunks else
        "\n\n(Nenhum trecho do corpus — opere com expert_judgment.)"
    )

    return f"""PROJETO COM CHARTER (kind=project)
====================================
Título: {goal.get('title')}
Métrica: {goal.get('metric') or '(não definida)'}
Alvo: {goal.get('target')}

CLASSIFICAÇÃO PRÉVIA (athena-classify)
======================================
- confidence: {goal.get('confidence')}
- business_case_strength: {goal.get('business_case_strength')}
- rationale: {rationale}

CONTEXTO ORGANIZACIONAL
=======================
{_json.dumps(company_context, ensure_ascii=False, indent=2) if company_context else '(sem contexto)'}
{rag_block}

INSTRUÇÃO
=========
Gere o Risk Register completo conforme PMBOK 5ª:
- Identifique ≥5 riscos cobrindo ≥3 das 4 categorias RBS (External, Organizational, Project Management, Technical)
- Pelo menos 1 risco de natureza 'opportunity' (Heldman explícito)
- Use ESCALA DISCRETA OFICIAL para probability e impact
- Calcule score, derive classification + emoji color
- response_plan concreto + residual_risk obrigatório por linha
- secondary_risks quando a response_plan introduz novos riscos
- transfer_details obrigatório SE strategy=transfer (instrumento financeiro real)

Aplique as 13 REGRAS HARD do system prompt.
Retorne APENAS o JSON conforme schema. Sem markdown, sem texto antes/depois."""


def _compute_evm(schedule: list, bac: Optional[float] = None) -> Dict[str, Any]:
    """Calcula métricas EVM PMBOK 5ª de forma determinística.

    Função PURA — sem efeitos colaterais, testável isolada.

    Args:
        schedule: list of dicts com keys planned_value, actual_cost, percent_complete.
        bac: Budget At Completion. Se None, usa sum(planned_value) do schedule.

    Returns:
        dict com pv, ev, ac, bac, sv, cv, spi, cpi, eac, etc, vac, tcpi_bac, tcpi_eac.
        Todos arredondados a 4 casas. Razões (spi/cpi) None quando denominador=0.

    PMBOK fórmulas:
        PV   = sum(planned_value)
        EV   = sum(planned_value × percent_complete/100)
        AC   = sum(actual_cost)
        SV   = EV − PV
        CV   = EV − AC
        SPI  = EV/PV       (None se PV=0)
        CPI  = EV/AC       (None se AC=0)
        EAC  = BAC × AC/EV (None se EV=0)
        ETC  = EAC − AC    (None se EAC None)
        VAC  = BAC − EAC   (None se EAC None)
        TCPI_BAC = (BAC − EV) / (BAC − AC)   (None se BAC=AC)
        TCPI_EAC = (BAC − EV) / (EAC − AC)   (None se EAC None ou EAC=AC)
    """
    pv = round(sum(float(t.get("planned_value", 0) or 0) for t in schedule), 4)
    ev = round(sum(
        float(t.get("planned_value", 0) or 0)
        * float(t.get("percent_complete", 0) or 0) / 100.0
        for t in schedule
    ), 4)
    ac = round(sum(float(t.get("actual_cost", 0) or 0) for t in schedule), 4)

    bac_final = float(bac) if bac is not None else pv
    sv = round(ev - pv, 4)
    cv = round(ev - ac, 4)
    spi = round(ev / pv, 4) if pv > 0 else None
    cpi = round(ev / ac, 4) if ac > 0 else None
    # EAC fórmula PMBOK equivalente: BAC × AC/EV (evita drift por arredondar CPI)
    eac = round(bac_final * ac / ev, 4) if ev > 0 else None
    etc = round(eac - ac, 4) if eac is not None else None
    vac = round(bac_final - eac, 4) if eac is not None else None
    tcpi_bac = round((bac_final - ev) / (bac_final - ac), 4) if bac_final != ac else None
    tcpi_eac = round((bac_final - ev) / (eac - ac), 4) if (eac is not None and eac != ac) else None

    return {
        "pv": pv, "ev": ev, "ac": ac, "bac": bac_final,
        "sv": sv, "cv": cv,
        "spi": spi, "cpi": cpi,
        "eac": eac, "etc": etc, "vac": vac,
        "tcpi_bac": tcpi_bac, "tcpi_eac": tcpi_eac,
    }


def _evm_alert_signals(metrics: Dict[str, Any]) -> list:
    """Gera alertas determinísticos a partir das métricas. Gemini NÃO inventa esses."""
    alerts = []
    if metrics["cpi"] is not None and metrics["cpi"] < 1.0:
        alerts.append(f"⚠️ CPI={metrics['cpi']:.3f} < 1.0 — projeto gastando mais que o planejado")
    if metrics["spi"] is not None and metrics["spi"] < 1.0:
        alerts.append(f"⚠️ SPI={metrics['spi']:.3f} < 1.0 — projeto atrasado vs cronograma")
    if metrics["vac"] is not None and metrics["vac"] < 0:
        alerts.append(f"🔴 VAC={metrics['vac']:.2f} negativo — projeto estourará o orçamento ao fim")
    if metrics["cpi"] is not None and metrics["cpi"] < 0.8:
        alerts.append(f"🔴 CPI={metrics['cpi']:.3f} crítico — escalar imediatamente para Steering")
    return alerts


async def _handle_evm(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """VEC-405 (real, output-only): EVM PMBOK 5ª — Python calcula, Gemini narra.

    Design diferente dos outros handlers Athena:
    - Métricas (PV/EV/AC/SV/CV/SPI/CPI/EAC/ETC/VAC/TCPI) calculadas determinísticamente
      em Python via _compute_evm — função pura testável.
    - Gemini recebe APENAS os números já calculados e produz:
      * narrative_md: interpretação humana do estado do projeto
      * executive_summary_md: resumo executivo curto
      * alerts: lista textual adicional (alertas determinísticos já vêm do Python)
    - Pydantic EVMMetrics rejeita output do Gemini se ele "alucinar" e mudar valores
      (drift ≤ 0.01 em valores, ≤ 0.001 em ratios — validators in athena_schemas).

    Args:
        prompt: ignorado.
        input_data: dict com `_supabase`, `_task_id`, `_company_id`, `goal_id`,
                    `schedule` (List[Dict] com planned_value/actual_cost/percent_complete),
                    `bac` (opcional), `interpretation_period` (opcional).
    """
    from datetime import datetime as _dt, timezone as _tz
    import json as _json

    from src.agents.athena_schemas import EVMOutput, ValidationBlock
    from src.services.gemini_client import generate as gemini_generate

    started_at = _dt.now(_tz.utc).isoformat()
    supabase = input_data.get("_supabase")
    task_id = input_data.get("_task_id", "")
    company_id = input_data.get("_company_id")
    goal_id = input_data.get("goal_id")
    schedule = input_data.get("schedule") or []
    bac_input = input_data.get("bac")
    interpretation_period = input_data.get("interpretation_period") or _dt.now(_tz.utc).strftime("%Y-%m-%d")

    if not goal_id:
        return _evm_error_output(task_id, started_at, "missing_goal_id",
                                 "input_json.goal_id é obrigatório")
    if supabase is None:
        return _evm_error_output(task_id, started_at, "missing_supabase",
                                 "Cliente Supabase não disponível")
    if not isinstance(schedule, list) or not schedule:
        return _evm_error_output(
            task_id, started_at, "missing_schedule",
            "input_json.schedule deve ser lista não-vazia de tasks com "
            "{planned_value, actual_cost, percent_complete}",
        )

    # 1) SELECT goal
    try:
        goal_res = (
            supabase.table("goals")
            .select("id,company_id,title,kind,confidence,pmoia_metadata")
            .eq("id", goal_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.exception("athena-evm select goal failed task=%s goal=%s", task_id, goal_id)
        return _evm_error_output(task_id, started_at, "goal_select_failed", str(exc))
    if not goal_res.data:
        return _evm_error_output(task_id, started_at, "goal_not_found",
                                 f"goals not found: {goal_id}")
    goal = goal_res.data[0]

    if company_id and str(goal.get("company_id")) != str(company_id):
        return _evm_error_output(task_id, started_at, "company_mismatch",
                                 "goal.company_id != task.company_id")

    # 2) Pré-validação (mesmo guard dos outros handlers PMBOK)
    if goal.get("kind") != "project":
        return _evm_error_output(task_id, started_at, "goal_not_classified_as_project",
                                 f"athena-evm exige goal.kind='project'. Atual: {goal.get('kind')!r}")
    try:
        if goal.get("confidence") is None or float(goal["confidence"]) < 0.7:
            return _evm_error_output(task_id, started_at, "low_classify_confidence",
                                     f"athena-evm exige confidence>=0.7. Atual: {goal.get('confidence')}")
    except (TypeError, ValueError):
        return _evm_error_output(task_id, started_at, "invalid_confidence",
                                 f"confidence inválido: {goal.get('confidence')!r}")

    # 3) CÁLCULO DETERMINÍSTICO (Python)
    try:
        metrics = _compute_evm(schedule, bac_input)
    except Exception as exc:
        logger.exception("athena-evm _compute_evm failed task=%s: %s", task_id, exc)
        return _evm_error_output(task_id, started_at, "compute_failed", str(exc))

    deterministic_alerts = _evm_alert_signals(metrics)

    # 4) Gemini gera apenas narrativa (NÃO recalcula números)
    user_prompt = _build_evm_prompt(goal, metrics, deterministic_alerts, interpretation_period)
    try:
        text, llm_meta = await gemini_generate(
            ATHENA_DEFAULT_MODEL,
            user_prompt,
            system_instruction=_EVM_SYSTEM_PROMPT,
            response_mime_type="application/json",
        )
    except Exception as exc:
        logger.exception("athena-evm gemini call failed task=%s", task_id)
        return _evm_error_output(task_id, started_at, "gemini_call_failed", str(exc))

    try:
        gemini_payload = _json.loads(text)
    except Exception as exc:
        return _evm_error_output(
            task_id, started_at, "gemini_invalid_json",
            f"JSON inválido: {exc}. Raw[:200]={text[:200]!r}",
        )

    # 5) Monta envelope FORÇANDO os números calculados em Python.
    #    Se o Gemini retornou números, eles são DESCARTADOS — só usamos a narrativa.
    completed_at = _dt.now(_tz.utc).isoformat()
    gemini_alerts = gemini_payload.get("alerts") or []
    all_alerts = list(deterministic_alerts) + [
        a for a in gemini_alerts if a not in deterministic_alerts
    ]

    envelope = {
        "handler_name": "athena-evm",
        "execution_id": task_id,
        "execution_started_at": started_at,
        "execution_completed_at": completed_at,
        "inputs_used": {
            "goal_id": goal_id,
            "schedule_tasks": len(schedule),
            "bac_input": bac_input,
            "interpretation_period": interpretation_period,
        },
        "tools_techniques_applied": ["expert_judgment", "earned_value_analysis"],
        "outputs": {
            "metrics": metrics,  # Python — fonte de verdade
            "narrative_md": gemini_payload.get("narrative_md", ""),
            "executive_summary_md": gemini_payload.get("executive_summary_md", ""),
            "alerts": all_alerts,
            "interpretation_period": interpretation_period,
        },
        "validation": ValidationBlock(
            all_required_inputs_present=True,
            confidence=0.95,  # EVM é determinístico; alta confiança intrínseca
            warnings=[],
            needs_human_review=False,
        ).model_dump(),
        "citations": [],
    }

    try:
        EVMOutput.model_validate(envelope)
    except Exception as exc:
        logger.exception("athena-evm pydantic validation failed task=%s: %s", task_id, exc)
        return _evm_error_output(
            task_id, started_at, "pydantic_validation_failed",
            f"{exc}. metrics={metrics}",
        )

    # 6) Cost + metadata
    tokens = {
        "input": int(llm_meta.get("input_token_count") or 0),
        "output": int(llm_meta.get("output_token_count") or 0),
    }
    tokens["total"] = tokens["input"] + tokens["output"]
    envelope["metadata"] = {"tokens": tokens}
    cost_usd = _calc_cost(tokens)

    logger.info(
        "athena-evm done task=%s goal=%s pv=%.2f ev=%.2f ac=%.2f cpi=%s spi=%s alerts=%d tokens=%d",
        task_id, goal_id, metrics["pv"], metrics["ev"], metrics["ac"],
        metrics["cpi"], metrics["spi"], len(all_alerts), tokens["total"],
    )

    return {
        "output_json": envelope,
        "cost_usd": cost_usd,
        "status_override": "done",
    }


def _evm_error_output(
    task_id: str, started_at: str, code: str, message: str,
) -> Dict[str, Any]:
    """Envelope I/T/O minimal para erros do athena-evm. status=blocked."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "output_json": {
            "handler_name": "athena-evm",
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


_EVM_SYSTEM_PROMPT = """Você é Athena, PMOia da Vectra Cargo, especialista em PMBOK 5ª (Kim Heldman, cap.7 Cost Management — EVM).

Sua tarefa: gerar NARRATIVA HUMANA a partir de métricas EVM JÁ CALCULADAS em Python. **NÃO recalcule números** — eles vêm prontos do sistema. Sua função é interpretar e contextualizar.

REGRAS HARD:
1. NÃO modifique os valores numéricos das métricas (pv, ev, ac, sv, cv, spi, cpi, eac, etc, vac, tcpi). Se você "achar" outro número, é alucinação — o sistema rejeita.
2. narrative_md (≥100 chars): texto markdown com 3-5 parágrafos cobrindo:
   - O estado geral (no rumo / atrasado / estourando custo / ambos)
   - Comparação SPI vs CPI (atraso vs custo são problemas independentes)
   - Projeção VAC (impacto financeiro ao fim)
   - Recomendação acionável concreta
3. executive_summary_md (≥50 chars): 1-2 frases para Steering. Use 🟢/🟡/🟠/🔴 conforme severidade.
4. alerts: lista textual extra (NÃO repetir os alertas determinísticos já fornecidos). Pode ser vazia.

FORMATO DE SAÍDA — apenas JSON:
{
  "narrative_md": "## Estado do Projeto\\n\\n...análise técnica...",
  "executive_summary_md": "🟠 Projeto atrasado (SPI=0.45) E estourando custo (CPI=0.87). Decisão de Steering recomendada.",
  "alerts": ["..."]
}"""


def _build_evm_prompt(
    goal: Dict[str, Any],
    metrics: Dict[str, Any],
    deterministic_alerts: list,
    interpretation_period: str,
) -> str:
    import json as _json

    metrics_block = _json.dumps(metrics, ensure_ascii=False, indent=2)
    alerts_block = "\n".join(f"- {a}" for a in deterministic_alerts) if deterministic_alerts else "(nenhum)"

    return f"""PROJETO (kind=project)
======================
Título: {goal.get('title')}
Período de referência: {interpretation_period}

MÉTRICAS EVM JÁ CALCULADAS (NÃO altere os valores)
==================================================
{metrics_block}

ALERTAS DETERMINÍSTICOS (já gerados pelo Python — NÃO repetir literalmente)
===========================================================================
{alerts_block}

INSTRUÇÃO
=========
Gere a NARRATIVA conforme schema do system prompt. Use os valores ACIMA — não recalcule.
Foco no significado: o que esses números dizem sobre o projeto? O que o Steering deveria fazer?
Retorne APENAS o JSON. Sem markdown wrapper, sem texto antes/depois."""


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
    "athena-charter":          _handle_charter,
    "athena-stakeholder-map":  _handle_stakeholder_map,
    "athena-risk-register":    _handle_risk_register,
    "athena-evm":              _handle_evm,
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
