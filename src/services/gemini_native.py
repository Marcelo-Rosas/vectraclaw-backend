"""
Cliente nativo do Gemini (Vertex AI / Google GenAI) para VectraClaw.
Permite execução de LLM direto pela nuvem sem depender de infra local (nous-hermes-runtime).
"""
import os
import logging
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger("Vectra.GeminiNative")

class GeminiNativeError(ValueError):
    """Erro de configuração ou execução do Gemini."""

def is_gemini_active(supabase_client, company_id: str) -> bool:
    """Verifica se o adapter Gemini está ativo na company."""
    if not supabase_client or not company_id:
        return False
    try:
        res = (
            supabase_client.table("adapter_catalog")
            .select("id")
            .eq("company_id", company_id)
            .eq("slug", "gemini_native")
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception as exc:
        logger.warning("is_gemini_active failed company=%s: %s", company_id, exc)
        return False

async def gemini_exec(
    *,
    prompt: str,
    gemini_config: Dict[str, Any],
    api_key: str,
    max_turns: Optional[int] = None,
    timeout_seconds: int = 60,
) -> Dict[str, Any]:
    """
    Executa a requisição diretamente contra a API oficial do Google Gemini.
    (Utilizando endpoint REST para máxima compatibilidade serverless)
    """
    model_id = gemini_config.get("model_id", "gemini-1.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8192,
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=float(timeout_seconds)) as client:
            resp = await client.post(url, json=payload)
            
            if resp.status_code >= 400:
                return {
                    "success": False,
                    "content": "",
                    "exit_code": resp.status_code,
                    "error": resp.text[:500]
                }
                
            data = resp.json()
            try:
                content = data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError):
                content = ""
                
            return {
                "success": True,
                "content": content,
                "exit_code": 200,
                "error": None
            }
            
    except Exception as e:
        logger.error(f"Gemini execution failed: {e}")
        return {
            "success": False,
            "content": "",
            "exit_code": 500,
            "error": str(e)
        }
