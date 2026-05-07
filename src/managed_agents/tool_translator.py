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
        "name": "read_hermes_inbox",
        "description": (
            "Lê os e-mails recentes do inbox IMAP do agente Hermes. "
            "Retorna uma lista de e-mails com from, subject, excerpt, receivedAt e o corpo completo. "
            "Use este tool para acessar cotações de frete recebidas por e-mail."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "UUID do agente Hermes cujas credenciais IMAP serão usadas",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máximo de e-mails a retornar (padrão 20)",
                    "default": 20,
                },
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "query_rag",
        "description": (
            "Consulta a memória corporativa (RAG) da company para encontrar trechos "
            "relevantes em documentos internos (PDFs, planilhas, manuais, contratos). "
            "Retorna os top-K trechos mais similares com filename + número da página "
            "para citação. Use ANTES de responder ao usuário sempre que precisar de "
            "contexto factual ou referência específica de docs internos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "string",
                    "description": (
                        "UUID da company (multi-tenant). Obrigatório. "
                        "Veja COMPANY_ID injetado no prompt da task."
                    ),
                },
                "query": {
                    "type": "string",
                    "description": "Pergunta ou frase de busca em linguagem natural.",
                },
                "k": {
                    "type": "integer",
                    "description": "Top-K trechos (1-50, default 5).",
                    "default": 5,
                },
                "min_score": {
                    "type": "number",
                    "description": "Score mínimo [0-1] para filtrar matches ruins (default 0.0).",
                    "default": 0.0,
                },
            },
            "required": ["company_id", "query"],
        },
    },
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


def _read_hermes_inbox(payload_json: str) -> str:
    """Fetch IMAP emails for a Hermes agent and return them as JSON."""
    try:
        import asyncio
        data = json.loads(payload_json)
        agent_id = data.get("agent_id", "")
        limit = int(data.get("limit", 20))

        from src.api import supabase, _fetch_imap_emails, _resolve_imap_field, _resolve_imap_port, _resolve_field_value

        if not supabase:
            return json.dumps({"success": False, "error": "Supabase não disponível"})

        cfg_res = supabase.table("agent_adapter_configs").select("field_values_json,company_id").eq("agent_id", agent_id).limit(1).execute()
        if not cfg_res.data:
            return json.dumps({"success": False, "error": f"Sem configuração IMAP para agente {agent_id}"})

        field_values = cfg_res.data[0].get("field_values_json") or {}
        company_id = cfg_res.data[0].get("company_id", "")
        host = _resolve_imap_field(field_values, "imap_host", "inbox_imap_host")
        port = _resolve_imap_port(field_values)
        username = _resolve_imap_field(field_values, "email", "inbox_email")
        raw_password = _resolve_imap_field(field_values, "password", "inbox_password")
        password = _resolve_field_value(raw_password, company_id)

        if not host or not username or not password:
            return json.dumps({"success": False, "error": "Credenciais IMAP incompletas"})

        emails = _fetch_imap_emails(host, port, username, password, limit)
        return json.dumps({"success": True, "emails": emails, "total": len(emails)})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def _query_rag(payload_json: str) -> str:
    """Query top-k chunks da memória corporativa via pgvector. Retorna JSON.

    Agente CMA passa company_id (injetado no prompt), query, k, min_score.
    Multi-tenant garantido pelo p_company_id no RPC match_rag_chunks.
    """
    try:
        import asyncio as _asyncio
        data = json.loads(payload_json)
        company_id = (data.get("company_id") or "").strip()
        query = (data.get("query") or "").strip()
        k = int(data.get("k", 5))
        min_score = float(data.get("min_score", 0.0))

        if not company_id:
            return json.dumps({"success": False, "error": "company_id obrigatório"})
        if not query:
            return json.dumps({"success": False, "error": "query obrigatória"})

        from src.api import supabase
        if not supabase:
            return json.dumps({"success": False, "error": "Supabase não disponível"})

        from src.services.rag.retriever import query_top_k

        results = _asyncio.run(query_top_k(
            query,
            company_id=company_id,
            k=k,
            min_score=min_score,
            supabase_client=supabase,
        ))

        return json.dumps({
            "success": True,
            "query": query,
            "matches": [
                {
                    "id": r.id,
                    "document_id": r.document_id,
                    "filename": r.document_filename,
                    "page": r.page_number,
                    "score": round(r.score, 4),
                    "content": r.content,
                }
                for r in results
            ],
            "total": len(results),
        })
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def _load_tools() -> None:
    global _TOOL_MAP
    if _TOOL_MAP:
        return
    try:
        from src.m3_tools import calculate_cbm, extract_bl_pl

        _TOOL_MAP = {
            "read_hermes_inbox": _read_hermes_inbox,
            "query_rag": _query_rag,
            "calculate_cbm": calculate_cbm,
            "extract_bl_pl": extract_bl_pl,
        }
    except ImportError as e:
        logger.warning(f"m3_tools import failed: {e} — tool dispatch disabled")
        _TOOL_MAP = {
            "read_hermes_inbox": _read_hermes_inbox,
            "query_rag": _query_rag,
        }


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


# --------------------------------------------------------------------------
# Definições em formato OpenAI (consumidas pelo OllamaAgentClient)
# Ollama expõe /v1/chat/completions compatível com OpenAI; reutilizamos as
# mesmas tools, só remapeando a estrutura.
# --------------------------------------------------------------------------

OPENAI_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in ANTHROPIC_TOOLS
]
