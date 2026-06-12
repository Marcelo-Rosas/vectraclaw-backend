"""Serviço para Browser Rendering da Cloudflare.

Content, PDF, screenshot, scrape, snapshot, JSON, links, markdown,
crawl e devtools session/browser/targets management.
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
        timeout=120.0,
    )


def _base_url() -> str:
    return os.getenv("CLOUDFLARE_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


# ── Content ───────────────────────────────────────────────────────────────────

async def create_content(
    account_id: str,
    *,
    url: str,
    cache_ttl: Optional[float] = None,
    action_timeout: Optional[float] = None,
    add_script_tag: Optional[List[Dict[str, Any]]] = None,
    add_style_tag: Optional[List[Dict[str, Any]]] = None,
    allow_request_pattern: Optional[List[str]] = None,
    allow_resource_types: Optional[List[str]] = None,
    authenticate: Optional[Dict[str, str]] = None,
    best_attempt: Optional[bool] = None,
    cookies: Optional[List[Dict[str, Any]]] = None,
    emulate_media_type: Optional[str] = None,
    goto_options: Optional[Dict[str, Any]] = None,
    reject_request_pattern: Optional[List[str]] = None,
    reject_resource_types: Optional[List[str]] = None,
    set_extra_http_headers: Optional[Dict[str, str]] = None,
    set_java_script_enabled: Optional[bool] = None,
    user_agent: Optional[str] = None,
    viewport: Optional[Dict[str, Any]] = None,
    wait_for_selector: Optional[Dict[str, Any]] = None,
    wait_for_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/browser-rendering/content"""
    payload: Dict[str, Any] = {"url": url}
    if cache_ttl is not None:
        payload["cache_ttl"] = cache_ttl
    if action_timeout is not None:
        payload["action_timeout"] = action_timeout
    if add_script_tag is not None:
        payload["add_script_tag"] = add_script_tag
    if add_style_tag is not None:
        payload["add_style_tag"] = add_style_tag
    if allow_request_pattern is not None:
        payload["allow_request_pattern"] = allow_request_pattern
    if allow_resource_types is not None:
        payload["allow_resource_types"] = allow_resource_types
    if authenticate is not None:
        payload["authenticate"] = authenticate
    if best_attempt is not None:
        payload["best_attempt"] = best_attempt
    if cookies is not None:
        payload["cookies"] = cookies
    if emulate_media_type is not None:
        payload["emulate_media_type"] = emulate_media_type
    if goto_options is not None:
        payload["goto_options"] = goto_options
    if reject_request_pattern is not None:
        payload["reject_request_pattern"] = reject_request_pattern
    if reject_resource_types is not None:
        payload["reject_resource_types"] = reject_resource_types
    if set_extra_http_headers is not None:
        payload["set_extra_http_headers"] = set_extra_http_headers
    if set_java_script_enabled is not None:
        payload["set_java_script_enabled"] = set_java_script_enabled
    if user_agent is not None:
        payload["user_agent"] = user_agent
    if viewport is not None:
        payload["viewport"] = viewport
    if wait_for_selector is not None:
        payload["wait_for_selector"] = wait_for_selector
    if wait_for_timeout is not None:
        payload["wait_for_timeout"] = wait_for_timeout

    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/content",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ── PDF ───────────────────────────────────────────────────────────────────────

