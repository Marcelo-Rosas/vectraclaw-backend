"""specialty_generic — executor catalog-driven de specialties.

Roda QUALQUER `agent_specialties` atribuída a um agente via seu
`system_prompt_template` + `config_schema`, sem handler Python dedicado.
Substitui o caminho `claude -p` DEPRECATED do daemon (ver agent_daemon.py).

Fluxo:
  1. daemon resolve `task["_resolved_specialty"]` (ResolvedSpecialty) +
     `_resolved_config` (agent_specialty_configs.values) + `_resolved_shared`.
  2. aqui: resolve valores (config > shared > defaults), renderiza o
     system_prompt_template, chama `generate_for_agent` (provider do agente,
     W5 hybrid + vault) e devolve {status, output_text, output_json}.
  3. hooks opcionais por slug:
       - INPUT_BUILDERS[slug](task, supabase, values) -> contexto extra no prompt
         (ex.: workflow-builder lê componentes SIPOC).
       - EFFECTS[slug](task, supabase, parsed_json, values) -> efeito colateral
         com a saída estruturada (ex.: workflow-builder escreve workflow_steps).
     Sem hook registrado = LLM puro, saída só em output_json.

Decisão Marcelo 2026-06-20: especialidades são catálogo atribuível; execução
é genérica via template, não Python por op_type. workflow-builder é o 1º cliente
(PR2). Zero-hardcode: provider/model/prompt/config vêm do catálogo.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from src.services.agent_llm import generate_for_agent
from src.services.specialty_resolver import render_system_prompt, resolve_value

logger = logging.getLogger("SpecialtyGeneric")

# Registries por slug de specialty. Populados por módulos clientes (PR2+).
# InputBuilder: devolve string de contexto extra pro user prompt (ou None).
InputBuilder = Callable[[Dict[str, Any], Any, Dict[str, Any]], Optional[str]]
# Effect: aplica efeito colateral com o JSON parseado; devolve dict de resumo.
Effect = Callable[[Dict[str, Any], Any, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]

INPUT_BUILDERS: Dict[str, InputBuilder] = {}
EFFECTS: Dict[str, Effect] = {}


def register_input_builder(slug: str, fn: InputBuilder) -> None:
    INPUT_BUILDERS[slug] = fn


def register_effect(slug: str, fn: Effect) -> None:
    EFFECTS[slug] = fn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _envelope(status: str, output_text: str, output_json: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": status, "output_text": output_text, "output_json": output_json}


def _error(task_id: str, op_type: str, started: str, code: str, message: str) -> Dict[str, Any]:
    logger.warning("specialty_generic error task=%s op=%s code=%s: %s", task_id, op_type, code, message)
    return _envelope(
        "error",
        message,
        {
            "handler_name": "specialty-generic",
            "execution_id": task_id,
            "error": {"code": code, "message": message},
            "execution_started_at": started,
            "execution_completed_at": _now_iso(),
        },
    )


def _resolve_template_values(spec: Any, config_values: Dict[str, Any],
                             shared_values: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve cada chave do config_schema pela cadeia de precedência + vars especiais."""
    defaults = spec.defaults if hasattr(spec, "defaults") else {}
    keys = set(defaults) | set(config_values or {}) | set(shared_values or {})
    out: Dict[str, Any] = {}
    for key in keys:
        out[key] = resolve_value(
            key,
            payload=payload,
            config_values=config_values,
            shared_values=shared_values,
            specialty_defaults=defaults,
            env_default=None,
        )
    # vars especiais do template (convenção VectraClaw)
    out.setdefault("DOMAIN", getattr(spec, "domain", "") or "")
    out.setdefault("AGENT_NAME", getattr(spec, "name", "") or "")
    return out


