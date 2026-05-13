"""Specialty Resolver — fonte de verdade para system_prompt + config dos agentes.

Pré-refatoração (VEC-XXX): `agent_specialties.system_prompt_template` e
`agent_specialty_configs.values` eram UI-only. Os handlers nativos liam apenas
`task.description` (KEY=VALUE) e o fallback `claude -p` lia `agents.system_prompt`.

Este módulo unifica a leitura num único ponto. Cadeia de precedência:

    payload (task.input_json)
        > config_values (agent_specialty_configs.values)
        > specialty_defaults (agent_specialties.config_schema)
        > env_default (literal do handler)

Funções públicas:
    resolve_specialty(client, agent_id, operation_type) -> ResolvedSpecialty | None
    resolve_config(client, agent_id, specialty_id, company_id) -> dict
    render_system_prompt(template, values, task) -> str
    resolve_value(key, *, payload, config_values, specialty_defaults, env_default) -> Any

O módulo é puro: recebe `client: Any` (Supabase) como argumento e nunca toca
em singletons. Pode ser testado com FakeSupabase / MagicMock.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger("SpecialtyResolver")


@dataclass
class ResolvedSpecialty:
    """Specialty enriquecida com defaults extraídos do config_schema."""

    id: str
    slug: str
    name: str
    domain: str
    system_prompt_template: str
    config_schema: Dict[str, Any] = field(default_factory=dict)

    @property
    def defaults(self) -> Dict[str, Any]:
        """Defaults declarados em `config_schema.properties[*].default`.

        Convenção JSON Schema: cada campo editável pode declarar um `default`.
        Devolve dict `{key: default_value}` para uso em `resolve_value`.
        """
        props = (self.config_schema or {}).get("properties") or {}
        out: Dict[str, Any] = {}
        for key, spec in props.items():
            if isinstance(spec, dict) and "default" in spec:
                out[key] = spec["default"]
        return out


def resolve_specialty(
    client: Any, agent_id: Optional[str], operation_type: Optional[str]
) -> Optional[ResolvedSpecialty]:
    """Acha a specialty do agente cujo `slug` ou `id` casa com `operation_type`.

    Itera `agent_specialty_configs` filtrado por `agent_id` e faz join com
    `agent_specialties`. Retorna a primeira specialty cujo `slug` ou `id`
    coincida com `operation_type`. Convenção do projeto: slug == operation_type.

    Falha silenciosa (retorna None + log warning) — handler deve seguir com
    fallback legado.
    """
    if not client or not agent_id or not operation_type:
        return None
    try:
        res = (
            client.table("agent_specialty_configs")
            .select(
                "specialty_id, "
                "agent_specialties(id, slug, name, domain, system_prompt_template, config_schema)"
            )
            .eq("agent_id", agent_id)
            .execute()
        )
        rows = getattr(res, "data", None) or []
        for row in rows:
            spec_data = row.get("agent_specialties")
            # PostgREST join pode vir como dict (1:1) ou list (*:1) dependendo
            # da inferência da relação. Normaliza para dict.
            if isinstance(spec_data, list):
                spec_data = spec_data[0] if spec_data else None
            if not spec_data:
                continue
            spec_id = spec_data.get("id") or row.get("specialty_id")
            spec_slug = spec_data.get("slug")
            if operation_type in (spec_id, spec_slug):
                return ResolvedSpecialty(
                    id=str(spec_id or ""),
                    slug=spec_slug or "",
                    name=spec_data.get("name") or "",
                    domain=spec_data.get("domain") or "",
                    system_prompt_template=spec_data.get("system_prompt_template") or "",
                    config_schema=spec_data.get("config_schema") or {},
                )
        return None
    except Exception as exc:
        logger.warning(
            "resolve_specialty failed agent=%s op=%s: %s", agent_id, operation_type, exc
        )
        return None


def resolve_config(
    client: Any,
    agent_id: Optional[str],
    specialty_id: Optional[str],
    company_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Lê `agent_specialty_configs.values` para o par (agent, specialty[, company]).

    `company_id` é opcional mas recomendado em ambiente multi-tenant (uma
    specialty pode ter configs por company). Retorna `{}` se não encontrar.
    """
    if not client or not agent_id or not specialty_id:
        return {}
    try:
        q = (
            client.table("agent_specialty_configs")
            .select("values, company_id")
            .eq("agent_id", agent_id)
            .eq("specialty_id", specialty_id)
        )
        if company_id:
            q = q.eq("company_id", company_id)
        res = q.limit(1).execute()
        rows = getattr(res, "data", None) or []
        if not rows:
            return {}
        return rows[0].get("values") or {}
    except Exception as exc:
        logger.warning(
            "resolve_config failed agent=%s spec=%s: %s", agent_id, specialty_id, exc
        )
        return {}


_PLACEHOLDER_RE = re.compile(r"\{\{\s*([\w\.]+)\s*\}\}")


def render_system_prompt(
    template: Optional[str],
    values: Optional[Dict[str, Any]] = None,
    task: Optional[Dict[str, Any]] = None,
) -> str:
    """Substitui `{{ placeholders }}` no template por `values` e `task`.

    Sintaxe (sem Jinja2 — evita dependência):
        {{ key }}                  → values["key"]
        {{ task.title }}            → task["title"]
        {{ task.input_json.foo }}   → task["input_json"]["foo"]

    Placeholders não resolvidos viram string vazia (não levanta exceção).
    """
    if not template:
        return ""
    if not values and not task:
        return template

    ctx_values = values or {}
    ctx_task = task or {}

    def _walk(source: Any, parts: list[str]) -> Any:
        current = source
        for p in parts:
            if not isinstance(current, dict):
                return None
            current = current.get(p)
            if current is None:
                return None
        return current

    def _lookup(path: str) -> str:
        parts = path.strip().split(".")
        if not parts:
            return ""
        if parts[0] == "task":
            val = _walk(ctx_task, parts[1:])
        else:
            val = _walk(ctx_values, parts)
        return "" if val is None else str(val)

    return _PLACEHOLDER_RE.sub(lambda m: _lookup(m.group(1)), template)


_MISSING = object()


def resolve_value(
    key: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    config_values: Optional[Dict[str, Any]] = None,
    specialty_defaults: Optional[Dict[str, Any]] = None,
    env_default: Any = _MISSING,
) -> Any:
    """Cadeia de precedência para resolver um valor de configuração:

        1. payload[key]              (override por execução — task.input_json)
        2. config_values[key]        (agent_specialty_configs.values)
        3. specialty_defaults[key]   (agent_specialties.config_schema defaults)
        4. env_default               (literal passado pelo handler; opcional)

    Considera `None` em qualquer fonte como "não preenchido" e segue para a
    próxima. Retorna `None` se nada bater e `env_default` não foi fornecido.
    """
    for source in (payload, config_values, specialty_defaults):
        if source and key in source and source[key] is not None:
            return source[key]
    if env_default is not _MISSING:
        return env_default
    return None
