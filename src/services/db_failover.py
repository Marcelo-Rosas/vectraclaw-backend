"""
VEC-188 + M2 (autopilot 2026-05-19): self-healing pra failover de DB.

Movido de `src/services/brain/db_failover.py` durante migração Brain → Daedalus
(Caminho 3 W14). `brain/db_failover.py` mantido como shim deprecado re-exportando
deste módulo até call-sites migrarem.

Quando uma operação Supabase/Postgres falha, este módulo:
  1. Classifica o erro (FK, constraint, schema, auth, rede, etc.)
  2. Monta `FailoverResult` com contexto suficiente pro agente corrigir e retentar
  3. Exporta decorator `@with_db_recovery` (alias legacy `@with_db_failover`)

Referência de códigos Postgres: https://www.postgresql.org/docs/current/errcodes-appendix.html
Referência de códigos PostgREST: https://postgrest.org/en/stable/errors.html
"""

from __future__ import annotations

import functools
import logging
import traceback
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("services.db_failover")


# ---------------------------------------------------------------------------
# Catálogo de erros
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ErrorCategory:
    code: str          # código interno nosso
    pg_codes: tuple    # códigos Postgres (23503, etc.)
    pgrst_codes: tuple # códigos PostgREST (PGRST***) 
    title: str
    diagnosis_template: str   # texto com {detail} para a IA
    fix_template: str         # instrução de correção para a IA
    can_auto_retry: bool      # o sistema pode retentar automaticamente?
    http_status: int          # sugerido para a resposta HTTP


_CATEGORIES: list[ErrorCategory] = [
    ErrorCategory(
        code="FK_VIOLATION",
        pg_codes=("23503",),
        pgrst_codes=(),
        title="Violação de Chave Estrangeira",
        diagnosis_template=(
            "O campo referenciado não existe na tabela pai. Detalhe Postgres: {detail}"
        ),
        fix_template=(
            "Verifique se o ID referenciado existe antes de salvar. "
            "Use GET no endpoint correspondente para obter IDs válidos. "
            "Corrija o campo e envie novamente."
        ),
        can_auto_retry=False,
        http_status=422,
    ),
    ErrorCategory(
        code="UNIQUE_VIOLATION",
        pg_codes=("23505",),
        pgrst_codes=(),
        title="Violação de Unicidade",
        diagnosis_template=(
            "Já existe um registro com os mesmos valores únicos. Detalhe: {detail}"
        ),
        fix_template=(
            "Verifique se o registro já existe (GET antes de POST). "
            "Se for atualização, use PATCH em vez de POST."
        ),
        can_auto_retry=False,
        http_status=409,
    ),
    ErrorCategory(
        code="NOT_NULL_VIOLATION",
        pg_codes=("23502",),
        pgrst_codes=(),
        title="Campo Obrigatório Nulo",
        diagnosis_template=(
            "Um campo NOT NULL está ausente no payload. Detalhe: {detail}"
        ),
        fix_template=(
            "Adicione o campo obrigatório ao payload antes de retentar."
        ),
        can_auto_retry=False,
        http_status=422,
    ),
    ErrorCategory(
        code="CHECK_VIOLATION",
        pg_codes=("23514",),
        pgrst_codes=(),
        title="Violação de Constraint CHECK",
        diagnosis_template=(
            "O valor enviado não satisfaz uma regra de validação do banco. Detalhe: {detail}"
        ),
        fix_template=(
            "Verifique os valores permitidos para o campo e corrija antes de retentar."
        ),
        can_auto_retry=False,
        http_status=422,
    ),
    ErrorCategory(
        code="SCHEMA_NOT_FOUND",
        pg_codes=(),
        pgrst_codes=("PGRST205",),
        title="Tabela ou Schema Não Encontrado",
        diagnosis_template=(
            "O PostgREST não encontrou a tabela/schema solicitado. Detalhe: {detail}"
        ),
        fix_template=(
            "Verifique se a tabela existe no schema 'vectraclip'. "
            "Se necessário, rode as migrations pendentes."
        ),
        can_auto_retry=True,   # pode retentar após cache refresh
        http_status=503,
    ),
    ErrorCategory(
        code="PERMISSION_DENIED",
        pg_codes=("42501",),
        pgrst_codes=("42501",),
        title="Permissão Negada",
        diagnosis_template=(
            "O usuário/role não tem permissão para esta operação. Detalhe: {detail}"
        ),
        fix_template=(
            "Use o cliente service_role para operações backend. "
            "Se for endpoint autenticado, verifique se o JWT está correto e não expirou."
        ),
        can_auto_retry=False,
        http_status=403,
    ),
    ErrorCategory(
        code="NETWORK_ERROR",
        pg_codes=(),
        pgrst_codes=(),
        title="Erro de Conectividade",
        diagnosis_template=(
            "Não foi possível conectar ao banco de dados. Detalhe: {detail}"
        ),
        fix_template=(
            "Verifique a conectividade com o Supabase. "
            "O sistema tentará novamente automaticamente na próxima janela."
        ),
        can_auto_retry=True,
        http_status=503,
    ),
    ErrorCategory(
        code="UNKNOWN_DB_ERROR",
        pg_codes=(),
        pgrst_codes=(),
        title="Erro de Banco Desconhecido",
        diagnosis_template=(
            "Erro não classificado. Stack: {detail}"
        ),
        fix_template=(
            "Inspecione o stack completo em 'stack_trace' e ajuste o payload antes de retentar."
        ),
        can_auto_retry=False,
        http_status=500,
    ),
]

