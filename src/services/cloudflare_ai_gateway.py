"""Serviço para AI Gateway da Cloudflare.

Evaluation types, logs e futuros recursos do AI Gateway.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

_DEFAULT_BASE_URL = "https://api.cloudflare.com/client/v4"


def _client() -> httpx.AsyncClient:
    token = os.getenv("CLOUDFLARE_API_TOKEN", "")
    if not token:
        raise RuntimeError("CLOUDFLARE_API_TOKEN não configurado")
    return httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=60.0,
    )


def _base_url() -> str:
    return os.getenv("CLOUDFLARE_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


# ── Evaluation Types ──────────────────────────────────────────────────────────

async def list_evaluation_types(
    account_id: str,
    *,
    order_by: Optional[str] = None,
    order_by_direction: Optional[str] = None,
    page: Optional[int] = None,
    per_page: Optional[int] = None,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/evaluation-types"""
    params: Dict[str, Any] = {}
    if order_by is not None:
        params["order_by"] = order_by
    if order_by_direction is not None:
        params["order_by_direction"] = order_by_direction
    if page is not None:
        params["page"] = page
    if per_page is not None:
        params["per_page"] = per_page

    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/evaluation-types",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


# ── Gateway Logs ──────────────────────────────────────────────────────────────

async def list_logs(
    account_id: str,
    gateway_id: str,
    *,
    cached: Optional[bool] = None,
    direction: Optional[str] = None,
    end_date: Optional[str] = None,
    feedback: Optional[int] = None,
    filters: Optional[List[Dict[str, Any]]] = None,
    max_cost: Optional[float] = None,
    max_duration: Optional[float] = None,
    max_tokens_in: Optional[float] = None,
    max_tokens_out: Optional[float] = None,
    max_total_tokens: Optional[float] = None,
    meta_info: Optional[bool] = None,
    min_cost: Optional[float] = None,
    min_duration: Optional[float] = None,
    min_tokens_in: Optional[float] = None,
    min_tokens_out: Optional[float] = None,
    min_total_tokens: Optional[float] = None,
    model: Optional[str] = None,
    model_type: Optional[str] = None,
    order_by: Optional[str] = None,
    order_by_direction: Optional[str] = None,
    page: Optional[int] = None,
    per_page: Optional[int] = None,
    provider: Optional[str] = None,
    request_content_type: Optional[str] = None,
    response_content_type: Optional[str] = None,
    search: Optional[str] = None,
    start_date: Optional[str] = None,
    success: Optional[bool] = None,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/logs"""
    params: Dict[str, Any] = {}
    if cached is not None:
        params["cached"] = str(cached).lower()
    if direction is not None:
        params["direction"] = direction
    if end_date is not None:
        params["end_date"] = end_date
    if feedback is not None:
        params["feedback"] = feedback
    if filters is not None:
        # Cloudflare espera filters como query params serializados;
        # enviamos como JSON string para simplificar
        import json

        params["filters"] = json.dumps(filters)
    if max_cost is not None:
        params["max_cost"] = max_cost
    if max_duration is not None:
        params["max_duration"] = max_duration
    if max_tokens_in is not None:
        params["max_tokens_in"] = max_tokens_in
    if max_tokens_out is not None:
        params["max_tokens_out"] = max_tokens_out
    if max_total_tokens is not None:
        params["max_total_tokens"] = max_total_tokens
    if meta_info is not None:
        params["meta_info"] = str(meta_info).lower()
    if min_cost is not None:
        params["min_cost"] = min_cost
    if min_duration is not None:
        params["min_duration"] = min_duration
    if min_tokens_in is not None:
        params["min_tokens_in"] = min_tokens_in
    if min_tokens_out is not None:
        params["min_tokens_out"] = min_tokens_out
    if min_total_tokens is not None:
        params["min_total_tokens"] = min_total_tokens
    if model is not None:
        params["model"] = model
    if model_type is not None:
        params["model_type"] = model_type
    if order_by is not None:
        params["order_by"] = order_by
    if order_by_direction is not None:
        params["order_by_direction"] = order_by_direction
    if page is not None:
        params["page"] = page
    if per_page is not None:
        params["per_page"] = per_page
    if provider is not None:
        params["provider"] = provider
    if request_content_type is not None:
        params["request_content_type"] = request_content_type
    if response_content_type is not None:
        params["response_content_type"] = response_content_type
    if search is not None:
        params["search"] = search
    if start_date is not None:
        params["start_date"] = start_date
    if success is not None:
        params["success"] = str(success).lower()

    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/logs",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def get_log(
    account_id: str,
    gateway_id: str,
    log_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/logs/{log_id}"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/logs/{log_id}",
        )
        resp.raise_for_status()
        return resp.json()


async def update_log(
    account_id: str,
    gateway_id: str,
    log_id: str,
    *,
    feedback: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
    score: Optional[float] = None,
) -> Dict[str, Any]:
    """PATCH /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/logs/{log_id}"""
    payload: Dict[str, Any] = {}
    if feedback is not None:
        payload["feedback"] = feedback
    if metadata is not None:
        payload["metadata"] = metadata
    if score is not None:
        payload["score"] = score

    async with _client() as client:
        resp = await client.patch(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/logs/{log_id}",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def delete_logs(
    account_id: str,
    gateway_id: str,
    *,
    filters: Optional[List[Dict[str, Any]]] = None,
    limit: Optional[int] = None,
    order_by: Optional[str] = None,
    order_by_direction: Optional[str] = None,
) -> Dict[str, Any]:
    """DELETE /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/logs"""
    params: Dict[str, Any] = {}
    if filters is not None:
        import json

        params["filters"] = json.dumps(filters)
    if limit is not None:
        params["limit"] = limit
    if order_by is not None:
        params["order_by"] = order_by
    if order_by_direction is not None:
        params["order_by_direction"] = order_by_direction

    async with _client() as client:
        resp = await client.delete(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/logs",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def get_log_request(
    account_id: str,
    gateway_id: str,
    log_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/logs/{log_id}/request"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/logs/{log_id}/request",
        )
        resp.raise_for_status()
        return resp.json()


async def get_log_response(
    account_id: str,
    gateway_id: str,
    log_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/logs/{log_id}/response"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/logs/{log_id}/response",
        )
        resp.raise_for_status()
        return resp.json()


# ── Datasets ──────────────────────────────────────────────────────────────────

async def list_datasets(
    account_id: str,
    gateway_id: str,
    *,
    enable: Optional[bool] = None,
    name: Optional[str] = None,
    page: Optional[int] = None,
    per_page: Optional[int] = None,
    search: Optional[str] = None,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/datasets"""
    params: Dict[str, Any] = {}
    if enable is not None:
        params["enable"] = str(enable).lower()
    if name is not None:
        params["name"] = name
    if page is not None:
        params["page"] = page
    if per_page is not None:
        params["per_page"] = per_page
    if search is not None:
        params["search"] = search

    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/datasets",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def get_dataset(
    account_id: str,
    gateway_id: str,
    dataset_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/datasets/{dataset_id}"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/datasets/{dataset_id}",
        )
        resp.raise_for_status()
        return resp.json()