async def create_pdf(
    account_id: str,
    *,
    html: Optional[str] = None,
    url: Optional[str] = None,
    cache_ttl: Optional[float] = None,
    action_timeout: Optional[float] = None,
    add_script_tag: Optional[List[Dict[str, Any]]] = None,
    add_style_tag: Optional[List[Dict[str, Any]]] = None,
    allow_request_pattern: Optional[List[str]] = None,
    allow_resource_types: Optional[List[str]] = None,
    authenticate: Optional[Dict[str, str]] = None,
    best_attempt: Optional[bool] = None,
    cookies: Optional[List[Dict[str, Any]]] = None,
    emulate_media_type: Optional[str] = None,
    goto_options: Optional[Dict[str, Any]] = None,
    pdf_options: Optional[Dict[str, Any]] = None,
    reject_request_pattern: Optional[List[str]] = None,
    reject_resource_types: Optional[List[str]] = None,
    set_extra_http_headers: Optional[Dict[str, str]] = None,
    set_java_script_enabled: Optional[bool] = None,
    user_agent: Optional[str] = None,
    viewport: Optional[Dict[str, Any]] = None,
    wait_for_selector: Optional[Dict[str, Any]] = None,
    wait_for_timeout: Optional[float] = None,
) -> bytes:
    """POST /accounts/{account_id}/browser-rendering/pdf — retorna bytes PDF."""
    payload: Dict[str, Any] = {}
    if html is not None:
        payload["html"] = html
    if url is not None:
        payload["url"] = url
    if cache_ttl is not None:
        payload["cache_ttl"] = cache_ttl
    if action_timeout is not None:
        payload["action_timeout"] = action_timeout
    if add_script_tag is not None:
        payload["add_script_tag"] = add_script_tag
    if add_style_tag is not None:
        payload["add_style_tag"] = add_style_tag
    if allow_request_pattern is not None:
        payload["allow_request_pattern"] = allow_request_pattern
    if allow_resource_types is not None:
        payload["allow_resource_types"] = allow_resource_types
    if authenticate is not None:
        payload["authenticate"] = authenticate
    if best_attempt is not None:
        payload["best_attempt"] = best_attempt
    if cookies is not None:
        payload["cookies"] = cookies
    if emulate_media_type is not None:
        payload["emulate_media_type"] = emulate_media_type
    if goto_options is not None:
        payload["goto_options"] = goto_options
    if pdf_options is not None:
        payload["pdf_options"] = pdf_options
    if reject_request_pattern is not None:
        payload["reject_request_pattern"] = reject_request_pattern
    if reject_resource_types is not None:
        payload["reject_resource_types"] = reject_resource_types
    if set_extra_http_headers is not None:
        payload["set_extra_http_headers"] = set_extra_http_headers
    if set_java_script_enabled is not None:
        payload["set_java_script_enabled"] = set_java_script_enabled
    if user_agent is not None:
        payload["user_agent"] = user_agent
    if viewport is not None:
        payload["viewport"] = viewport
    if wait_for_selector is not None:
        payload["wait_for_selector"] = wait_for_selector
    if wait_for_timeout is not None:
        payload["wait_for_timeout"] = wait_for_timeout

    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/pdf",
            json=payload,
        )
        resp.raise_for_status()
        return resp.content


# ── Scrape ────────────────────────────────────────────────────────────────────