# Índice rápido: pg_code → category
_BY_PG_CODE: dict[str, ErrorCategory] = {}
_BY_PGRST_CODE: dict[str, ErrorCategory] = {}
for _cat in _CATEGORIES:
    for _code in _cat.pg_codes:
        _BY_PG_CODE[_code] = _cat
    for _code in _cat.pgrst_codes:
        _BY_PGRST_CODE[_code] = _cat

_NETWORK_KEYWORDS = ("connection", "timeout", "unreachable", "refused", "reset")


def _classify(exc: Exception) -> ErrorCategory:
    """Classifica uma exceção em uma ErrorCategory."""
    exc_str = str(exc).lower()

    # PostgREST APIError tem atributo .code
    code = getattr(exc, "code", None) or ""
    message = getattr(exc, "message", "") or ""

    if code in _BY_PG_CODE:
        return _BY_PG_CODE[code]
    if code in _BY_PGRST_CODE:
        return _BY_PGRST_CODE[code]

    # Tenta pelo conteúdo da mensagem
    if any(k in exc_str for k in _NETWORK_KEYWORDS):
        return _BY_PGRST_CODE.get("NETWORK", _CATEGORIES[-1])

    return _CATEGORIES[-1]  # UNKNOWN_DB_ERROR


# ---------------------------------------------------------------------------
# FailoverResult
# ---------------------------------------------------------------------------

@dataclass
class FailoverResult:
    """
    Payload completo retornado quando uma operação de banco falha.

    Campos para o agente:
      - error_category: tipo classificado do erro
      - diagnosis: o que deu errado (em linguagem natural)
      - suggested_fix: como corrigir
      - can_auto_retry: se o sistema pode retentar sozinho
      - ai_instruction: prompt compacto para o LLM raciocinar e retentar
      - original_payload: o que foi enviado (para o agente corrigir)
      - retry_hint: endpoint/operação sugerida para retry
    """
    success: bool = False
    error_category: str = ""
    error_title: str = ""
    error_detail: str = ""
    stack_trace: str = ""
    http_status: int = 500
    diagnosis: str = ""
    suggested_fix: str = ""
    can_auto_retry: bool = False
    ai_instruction: str = ""
    original_payload: dict = field(default_factory=dict)
    retry_hint: str = ""
    operation: str = ""     # ex: "insert:tasks", "update:agents"
    table: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_http_detail(self) -> dict:
        """Versão compacta para o `detail` de uma HTTPException."""
        return {
            "error_category": self.error_category,
            "error_title": self.error_title,
            "diagnosis": self.diagnosis,
            "suggested_fix": self.suggested_fix,
            "can_auto_retry": self.can_auto_retry,
            "ai_instruction": self.ai_instruction,
            "retry_hint": self.retry_hint,
            "original_payload": self.original_payload,
        }