async def create_dataset(
    account_id: str,
    gateway_id: str,
    *,
    enable: bool,
    filters: List[Dict[str, Any]],
    name: str,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/datasets"""
    payload = {
        "enable": enable,
        "filters": filters,
        "name": name,
    }
    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/datasets",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def update_dataset(
    account_id: str,
    gateway_id: str,
    dataset_id: str,
    *,
    enable: bool,
    filters: List[Dict[str, Any]],
    name: str,
) -> Dict[str, Any]:
    """PUT /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/datasets/{dataset_id}"""
    payload = {
        "enable": enable,
        "filters": filters,
        "name": name,
    }
    async with _client() as client:
        resp = await client.put(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/datasets/{dataset_id}",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def delete_dataset(
    account_id: str,
    gateway_id: str,
    dataset_id: str,
) -> Dict[str, Any]:
    """DELETE /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/datasets/{dataset_id}"""
    async with _client() as client:
        resp = await client.delete(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/datasets/{dataset_id}",
        )
        resp.raise_for_status()
        return resp.json()


# ── Evaluations ───────────────────────────────────────────────────────────────

async def list_evaluations(
    account_id: str,
    gateway_id: str,
    *,
    name: Optional[str] = None,
    page: Optional[int] = None,
    per_page: Optional[int] = None,
    processed: Optional[bool] = None,
    search: Optional[str] = None,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/evaluations"""
    params: Dict[str, Any] = {}
    if name is not None:
        params["name"] = name
    if page is not None:
        params["page"] = page
    if per_page is not None:
        params["per_page"] = per_page
    if processed is not None:
        params["processed"] = str(processed).lower()
    if search is not None:
        params["search"] = search

    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/evaluations",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def get_evaluation(
    account_id: str,
    gateway_id: str,
    evaluation_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/evaluations/{evaluation_id}"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/evaluations/{evaluation_id}",
        )
        resp.raise_for_status()
        return resp.json()


