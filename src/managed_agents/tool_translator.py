"""
Traduz M3 tools (calculate_cbm, extract_bl_pl) para o formato de tools do Anthropic SDK.
Provê também um dispatcher que executa tool_use blocks recebidos da API.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger("ManagedAgents.ToolTranslator")

# --------------------------------------------------------------------------
# Definições em formato Anthropic
# --------------------------------------------------------------------------

ANTHROPIC_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "calculate_cbm",
        "description": (
            "Calcula o Cubo Metragem (CBM) de uma carga com base nas dimensões "
            "em centímetros e na quantidade de volumes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "length_cm": {"type": "number", "description": "Comprimento em cm"},
                "width_cm": {"type": "number", "description": "Largura em cm"},
                "height_cm": {"type": "number", "description": "Altura em cm"},
                "quantity": {"type": "integer", "description": "Número de volumes", "default": 1},
            },
            "required": ["length_cm", "width_cm", "height_cm"],
        },
    },
    {
        "name": "extract_bl_pl",
        "description": (
            "Extrai dados estruturados de documentos logísticos (BL e Packing List) "
            "a partir de um arquivo PDF (caminho ou base64)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Caminho local do PDF"},
                "base64_content": {"type": "string", "description": "PDF codificado em base64"},
                "cross_ref": {
                    "type": "boolean",
                    "description": "Cruzar BL x PL se doc_type=mixed",
                    "default": False,
                },
            },
        },
    },
]

# Mapa name → callable para dispatch rápido
_TOOL_MAP: Dict[str, Any] = {}


def _load_tools() -> None:
    global _TOOL_MAP
    if _TOOL_MAP:
        return
    try:
        from src.m3_tools import calculate_cbm, extract_bl_pl

        _TOOL_MAP = {
            "calculate_cbm": calculate_cbm,
            "extract_bl_pl": extract_bl_pl,
        }
    except ImportError as e:
        logger.warning(f"m3_tools import failed: {e} — tool dispatch disabled")


def dispatch_tool_call(tool_name: str, tool_input: Dict[str, Any]) -> str:
    """Executa um tool_use block e retorna o resultado como string JSON."""
    _load_tools()
    fn = _TOOL_MAP.get(tool_name)
    if fn is None:
        return json.dumps({"success": False, "error": f"Tool '{tool_name}' não encontrada"})
    try:
        payload_json = json.dumps(tool_input)
        result = fn(payload_json)
        logger.debug(f"dispatch_tool_call tool={tool_name} result={result[:120]}")
        return result
    except Exception as e:
        logger.error(f"dispatch_tool_call error tool={tool_name}: {e}")
        return json.dumps({"success": False, "error": str(e)})
