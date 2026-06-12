"""CloudflareAIClient: executa tasks via Cloudflare Workers AI.

Cloudflare Workers AI oferece inference serverless com modelos open-source
(Llama, Mistral, Qwen, etc.) via endpoint REST único por account.

Auth:     Bearer {api_token}
Endpoint: https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model_name}
Docs:     https://developers.cloudflare.com/workers-ai/models/

Mesma interface (`async def execute_task -> ExecutionResult`) que
ManagedAgentClient / GroqAgentClient / HuggingFaceAgentClient — o router
permanece agnóstico.

Catalog-driven: account_id, api_token, model_id, base_url vêm de
`agent_adapter_configs.field_values_json`.  base_url default é a API v4
oficial da Cloudflare; admin pode sobrescrever (mirror, proxy).
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from .managed_agent_client import ExecutionResult
from .tool_translator import OPENAI_TOOLS, dispatch_tool_call

logger = logging.getLogger("ManagedAgents.CloudflareAI")

_MAX_TURNS = 20
_DEFAULT_BASE_URL = "https://api.cloudflare.com/client/v4"


class CloudflareAIClient:
    """Cliente para Cloudflare Workers AI (REST API). 100%% catalog-driven."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        config = config or {}

        self.account_id = config.get("account_id") or os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
        if not self.account_id:
            raise ValueError(
                "CloudflareAIClient: account_id ausente no config e no env CLOUDFLARE_ACCOUNT_ID. "
                "Configure 'account_id' em agent_adapter_configs.field_values_json."
            )

        api_token = config.get("api_token") or os.getenv("CLOUDFLARE_API_TOKEN", "")
        if not api_token:
            logger.warning(
                "CloudflareAIClient: api_token ausente no config e no env CLOUDFLARE_API_TOKEN. "
                "execute_task vai retornar erro até que seja configurado."
            )

        self.model = config.get("model_id")
        if not self.model:
            raise ValueError(
                "CloudflareAIClient: model_id ausente no config. "
                "Configure 'model_id' em agent_adapter_configs.field_values_json "
                "(ex: @cf/meta/llama-3.1-8b-instruct, @cf/mistral/mistral-7b-instruct-v0.2)."
            )

        self._base_url = (config.get("base_url") or _DEFAULT_BASE_URL).rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_token or 'missing'}",
            "Content-Type": "application/json",
        }
        self._has_token = bool(api_token)

        try:
            self.temperature = float(config.get("temperature", 0.3))
        except (TypeError, ValueError):
            self.temperature = 0.3
        try:
            self.max_tokens = int(config.get("max_tokens", 4096))
        except (TypeError, ValueError):
            self.max_tokens = 4096

    # ── helpers ──────────────────────────────────────────────────────────────

    def _run_url(self) -> str:
        return f"{self._base_url}/accounts/{self.account_id}/ai/run/{self.model}"

    async def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(self._run_url(), headers=self._headers, json=payload)
            resp.raise_for_status()
            return resp.json()

    # ── public interface ─────────────────────────────────────────────────────

    async def execute_task(
        self,
        prompt: str,
        max_turns: int = 3,
        system_prompt: Optional[str] = None,
        agent_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> ExecutionResult:
        start = time.monotonic()

        if not self._has_token:
            return ExecutionResult(
                success=False,
                content="",
                error="CloudflareAIClient: api_token não configurado. "
                      "Defina CLOUDFLARE_API_TOKEN no .env ou 'api_token' no adapter config.",
            )

        # Cloudflare Workers AI suporta formato OpenAI-compatible via /ai/run/{model}
        # com campo "messages".  Alguns modelos mais antigos usam "prompt" raw,
        # mas a maioria dos modelos de chat (Llama, Mistral, Qwen) aceita "messages".
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # MCP tools (prefixo mcp__) — Cloudflare não suporta tool_calling nativo
        # em todos os modelos, então registramos como OpenAI function schema
        # e fazemos dispatch manual quando a resposta contém tool_calls.
        _mcp_openai: List[Dict[str, Any]] = []
        if agent_id and company_id:
            try:
                from src.api import supabase as _supabase_mcp
                from src.services.mcp_tool_runner import list_agent_mcp_tools
                if _supabase_mcp:
                    for t in list_agent_mcp_tools(_supabase_mcp, agent_id):
                        _mcp_openai.append({
                            "type": "function",
                            "function": {
                                "name": t["name"],
                                "description": t.get("description") or "",
                                "parameters": t.get("input_schema") or {"type": "object"},
                            },
                        })
            except Exception as e:
                logger.debug("mcp_tools injeção falhou: %s", e)

        tools = OPENAI_TOOLS + _mcp_openai
        turn_count = 0
        all_tool_calls: List[Dict[str, Any]] = []
        tokens_input = 0
        tokens_output = 0

        while turn_count < min(max_turns, _MAX_TURNS):
            turn_count += 1
            payload: Dict[str, Any] = {
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            try:
                data = await self._post(payload)
            except httpx.HTTPStatusError as exc:
                err_text = f"HTTP {exc.response.status_code}: {exc.response.text[:500]}"
                logger.error("Cloudflare AI error: %s", err_text)
                return ExecutionResult(
                    success=False,
                    content="",
                    error=err_text,
                    turn_count=turn_count,
                    execution_time_seconds=time.monotonic() - start,
                )
            except Exception as exc:
                logger.error("Cloudflare AI exception: %s", exc)
                return ExecutionResult(
                    success=False,
                    content="",
                    error=str(exc),
                    turn_count=turn_count,
                    execution_time_seconds=time.monotonic() - start,
                )

            # Cloudflare responde com { result: { response: "...", tool_calls: [...] } }
            # ou { result: "..." } dependendo do modelo.  Normalizamos abaixo.
            result = data.get("result", data)

            if isinstance(result, str):
                # Modelo retornou string direta (ex: completion simples)
                return ExecutionResult(
                    success=True,
                    content=result,
                    tool_calls=all_tool_calls,
                    turn_count=turn_count,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    execution_time_seconds=time.monotonic() - start,
                )

            # Formato chat/completion estruturado
            response_text = result.get("response") or ""
            tool_calls = result.get("tool_calls") or []

            tokens_input += result.get("usage", {}).get("prompt_tokens", 0)
            tokens_output += result.get("usage", {}).get("completion_tokens", 0)

            if not tool_calls:
                return ExecutionResult(
                    success=True,
                    content=response_text,
                    tool_calls=all_tool_calls,
                    turn_count=turn_count,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    execution_time_seconds=time.monotonic() - start,
                )

            # ── dispatch tool calls ──────────────────────────────────────────
            messages.append({
                "role": "assistant",
                "content": response_text or "",
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                all_tool_calls.append(tc)
                fn_name = tc.get("name") or tc.get("function", {}).get("name")
                arguments = tc.get("arguments") or tc.get("function", {}).get("arguments", "{}")
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                logger.info("Tool call: %s(%s)", fn_name, arguments)
                try:
                    tool_result = dispatch_tool_call(fn_name, arguments)
                except Exception as exc:
                    tool_result = f"[ERRO] {exc}"

                messages.append({
                    "role": "tool",
                    "name": fn_name,
                    "content": str(tool_result),
                })

        # max_turns atingido
        return ExecutionResult(
            success=True,
            content="[max_turns atingido]",
            tool_calls=all_tool_calls,
            turn_count=turn_count,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            execution_time_seconds=time.monotonic() - start,
        )
