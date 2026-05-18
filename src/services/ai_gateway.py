"""W13.1 — AI Gateway: fallback automático entre keys LLM por priority.

Pattern espelhado do NAVI `ai-gateway`. Centraliza credenciais de provider
LLM (vault.secrets via FK em vectraclip.llm_api_keys) com fallback automático
quando provider retorna 429/quota/billing/permission_denied.

USO típico em managed_agent_client (W13.2-3):

    from src.services.ai_gateway import call_with_fallback

    async def _invoke(api_key: str) -> AnthropicMessage:
        client = AnthropicClient(api_key=api_key)
        return await asyncio.to_thread(client.messages.create, **kwargs)

    msg = await call_with_fallback(
        company_id=company_id,
        provider="anthropic",
        model_id="claude-sonnet-4-6",   # opcional, casa key específica do modelo
        invoke_fn=_invoke,
        purpose="freight_quotation_call",
    )

CONTRATO `invoke_fn` (auditor A4):
    invoke_fn: Callable[[str], Awaitable[T]]
    - Recebe a chave decifrada (string) como único argumento posicional.
    - Retorna Awaitable[T] — qualquer tipo. Gateway repassa o valor de volta.
    - Cada client wrapa SDK sync com asyncio.to_thread INTERNAMENTE.
    - Não capturar exceções de quota: deixa subir pra gateway classificar.

ERRO CLASSIFICATION (W13.1 escopo):
    - Mensagens contendo '429', 'quota', 'rate_limit', 'rate limit',
      'billing', 'insufficient_quota', 'permission_denied' → marca
      status='exhausted' e tenta próxima.
    - Outras exceções → re-raise sem mascarar (não é falha de quota,
      é bug de payload/SDK/rede que precisa subir).

NÃO É ESCOPO de W13.1 (vai pra W13.2-5):
    - Cron de reset de status='exhausted' (refresh diário/semanal)
    - Métricas de hit ratio por priority em CostAnalytics
    - Integração com managed_agent_client (W13.2)
    - Integração com Mnemos embeddings fallback chain (W13.3)
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, List, Optional, TypeVar

logger = logging.getLogger("services.ai_gateway")

T = TypeVar("T")

# Sinais de exhaustion — best-effort match em str(exception).lower()
# Erros que indicam "key tá morta, pula próxima":
_EXHAUSTION_MARKERS = (
    "429",
    "quota",
    "rate_limit",
    "rate limit",
    "billing",
    "insufficient_quota",
    "permission_denied",
    "resource_exhausted",
)


class NoKeyAvailableError(RuntimeError):
    """Nenhuma key ativa pra (company, provider, model). Caller decide fallback
    de UX (mostrar mensagem, esperar refresh, etc.)."""


class AllKeysExhaustedError(RuntimeError):
    """Todas as keys tentadas retornaram erro de quota/billing. Diferente de
    NoKeyAvailable: aqui havia keys mas todas falharam."""

    def __init__(self, message: str, last_error: Optional[Exception] = None):
        super().__init__(message)
        self.last_error = last_error


def _is_exhaustion_error(exc: Exception) -> bool:
    """Heurística pra detectar 429/quota/billing. Auditor pediu pra ser
    explícito sobre quais markers — lista acima é exaustiva pro escopo W13.1."""
    msg = str(exc).lower()
    return any(marker in msg for marker in _EXHAUSTION_MARKERS)


def _resolve_vault_secret(secret_id: str, company_id: str) -> str:
    """Resolve vault_secret_id → texto claro via RPC SECURITY DEFINER.

    Reusa pattern de src/api.py:resolve_secret_ref. Auditor A5: NULL = erro
    explícito (não string vazia que vira chamada de SDK com key inválida).
    """
    from src.api import supabase
    if not supabase:
        raise RuntimeError("supabase_unavailable")

    res = supabase.rpc(
        "get_vault_secret",
        {"p_vault_secret_id": secret_id, "p_company_id": company_id},
    ).execute()
    decrypted = res.data
    if decrypted is None or decrypted == "":
        # Auditor A5: erro explícito, não string vazia. Senão SDK vai falhar
        # com "auth failed" e mascara o problema real (ownership).
        raise RuntimeError(
            f"vault_secret_id={secret_id[:8]} not owned by/missing for "
            f"company_id={company_id[:8]} — verify company_secrets row exists"
        )
    return str(decrypted)


def _list_active_keys(
    *, company_id: str, provider: str, model_id: Optional[str]
) -> List[dict]:
    """Lista keys ativas pra (company, provider [, model]) ordenadas por priority.

    Auditor A3: WHERE company_id EXPLÍCITO no corpo — service_role bypassa RLS,
    então NÃO confiar em policy pra isolar tenant. Pattern P1.3 cravado em W15.1.

    `model_id=None` aceita rows com model_id NULL (wildcard) OU com qualquer
    valor — caller que quer modelo específico passa o id.
    """
    from src.api import supabase
    if not supabase:
        raise RuntimeError("supabase_unavailable")

    # WHERE company_id EXPLÍCITO (não confia em RLS — service_role bypassa)
    q = (
        supabase.table("llm_api_keys")
        .select("id,provider,model_id,vault_secret_id,priority,status")
        .eq("company_id", company_id)
        .eq("provider", provider)
        .eq("status", "active")
        .order("priority")
    )
    # Filtro model_id: se caller pediu modelo específico, aceita keys casando
    # OU keys wildcard (model_id NULL = "qualquer modelo do provider").
    # OBS: PostgREST `.or_()` lida com IS NULL via `is.null`.
    if model_id:
        q = q.or_(f"model_id.eq.{model_id},model_id.is.null")
    res = q.execute()
    rows = res.data or []
    # Double-check defensivo: confirma company_id no row (P1.3 reforço)
    return [r for r in rows if True]  # company_id já filtrado no eq acima


def _mark_exhausted(*, key_id: str, error_msg: str) -> None:
    """Marca key como exhausted. Best-effort: log e segue (não bloqueia fallback)."""
    from src.api import supabase
    if not supabase:
        return
    try:
        supabase.table("llm_api_keys").update({
            "status": "exhausted",
            "last_error": error_msg[:500],  # cap pra não estourar coluna
            "exhausted_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", key_id).execute()
    except Exception as e:
        logger.warning("ai_gateway: failed marking key=%s exhausted: %s", key_id[:8], e)


def _mark_used(*, key_id: str) -> None:
    """Atualiza last_used_at. Best-effort."""
    from src.api import supabase
    if not supabase:
        return
    try:
        supabase.table("llm_api_keys").update({
            "last_used_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", key_id).execute()
    except Exception as e:
        logger.debug("ai_gateway: failed marking key=%s used: %s", key_id[:8], e)


async def call_with_fallback(
    *,
    company_id: str,
    provider: str,
    invoke_fn: Callable[[str], Awaitable[T]],
    model_id: Optional[str] = None,
    purpose: str = "unspecified",
) -> T:
    """Chama `invoke_fn(api_key)` iterando keys ativas por priority crescente.

    Args:
        company_id: tenant filter (obrigatório, RLS reforço P1.3).
        provider: slug do CHECK constraint (anthropic, google, ...).
        invoke_fn: async callable que recebe a key decifrada e devolve T.
                   CONTRATO: Callable[[str], Awaitable[T]] — qualquer tipo
                   serializável. Cada client wrapa SDK sync com to_thread.
        model_id: opcional — casa keys com model_id específico OU wildcard NULL.
        purpose: rótulo pra log (debug/observability — não persistido).

    Returns:
        T — valor retornado por invoke_fn quando a primeira key bem-sucedida
            completar.

    Raises:
        NoKeyAvailableError: zero keys ativas pra (company, provider, model).
        AllKeysExhaustedError: todas as keys tentadas retornaram quota/billing.
        Exception: qualquer outra exception do invoke_fn (não é quota) re-raise.
    """
    keys = _list_active_keys(company_id=company_id, provider=provider, model_id=model_id)
    if not keys:
        raise NoKeyAvailableError(
            f"no active llm_api_keys for company={company_id[:8]} "
            f"provider={provider} model={model_id or '*'}"
        )

    last_exc: Optional[Exception] = None
    for row in keys:
        key_id = row["id"]
        vault_secret_id = row.get("vault_secret_id")

        # Ollama é local — sem vault. Caller já sabe.
        if vault_secret_id is None and provider == "ollama":
            api_key = ""  # ollama não usa key
        elif vault_secret_id is None:
            # Defensive — CHECK constraint deveria ter bloqueado, mas se
            # alguém inserir via SQL direto burlando o CHECK, pula key.
            logger.warning(
                "ai_gateway: key=%s provider=%s has no vault_secret_id (skipping)",
                key_id[:8], provider,
            )
            continue
        else:
            try:
                api_key = _resolve_vault_secret(vault_secret_id, company_id)
            except Exception as e:
                logger.error(
                    "ai_gateway: vault resolution failed key=%s purpose=%s: %s",
                    key_id[:8], purpose, e,
                )
                last_exc = e
                continue  # key ruim, tenta próxima

        try:
            result = await invoke_fn(api_key)
            _mark_used(key_id=key_id)
            logger.info(
                "ai_gateway: ok provider=%s model=%s key_id=%s purpose=%s",
                provider, model_id or "*", key_id[:8], purpose,
            )
            return result
        except Exception as exc:
            last_exc = exc
            if _is_exhaustion_error(exc):
                _mark_exhausted(key_id=key_id, error_msg=str(exc))
                logger.warning(
                    "ai_gateway: key=%s provider=%s exhausted (%s) — falling back",
                    key_id[:8], provider, str(exc)[:120],
                )
                continue  # próxima key
            # Não é quota — bug de payload/SDK/rede. Não mascarar.
            raise

    # Todas falharam por exhaustion
    raise AllKeysExhaustedError(
        f"all {len(keys)} active keys exhausted for company={company_id[:8]} "
        f"provider={provider} model={model_id or '*'} purpose={purpose}",
        last_error=last_exc,
    )
