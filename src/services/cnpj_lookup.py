"""CNPJ lookup via BrasilAPI — cartão completo da Receita.

Restaurado em 2026-05-17 após `/api/companies/{id}/lookup-cnpj` quebrar com
ModuleNotFoundError em produção (provavelmente perdido em refactor anterior).
Frontend `/prospects` consome esse endpoint e ficou inoperante.

Próximos consumidores:
- Signup self-service (PR 2): preencher company_name automaticamente
- Athena onboarding (PR 3): input estruturado pro CMA Claude sintetizar
  perfil empresarial pra RAG corpus inicial do tenant

API externa: https://brasilapi.com.br/api/cnpj/v1/{cnpj} (gratuita, sem auth)
Rate limit BrasilAPI: ~3 req/s, suficiente pra uso casual.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("CnpjLookup")

_BRASIL_API_URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
_TIMEOUT_S = 15.0

# Cache in-memory TTL 1h — BrasilAPI dados mudam raramente; evita bater toda
# vez que o user digita o CNPJ no signup form (debounce 800ms ainda mandaria
# múltiplas requests se backend não cacheasse).
_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL_S = 3600.0


class CnpjLookupError(Exception):
    """Erro estruturado de lookup CNPJ — capturado por endpoints pra HTTP útil.

    Códigos canônicos (constantes públicas — endpoint legado
    `/companies/{cid}/lookup-cnpj` esperava esses nomes):
    """

    CODE_INVALID = "invalid_cnpj_format"
    CODE_NOT_FOUND = "cnpj_not_found"
    CODE_NETWORK = "brasilapi_unreachable"
    CODE_TIMEOUT = "brasilapi_timeout"
    CODE_RATE_LIMITED = "brasilapi_rate_limited"
    CODE_SERVER_ERROR = "brasilapi_server_error"
    CODE_UNEXPECTED = "brasilapi_unexpected"
    CODE_INVALID_JSON = "brasilapi_invalid_json"

    def __init__(self, code: str, message: str, status_hint: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_hint = status_hint


def _sanitize_cnpj(raw: str) -> str:
    """Remove tudo que não é dígito; valida 14 chars."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != 14:
        raise CnpjLookupError(
            "invalid_cnpj_format",
            f"CNPJ deve ter 14 dígitos (recebeu {len(digits)})",
            status_hint=400,
        )
    return digits


