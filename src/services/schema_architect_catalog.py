"""Catálogos admin com JSON schema — carga e persistência para Schema Architect."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("SchemaArchitectCatalog")

CATALOG_AGENT_SPECIALTY = "agent_specialty"
CATALOG_ADAPTER_RUNTIME_PROFILE = "adapter_runtime_profile"
CATALOG_MCP_SERVER = "mcp_server"
CATALOG_AGENT_EXECUTION_MODE = "agent_execution_mode"

VALID_CATALOG_TYPES = frozenset({
    CATALOG_AGENT_SPECIALTY,
    CATALOG_ADAPTER_RUNTIME_PROFILE,
    CATALOG_MCP_SERVER,
    CATALOG_AGENT_EXECUTION_MODE,
})


@dataclass(frozen=True)
class CatalogTypeMeta:
    id: str
    label: str
    admin_route: str
    schema_column: str
    table: str
    shape_hint: str


CATALOG_REGISTRY: Dict[str, CatalogTypeMeta] = {
    CATALOG_AGENT_SPECIALTY: CatalogTypeMeta(
        id=CATALOG_AGENT_SPECIALTY,
        label="Especialidades de agente",
        admin_route="/admin/specialties",
        schema_column="config_schema",
        table="agent_specialties",
        shape_hint=(
            "Array JSON de definições de campo para formulário dinâmico. "
            "Cada item: key, label, type (text|textarea|number|boolean|secret|select|multiselect|url), "
            "required (boolean), defaultValue opcional, options (array de strings) se select, placeholder opcional."
        ),
    ),
    CATALOG_ADAPTER_RUNTIME_PROFILE: CatalogTypeMeta(
        id=CATALOG_ADAPTER_RUNTIME_PROFILE,
        label="Perfis de runtime (Connectors)",
        admin_route="/admin/connectors",
        schema_column="field_definitions_template",
        table="adapter_runtime_profiles",
        shape_hint=(
            "Array JSON de campos do template do perfil. "
            "Cada item: fieldKey, fieldLabel, fieldType, isRequired, optionsJson (objeto ou null), sortOrder (número)."
        ),
    ),
    CATALOG_MCP_SERVER: CatalogTypeMeta(
        id=CATALOG_MCP_SERVER,
        label="MCP Servers (catálogo)",
        admin_route="/admin/mcp",
        schema_column="field_definitions",
        table="mcp_server_catalog",
        shape_hint=(
            "Array JSON de credenciais/campos do servidor MCP. "
            "Cada item: fieldKey, fieldLabel opcional, fieldType, isRequired opcional, sortOrder opcional."
        ),
    ),
    CATALOG_AGENT_EXECUTION_MODE: CatalogTypeMeta(
        id=CATALOG_AGENT_EXECUTION_MODE,
        label="Modos de execução de agente",
        admin_route="/admin/agent-builder",
        schema_column="config_schema",
        table="agent_execution_modes",
        shape_hint=(
            "Array JSON de campos de configuração do modo. "
            "Cada item: key, label, type, required opcional, default opcional, description opcional, "
            "options (array {value, label}) se type=select."
        ),
    ),
}


def list_catalog_types() -> List[Dict[str, str]]:
    return [
        {
            "id": m.id,
            "label": m.label,
            "adminRoute": m.admin_route,
        }
        for m in CATALOG_REGISTRY.values()
    ]


def _row_name(row: Dict[str, Any]) -> str:
    return str(row.get("name") or row.get("id") or "")


def _row_description(row: Dict[str, Any]) -> str:
    return str(row.get("description") or "")


def _schema_from_row(meta: CatalogTypeMeta, row: Dict[str, Any]) -> Any:
    return row.get(meta.schema_column)


def load_catalog_item(supabase, catalog_type: str, catalog_id: str) -> Dict[str, Any]:
    """Carrega item do catálogo + metadados para o Schema Architect."""
    if catalog_type not in VALID_CATALOG_TYPES:
        raise ValueError("invalid_catalog_type")
    meta = CATALOG_REGISTRY[catalog_type]
    res = (
        supabase.table(meta.table)
        .select("*")
        .eq("id", catalog_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise LookupError("catalog_item_not_found")
    row = res.data[0]
    schema = _schema_from_row(meta, row)
    return {
        "catalogType": catalog_type,
        "catalogId": catalog_id,
        "name": _row_name(row),
        "description": _row_description(row),
        "schema": schema,
        "schemaJson": json.dumps(schema, ensure_ascii=False, indent=2)
        if schema is not None
        else "",
        "shapeHint": meta.shape_hint,
        "extra": _extra_fields(catalog_type, row),
    }


def _extra_fields(catalog_type: str, row: Dict[str, Any]) -> Dict[str, Any]:
    if catalog_type == CATALOG_AGENT_SPECIALTY:
        return {
            "slug": row.get("slug"),
            "domain": row.get("domain"),
            "systemPromptTemplate": (row.get("system_prompt_template") or "")[:500],
        }
    if catalog_type == CATALOG_ADAPTER_RUNTIME_PROFILE:
        return {"defaultProvider": row.get("default_provider")}
    if catalog_type == CATALOG_MCP_SERVER:
        return {
            "transport": row.get("transport"),
            "category": row.get("category"),
        }
    return {}


def list_catalog_items(supabase, catalog_type: str, *, include_inactive: bool = False) -> List[Dict[str, Any]]:
    if catalog_type not in VALID_CATALOG_TYPES:
        raise ValueError("invalid_catalog_type")
    meta = CATALOG_REGISTRY[catalog_type]
    q = supabase.table(meta.table).select(f"id,name,description,{meta.schema_column},is_active")
    if not include_inactive:
        q = q.eq("is_active", True)
    order_col = "display_order" if catalog_type != CATALOG_AGENT_SPECIALTY else "name"
    try:
        res = q.order(order_col).execute()
    except Exception:
        res = q.order("name").execute()
    items: List[Dict[str, Any]] = []
    for row in res.data or []:
        schema = _schema_from_row(meta, row)
        field_count = len(schema) if isinstance(schema, list) else (1 if schema else 0)
        items.append({
            "id": row.get("id"),
            "name": _row_name(row),
            "description": _row_description(row),
            "hasSchema": bool(schema),
            "fieldCount": field_count,
            "isActive": row.get("is_active", True),
        })
    return items


def apply_catalog_schema(
    supabase,
    catalog_type: str,
    catalog_id: str,
    schema_payload: Any,
) -> Dict[str, Any]:
    """Persiste schema no catálogo (service_role)."""
    if catalog_type not in VALID_CATALOG_TYPES:
        raise ValueError("invalid_catalog_type")
    if not isinstance(schema_payload, list):
        raise ValueError("schema_must_be_array")
    meta = CATALOG_REGISTRY[catalog_type]
    res = (
        supabase.table(meta.table)
        .update({meta.schema_column: schema_payload})
        .eq("id", catalog_id)
        .execute()
    )
    if not res.data:
        raise LookupError("catalog_item_not_found")
    logger.info(
        "schema_architect apply catalog=%s id=%s fields=%d",
        catalog_type,
        catalog_id,
        len(schema_payload),
    )
    return load_catalog_item(supabase, catalog_type, catalog_id)