def build_failover_result(
    exc: Exception,
    operation: str = "",
    table: str = "",
    original_payload: Optional[dict] = None,
    retry_hint: str = "",
) -> FailoverResult:
    """
    Constrói um FailoverResult a partir de qualquer exceção de banco de dados.

    Args:
        exc:              exceção capturada
        operation:        descrição da operação (ex: "insert:tasks")
        table:            nome da tabela alvo
        original_payload: payload que causou o erro
        retry_hint:       endpoint ou operação sugerida para retry
    """
    category = _classify(exc)
    detail = str(exc)
    stack = traceback.format_exc()

    diagnosis = category.diagnosis_template.format(detail=detail)

    ai_instruction = (
        f"[self-healing] Operação '{operation}' falhou com {category.code}. "
        f"Diagnóstico: {diagnosis} "
        f"Correção sugerida: {category.fix_template} "
        f"{'O sistema pode retentar automaticamente.' if category.can_auto_retry else 'Corrija o payload antes de retentar.'}"
    )

    return FailoverResult(
        success=False,
        error_category=category.code,
        error_title=category.title,
        error_detail=detail,
        stack_trace=stack,
        http_status=category.http_status,
        diagnosis=diagnosis,
        suggested_fix=category.fix_template,
        can_auto_retry=category.can_auto_retry,
        ai_instruction=ai_instruction,
        original_payload=original_payload or {},
        retry_hint=retry_hint,
        operation=operation,
        table=table,
    )


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def with_db_recovery(
    operation: str = "",
    table: str = "",
    retry_hint: str = "",
    reraise_http: bool = True,
):
    """
    Decorator pra corrotinas async que fazem operações de DB.

    Captura exceções de DB, constrói FailoverResult e lança HTTPException
    estruturada. O `detail` contém contexto pro agente (`ai_instruction`,
    `suggested_fix`, etc.).

    Args:
        operation:    label (ex: "insert:tasks")
        table:        tabela alvo
        retry_hint:   endpoint sugerido pra retry
        reraise_http: se True (padrão), lança HTTPException; se False, retorna FailoverResult

    Uso:
        @with_db_recovery(operation="insert:tasks", table="tasks")
        async def create_task(...): ...

    Renomeado de `with_db_failover` em M2 (autopilot 2026-05-19). Alias
    legacy mantido no fim do módulo e no shim brain/db_failover.py.
    """
    def decorator(func: Callable[..., Coroutine]):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Extrai o payload do primeiro argumento kwarg "payload" se existir
            payload_arg = kwargs.get("payload") or (args[1] if len(args) > 1 else None)
            original: dict = {}
            if hasattr(payload_arg, "dict"):
                original = payload_arg.dict()
            elif isinstance(payload_arg, dict):
                original = payload_arg

            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                # Não envolve HTTPExceptions — deixa passar
                from fastapi import HTTPException as _HTTPException
                if isinstance(exc, _HTTPException):
                    raise

                result = build_failover_result(
                    exc=exc,
                    operation=operation or func.__name__,
                    table=table,
                    original_payload=original,
                    retry_hint=retry_hint,
                )
                logger.error(
                    "DB failover [%s] %s: %s",
                    result.error_category,
                    result.operation,
                    result.error_detail,
                )

                if reraise_http:
                    from fastapi import HTTPException as _HTTPException
                    raise _HTTPException(
                        status_code=result.http_status,
                        detail=result.to_http_detail(),
                    )
                return result

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Aliases legacy (M2 autopilot 2026-05-19)
# ---------------------------------------------------------------------------
# `@with_db_failover` continua funcionando mas é deprecado. Próximo PR pode
# fazer search/replace pra `@with_db_recovery` em todos os call-sites e
# remover este alias.
with_db_failover = with_db_recovery
