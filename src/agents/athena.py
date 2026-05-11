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


def _score_agent_quality(agent: Dict[str, Any], specialty_count: int) -> Dict[str, Any]:
    """Calcula score 0-4 + grade + flags para um agente. Função PURA testável.

    Critérios:
      +1 se prompt_length >= 200
      +1 se prompt_length >= 1000 (excelente cobertura)
      +1 se specialty_count >= 1
      +1 se name presente e não-vazio

    Grade:
      0-1 = stub
      2   = ok
      3   = good
      4   = excellent
    """
    prompt = agent.get("system_prompt") or ""
    prompt_len = len(prompt)
    name = (agent.get("name") or "").strip()

    score = 0
    flags = []

    if prompt_len >= 200:
        score += 1
    else:
        flags.append(f"prompt_length={prompt_len} (< 200 chars; provável stub)")
    if prompt_len >= 1000:
        score += 1
    if specialty_count >= 1:
        score += 1
    else:
        flags.append("sem specialty associada — agente sem domínio explícito")
    if name:
        score += 1
    else:
        flags.append("agent.name vazio")

    if score <= 1:
        grade: str = "stub"
    elif score == 2:
        grade = "ok"
    elif score == 3:
        grade = "good"
    else:
        grade = "excellent"

    return {
        "quality_score": score,
        "prompt_length": prompt_len,
        "specialty_count": specialty_count,
        "flags": flags,
        "grade": grade,
    }