async def create_evaluation(
    account_id: str,
    gateway_id: str,
    *,
    dataset_ids: List[str],
    evaluation_type_ids: List[str],
    name: str,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/evaluations"""
    payload = {
        "dataset_ids": dataset_ids,
        "evaluation_type_ids": evaluation_type_ids,
        "name": name,
    }
    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/evaluations",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def delete_evaluation(
    account_id: str,
    gateway_id: str,
    evaluation_id: str,
) -> Dict[str, Any]:
    """DELETE /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/evaluations/{evaluation_id}"""
    async with _client() as client:
        resp = await client.delete(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/evaluations/{evaluation_id}",
        )
        resp.raise_for_status()
        return resp.json()


# ── Dynamic Routing ───────────────────────────────────────────────────────────

async def list_routes(
    account_id: str,
    gateway_id: str,
    *,
    page: Optional[int] = None,
    per_page: Optional[int] = None,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes"""
    params: Dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if per_page is not None:
        params["per_page"] = per_page

    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def get_route(
    account_id: str,
    gateway_id: str,
    route_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}",
        )
        resp.raise_for_status()
        return resp.json()


async def create_route(
    account_id: str,
    gateway_id: str,
    *,
    elements: List[Dict[str, Any]],
    name: str,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes"""
    payload = {
        "elements": elements,
        "name": name,
    }
    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def update_route(
    account_id: str,
    gateway_id: str,
    route_id: str,
    *,
    name: str,
) -> Dict[str, Any]:
    """PATCH /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}"""
    payload = {"name": name}
    async with _client() as client:
        resp = await client.patch(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def delete_route(
    account_id: str,
    gateway_id: str,
    route_id: str,
) -> Dict[str, Any]:
    """DELETE /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}"""
    async with _client() as client:
        resp = await client.delete(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}",
        )
        resp.raise_for_status()
        return resp.json()


# ── Route Deployments ─────────────────────────────────────────────────────────

async def list_route_deployments(
    account_id: str,
    gateway_id: str,
    route_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}/deployments"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}/deployments",
        )
        resp.raise_for_status()
        return resp.json()


async def create_route_deployment(
    account_id: str,
    gateway_id: str,
    route_id: str,
    *,
    version_id: str,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}/deployments"""
    payload = {"version_id": version_id}
    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}/deployments",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ── Route Versions ────────────────────────────────────────────────────────────

async def list_route_versions(
    account_id: str,
    gateway_id: str,
    route_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}/versions"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}/versions",
        )
        resp.raise_for_status()
        return resp.json()


async def create_route_version(
    account_id: str,
    gateway_id: str,
    route_id: str,
    *,
    elements: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}/versions"""
    payload = {"elements": elements}
    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}/versions",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def get_route_version(
    account_id: str,
    gateway_id: str,
    route_id: str,
    version_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}/versions/{version_id}"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/routes/{route_id}/versions/{version_id}",
        )
        resp.raise_for_status()
        return resp.json()


# ── Gateway URL ───────────────────────────────────────────────────────────────

async def get_gateway_url(
    account_id: str,
    gateway_id: str,
    provider: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/url/{provider}"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/url/{provider}",
        )
        resp.raise_for_status()
        return resp.json()


# ── Billing ───────────────────────────────────────────────────────────────────

async def get_credit_balance(account_id: str) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/billing/credit-balance"""
    async with _client() as client:
        resp = await client.get(f"{_base_url()}/accounts/{account_id}/ai-gateway/billing/credit-balance")
        resp.raise_for_status()
        return resp.json()