def _build_user_prompt(task: Dict[str, Any], extra_context: Optional[str]) -> str:
    parts = []
    title = task.get("title") or ""
    desc = task.get("description") or ""
    if title:
        parts.append(f"Tarefa: {title}")
    if desc:
        parts.append(desc)
    input_json = task.get("input_json")
    if isinstance(input_json, dict) and input_json:
        # Remove chaves internas (resolved_*) — não fazem parte do input do usuário.
        clean = {k: v for k, v in input_json.items() if not k.startswith("_")}
        if clean:
            parts.append("Input:\n" + json.dumps(clean, ensure_ascii=False, indent=2))
    if extra_context:
        parts.append(extra_context)
    return "\n\n".join(parts) or title or "(sem conteúdo)"


def _safe_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"_list": parsed}
    except Exception:
        # tenta extrair o primeiro objeto {...} embutido
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                return None
        return None


async def execute_specialty(task: Dict[str, Any], supabase: Any) -> Dict[str, Any]:
    """Entrypoint chamado pelo daemon quando há `_resolved_specialty` com template."""
    started = _now_iso()
    task_id = str(task.get("id") or "")
    op_type = str(task.get("operation_type") or "")
    agent_id = task.get("assigned_to_agent_id")
    spec = task.get("_resolved_specialty")

    if spec is None or not getattr(spec, "system_prompt_template", ""):
        return _error(task_id, op_type, started, "no_specialty_template",
                      "Sem _resolved_specialty/system_prompt_template — não executável pelo motor genérico.")
    if not agent_id:
        return _error(task_id, op_type, started, "no_agent",
                      "Task sem assigned_to_agent_id — não há adapter de LLM pra resolver.")

    config_values = dict(task.get("_resolved_config") or {})
    shared_values = dict(task.get("_resolved_shared") or {})
    payload = task.get("input_json") if isinstance(task.get("input_json"), dict) else {}

    values = _resolve_template_values(spec, config_values, shared_values, payload)
    slug = str(getattr(spec, "slug", "") or "")

    # input-builder hook (ex.: workflow-builder injeta componentes SIPOC)
    extra_context: Optional[str] = None
    builder = INPUT_BUILDERS.get(slug)
    if builder:
        try:
            extra_context = builder(task, supabase, values)
        except Exception as exc:
            return _error(task_id, op_type, started, "input_builder_failed",
                          f"input_builder[{slug}] falhou: {exc}")

    system_prompt = render_system_prompt(spec.system_prompt_template, values, task)
    user_prompt = _build_user_prompt(task, extra_context)

    effect = EFFECTS.get(slug)
    want_json = effect is not None or str(values.get("output_format") or "").lower() == "json"

    logger.info("specialty_generic run task=%s slug=%s agent=%s json=%s", task_id, slug, agent_id, want_json)
    try:
        text, meta = await generate_for_agent(
            str(agent_id), user_prompt,
            system_instruction=system_prompt,
            response_mime_type="application/json" if want_json else None,
            fallback_model=values.get("gemini_model") or values.get("model_id"),
        )
    except Exception as exc:
        return _error(task_id, op_type, started, "llm_call_failed", f"generate_for_agent falhou: {exc}")

    parsed = _safe_json(text) if want_json else None
    effect_out: Optional[Dict[str, Any]] = None
    if effect:
        if parsed is None:
            return _error(task_id, op_type, started, "invalid_json_output",
                          f"specialty {slug} exige JSON estruturado mas a saída não parseou.")
        try:
            effect_out = effect(task, supabase, parsed, values)
        except Exception as exc:
            return _error(task_id, op_type, started, "effect_failed", f"effect[{slug}] falhou: {exc}")

    output_text = text
    if effect_out and isinstance(effect_out, dict) and effect_out.get("summary"):
        output_text = str(effect_out["summary"])

    output_json = {
        "handler_name": "specialty-generic",
        "specialty_slug": slug,
        "execution_id": task_id,
        "outputs": parsed if parsed is not None else {"text": text},
        "effect": effect_out,
        "metadata": meta,
        "execution_started_at": started,
        "execution_completed_at": _now_iso(),
    }
    return _envelope("succeeded", output_text, output_json)