async def _handle_audit(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """VEC-407 (real, read-only): audita quadro de agentes da company e gera
    relatório markdown no output_json.

    Pipeline:
      1. SELECT agents da company (filtra is_system conforme scope; sempre exclui Athena)
      2. SELECT agent_specialty_configs por agent_id (count por agente)
      3. _score_agent_quality em Python (PURA, determinística) por agente
      4. RAG corpus Athena: chunks sobre "papel do PM, system prompts, skills" (best-effort)
      5. Gemini gera coverage_gaps + recommendations textuais + audit_summary_md
      6. Pydantic AuditOutput strict valida
      7. Retorna envelope sem tocar em nenhuma tabela (read-only)

    Args:
        input_data: dict com `_supabase`, `_task_id`, `_company_id`,
                    `scope` (default 'non_system'), opcional `agent_id`.
    """
    from datetime import datetime as _dt, timezone as _tz
    import json as _json

    from src.agents.athena_schemas import AuditOutput, ValidationBlock
    from src.services.gemini_client import generate as gemini_generate

    started_at = _dt.now(_tz.utc).isoformat()
    supabase = input_data.get("_supabase")
    task_id = input_data.get("_task_id", "")
    company_id = input_data.get("_company_id")
    scope = (input_data.get("scope") or "non_system").strip()
    specific_agent_id = input_data.get("agent_id")

    if supabase is None:
        return _audit_error_output(task_id, started_at, "missing_supabase",
                                   "Cliente Supabase não disponível")
    if not company_id:
        return _audit_error_output(task_id, started_at, "missing_company_id",
                                   "task.company_id é obrigatório para audit")
    if scope not in ("all_agents", "non_system", "specific_agent"):
        return _audit_error_output(
            task_id, started_at, "invalid_scope",
            f"scope inválido: {scope!r}. Esperado: all_agents|non_system|specific_agent",
        )

    # 1) SELECT agents (sempre exclui Athena pra não auditar a si mesma)
    try:
        q = (
            supabase.table("agents")
            .select("id,name,role,system_prompt,is_system")
            .eq("company_id", company_id)
            .neq("id", ATHENA_AGENT_ID)
        )
        if scope == "non_system":
            q = q.eq("is_system", False)
        elif scope == "specific_agent":
            if not specific_agent_id:
                return _audit_error_output(
                    task_id, started_at, "missing_agent_id",
                    "scope=specific_agent exige input.agent_id",
                )
            if str(specific_agent_id) == ATHENA_AGENT_ID:
                return _audit_error_output(
                    task_id, started_at, "self_audit_blocked",
                    "Athena não audita a si mesma",
                )
            q = q.eq("id", specific_agent_id)
        agents_res = q.execute()
    except Exception as exc:
        logger.exception("athena-audit select agents failed task=%s: %s", task_id, exc)
        return _audit_error_output(task_id, started_at, "agents_select_failed", str(exc))

    agents = agents_res.data or []
    if not agents:
        return _audit_error_output(
            task_id, started_at, "no_agents_in_scope",
            f"Nenhum agente encontrado para scope={scope} company={company_id}",
        )

    # 2) Conta specialties por agent_id (1 query, group em Python)
    agent_ids = [a["id"] for a in agents]
    specialty_count_by_agent: Dict[str, int] = {aid: 0 for aid in agent_ids}
    try:
        sp_res = (
            supabase.table("agent_specialty_configs")
            .select("agent_id")
            .in_("agent_id", agent_ids)
            .execute()
        )
        for row in (sp_res.data or []):
            aid = str(row.get("agent_id") or "")
            if aid in specialty_count_by_agent:
                specialty_count_by_agent[aid] += 1
    except Exception as exc:
        # Não-fatal: continua audit sem specialty_count (será 0 pra todos)
        logger.warning("athena-audit specialty count failed (non-fatal): %s", exc)

    # 3) Score determinístico por agente
    scorecards = []
    for a in agents:
        spec_count = specialty_count_by_agent.get(str(a["id"]), 0)
        scoring = _score_agent_quality(a, spec_count)
        scorecards.append({
            "agent_id": str(a["id"]),
            "agent_name": a.get("name") or "(sem nome)",
            "quality_score": scoring["quality_score"],
            "prompt_length": scoring["prompt_length"],
            "specialty_count": scoring["specialty_count"],
            "is_system": bool(a.get("is_system")),
            "flags": scoring["flags"],
            "grade": scoring["grade"],
        })

    agents_below_threshold = sum(1 for sc in scorecards if sc["grade"] in ("stub", "ok"))

    # 4) RAG best-effort
    rag_chunks: list = []
    try:
        from src.services.athena_rag import query_top_k as _athena_query
        rag_results = await _athena_query(
            "papel gerente de projetos habilidades competências system prompt agente PM",
            company_id=company_id,
            k=3,
            min_score=0.3,
            supabase_client=supabase,
        )
        for r in rag_results:
            rag_chunks.append(
                f"[chunk {r.chunk_index} | score {r.score:.2f}]\n{r.content[:1200]}"
            )
    except Exception as exc:
        logger.warning("athena-audit RAG indisponível (degradando): %s", exc)

    # 5) Gemini: gaps + recommendations + audit_summary_md
    user_prompt = _build_audit_prompt(scorecards, rag_chunks, scope)
    try:
        text, llm_meta = await gemini_generate(
            ATHENA_DEFAULT_MODEL,
            user_prompt,
            system_instruction=_AUDIT_SYSTEM_PROMPT,
            response_mime_type="application/json",
        )
    except Exception as exc:
        logger.exception("athena-audit gemini call failed task=%s", task_id)
        return _audit_error_output(task_id, started_at, "gemini_call_failed", str(exc))

    try:
        gemini_payload = _json.loads(text)
    except Exception as exc:
        return _audit_error_output(
            task_id, started_at, "gemini_invalid_json",
            f"JSON inválido: {exc}. Raw[:200]={text[:200]!r}",
        )

    # 6) Envelope (scorecards vem do Python; Gemini só preencheu gaps/recs/summary)
    completed_at = _dt.now(_tz.utc).isoformat()
    envelope = {
        "handler_name": "athena-audit",
        "execution_id": task_id,
        "execution_started_at": started_at,
        "execution_completed_at": completed_at,
        "inputs_used": {
            "scope": scope,
            "specific_agent_id": specific_agent_id,
            "total_agents_scanned": len(agents),
            "rag_chunks_used": len(rag_chunks),
        },
        "tools_techniques_applied": ["expert_judgment", "gap_analysis", "prompt_quality_scoring"],
        "outputs": {
            "agent_scorecards": scorecards,
            "coverage_gaps": gemini_payload.get("coverage_gaps", []),
            "recommendations_textual": gemini_payload.get("recommendations_textual", []),
            "audit_summary_md": gemini_payload.get("audit_summary_md", ""),
            "total_agents": len(scorecards),
            "agents_below_threshold": agents_below_threshold,
        },
        "validation": ValidationBlock(
            all_required_inputs_present=True,
            confidence=0.9,
            warnings=[],
            needs_human_review=False,
        ).model_dump(),
        "citations": [],
    }

    try:
        AuditOutput.model_validate(envelope)
    except Exception as exc:
        logger.exception("athena-audit pydantic validation failed task=%s", task_id)
        return _audit_error_output(
            task_id, started_at, "pydantic_validation_failed",
            f"{exc}. scorecards_count={len(scorecards)}",
        )

    # 7) Cost
    tokens = {
        "input": int(llm_meta.get("input_token_count") or 0),
        "output": int(llm_meta.get("output_token_count") or 0),
    }
    tokens["total"] = tokens["input"] + tokens["output"]
    envelope["metadata"] = {"tokens": tokens}
    cost_usd = _calc_cost(tokens)

    logger.info(
        "athena-audit done task=%s scope=%s agents=%d below_threshold=%d tokens=%d",
        task_id, scope, len(scorecards), agents_below_threshold, tokens["total"],
    )

    return {
        "output_json": envelope,
        "cost_usd": cost_usd,
        "status_override": "done",
    }


def _audit_error_output(
    task_id: str, started_at: str, code: str, message: str,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "output_json": {
            "handler_name": "athena-audit",
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


_AUDIT_SYSTEM_PROMPT = """Você é Athena, PMOia da Vectra Cargo, especialista em PMBOK 5ª (Kim Heldman cap.5 — papel do gerente de projetos, habilidades e responsabilidades). Aqui você atua como Agent Coverage Manager: audita o quadro de daemons da company.

Sua tarefa: a partir dos SCORECARDS já calculados em Python (você NÃO recalcula scores), gere:
1. coverage_gaps — domínios/skills faltantes ou subatendidos no quadro atual
2. recommendations_textual — sugestões textuais (PR futuro fará registro estruturado em athena_recommendations)
3. audit_summary_md — relatório markdown completo (≥200 chars)

REGRAS HARD:
1. NÃO modifique os campos quality_score, grade, flags dos scorecards — eles vêm prontos.
2. coverage_gaps DEVE conter pelo menos 1 entry se há agentes com grade='stub'.
3. severity ∈ {low, medium, high, critical}. critical apenas se há gap em skill bloqueante (ex: financial em company com regulação fiscal pendente).
4. recommendation_kind ∈ {hire_new_agent, add_specialty, rewrite_system_prompt, consolidate_agents}.
5. audit_summary_md (≥200 chars) com 3-5 parágrafos:
   - Estado geral do quadro (quantos stub, ok, good, excellent)
   - Top-3 problemas priorizados por severidade
   - Sugestão de próximo passo PMBOK

FORMATO DE SAÍDA — apenas JSON, sem markdown wrapper:
{
  "coverage_gaps": [
    {
      "domain": "...",
      "description": "<≥20 chars>",
      "recommendation_kind": "hire_new_agent | add_specialty | rewrite_system_prompt | consolidate_agents",
      "affected_goal_kinds": ["project", "operation"],
      "severity": "low | medium | high | critical"
    }
  ],
  "recommendations_textual": ["...", "..."],
  "audit_summary_md": "## Audit do Quadro de Agentes\\n\\n..."
}"""


def _build_audit_prompt(scorecards: list, rag_chunks: list, scope: str) -> str:
    import json as _json

    rag_block = (
        "\n\n--- TRECHOS DE HELDMAN/PMBOK ---\n" + "\n\n".join(rag_chunks)
        if rag_chunks else
        "\n\n(Nenhum trecho do corpus — opere com expert_judgment.)"
    )

    return f"""SCOPE DA AUDITORIA
==================
{scope}

SCORECARDS JÁ CALCULADOS (NÃO recalcule)
========================================
{_json.dumps(scorecards, ensure_ascii=False, indent=2)}
{rag_block}

INSTRUÇÃO
=========
Use os scorecards acima como FATO (foram calculados em Python).
Foque na análise qualitativa:
- Onde há gaps de cobertura?
- Quais agentes precisam de rewrite (grade=stub)?
- Há sobreposição entre agentes que sugere consolidate?

Aplique as REGRAS HARD do system prompt.
Retorne APENAS o JSON. Sem markdown wrapper, sem texto antes/depois."""


_RECOMMEND_VALID_KINDS = {
    "hire_new_agent", "add_specialty", "rewrite_system_prompt",
    "create_specialty", "consolidate_agents",
}


def _validate_proposed_changes_by_kind(kind: str, payload: Dict[str, Any]) -> Optional[str]:
    """Valida estrutura do proposed_changes_json conforme kind.
    Retorna None se OK, ou string de erro descrevendo o gap.
    """
    if not isinstance(payload, dict):
        return f"proposed_changes_json deve ser dict, recebeu {type(payload).__name__}"

    if kind == "hire_new_agent":
        required = ["name", "role", "system_prompt"]
    elif kind == "add_specialty":
        required = ["agent_id", "specialty_id", "prompt_addendum"]
    elif kind == "rewrite_system_prompt":
        required = ["agent_id", "proposed_prompt"]
    elif kind == "create_specialty":
        required = ["name", "slug", "description"]
    elif kind == "consolidate_agents":
        required = ["source_agent_ids", "merged_prompt"]
    else:
        return f"kind '{kind}' não tem schema de validação registrado"

    missing = [k for k in required if not payload.get(k)]
    if missing:
        return f"proposed_changes_json para kind={kind} faltando: {missing}"

    if kind == "rewrite_system_prompt":
        if len(str(payload.get("proposed_prompt", ""))) < 100:
            return "proposed_prompt deve ter >=100 chars (anti-stub)"
    if kind == "consolidate_agents":
        sids = payload.get("source_agent_ids")
        if not isinstance(sids, list) or len(sids) < 2:
            return "source_agent_ids deve ser list com >=2 UUIDs"

    return None


async def _handle_recommend(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """VEC-408 sub-PR 2 (real): cria athena_recommendations status='pending'.

    Pipeline:
      1. Valida kind + target_agent_id (obrigatório se kind != hire_new_agent)
      2. Guardrails HARD (rejected_at_source, sem chamar Gemini):
         - target == ATHENA_AGENT_ID
         - target.is_system == True
      3. Idempotência: SELECT pending existente WHERE target_agent_id+kind
         → retorna pointer (status='idempotent_existing') sem chamar Gemini
      4. SELECT goal (se goal_id) + target agent (se target_agent_id)
      5. RAG corpus Athena com query específica por kind (best-effort)
      6. Gemini Flash gera title + rationale + proposed_changes_json +
         confidence + estimated_effort + citations
      7. Valida proposed_changes_json pelo kind (Python)
      8. INSERT em vectraclip.athena_recommendations status='pending'
      9. Pydantic RecommendOutput valida envelope
      10. Retorna envelope com recommendation_id

    NUNCA auto-aplica. Aprovação manual via UI (sub-PR 3 + frontend).

    Args:
        input_data: dict com `_supabase`, `_task_id`, `_company_id`,
                    `kind` (obrigatório), `target_agent_id` (cond.),
                    `goal_id` (opcional), `triggered_by_task_id` (opcional).
    """
    from datetime import datetime as _dt, timezone as _tz
    import json as _json

    from src.agents.athena_schemas import RecommendOutput, ValidationBlock
    from src.services.gemini_client import generate as gemini_generate

    started_at = _dt.now(_tz.utc).isoformat()
    supabase = input_data.get("_supabase")
    task_id = input_data.get("_task_id", "")
    company_id = input_data.get("_company_id")
    kind = (input_data.get("kind") or "").strip()
    target_agent_id = input_data.get("target_agent_id")
    goal_id = input_data.get("goal_id")
    triggered_by_task_id = input_data.get("triggered_by_task_id") or task_id

    if supabase is None:
        return _recommend_error_output(task_id, started_at, "missing_supabase",
                                       "Cliente Supabase não disponível", kind=kind)
    if not company_id:
        return _recommend_error_output(task_id, started_at, "missing_company_id",
                                       "task.company_id é obrigatório", kind=kind)
    if kind not in _RECOMMEND_VALID_KINDS:
        return _recommend_error_output(
            task_id, started_at, "invalid_kind",
            f"kind '{kind}' inválido. Esperado um de: {sorted(_RECOMMEND_VALID_KINDS)}",
            kind=kind,
        )
    if kind != "hire_new_agent" and not target_agent_id:
        return _recommend_error_output(
            task_id, started_at, "missing_target_agent",
            f"input.target_agent_id é obrigatório para kind={kind}", kind=kind,
        )

    # ─── 1) Guardrails HARD (sem chamar Gemini) ────────────────────────────
    target_agent: Optional[Dict[str, Any]] = None
    if target_agent_id:
        if str(target_agent_id) == ATHENA_AGENT_ID:
            return _recommend_rejected_envelope(
                task_id, started_at, kind, target_agent_id, None,
                "rejected_at_source: Athena nunca modifica a si mesma",
            )
        try:
            ta_res = (
                supabase.table("agents")
                .select("id,name,role,system_prompt,is_system,company_id")
                .eq("id", target_agent_id)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            return _recommend_error_output(
                task_id, started_at, "target_agent_select_failed",
                str(exc), kind=kind,
            )
        if not ta_res.data:
            return _recommend_error_output(
                task_id, started_at, "target_agent_not_found",
                f"target_agent_id={target_agent_id} não existe", kind=kind,
            )
        target_agent = ta_res.data[0]
        if str(target_agent.get("company_id")) != str(company_id):
            return _recommend_error_output(
                task_id, started_at, "company_mismatch",
                "target_agent_id pertence a outra company", kind=kind,
            )
        if target_agent.get("is_system"):
            return _recommend_rejected_envelope(
                task_id, started_at, kind, target_agent_id,
                target_agent.get("name"),
                "rejected_at_source: Athena não modifica agentes is_system=true",
            )

    # ─── 2) Idempotência (soft guard — UNIQUE PARTIAL é hard guard) ────────
    if target_agent_id and kind != "hire_new_agent":
        try:
            existing = (
                supabase.table("athena_recommendations")
                .select("id,title,confidence,created_at")
                .eq("target_agent_id", target_agent_id)
                .eq("kind", kind)
                .eq("status", "pending")
                .limit(1)
                .execute()
            )
            if existing.data:
                exist = existing.data[0]
                return _recommend_idempotent_envelope(
                    task_id, started_at, kind, target_agent_id,
                    (target_agent or {}).get("name") if target_agent else None,
                    exist["id"], exist.get("title", ""),
                    float(exist.get("confidence") or 0.0),
                )
        except Exception as exc:
            logger.warning("athena-recommend idempotency lookup failed (non-fatal): %s", exc)

    # ─── 3) Contexto: goal + companies.context_json + RAG ──────────────────
    goal_block: Dict[str, Any] = {}
    if goal_id:
        try:
            g_res = (
                supabase.table("goals")
                .select("id,title,metric,target,kind,confidence,business_case_strength,pmoia_metadata")
                .eq("id", goal_id)
                .limit(1)
                .execute()
            )
            if g_res.data:
                goal_block = g_res.data[0]
        except Exception as exc:
            logger.warning("athena-recommend goal lookup non-fatal: %s", exc)

    company_context = _get_company_context(supabase, company_id)

    rag_chunks: list = []
    rag_citations: list = []
    try:
        from src.services.athena_rag import query_top_k as _athena_query
        rag_query = _build_recommend_rag_query(kind)
        rag_results = await _athena_query(
            rag_query, company_id=company_id, k=4, min_score=0.3,
            supabase_client=supabase,
        )
        for r in rag_results:
            rag_chunks.append(
                f"[chunk {r.chunk_index} | score {r.score:.2f}]\n{r.content[:1500]}"
            )
            rag_citations.append({
                "chunk_id": r.id,
                "page": r.page_number,
                "source": r.document_filename,
                "text_excerpt": (r.content[:200] + "...") if r.content else None,
            })
    except Exception as exc:
        logger.warning("athena-recommend RAG indisponível (degradando): %s", exc)

    # ─── 4) Gemini structured output ───────────────────────────────────────
    user_prompt = _build_recommend_prompt(
        kind, goal_block, target_agent, company_context, rag_chunks,
    )
    try:
        text, llm_meta = await gemini_generate(
            ATHENA_DEFAULT_MODEL,
            user_prompt,
            system_instruction=_RECOMMEND_SYSTEM_PROMPT,
            response_mime_type="application/json",
        )
    except Exception as exc:
        logger.exception("athena-recommend gemini call failed task=%s", task_id)
        return _recommend_error_output(task_id, started_at, "gemini_call_failed",
                                       str(exc), kind=kind)
    try:
        gp = _json.loads(text)
    except Exception as exc:
        return _recommend_error_output(
            task_id, started_at, "gemini_invalid_json",
            f"JSON inválido: {exc}. Raw[:200]={text[:200]!r}", kind=kind,
        )

    # ─── 5) Valida proposed_changes_json pelo kind ─────────────────────────
    proposed = gp.get("proposed_changes_json") or {}
    val_err = _validate_proposed_changes_by_kind(kind, proposed)
    if val_err:
        return _recommend_error_output(
            task_id, started_at, "proposed_changes_invalid", val_err, kind=kind,
        )

    # ─── 6) INSERT em athena_recommendations ───────────────────────────────
    try:
        confidence = float(gp.get("confidence", 0.7))
        confidence = max(0.0, min(1.0, confidence))
        effort = gp.get("estimated_effort", "M")
        if effort not in ("S", "M", "L", "XL"):
            effort = "M"

        rec_row = {
            "company_id": company_id,
            "triggered_by_goal_id": goal_id,
            "triggered_by_task_id": triggered_by_task_id,
            "kind": kind,
            "target_agent_id": target_agent_id,
            "title": gp.get("title", f"Recomendação {kind}")[:500],
            "rationale": gp.get("rationale", "Rationale ausente — revisar manualmente."),
            "proposed_changes_json": proposed,
            "citations": rag_citations,
            "confidence": confidence,
            "estimated_effort": effort,
            "status": "pending",
        }
        ins = supabase.table("athena_recommendations").insert(rec_row).execute()
        if not ins.data:
            return _recommend_error_output(
                task_id, started_at, "insert_returned_empty",
                "INSERT em athena_recommendations retornou data vazia", kind=kind,
            )
        rec_id = ins.data[0]["id"]
    except Exception as exc:
        # UNIQUE PARTIAL pode pegar (race condition entre soft guard e INSERT)
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return _recommend_error_output(
                task_id, started_at, "race_unique_partial",
                f"UNIQUE PARTIAL bloqueou INSERT (race condition idempotência): {exc}",
                kind=kind,
            )
        logger.exception("athena-recommend INSERT failed task=%s", task_id)
        return _recommend_error_output(task_id, started_at, "insert_failed",
                                       str(exc), kind=kind)

    # ─── 7) Monta envelope final + valida Pydantic ─────────────────────────
    completed_at = _dt.now(_tz.utc).isoformat()
    tools = ["expert_judgment", "gap_analysis"]
    if rag_chunks:
        tools.append("rag_retrieval")

    envelope = {
        "handler_name": "athena-recommend",
        "execution_id": task_id,
        "execution_started_at": started_at,
        "execution_completed_at": completed_at,
        "inputs_used": {
            "kind": kind,
            "target_agent_id": target_agent_id,
            "goal_id": goal_id,
            "rag_chunks_used": len(rag_chunks),
        },
        "tools_techniques_applied": tools,
        "outputs": {
            "recommendation_id": rec_id,
            "status": "pending",
            "kind": kind,
            "target_agent_id": target_agent_id,
            "target_agent_name": (target_agent or {}).get("name") if target_agent else None,
            "title": rec_row["title"],
            "rationale": rec_row["rationale"],
            "proposed_changes_json": proposed,
            "confidence": confidence,
            "estimated_effort": effort,
            "citations": rag_citations,
            "rejected_reason": None,
        },
        "validation": ValidationBlock(
            all_required_inputs_present=True,
            confidence=confidence,
            warnings=[],
            needs_human_review=True,  # recommendation SEMPRE precisa review humano
        ).model_dump(),
        "citations": rag_citations,
    }

    try:
        RecommendOutput.model_validate(envelope)
    except Exception as exc:
        logger.exception("athena-recommend pydantic validation failed task=%s", task_id)
        # Pydantic falhou DEPOIS do INSERT — não vamos reverter; só sinalizar review
        envelope["validation"]["needs_human_review"] = True
        envelope["validation"]["warnings"] = [f"pydantic_validation_failed: {exc}"]

    # 8) Cost + WS broadcast (não-fatal)
    tokens = {
        "input": int(llm_meta.get("input_token_count") or 0),
        "output": int(llm_meta.get("output_token_count") or 0),
    }
    tokens["total"] = tokens["input"] + tokens["output"]
    envelope["metadata"] = {"tokens": tokens}
    cost_usd = _calc_cost(tokens)

    try:
        from src.ws_manager import manager as _ws
        await _ws.broadcast_company(company_id, {
            "type": "athena_recommendation_created",
            "recommendation_id": rec_id,
            "target_agent_id": target_agent_id,
            "kind": kind,
            "confidence": confidence,
        })
    except Exception as exc:
        logger.debug("athena-recommend WS broadcast non-fatal: %s", exc)

    logger.info(
        "athena-recommend done task=%s kind=%s target=%s rec=%s conf=%.2f effort=%s tokens=%d",
        task_id, kind, target_agent_id, rec_id, confidence, effort, tokens["total"],
    )

    return {
        "output_json": envelope,
        "cost_usd": cost_usd,
        "status_override": "done",
    }


def _recommend_error_output(
    task_id: str, started_at: str, code: str, message: str, kind: str = "",
) -> Dict[str, Any]:
    """Erro técnico — status=blocked. NÃO insere em DB."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "output_json": {
            "handler_name": "athena-recommend",
            "execution_id": task_id,
            "execution_started_at": started_at,
            "execution_completed_at": now,
            "inputs_used": {"kind": kind},
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


def _recommend_rejected_envelope(
    task_id: str, started_at: str, kind: str,
    target_agent_id: Optional[str], target_agent_name: Optional[str],
    reason: str,
) -> Dict[str, Any]:
    """Guardrail bloqueou (is_system ou Athena) — status=done com rejected_at_source.
    NÃO insere em DB. UI deve mostrar como recommendation morta, não como erro."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "output_json": {
            "handler_name": "athena-recommend",
            "execution_id": task_id,
            "execution_started_at": started_at,
            "execution_completed_at": now,
            "inputs_used": {"kind": kind, "target_agent_id": target_agent_id},
            "tools_techniques_applied": ["expert_judgment"],
            "outputs": {
                "recommendation_id": None,
                "status": "rejected_at_source",
                "kind": kind,
                "target_agent_id": target_agent_id,
                "target_agent_name": target_agent_name,
                "title": "Guardrail Athena: target protegido",
                "rationale": reason,
                "proposed_changes_json": {},
                "confidence": 1.0,
                "estimated_effort": "S",
                "citations": [],
                "rejected_reason": reason,
            },
            "validation": {
                "schema_version": ATHENA_SCHEMA_VERSION,
                "all_required_inputs_present": True,
                "confidence": 1.0,
                "warnings": [reason],
                "needs_human_review": False,
            },
            "citations": [],
            "metadata": {"tokens": {"input": 0, "output": 0, "total": 0}},
        },
        "cost_usd": 0.0,
        "status_override": "done",
    }


def _recommend_idempotent_envelope(
    task_id: str, started_at: str, kind: str,
    target_agent_id: str, target_agent_name: Optional[str],
    existing_rec_id: str, existing_title: str, existing_confidence: float,
) -> Dict[str, Any]:
    """Idempotência: já existe pending pra mesmo (target, kind).
    Retorna pointer pro existente. NÃO chama Gemini, NÃO insere."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "output_json": {
            "handler_name": "athena-recommend",
            "execution_id": task_id,
            "execution_started_at": started_at,
            "execution_completed_at": now,
            "inputs_used": {"kind": kind, "target_agent_id": target_agent_id},
            "tools_techniques_applied": ["expert_judgment"],
            "outputs": {
                "recommendation_id": existing_rec_id,
                "status": "idempotent_existing",
                "kind": kind,
                "target_agent_id": target_agent_id,
                "target_agent_name": target_agent_name,
                "title": existing_title,
                "rationale": "Recommendation pending pré-existente para mesmo (target_agent, kind). Aprovar/rejeitar a existente.",
                "proposed_changes_json": {},
                "confidence": existing_confidence,
                "estimated_effort": "S",
                "citations": [],
                "rejected_reason": None,
            },
            "validation": {
                "schema_version": ATHENA_SCHEMA_VERSION,
                "all_required_inputs_present": True,
                "confidence": 1.0,
                "warnings": ["idempotent_existing"],
                "needs_human_review": True,
            },
            "citations": [],
            "metadata": {"tokens": {"input": 0, "output": 0, "total": 0}},
        },
        "cost_usd": 0.0,
        "status_override": "done",
    }


def _build_recommend_rag_query(kind: str) -> str:
    """Query RAG específica por kind (chunks Heldman relevantes)."""
    return {
        "hire_new_agent":         "papel gerente projetos PMO contratação skills competências PMBOK cap 1 cap 5",
        "add_specialty":          "gerenciamento recursos humanos habilidades técnicas matriz competências",
        "rewrite_system_prompt":  "papel PM habilidades comunicação técnicas Heldman cap 5",
        "create_specialty":       "EAP definição responsabilidades domínio conhecimento PMBOK",
        "consolidate_agents":     "consolidação responsabilidades overlap projetos múltiplos agentes",
    }.get(kind, "papel gerente projetos PMBOK habilidades competências")


_RECOMMEND_SYSTEM_PROMPT = """Você é Athena, PMOia da Vectra Cargo, especialista em PMBOK 5ª (Kim Heldman cap.5 — papel do gerente de projetos). Aqui você atua como Agent Coverage Manager: propõe melhorias no quadro de agentes.

Sua tarefa: gerar UMA recomendação concreta de melhoria — sem auto-aplicar. Humano vai revisar e aprovar manualmente.

REGRAS HARD:
1. proposed_changes_json deve ter estrutura específica conforme kind:
   - hire_new_agent: {name, role, system_prompt (≥100 chars), specialties[]}
   - add_specialty: {agent_id, specialty_id, prompt_addendum}
   - rewrite_system_prompt: {agent_id, current_prompt, proposed_prompt (≥100 chars), diff_summary}
   - create_specialty: {name, slug, description, prompt_template}
   - consolidate_agents: {source_agent_ids (≥2), merged_prompt}
2. rationale (≥20 chars) cita critério PMBOK ou diagnóstico do quadro.
3. confidence ∈ [0,1]. Use 0.5-0.7 se há pouco contexto; 0.8-0.95 quando há evidência clara.
4. estimated_effort ∈ {S, M, L, XL}.
5. title concisa (≤80 chars).
6. NÃO sugira mudanças em agentes que parecem ser system (Oracle, Mnemos, Morpheus) — o sistema filtra isso de qualquer jeito.

FORMATO DE SAÍDA — apenas JSON, sem markdown wrapper:
{
  "title": "<≤80 chars>",
  "rationale": "<≥20 chars com critério PMBOK>",
  "proposed_changes_json": { <estrutura conforme kind acima> },
  "confidence": <float 0..1>,
  "estimated_effort": "S|M|L|XL"
}"""


def _build_recommend_prompt(
    kind: str,
    goal: Dict[str, Any],
    target_agent: Optional[Dict[str, Any]],
    company_context: Dict[str, Any],
    rag_chunks: list,
) -> str:
    import json as _json
    target_block = "(sem target — kind=hire_new_agent)"
    if target_agent:
        target_block = _json.dumps({
            "agent_id": target_agent.get("id"),
            "name": target_agent.get("name"),
            "role": target_agent.get("role"),
            "current_system_prompt": (target_agent.get("system_prompt") or "")[:2000],
            "current_prompt_length": len(target_agent.get("system_prompt") or ""),
            "is_system": target_agent.get("is_system"),
        }, ensure_ascii=False, indent=2)

    goal_block = "(sem goal vinculado)"
    if goal:
        goal_block = _json.dumps({
            "goal_id": goal.get("id"),
            "title": goal.get("title"),
            "kind": goal.get("kind"),
            "confidence": goal.get("confidence"),
        }, ensure_ascii=False, indent=2)

    rag_block = (
        "\n\n--- HELDMAN/PMBOK chunks ---\n" + "\n\n".join(rag_chunks)
        if rag_chunks else
        "\n\n(Sem chunks RAG — opere com expert_judgment.)"
    )

    return f"""KIND: {kind}

GOAL DISPARADOR (se houver)
===========================
{goal_block}

TARGET AGENT (se aplicável)
===========================
{target_block}

COMPANY CONTEXT
===============
{_json.dumps(company_context, ensure_ascii=False, indent=2) if company_context else '(sem context)'}
{rag_block}

INSTRUÇÃO
=========
Gere UMA recomendação concreta para o kind={kind}, seguindo as REGRAS HARD do system prompt.
Aplique a estrutura específica de proposed_changes_json para esse kind.
Retorne APENAS o JSON. Sem markdown wrapper, sem texto antes/depois."""


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


_PRIORITIZE_DEFAULT_CRITERIA = [
    {
        "key": "potencial_lucro",
        "label": "Potencial de Lucro",
        "weight": 0.30,
        "scoring_hints": [
            "1 = ROI estimado < R$ 5k/ano",
            "5 = ROI estimado > R$ 100k/ano",
        ],
    },
    {
        "key": "urgencia_estrategica",
        "label": "Urgência Estratégica",
        "weight": 0.25,
        "scoring_hints": [
            "1 = sem deadline ou janela > 12 meses",
            "5 = deadline < 3 meses ou risco regulatório iminente",
        ],
    },
    {
        "key": "alinhamento_portfolio",
        "label": "Alinhamento Portfólio",
        "weight": 0.25,
        "scoring_hints": [
            "1 = não conecta com strategic_priorities",
            "5 = entrega direta de prioridade estratégica top-3",
        ],
    },
    {
        "key": "viabilidade_recursos",
        "label": "Viabilidade de Recursos",
        "weight": 0.20,
        "scoring_hints": [
            "1 = equipe/agentes saturados, impacta projetos in_progress",
            "5 = recursos prontos, sem conflito",
        ],
    },
]


def _resolve_prioritization_criteria(
    company_context: Dict[str, Any],
) -> tuple[list, int]:
    """Resolve critérios de priorização: usa companies.context_json se válido,
    senão fallback hardcoded default. Retorna (criteria_list, version).

    Validações para usar DB criteria:
    - lista não-vazia
    - cada item tem key, label, weight
    - soma de weights = 1.0 (tolerância 0.01)
    """
    raw = (company_context or {}).get("prioritization_criteria") or {}
    db_criteria = raw.get("criteria")
    if not isinstance(db_criteria, list) or len(db_criteria) < 2:
        return [dict(c) for c in _PRIORITIZE_DEFAULT_CRITERIA], 0

    try:
        total_w = sum(float(c.get("weight", 0)) for c in db_criteria)
        if abs(total_w - 1.0) > 0.01:
            logger.warning(
                "athena-prioritize: DB criteria weights sum=%.4f (esperado 1.0). "
                "Usando default fallback.", total_w
            )
            return [dict(c) for c in _PRIORITIZE_DEFAULT_CRITERIA], 0
        # Normaliza pra schema esperado (drop campos extras)
        cleaned = []
        for c in db_criteria:
            cleaned.append({
                "key": c.get("key"),
                "label": c.get("label"),
                "weight": float(c.get("weight")),
                "scoring_hints": list(c.get("scoring_hints") or []),
            })
        version = int(raw.get("version") or 0)
        return cleaned, version
    except Exception as exc:
        logger.warning("athena-prioritize: erro ao parsear DB criteria (%s). Usando fallback.", exc)
        return [dict(c) for c in _PRIORITIZE_DEFAULT_CRITERIA], 0


def _compute_weighted_score(
    ratings_by_criterion: Dict[str, int],
    criteria: list,
) -> tuple[float, list]:
    """Calcula score ponderado para um goal a partir de ratings 1-5 por critério.

    Função PURA. Retorna (total_score, breakdown_list) onde breakdown contém
    weighted_contribution = rating × weight por critério.
    """
    breakdown = []
    total = 0.0
    for c in criteria:
        key = c["key"]
        rating = int(ratings_by_criterion.get(key, 0))
        if rating < 1 or rating > 5:
            raise ValueError(f"rating de '{key}' fora do range 1-5: {rating}")
        weight = float(c["weight"])
        wc = round(rating * weight, 4)
        total += wc
        breakdown.append({
            "criterion_key": key,
            "rating": rating,
            "weight": weight,
            "weighted_contribution": wc,
            # rationale será preenchido pelo handler com texto do Gemini
        })
    return round(total, 4), breakdown


async def _handle_prioritize(prompt: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """VEC-406 (real, output-only): ranking ponderado entre múltiplos goals
    (Heldman cap.4 weighted scoring).

    Pipeline:
      1. Lê goal_ids[] do input_data (2-10 goals da mesma company)
      2. SELECT goals + valida kind=project + conf>=0.7 + mesma company
      3. SELECT companies.context_json.prioritization_criteria
         (fallback default 4 critérios se ausente/inválido)
      4. Gemini pontua cada goal × critério (rating 1-5 + rationale curta)
      5. Python calcula score ponderado e ordena ranking
      6. Gemini gera narrative_md + recomendações
      7. Pydantic PrioritizeOutput strict valida

    Args:
        input_data: dict com `_supabase`, `_task_id`, `_company_id`,
                    `goal_ids` (List[str]), opcional `scope_note`.
    """
    from datetime import datetime as _dt, timezone as _tz
    import json as _json

    from src.agents.athena_schemas import PrioritizeOutput, ValidationBlock
    from src.services.gemini_client import generate as gemini_generate

    started_at = _dt.now(_tz.utc).isoformat()
    supabase = input_data.get("_supabase")
    task_id = input_data.get("_task_id", "")
    company_id = input_data.get("_company_id")
    goal_ids = input_data.get("goal_ids") or []
    scope_note = input_data.get("scope_note") or ""

    if supabase is None:
        return _prioritize_error_output(task_id, started_at, "missing_supabase",
                                        "Cliente Supabase não disponível")
    if not isinstance(goal_ids, list) or len(goal_ids) < 2 or len(goal_ids) > 10:
        return _prioritize_error_output(
            task_id, started_at, "invalid_goal_ids",
            f"input.goal_ids deve ter 2-10 entradas. Recebido: {len(goal_ids) if isinstance(goal_ids, list) else type(goal_ids).__name__}",
        )

    # 1) SELECT goals
    try:
        goals_res = (
            supabase.table("goals")
            .select("id,company_id,title,metric,target,kind,confidence,business_case_strength,pmoia_metadata")
            .in_("id", goal_ids)
            .execute()
        )
    except Exception as exc:
        logger.exception("athena-prioritize select goals failed task=%s: %s", task_id, exc)
        return _prioritize_error_output(task_id, started_at, "goals_select_failed", str(exc))

    goals = goals_res.data or []
    if len(goals) != len(goal_ids):
        missing = set(goal_ids) - {g["id"] for g in goals}
        return _prioritize_error_output(
            task_id, started_at, "goals_missing",
            f"Goals não encontrados: {sorted(missing)}",
        )

    # Cross-tenant guard
    companies_in_set = {str(g.get("company_id")) for g in goals}
    if len(companies_in_set) > 1:
        return _prioritize_error_output(
            task_id, started_at, "multi_company_goals",
            f"Goals de múltiplas companies não permitido: {companies_in_set}",
        )
    if company_id and companies_in_set != {str(company_id)}:
        return _prioritize_error_output(
            task_id, started_at, "company_mismatch",
            f"goals company_id != task company_id ({companies_in_set} != {company_id})",
        )

    # Defense-in-depth: todos goals precisam estar classificados como project
    bad_goals = []
    for g in goals:
        if g.get("kind") != "project":
            bad_goals.append(f"{g['id']}(kind={g.get('kind')!r})")
            continue
        try:
            if g.get("confidence") is None or float(g["confidence"]) < 0.7:
                bad_goals.append(f"{g['id']}(conf={g.get('confidence')})")
        except (TypeError, ValueError):
            bad_goals.append(f"{g['id']}(conf_invalid)")
    if bad_goals:
        return _prioritize_error_output(
            task_id, started_at, "goals_not_classified",
            f"athena-prioritize exige todos os goals kind=project + conf>=0.7. Inválidos: {bad_goals}",
        )

    # 2) Critérios (DB ou fallback)
    goals_company_id = next(iter(companies_in_set))
    company_context = _get_company_context(supabase, goals_company_id)
    criteria, criteria_version = _resolve_prioritization_criteria(company_context)

    # 3) Gemini pontua cada goal × critério
    user_prompt = _build_prioritize_prompt(goals, criteria, scope_note)
    try:
        text, llm_meta = await gemini_generate(
            ATHENA_DEFAULT_MODEL,
            user_prompt,
            system_instruction=_PRIORITIZE_SYSTEM_PROMPT,
            response_mime_type="application/json",
        )
    except Exception as exc:
        logger.exception("athena-prioritize gemini call failed task=%s", task_id)
        return _prioritize_error_output(task_id, started_at, "gemini_call_failed", str(exc))

    try:
        gemini_payload = _json.loads(text)
    except Exception as exc:
        return _prioritize_error_output(
            task_id, started_at, "gemini_invalid_json",
            f"JSON inválido: {exc}. Raw[:200]={text[:200]!r}",
        )

    # 4) Python calcula scores (anti-hallucination — Gemini só dá ratings)
    gemini_scores = gemini_payload.get("scores_by_goal") or {}
    if not isinstance(gemini_scores, dict):
        return _prioritize_error_output(
            task_id, started_at, "gemini_missing_scores",
            f"Gemini retornou scores_by_goal inválido: type={type(gemini_scores).__name__}",
        )

    ranking = []
    for g in goals:
        gid = str(g["id"])
        gscore_block = gemini_scores.get(gid)
        if not isinstance(gscore_block, dict):
            return _prioritize_error_output(
                task_id, started_at, "missing_scores_for_goal",
                f"Gemini não retornou scores_by_goal['{gid}']. Disponíveis: {list(gemini_scores.keys())}",
            )
        ratings = gscore_block.get("ratings") or {}
        rationales = gscore_block.get("rationales") or {}
        try:
            total, breakdown_partial = _compute_weighted_score(ratings, criteria)
        except Exception as exc:
            return _prioritize_error_output(
                task_id, started_at, "compute_failed",
                f"Erro ao calcular score do goal {gid}: {exc}",
            )
        # Preenche rationale por critério
        for item in breakdown_partial:
            item["rationale"] = (rationales.get(item["criterion_key"])
                                  or "Avaliação automática Athena").strip()
            if len(item["rationale"]) < 10:
                item["rationale"] = item["rationale"] + " (Athena PMOia weighted scoring)"
        ranking.append({
            "goal_id": gid,
            "goal_title": g.get("title") or "(sem título)",
            "total_score": total,
            "breakdown": breakdown_partial,
        })

    # 5) Ordena DESC e atribui rank sequencial
    ranking.sort(key=lambda r: r["total_score"], reverse=True)
    for i, r in enumerate(ranking, start=1):
        r["rank"] = i

    # 6) Monta envelope
    completed_at = _dt.now(_tz.utc).isoformat()
    envelope = {
        "handler_name": "athena-prioritize",
        "execution_id": task_id,
        "execution_started_at": started_at,
        "execution_completed_at": completed_at,
        "inputs_used": {
            "goal_ids": [str(g) for g in goal_ids],
            "goals_count": len(goals),
            "weights_used": {c["key"]: c["weight"] for c in criteria},
            "criteria_version": criteria_version,
            "scope_note": scope_note,
        },
        "tools_techniques_applied": ["expert_judgment", "weighted_scoring"],
        "outputs": {
            "ranking": ranking,
            "narrative_md": gemini_payload.get("narrative_md", ""),
            "execution_recommendations": gemini_payload.get("execution_recommendations", []),
            "score_gaps": gemini_payload.get("score_gaps", {
                "largest_gap": "Análise de gap não disponível",
                "tightest_competition": "Análise de empate não disponível",
            }),
            "criteria_used": criteria,
            "criteria_version": criteria_version,
        },
        "validation": ValidationBlock(
            all_required_inputs_present=True,
            confidence=0.9,
            warnings=[],
            needs_human_review=False,
        ).model_dump(),
        "citations": [],
    }

    try:
        PrioritizeOutput.model_validate(envelope)
    except Exception as exc:
        logger.exception("athena-prioritize pydantic validation failed task=%s", task_id)
        return _prioritize_error_output(
            task_id, started_at, "pydantic_validation_failed",
            f"{exc}. ranking_count={len(ranking)}",
        )

    # 7) Cost
    tokens = {
        "input": int(llm_meta.get("input_token_count") or 0),
        "output": int(llm_meta.get("output_token_count") or 0),
    }
    tokens["total"] = tokens["input"] + tokens["output"]
    envelope["metadata"] = {"tokens": tokens}
    cost_usd = _calc_cost(tokens)

    logger.info(
        "athena-prioritize done task=%s goals=%d criteria=%d top=%s(%.2f) tokens=%d cost=%.6f",
        task_id, len(goals), len(criteria),
        ranking[0]["goal_id"][:8], ranking[0]["total_score"],
        tokens["total"], cost_usd,
    )

    return {
        "output_json": envelope,
        "cost_usd": cost_usd,
        "status_override": "done",
    }


def _prioritize_error_output(
    task_id: str, started_at: str, code: str, message: str,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "output_json": {
            "handler_name": "athena-prioritize",
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


_PRIORITIZE_SYSTEM_PROMPT = """Você é Athena, PMOia da Vectra Cargo, especialista em PMBOK 5ª (Kim Heldman, cap.4 — modelos de seleção de projetos por pontuação ponderada).

Sua tarefa: pontuar cada GOAL contra cada CRITÉRIO em escala 1-5 e fornecer rationale curta por (goal × critério). **NÃO calcule scores ponderados** — Python faz isso a partir dos seus ratings. Sua função é avaliar 1-5.

REGRAS HARD:
1. rating ∈ {1, 2, 3, 4, 5} (inteiro). Qualquer outro valor é REJEITADO.
2. Para CADA goal, pontue TODOS os critérios fornecidos. Omitir critério = REJEITADO.
3. rationale por (goal × critério) ≥10 chars, concreta. Cite fato do goal (ex: deadline, ROI estimado).
4. narrative_md ≥100 chars com 2-4 parágrafos cobrindo: contexto do batch, top-3 e por que, riscos do desempate.
5. execution_recommendations ≥1: passos acionáveis (ex: "Iniciar charter do Goal #1 imediatamente", "Goal #2 pode rodar em paralelo se RH ok").
6. score_gaps.largest_gap + score_gaps.tightest_competition: descrição textual de onde o ranking é claro vs ambíguo.

FORMATO DE SAÍDA — apenas JSON, sem markdown:
{
  "scores_by_goal": {
    "<goal_uuid>": {
      "ratings": {
        "<criterion_key_1>": <1-5>,
        "<criterion_key_2>": <1-5>,
        ...
      },
      "rationales": {
        "<criterion_key_1>": "<≥10 chars>",
        "<criterion_key_2>": "<≥10 chars>",
        ...
      }
    },
    "<goal_uuid_2>": { ... }
  },
  "narrative_md": "## Ranking Analysis\\n\\n...",
  "execution_recommendations": ["...", "..."],
  "score_gaps": {
    "largest_gap": "rank 1 → rank 2 com diferença de X",
    "tightest_competition": "rank N e N+1 quase empatados"
  }
}"""


def _build_prioritize_prompt(
    goals: list,
    criteria: list,
    scope_note: str,
) -> str:
    import json as _json

    goals_block = []
    for g in goals:
        pmoia = g.get("pmoia_metadata") or {}
        rationale = pmoia.get("classification_rationale") or "(não disponível)"
        goals_block.append({
            "goal_id": g["id"],
            "title": g.get("title"),
            "metric": g.get("metric"),
            "target": g.get("target"),
            "kind": g.get("kind"),
            "confidence": g.get("confidence"),
            "business_case_strength": g.get("business_case_strength"),
            "classification_rationale": rationale,
        })

    criteria_block = [
        {
            "key": c["key"],
            "label": c["label"],
            "weight": c["weight"],
            "scoring_hints": c.get("scoring_hints", []),
        }
        for c in criteria
    ]

    return f"""SCOPE
=====
{scope_note or '(sem escopo extra)'}

GOALS A RANKEAR ({len(goals)} entradas)
========================================
{_json.dumps(goals_block, ensure_ascii=False, indent=2)}

CRITÉRIOS DE PONTUAÇÃO (com weights — Python calcula score final)
==================================================================
{_json.dumps(criteria_block, ensure_ascii=False, indent=2)}

INSTRUÇÃO
=========
Para CADA goal, pontue CADA critério em 1-5 com rationale concreta (cite fato do goal).
Use as scoring_hints como guia. NÃO calcule total_score — Python faz isso.
Retorne APENAS o JSON conforme schema do system prompt. Sem markdown wrapper."""


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
    "athena-audit":            _handle_audit,
    "athena-recommend":        _handle_recommend,
    # VEC-390 (Prioritizer — mandato 3)
    "athena-prioritize":       _handle_prioritize,
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