async def get_usage_history(
    account_id: str,
    *,
    value_grouping_window: str,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/billing/usage-history"""
    params: Dict[str, Any] = {"value_grouping_window": value_grouping_window}
    if start_time is not None:
        params["start_time"] = start_time
    if end_time is not None:
        params["end_time"] = end_time
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/billing/usage-history",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def get_invoice_history(
    account_id: str,
    *,
    type_: Optional[str] = None,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/billing/invoice-history"""
    params: Dict[str, Any] = {}
    if type_ is not None:
        params["type"] = type_
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/billing/invoice-history",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def get_invoice_preview(account_id: str) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/billing/invoice-preview"""
    async with _client() as client:
        resp = await client.get(f"{_base_url()}/accounts/{account_id}/ai-gateway/billing/invoice-preview")
        resp.raise_for_status()
        return resp.json()


# ── Topup ─────────────────────────────────────────────────────────────────────

async def create_topup(
    account_id: str,
    *,
    amount: int,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai-gateway/billing/topup"""
    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/billing/topup",
            json={"amount": amount},
        )
        resp.raise_for_status()
        return resp.json()


async def get_topup_status(
    account_id: str,
    *,
    payment_intent_id: str,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai-gateway/billing/topup/status"""
    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/billing/topup/status",
            json={"payment_intent_id": payment_intent_id},
        )
        resp.raise_for_status()
        return resp.json()


# ── Topup Config ──────────────────────────────────────────────────────────────

async def get_topup_config(account_id: str) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/billing/topup/config"""
    async with _client() as client:
        resp = await client.get(f"{_base_url()}/accounts/{account_id}/ai-gateway/billing/topup/config")
        resp.raise_for_status()
        return resp.json()


async def create_topup_config(
    account_id: str,
    *,
    amount: int,
    threshold: int,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai-gateway/billing/topup/config"""
    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/billing/topup/config",
            json={"amount": amount, "threshold": threshold},
        )
        resp.raise_for_status()
        return resp.json()


async def delete_topup_config(account_id: str) -> Dict[str, Any]:
    """DELETE /accounts/{account_id}/ai-gateway/billing/topup/config"""
    async with _client() as client:
        resp = await client.delete(f"{_base_url()}/accounts/{account_id}/ai-gateway/billing/topup/config")
        resp.raise_for_status()
        return resp.json()


# ── Spending Limit ────────────────────────────────────────────────────────────

async def get_spending_limit(account_id: str) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/billing/spending-limit"""
    async with _client() as client:
        resp = await client.get(f"{_base_url()}/accounts/{account_id}/ai-gateway/billing/spending-limit")
        resp.raise_for_status()
        return resp.json()


async def create_spending_limit(
    account_id: str,
    *,
    amount: int,
    duration: str,
    strategy: str,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai-gateway/billing/spending-limit"""
    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/billing/spending-limit",
            json={"amount": amount, "duration": duration, "strategy": strategy},
        )
        resp.raise_for_status()
        return resp.json()


async def delete_spending_limit(account_id: str) -> Dict[str, Any]:
    """DELETE /accounts/{account_id}/ai-gateway/billing/spending-limit"""
    async with _client() as client:
        resp = await client.delete(f"{_base_url()}/accounts/{account_id}/ai-gateway/billing/spending-limit")
        resp.raise_for_status()
        return resp.json()


# ── Provider Configs ──────────────────────────────────────────────────────────

async def list_provider_configs(
    account_id: str,
    gateway_id: str,
    *,
    page: Optional[int] = None,
    per_page: Optional[int] = None,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/provider_configs"""
    params: Dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if per_page is not None:
        params["per_page"] = per_page

    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/provider_configs",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def create_provider_config(
    account_id: str,
    gateway_id: str,
    *,
    alias: str,
    default_config: bool,
    provider_slug: str,
    secret: str,
    secret_id: str,
    rate_limit: Optional[float] = None,
    rate_limit_period: Optional[float] = None,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/ai-gateway/gateways/{gateway_id}/provider_configs"""
    payload: Dict[str, Any] = {
        "alias": alias,
        "default_config": default_config,
        "provider_slug": provider_slug,
        "secret": secret,
        "secret_id": secret_id,
    }
    if rate_limit is not None:
        payload["rate_limit"] = rate_limit
    if rate_limit_period is not None:
        payload["rate_limit_period"] = rate_limit_period

    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/ai-gateway/gateways/{gateway_id}/provider_configs",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()