def _map_partners(qsa: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """BrasilAPI qsa[] → frontend CnpjPartner[]."""
    if not qsa:
        return []
    return [
        {
            "name": p.get("nome_socio") or "",
            "role": p.get("qualificacao_socio"),
            "role_code": str(p.get("codigo_qualificacao_socio")) if p.get("codigo_qualificacao_socio") is not None else None,
            "document": p.get("cnpj_cpf_do_socio"),
            "entry_date": p.get("data_entrada_sociedade"),
            "country": p.get("pais"),
            "age_range": p.get("faixa_etaria"),
        }
        for p in qsa
    ]


def _map_cnaes_secondary(cnaes: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    """BrasilAPI cnaes_secundarios[] → frontend CnpjCnaeSecondary[]."""
    if not cnaes:
        return []
    return [
        {"codigo": str(c.get("codigo") or ""), "descricao": c.get("descricao") or ""}
        for c in cnaes
        if c.get("codigo") is not None
    ]


def _normalize_brasilapi_response(raw: Dict[str, Any]) -> Dict[str, Any]:
    """BrasilAPI → CnpjLookupResult (shape esperado pelo frontend).

    Mapeamento explícito pra desacoplar frontend de mudanças BrasilAPI.
    """
    return {
        "cnpj": str(raw.get("cnpj") or ""),
        "name": raw.get("razao_social"),
        "trade_name": raw.get("nome_fantasia"),
        "email": raw.get("email"),
        "phone": raw.get("ddd_telefone_1"),
        "address": raw.get("logradouro"),
        "address_number": raw.get("numero"),
        "address_complement": raw.get("complemento"),
        "address_neighborhood": raw.get("bairro"),
        "zip_code": raw.get("cep"),
        "city": raw.get("municipio"),
        "state": raw.get("uf"),
        "legal_nature": raw.get("natureza_juridica"),
        "legal_nature_code": str(raw.get("codigo_natureza_juridica")) if raw.get("codigo_natureza_juridica") is not None else None,
        "company_size": raw.get("porte"),
        "opening_date": raw.get("data_inicio_atividade"),
        "registration_status": raw.get("descricao_situacao_cadastral"),
        "registration_status_date": raw.get("data_situacao_cadastral"),
        "registration_status_reason": raw.get("motivo_situacao_cadastral"),
        "efr": raw.get("ente_federativo_responsavel"),
        "cnae_main_code": str(raw.get("cnae_fiscal")) if raw.get("cnae_fiscal") is not None else None,
        "cnae_main_description": raw.get("cnae_fiscal_descricao"),
        "cnaes_secondary": _map_cnaes_secondary(raw.get("cnaes_secundarios")),
        "share_capital": float(raw.get("capital_social")) if raw.get("capital_social") is not None else None,
        "partners": _map_partners(raw.get("qsa")),
    }


async def lookup_cnpj(raw_cnpj: str) -> Dict[str, Any]:
    """Consulta CNPJ na BrasilAPI e retorna shape normalizado.

    Raises:
        CnpjLookupError: format inválido (400), não encontrado (404),
            BrasilAPI down (503), erro inesperado (500).
    """
    cnpj = _sanitize_cnpj(raw_cnpj)

    # Cache hit?
    cached = _CACHE.get(cnpj)
    now = time.time()
    if cached and (now - cached[0]) < _CACHE_TTL_S:
        logger.debug("cnpj_lookup cache HIT %s", cnpj)
        return cached[1]

    url = _BRASIL_API_URL.format(cnpj=cnpj)
    logger.info("cnpj_lookup fetch %s", cnpj)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(url)
    except httpx.TimeoutException:
        raise CnpjLookupError("brasilapi_timeout", "BrasilAPI demorou demais (timeout 15s).", status_hint=504)
    except httpx.RequestError as exc:
        raise CnpjLookupError("brasilapi_unreachable", f"BrasilAPI indisponível: {exc}", status_hint=503)

    if resp.status_code == 404:
        raise CnpjLookupError("cnpj_not_found", f"CNPJ {cnpj} não consta na Receita.", status_hint=404)
    if resp.status_code == 400:
        # BrasilAPI valida dígito verificador e retorna 400 pra "CNPJ inválido"
        # (caso DV diferente do calculado). Traduzimos pra 400 do nosso endpoint
        # — não é problema do BrasilAPI, é input do user.
        raise CnpjLookupError(
            "cnpj_not_found",
            f"CNPJ {cnpj} é inválido (dígito verificador não confere ou não consta na Receita).",
            status_hint=404,
        )
    if resp.status_code == 429:
        raise CnpjLookupError("brasilapi_rate_limited", "BrasilAPI rate limit excedido — tente em 1min.", status_hint=429)
    if resp.status_code >= 500:
        raise CnpjLookupError("brasilapi_server_error", f"BrasilAPI HTTP {resp.status_code}.", status_hint=503)
    if resp.status_code != 200:
        raise CnpjLookupError("brasilapi_unexpected", f"BrasilAPI HTTP {resp.status_code}: {resp.text[:200]}", status_hint=502)

    try:
        raw_data = resp.json()
    except Exception as exc:
        raise CnpjLookupError("brasilapi_invalid_json", f"BrasilAPI retornou JSON inválido: {exc}", status_hint=502)

    normalized = _normalize_brasilapi_response(raw_data)
    _CACHE[cnpj] = (now, normalized)
    logger.info("cnpj_lookup OK %s razao=%r", cnpj, normalized.get("name"))
    return normalized