async def create_scrape(
    account_id: str,
    *,
    elements: List[Dict[str, str]],
    html: Optional[str] = None,
    url: Optional[str] = None,
    cache_ttl: Optional[float] = None,
    action_timeout: Optional[float] = None,
    add_script_tag: Optional[List[Dict[str, Any]]] = None,
    add_style_tag: Optional[List[Dict[str, Any]]] = None,
    allow_request_pattern: Optional[List[str]] = None,
    allow_resource_types: Optional[List[str]] = None,
    authenticate: Optional[Dict[str, str]] = None,
    best_attempt: Optional[bool] = None,
    cookies: Optional[List[Dict[str, Any]]] = None,
    emulate_media_type: Optional[str] = None,
    goto_options: Optional[Dict[str, Any]] = None,
    reject_request_pattern: Optional[List[str]] = None,
    reject_resource_types: Optional[List[str]] = None,
    set_extra_http_headers: Optional[Dict[str, str]] = None,
    set_java_script_enabled: Optional[bool] = None,
    user_agent: Optional[str] = None,
    viewport: Optional[Dict[str, Any]] = None,
    wait_for_selector: Optional[Dict[str, Any]] = None,
    wait_for_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/browser-rendering/scrape"""
    payload: Dict[str, Any] = {"elements": elements}
    if html is not None:
        payload["html"] = html
    if url is not None:
        payload["url"] = url
    if cache_ttl is not None:
        payload["cache_ttl"] = cache_ttl
    if action_timeout is not None:
        payload["action_timeout"] = action_timeout
    if add_script_tag is not None:
        payload["add_script_tag"] = add_script_tag
    if add_style_tag is not None:
        payload["add_style_tag"] = add_style_tag
    if allow_request_pattern is not None:
        payload["allow_request_pattern"] = allow_request_pattern
    if allow_resource_types is not None:
        payload["allow_resource_types"] = allow_resource_types
    if authenticate is not None:
        payload["authenticate"] = authenticate
    if best_attempt is not None:
        payload["best_attempt"] = best_attempt
    if cookies is not None:
        payload["cookies"] = cookies
    if emulate_media_type is not None:
        payload["emulate_media_type"] = emulate_media_type
    if goto_options is not None:
        payload["goto_options"] = goto_options
    if reject_request_pattern is not None:
        payload["reject_request_pattern"] = reject_request_pattern
    if reject_resource_types is not None:
        payload["reject_resource_types"] = reject_resource_types
    if set_extra_http_headers is not None:
        payload["set_extra_http_headers"] = set_extra_http_headers
    if set_java_script_enabled is not None:
        payload["set_java_script_enabled"] = set_java_script_enabled
    if user_agent is not None:
        payload["user_agent"] = user_agent
    if viewport is not None:
        payload["viewport"] = viewport
    if wait_for_selector is not None:
        payload["wait_for_selector"] = wait_for_selector
    if wait_for_timeout is not None:
        payload["wait_for_timeout"] = wait_for_timeout

    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/scrape",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ── Screenshot ────────────────────────────────────────────────────────────────

async def create_screenshot(
    account_id: str,
    *,
    html: Optional[str] = None,
    url: Optional[str] = None,
    cache_ttl: Optional[float] = None,
    action_timeout: Optional[float] = None,
    add_script_tag: Optional[List[Dict[str, Any]]] = None,
    add_style_tag: Optional[List[Dict[str, Any]]] = None,
    allow_request_pattern: Optional[List[str]] = None,
    allow_resource_types: Optional[List[str]] = None,
    authenticate: Optional[Dict[str, str]] = None,
    best_attempt: Optional[bool] = None,
    cookies: Optional[List[Dict[str, Any]]] = None,
    emulate_media_type: Optional[str] = None,
    goto_options: Optional[Dict[str, Any]] = None,
    reject_request_pattern: Optional[List[str]] = None,
    reject_resource_types: Optional[List[str]] = None,
    screenshot_options: Optional[Dict[str, Any]] = None,
    scroll_page: Optional[bool] = None,
    selector: Optional[str] = None,
    set_extra_http_headers: Optional[Dict[str, str]] = None,
    set_java_script_enabled: Optional[bool] = None,
    user_agent: Optional[str] = None,
    viewport: Optional[Dict[str, Any]] = None,
    wait_for_selector: Optional[Dict[str, Any]] = None,
    wait_for_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/browser-rendering/screenshot"""
    payload: Dict[str, Any] = {}
    if html is not None:
        payload["html"] = html
    if url is not None:
        payload["url"] = url
    if cache_ttl is not None:
        payload["cache_ttl"] = cache_ttl
    if action_timeout is not None:
        payload["action_timeout"] = action_timeout
    if add_script_tag is not None:
        payload["add_script_tag"] = add_script_tag
    if add_style_tag is not None:
        payload["add_style_tag"] = add_style_tag
    if allow_request_pattern is not None:
        payload["allow_request_pattern"] = allow_request_pattern
    if allow_resource_types is not None:
        payload["allow_resource_types"] = allow_resource_types
    if authenticate is not None:
        payload["authenticate"] = authenticate
    if best_attempt is not None:
        payload["best_attempt"] = best_attempt
    if cookies is not None:
        payload["cookies"] = cookies
    if emulate_media_type is not None:
        payload["emulate_media_type"] = emulate_media_type
    if goto_options is not None:
        payload["goto_options"] = goto_options
    if reject_request_pattern is not None:
        payload["reject_request_pattern"] = reject_request_pattern
    if reject_resource_types is not None:
        payload["reject_resource_types"] = reject_resource_types
    if screenshot_options is not None:
        payload["screenshot_options"] = screenshot_options
    if scroll_page is not None:
        payload["scroll_page"] = scroll_page
    if selector is not None:
        payload["selector"] = selector
    if set_extra_http_headers is not None:
        payload["set_extra_http_headers"] = set_extra_http_headers
    if set_java_script_enabled is not None:
        payload["set_java_script_enabled"] = set_java_script_enabled
    if user_agent is not None:
        payload["user_agent"] = user_agent
    if viewport is not None:
        payload["viewport"] = viewport
    if wait_for_selector is not None:
        payload["wait_for_selector"] = wait_for_selector
    if wait_for_timeout is not None:
        payload["wait_for_timeout"] = wait_for_timeout

    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/screenshot",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ── Snapshot ──────────────────────────────────────────────────────────────────

async def create_snapshot(
    account_id: str,
    *,
    html: Optional[str] = None,
    url: Optional[str] = None,
    cache_ttl: Optional[float] = None,
    action_timeout: Optional[float] = None,
    add_script_tag: Optional[List[Dict[str, Any]]] = None,
    add_style_tag: Optional[List[Dict[str, Any]]] = None,
    allow_request_pattern: Optional[List[str]] = None,
    allow_resource_types: Optional[List[str]] = None,
    authenticate: Optional[Dict[str, str]] = None,
    best_attempt: Optional[bool] = None,
    cookies: Optional[List[Dict[str, Any]]] = None,
    emulate_media_type: Optional[str] = None,
    goto_options: Optional[Dict[str, Any]] = None,
    reject_request_pattern: Optional[List[str]] = None,
    reject_resource_types: Optional[List[str]] = None,
    screenshot_options: Optional[Dict[str, Any]] = None,
    set_extra_http_headers: Optional[Dict[str, str]] = None,
    set_java_script_enabled: Optional[bool] = None,
    user_agent: Optional[str] = None,
    viewport: Optional[Dict[str, Any]] = None,
    wait_for_selector: Optional[Dict[str, Any]] = None,
    wait_for_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/browser-rendering/snapshot"""
    payload: Dict[str, Any] = {}
    if html is not None:
        payload["html"] = html
    if url is not None:
        payload["url"] = url
    if cache_ttl is not None:
        payload["cache_ttl"] = cache_ttl
    if action_timeout is not None:
        payload["action_timeout"] = action_timeout
    if add_script_tag is not None:
        payload["add_script_tag"] = add_script_tag
    if add_style_tag is not None:
        payload["add_style_tag"] = add_style_tag
    if allow_request_pattern is not None:
        payload["allow_request_pattern"] = allow_request_pattern
    if allow_resource_types is not None:
        payload["allow_resource_types"] = allow_resource_types
    if authenticate is not None:
        payload["authenticate"] = authenticate
    if best_attempt is not None:
        payload["best_attempt"] = best_attempt
    if cookies is not None:
        payload["cookies"] = cookies
    if emulate_media_type is not None:
        payload["emulate_media_type"] = emulate_media_type
    if goto_options is not None:
        payload["goto_options"] = goto_options
    if reject_request_pattern is not None:
        payload["reject_request_pattern"] = reject_request_pattern
    if reject_resource_types is not None:
        payload["reject_resource_types"] = reject_resource_types
    if screenshot_options is not None:
        payload["screenshot_options"] = screenshot_options
    if set_extra_http_headers is not None:
        payload["set_extra_http_headers"] = set_extra_http_headers
    if set_java_script_enabled is not None:
        payload["set_java_script_enabled"] = set_java_script_enabled
    if user_agent is not None:
        payload["user_agent"] = user_agent
    if viewport is not None:
        payload["viewport"] = viewport
    if wait_for_selector is not None:
        payload["wait_for_selector"] = wait_for_selector
    if wait_for_timeout is not None:
        payload["wait_for_timeout"] = wait_for_timeout

    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/snapshot",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ── JSON ──────────────────────────────────────────────────────────────────────

async def create_json(
    account_id: str,
    *,
    html: Optional[str] = None,
    url: Optional[str] = None,
    cache_ttl: Optional[float] = None,
    action_timeout: Optional[float] = None,
    add_script_tag: Optional[List[Dict[str, Any]]] = None,
    add_style_tag: Optional[List[Dict[str, Any]]] = None,
    allow_request_pattern: Optional[List[str]] = None,
    allow_resource_types: Optional[List[str]] = None,
    authenticate: Optional[Dict[str, str]] = None,
    best_attempt: Optional[bool] = None,
    cookies: Optional[List[Dict[str, Any]]] = None,
    custom_ai: Optional[List[Dict[str, Any]]] = None,
    emulate_media_type: Optional[str] = None,
    goto_options: Optional[Dict[str, Any]] = None,
    prompt: Optional[str] = None,
    reject_request_pattern: Optional[List[str]] = None,
    reject_resource_types: Optional[List[str]] = None,
    response_format: Optional[Dict[str, Any]] = None,
    set_extra_http_headers: Optional[Dict[str, str]] = None,
    set_java_script_enabled: Optional[bool] = None,
    user_agent: Optional[str] = None,
    viewport: Optional[Dict[str, Any]] = None,
    wait_for_selector: Optional[Dict[str, Any]] = None,
    wait_for_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/browser-rendering/json"""
    payload: Dict[str, Any] = {}
    if html is not None:
        payload["html"] = html
    if url is not None:
        payload["url"] = url
    if cache_ttl is not None:
        payload["cache_ttl"] = cache_ttl
    if action_timeout is not None:
        payload["action_timeout"] = action_timeout
    if add_script_tag is not None:
        payload["add_script_tag"] = add_script_tag
    if add_style_tag is not None:
        payload["add_style_tag"] = add_style_tag
    if allow_request_pattern is not None:
        payload["allow_request_pattern"] = allow_request_pattern
    if allow_resource_types is not None:
        payload["allow_resource_types"] = allow_resource_types
    if authenticate is not None:
        payload["authenticate"] = authenticate
    if best_attempt is not None:
        payload["best_attempt"] = best_attempt
    if cookies is not None:
        payload["cookies"] = cookies
    if custom_ai is not None:
        payload["custom_ai"] = custom_ai
    if emulate_media_type is not None:
        payload["emulate_media_type"] = emulate_media_type
    if goto_options is not None:
        payload["goto_options"] = goto_options
    if prompt is not None:
        payload["prompt"] = prompt
    if reject_request_pattern is not None:
        payload["reject_request_pattern"] = reject_request_pattern
    if reject_resource_types is not None:
        payload["reject_resource_types"] = reject_resource_types
    if response_format is not None:
        payload["response_format"] = response_format
    if set_extra_http_headers is not None:
        payload["set_extra_http_headers"] = set_extra_http_headers
    if set_java_script_enabled is not None:
        payload["set_java_script_enabled"] = set_java_script_enabled
    if user_agent is not None:
        payload["user_agent"] = user_agent
    if viewport is not None:
        payload["viewport"] = viewport
    if wait_for_selector is not None:
        payload["wait_for_selector"] = wait_for_selector
    if wait_for_timeout is not None:
        payload["wait_for_timeout"] = wait_for_timeout

    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/json",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ── Links ─────────────────────────────────────────────────────────────────────

async def create_links(
    account_id: str,
    *,
    html: Optional[str] = None,
    url: Optional[str] = None,
    cache_ttl: Optional[float] = None,
    action_timeout: Optional[float] = None,
    add_script_tag: Optional[List[Dict[str, Any]]] = None,
    add_style_tag: Optional[List[Dict[str, Any]]] = None,
    allow_request_pattern: Optional[List[str]] = None,
    allow_resource_types: Optional[List[str]] = None,
    authenticate: Optional[Dict[str, str]] = None,
    best_attempt: Optional[bool] = None,
    cookies: Optional[List[Dict[str, Any]]] = None,
    emulate_media_type: Optional[str] = None,
    exclude_external_links: Optional[bool] = None,
    goto_options: Optional[Dict[str, Any]] = None,
    reject_request_pattern: Optional[List[str]] = None,
    reject_resource_types: Optional[List[str]] = None,
    set_extra_http_headers: Optional[Dict[str, str]] = None,
    set_java_script_enabled: Optional[bool] = None,
    user_agent: Optional[str] = None,
    viewport: Optional[Dict[str, Any]] = None,
    visible_links_only: Optional[bool] = None,
    wait_for_selector: Optional[Dict[str, Any]] = None,
    wait_for_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/browser-rendering/links"""
    payload: Dict[str, Any] = {}
    if html is not None:
        payload["html"] = html
    if url is not None:
        payload["url"] = url
    if cache_ttl is not None:
        payload["cache_ttl"] = cache_ttl
    if action_timeout is not None:
        payload["action_timeout"] = action_timeout
    if add_script_tag is not None:
        payload["add_script_tag"] = add_script_tag
    if add_style_tag is not None:
        payload["add_style_tag"] = add_style_tag
    if allow_request_pattern is not None:
        payload["allow_request_pattern"] = allow_request_pattern
    if allow_resource_types is not None:
        payload["allow_resource_types"] = allow_resource_types
    if authenticate is not None:
        payload["authenticate"] = authenticate
    if best_attempt is not None:
        payload["best_attempt"] = best_attempt
    if cookies is not None:
        payload["cookies"] = cookies
    if emulate_media_type is not None:
        payload["emulate_media_type"] = emulate_media_type
    if exclude_external_links is not None:
        payload["exclude_external_links"] = exclude_external_links
    if goto_options is not None:
        payload["goto_options"] = goto_options
    if reject_request_pattern is not None:
        payload["reject_request_pattern"] = reject_request_pattern
    if reject_resource_types is not None:
        payload["reject_resource_types"] = reject_resource_types
    if set_extra_http_headers is not None:
        payload["set_extra_http_headers"] = set_extra_http_headers
    if set_java_script_enabled is not None:
        payload["set_java_script_enabled"] = set_java_script_enabled
    if user_agent is not None:
        payload["user_agent"] = user_agent
    if viewport is not None:
        payload["viewport"] = viewport
    if visible_links_only is not None:
        payload["visible_links_only"] = visible_links_only
    if wait_for_selector is not None:
        payload["wait_for_selector"] = wait_for_selector
    if wait_for_timeout is not None:
        payload["wait_for_timeout"] = wait_for_timeout

    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/links",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ── Markdown ──────────────────────────────────────────────────────────────────

async def create_markdown(
    account_id: str,
    *,
    url: str,
    cache_ttl: Optional[float] = None,
    action_timeout: Optional[float] = None,
    add_script_tag: Optional[List[Dict[str, Any]]] = None,
    add_style_tag: Optional[List[Dict[str, Any]]] = None,
    allow_request_pattern: Optional[List[str]] = None,
    allow_resource_types: Optional[List[str]] = None,
    authenticate: Optional[Dict[str, str]] = None,
    best_attempt: Optional[bool] = None,
    cookies: Optional[List[Dict[str, Any]]] = None,
    emulate_media_type: Optional[str] = None,
    goto_options: Optional[Dict[str, Any]] = None,
    reject_request_pattern: Optional[List[str]] = None,
    reject_resource_types: Optional[List[str]] = None,
    set_extra_http_headers: Optional[Dict[str, str]] = None,
    set_java_script_enabled: Optional[bool] = None,
    user_agent: Optional[str] = None,
    viewport: Optional[Dict[str, Any]] = None,
    wait_for_selector: Optional[Dict[str, Any]] = None,
    wait_for_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/browser-rendering/markdown"""
    payload: Dict[str, Any] = {"url": url}
    if cache_ttl is not None:
        payload["cache_ttl"] = cache_ttl
    if action_timeout is not None:
        payload["action_timeout"] = action_timeout
    if add_script_tag is not None:
        payload["add_script_tag"] = add_script_tag
    if add_style_tag is not None:
        payload["add_style_tag"] = add_style_tag
    if allow_request_pattern is not None:
        payload["allow_request_pattern"] = allow_request_pattern
    if allow_resource_types is not None:
        payload["allow_resource_types"] = allow_resource_types
    if authenticate is not None:
        payload["authenticate"] = authenticate
    if best_attempt is not None:
        payload["best_attempt"] = best_attempt
    if cookies is not None:
        payload["cookies"] = cookies
    if emulate_media_type is not None:
        payload["emulate_media_type"] = emulate_media_type
    if goto_options is not None:
        payload["goto_options"] = goto_options
    if reject_request_pattern is not None:
        payload["reject_request_pattern"] = reject_request_pattern
    if reject_resource_types is not None:
        payload["reject_resource_types"] = reject_resource_types
    if set_extra_http_headers is not None:
        payload["set_extra_http_headers"] = set_extra_http_headers
    if set_java_script_enabled is not None:
        payload["set_java_script_enabled"] = set_java_script_enabled
    if user_agent is not None:
        payload["user_agent"] = user_agent
    if viewport is not None:
        payload["viewport"] = viewport
    if wait_for_selector is not None:
        payload["wait_for_selector"] = wait_for_selector
    if wait_for_timeout is not None:
        payload["wait_for_timeout"] = wait_for_timeout

    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/markdown",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ── Crawl ─────────────────────────────────────────────────────────────────────

async def create_crawl(
    account_id: str,
    *,
    url: str,
    cache_ttl: Optional[float] = None,
    action_timeout: Optional[float] = None,
    add_script_tag: Optional[List[Dict[str, Any]]] = None,
    add_style_tag: Optional[List[Dict[str, Any]]] = None,
    allow_request_pattern: Optional[List[str]] = None,
    allow_resource_types: Optional[List[str]] = None,
    authenticate: Optional[Dict[str, str]] = None,
    best_attempt: Optional[bool] = None,
    cookies: Optional[List[Dict[str, Any]]] = None,
    crawl_purposes: Optional[List[str]] = None,
    depth: Optional[float] = None,
    emulate_media_type: Optional[str] = None,
    formats: Optional[List[str]] = None,
    goto_options: Optional[Dict[str, Any]] = None,
    json_options: Optional[Dict[str, Any]] = None,
    limit: Optional[float] = None,
    max_age: Optional[float] = None,
    modified_since: Optional[int] = None,
    options: Optional[Dict[str, Any]] = None,
    reject_request_pattern: Optional[List[str]] = None,
    reject_resource_types: Optional[List[str]] = None,
    render: Optional[bool] = None,
    set_extra_http_headers: Optional[Dict[str, str]] = None,
    set_java_script_enabled: Optional[bool] = None,
    source: Optional[str] = None,
    viewport: Optional[Dict[str, Any]] = None,
    wait_for_selector: Optional[Dict[str, Any]] = None,
    wait_for_timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/browser-rendering/crawl"""
    payload: Dict[str, Any] = {"url": url}
    if cache_ttl is not None:
        payload["cache_ttl"] = cache_ttl
    if action_timeout is not None:
        payload["action_timeout"] = action_timeout
    if add_script_tag is not None:
        payload["add_script_tag"] = add_script_tag
    if add_style_tag is not None:
        payload["add_style_tag"] = add_style_tag
    if allow_request_pattern is not None:
        payload["allow_request_pattern"] = allow_request_pattern
    if allow_resource_types is not None:
        payload["allow_resource_types"] = allow_resource_types
    if authenticate is not None:
        payload["authenticate"] = authenticate
    if best_attempt is not None:
        payload["best_attempt"] = best_attempt
    if cookies is not None:
        payload["cookies"] = cookies
    if crawl_purposes is not None:
        payload["crawl_purposes"] = crawl_purposes
    if depth is not None:
        payload["depth"] = depth
    if emulate_media_type is not None:
        payload["emulate_media_type"] = emulate_media_type
    if formats is not None:
        payload["formats"] = formats
    if goto_options is not None:
        payload["goto_options"] = goto_options
    if json_options is not None:
        payload["json_options"] = json_options
    if limit is not None:
        payload["limit"] = limit
    if max_age is not None:
        payload["max_age"] = max_age
    if modified_since is not None:
        payload["modified_since"] = modified_since
    if options is not None:
        payload["options"] = options
    if reject_request_pattern is not None:
        payload["reject_request_pattern"] = reject_request_pattern
    if reject_resource_types is not None:
        payload["reject_resource_types"] = reject_resource_types
    if render is not None:
        payload["render"] = render
    if set_extra_http_headers is not None:
        payload["set_extra_http_headers"] = set_extra_http_headers
    if set_java_script_enabled is not None:
        payload["set_java_script_enabled"] = set_java_script_enabled
    if source is not None:
        payload["source"] = source
    if viewport is not None:
        payload["viewport"] = viewport
    if wait_for_selector is not None:
        payload["wait_for_selector"] = wait_for_selector
    if wait_for_timeout is not None:
        payload["wait_for_timeout"] = wait_for_timeout

    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/crawl",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def get_crawl(
    account_id: str,
    job_id: str,
    *,
    cache_ttl: Optional[float] = None,
    cursor: Optional[float] = None,
    limit: Optional[float] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/browser-rendering/crawl/{job_id}"""
    params: Dict[str, Any] = {}
    if cache_ttl is not None:
        params["cache_ttl"] = cache_ttl
    if cursor is not None:
        params["cursor"] = cursor
    if limit is not None:
        params["limit"] = limit
    if status is not None:
        params["status"] = status

    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/crawl/{job_id}",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def delete_crawl(
    account_id: str,
    job_id: str,
) -> Dict[str, Any]:
    """DELETE /accounts/{account_id}/browser-rendering/crawl/{job_id}"""
    async with _client() as client:
        resp = await client.delete(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/crawl/{job_id}",
        )
        resp.raise_for_status()
        return resp.json()


# ── Devtools Session ──────────────────────────────────────────────────────────

async def list_devtools_sessions(
    account_id: str,
    *,
    limit: Optional[float] = None,
    offset: Optional[float] = None,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/browser-rendering/devtools/session"""
    params: Dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset

    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/devtools/session",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def get_devtools_session(
    account_id: str,
    session_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/browser-rendering/devtools/session/{session_id}"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/devtools/session/{session_id}",
        )
        resp.raise_for_status()
        return resp.json()


# ── Devtools Browser ──────────────────────────────────────────────────────────

async def create_devtools_browser(
    account_id: str,
    *,
    keep_alive: Optional[float] = None,
    lab: Optional[bool] = None,
    recording: Optional[bool] = None,
    targets: Optional[bool] = None,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/browser-rendering/devtools/browser"""
    payload: Dict[str, Any] = {}
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    if lab is not None:
        payload["lab"] = lab
    if recording is not None:
        payload["recording"] = recording
    if targets is not None:
        payload["targets"] = targets

    async with _client() as client:
        resp = await client.post(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/devtools/browser",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def get_devtools_browser_version(
    account_id: str,
    session_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/browser-rendering/devtools/browser/{session_id}/json/version"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/devtools/browser/{session_id}/json/version",
        )
        resp.raise_for_status()
        return resp.json()


async def get_devtools_browser_protocol(
    account_id: str,
    session_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/browser-rendering/devtools/browser/{session_id}/json/protocol"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/devtools/browser/{session_id}/json/protocol",
        )
        resp.raise_for_status()
        return resp.json()


async def delete_devtools_browser(
    account_id: str,
    session_id: str,
) -> Dict[str, Any]:
    """DELETE /accounts/{account_id}/browser-rendering/devtools/browser/{session_id}"""
    async with _client() as client:
        resp = await client.delete(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/devtools/browser/{session_id}",
        )
        resp.raise_for_status()
        return resp.json()


# ── Devtools Targets ──────────────────────────────────────────────────────────

async def create_devtools_target(
    account_id: str,
    session_id: str,
    *,
    url: Optional[str] = None,
) -> Dict[str, Any]:
    """PUT /accounts/{account_id}/browser-rendering/devtools/browser/{session_id}/json/new"""
    payload: Dict[str, Any] = {}
    if url is not None:
        payload["url"] = url

    async with _client() as client:
        resp = await client.put(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/devtools/browser/{session_id}/json/new",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def list_devtools_targets(
    account_id: str,
    session_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/browser-rendering/devtools/browser/{session_id}/json/list"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/devtools/browser/{session_id}/json/list",
        )
        resp.raise_for_status()
        return resp.json()


async def get_devtools_target(
    account_id: str,
    session_id: str,
    target_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/browser-rendering/devtools/browser/{session_id}/json/list/{target_id}"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/devtools/browser/{session_id}/json/list/{target_id}",
        )
        resp.raise_for_status()
        return resp.json()


async def activate_devtools_target(
    account_id: str,
    session_id: str,
    target_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/browser-rendering/devtools/browser/{session_id}/json/activate/{target_id}"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/devtools/browser/{session_id}/json/activate/{target_id}",
        )
        resp.raise_for_status()
        return resp.json()


async def close_devtools_target(
    account_id: str,
    session_id: str,
    target_id: str,
) -> Dict[str, Any]:
    """GET /accounts/{account_id}/browser-rendering/devtools/browser/{session_id}/json/close/{target_id}"""
    async with _client() as client:
        resp = await client.get(
            f"{_base_url()}/accounts/{account_id}/browser-rendering/devtools/browser/{session_id}/json/close/{target_id}",
        )
        resp.raise_for_status()
        return resp.json()
