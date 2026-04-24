"""Traduz ferramentas locais para formato Anthropic SDK."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("ToolTranslator")

SCHEMAS_PATH = Path(__file__).resolve().parent / "tool_schemas.json"


@dataclass(frozen=True)
class AnthropicToolInput:
    """Definição de parâmetro de entrada de uma ferramenta Anthropic."""
    type: str
    description: str
    enum: Optional[list[str]] = None


@dataclass(frozen=True)
class AnthropicToolSchema:
    """Schema de entrada para uma ferramenta no formato Anthropic."""
    type: str
    properties: dict[str, dict[str, Any]]
    required: list[str]


@dataclass(frozen=True)
class AnthropicTool:
    """Definição de ferramenta no formato Anthropic SDK."""
    name: str
    description: str
    input_schema: AnthropicToolSchema


def load_tool_schemas() -> dict[str, dict[str, Any]]:
    """Carrega mapeamento de schemas de ferramentas."""
    try:
        if SCHEMAS_PATH.exists():
            with open(SCHEMAS_PATH, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Falha ao carregar schemas: {e}. Usando defaults.")

    return get_default_tool_schemas()


def get_default_tool_schemas() -> dict[str, dict[str, Any]]:
    """Schemas padrão para as ferramentas M3 principais."""
    return {
        "calculate_cbm": {
            "description": "Calcula o Cubo Metragem (CBM) em metros cúbicos com exatidão matemática.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "length_cm": {
                        "type": "number",
                        "description": "Comprimento em centímetros"
                    },
                    "width_cm": {
                        "type": "number",
                        "description": "Largura em centímetros"
                    },
                    "height_cm": {
                        "type": "number",
                        "description": "Altura em centímetros"
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Quantidade de itens (padrão: 1)",
                        "default": 1
                    }
                },
                "required": ["length_cm", "width_cm", "height_cm"]
            },
            "timeout_seconds": 10,
            "input_parser": "json",
            "output_parser": "json"
        },
        "extract_bl_pl": {
            "description": "Extrai dados de documentos logísticos (BL/PL) via OCR com suporte a PDF.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Caminho do arquivo PDF local"
                    },
                    "base64_content": {
                        "type": "string",
                        "description": "Conteúdo PDF codificado em base64"
                    },
                    "cross_ref": {
                        "type": "boolean",
                        "description": "Cruzar referências entre BL e PL se documento misto",
                        "default": False
                    }
                },
                "required": []
            },
            "timeout_seconds": 30,
            "input_parser": "json",
            "output_parser": "json"
        },
        "send_whatsapp_webhook": {
            "description": "Envia mensagem WhatsApp via Meta Cloud API (texto ou template).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Número de telefone com código de país (+55xx)"
                    },
                    "message": {
                        "type": "string",
                        "description": "Mensagem de texto a enviar"
                    },
                    "type": {
                        "type": "string",
                        "enum": ["text", "template"],
                        "description": "Tipo de mensagem (texto ou template)",
                        "default": "text"
                    },
                    "template_name": {
                        "type": "string",
                        "description": "Nome do template (se type=template)"
                    },
                    "language": {
                        "type": "string",
                        "description": "Código de idioma (padrão: pt_BR)",
                        "default": "pt_BR"
                    }
                },
                "required": ["phone"]
            },
            "timeout_seconds": 15,
            "input_parser": "json",
            "output_parser": "json"
        }
    }


def translate_tools_to_anthropic(
    tool_names: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """
    Traduz ferramentas locais para formato Anthropic.

    Args:
        tool_names: Lista de nomes de ferramentas a incluir. Se None, usa defaults.

    Returns:
        Lista de tools no formato Anthropic SDK.
    """
    schemas = load_tool_schemas()

    if tool_names is None:
        tool_names = ["calculate_cbm", "extract_bl_pl", "send_whatsapp_webhook"]

    anthropic_tools = []

    for tool_name in tool_names:
        if tool_name not in schemas:
            logger.warning(f"Schema não encontrado para ferramenta: {tool_name}")
            continue

        schema_def = schemas[tool_name]

        tool_spec = {
            "name": tool_name,
            "description": schema_def.get("description", ""),
            "input_schema": schema_def.get("input_schema", {
                "type": "object",
                "properties": {},
                "required": []
            })
        }

        anthropic_tools.append(tool_spec)
        logger.info(f"Tool traduzido: {tool_name}")

    return anthropic_tools


def validate_tool_input(tool_name: str, input_data: dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Valida entrada de ferramenta contra seu schema.

    Args:
        tool_name: Nome da ferramenta
        input_data: Dados de entrada

    Returns:
        Tupla (válido, mensagem_erro)
    """
    schemas = load_tool_schemas()

    if tool_name not in schemas:
        return False, f"Ferramenta desconhecida: {tool_name}"

    schema = schemas[tool_name].get("input_schema", {})
    required = schema.get("required", [])

    for field in required:
        if field not in input_data:
            return False, f"Campo obrigatório faltando: {field}"

    return True, None
