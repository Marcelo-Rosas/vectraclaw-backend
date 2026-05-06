"""
Captura opcional de páginas sociais (LinkedIn/Instagram) via Playwright + upload no Storage.

Env:
  PROSPECT_PLAYWRIGHT_ENABLED=true|false
  PROSPECT_PLAYWRIGHT_STORAGE_STATE=/caminho/auth.json  (exportado do Playwright log-in)
  PROSPECT_STORAGE_BUCKET=prospect-research  (default)

Dois modos de uso:
  capture_social_pages_for_context  — captura ANTES do Gemini, retorna texto para o prompt
  capture_social_pages_to_storage   — captura APÓS o Gemini, salva HTML no Storage
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def collect_document_urls(documents: Any) -> List[str]:
    out: List[str] = []
    if not isinstance(documents, list):
        return out
    for d in documents:
        if isinstance(d, dict):
            u = d.get("uri") or d.get("url")
            if u and isinstance(u, str) and u.startswith(("http://", "https://")):
                out.append(u.strip())
    return out


def _is_social_url(url: str) -> bool:
    u = url.lower()
    return "linkedin.com" in u or "instagram.com" in u


def _url_slug(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def _playwright_enabled() -> bool:
    return os.getenv("PROSPECT_PLAYWRIGHT_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


_MAX_CHARS_PER_PAGE = 12_000


async def capture_social_pages_for_context(
    *,
    urls: List[str],
    max_chars_per_page: int = _MAX_CHARS_PER_PAGE,
) -> List[Dict[str, Any]]:
    """
    Captura LinkedIn/Instagram ANTES do Gemini e devolve texto extraído de cada página.
    Retorna lista de {url, content: str, error?: str}.
    Requer PROSPECT_PLAYWRIGHT_ENABLED=true + PROSPECT_PLAYWRIGHT_STORAGE_STATE válido.
    """
    result: List[Dict[str, Any]] = []
    if not _playwright_enabled():
        return result

    state_path = os.getenv("PROSPECT_PLAYWRIGHT_STORAGE_STATE", "").strip()
    if not state_path or not os.path.isfile(state_path):
        logger.info("prospect_playwright: storage_state ausente — skip context capture")
        return result

    social = [u for u in urls if _is_social_url(u)]
    if not social:
        return result

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("prospect_playwright: playwright não instalado")
        return result

    logger.info("prospect_playwright: capturando %d URLs para contexto Gemini", len(social))
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            ctx = await browser.new_context(
                storage_state=state_path,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = await ctx.new_page()
            for url in social[:6]:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    # Aguarda conteúdo dinâmico mínimo
                    await page.wait_for_timeout(2500)
                    # Extrai texto visível (mais compacto que HTML bruto)
                    text: str = await page.evaluate(
                        "() => document.body ? document.body.innerText : ''"
                    )
                    text = (text or "").strip()
                    if len(text) > max_chars_per_page:
                        text = text[:max_chars_per_page] + "\n[...truncado]"
                    result.append({"url": url, "content": text})
                    logger.info(
                        "prospect_playwright: capturado url=%s chars=%d", url, len(text)
                    )
                except Exception as exc:
                    err = str(exc)[:300]
                    logger.warning("prospect_playwright: falha context url=%s: %s", url, err)
                    result.append({"url": url, "content": "", "error": err})
            await ctx.close()
        finally:
            await browser.close()

    return result


async def capture_social_pages_to_storage(
    supabase: Any,
    *,
    company_id: str,
    task_id: str,
    urls: List[str],
) -> List[Dict[str, Any]]:
    """
    Para URLs LinkedIn/Instagram, tenta renderizar com Playwright (storage_state com cookie de sessão)
    e envia HTML ao Storage. Retorna lista de refs {bucket, path, url, error?}.
    """
    refs: List[Dict[str, Any]] = []
    if not supabase or not _playwright_enabled():
        return refs

    state_path = os.getenv("PROSPECT_PLAYWRIGHT_STORAGE_STATE", "").strip()
    if not state_path or not os.path.isfile(state_path):
        logger.info(
            "prospect_playwright: PROSPECT_PLAYWRIGHT_STORAGE_STATE ausente ou arquivo inexistente — skip capture"
        )
        return refs

    social = [u for u in urls if _is_social_url(u)]
    if not social:
        return refs

    bucket = os.getenv("PROSPECT_STORAGE_BUCKET", "prospect-research").strip() or "prospect-research"

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("prospect_playwright: playwright não instalado")
        return refs

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(storage_state=state_path)
            page = await context.new_page()
            for url in social[:8]:
                path = f"{company_id}/{task_id}/{_url_slug(url)}.html"
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    html = await page.content()
                    raw = html.encode("utf-8")
                    supabase.storage.from_(bucket).upload(
                        path,
                        raw,
                        file_options={
                            "content-type": "text/html; charset=utf-8",
                            "x-upsert": "true",
                        },
                    )
                    refs.append({"bucket": bucket, "path": path, "url": url})
                    logger.info("prospect_playwright: uploaded url=%s path=%s", url, path)
                except Exception as exc:
                    err = str(exc)[:400]
                    logger.warning("prospect_playwright: falha url=%s: %s", url, err)
                    refs.append({"bucket": bucket, "path": None, "url": url, "error": err})
            await context.close()
        finally:
            await browser.close()

    return refs
