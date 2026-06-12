"""
KronosPlannerSession — wrapper async Playwright pra automação do webapp
Meu Planner Financeiro (https://web.meuplannerfinanceiro.com.br).

VEC-418 (sub-PR1 do VEC-416). Não inclui handler de import nem de
categorização — só a infra que VEC-419..VEC-422 vão reusar.

Uso típico:

    async with KronosPlannerSession() as session:
        await session.page.goto(
            "https://web.meuplannerfinanceiro.com.br/controle/lancamentos"
        )
        await session.dismiss_known_modals()
        # ... interações
        toast = await session.wait_for_save_toast()
        # toast == "Lançamento atualizado com sucesso."
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from playwright.async_api import (  # pyright: ignore[reportMissingImports]
        BrowserContext,
        Page,
        Playwright,
        TimeoutError as PlaywrightTimeoutError,
        async_playwright,
    )
except ImportError as exc:  # pragma: no cover — exercitado só sem playwright instalado
    raise ImportError(
        "playwright não instalado. Rode `pip install playwright` e depois "
        "`playwright install chromium`."
    ) from exc


logger = logging.getLogger(__name__)


# ── Constantes mapeadas na recon (2026-05-12) ─────────────────────────

PLANNER_BASE_URL = "https://web.meuplannerfinanceiro.com.br"
PLANNER_LOGIN_URL = f"{PLANNER_BASE_URL}/login"
PLANNER_HOME_URL = f"{PLANNER_BASE_URL}/inicio"

SELECTOR_LOADING_OVERLAY = "div.absolute.top-0.left-0.z-50.bg-opacity-50"
SELECTOR_TOAST_SUCCESS = ".Toastify__toast--success"
SELECTOR_TOAST_ERROR = ".Toastify__toast--error"
SELECTOR_TOAST_BODY = ".Toastify__toast-body"

INPUT_EMAIL = 'input[name="username"]'
INPUT_PASSWORD = 'input[name="password"]'

DEFAULT_NAV_TIMEOUT_MS = 15_000
DEFAULT_OVERLAY_TIMEOUT_MS = 10_000
DEFAULT_TOAST_TIMEOUT_MS = 5_000


# ── Erros ────────────────────────────────────────────────────────────


class KronosBrowserError(Exception):
    """Erro base do KronosPlannerSession."""


class KronosBrowserConfigError(KronosBrowserError):
    """Configuração inválida (env vars ausentes, paths inválidos, etc)."""


class KronosLoginFailed(KronosBrowserError):
    """Login não completou (captcha, credenciais erradas, DOM mudou, etc)."""


class KronosSaveTimeout(KronosBrowserError):
    """Toast de sucesso não apareceu dentro do timeout."""


# ── Helpers ─────────────────────────────────────────────────────────


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("true", "1", "yes", "on")


def _safe_label(label: str, max_len: int = 60) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", label)[:max_len] or "noname"


# ── Sessão principal ────────────────────────────────────────────────


class KronosPlannerSession:
    """Async context manager pra browser Playwright autenticado no Meu Planner.

    Garantias do `__aenter__`:
    - Chromium iniciado (headless por default).
    - Sessão autenticada — faz login se não houver cookie válido.
    - Modais conhecidos dismissados (Upgrade Premium, alert de sessão expirada).

    Side effects do `__aexit__`:
    - Em caso de exceção, captura screenshot full-page em `audit-results/`.
    - Persiste cookies/storage em `.kronos-browser-storage/state.json` pra reuso.
    """

    STORAGE_DIR = Path(".kronos-browser-storage")
    DEFAULT_STORAGE_PATH = STORAGE_DIR / "state.json"
    SCREENSHOT_DIR = Path("audit-results")

    def __init__(
        self,
        email: Optional[str] = None,
        password: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        login_url: Optional[str] = None,
        headless: Optional[bool] = None,
        storage_state_path: Optional[Path] = None,
        nav_timeout_ms: int = DEFAULT_NAV_TIMEOUT_MS,
    ) -> None:
        self.email = (email if email is not None else os.getenv("PLANNER_EMAIL", "")).strip()
        self.password = (
            password if password is not None else os.getenv("PLANNER_PASSWORD", "")
        ).strip()
        if not self.email or not self.password:
            raise KronosBrowserConfigError(
                "Credenciais de automação web ausentes — passe email/password, "
                "configure Admin → MCP (mcp-web-automation) ou .env PLANNER_* (dev)."
            )

        self.base_url = (base_url or PLANNER_BASE_URL).rstrip("/")
        self.login_url = (login_url or f"{self.base_url}/login").rstrip("/")
        self.home_url = f"{self.base_url}/inicio"

        if headless is None:
            headless = not _truthy_env("KRONOS_PLAYWRIGHT_HEADED", default=False)
        self.headless = headless

        self.storage_state_path = (
            Path(storage_state_path)
            if storage_state_path is not None
            else self.DEFAULT_STORAGE_PATH
        )
        self.nav_timeout_ms = nav_timeout_ms

        self._playwright: Optional[Playwright] = None
        self._browser: Any = None
        self._context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    # ── Context manager ──

    async def __aenter__(self) -> "KronosPlannerSession":
        try:
            self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
            self.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise KronosBrowserConfigError(
                f"não foi possível criar diretórios de storage/screenshot: {exc}"
            ) from exc

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        storage_arg = (
            str(self.storage_state_path) if self.storage_state_path.exists() else None
        )
        self._context = await self._browser.new_context(storage_state=storage_arg)
        self._context.set_default_navigation_timeout(self.nav_timeout_ms)
        self._context.set_default_timeout(self.nav_timeout_ms)

        self.page = await self._context.new_page()
        # Alert nativo "Sua sessão expirou" — aceita automaticamente.
        self.page.on(
            "dialog", lambda dialog: asyncio.create_task(dialog.accept())
        )

        try:
            await self._ensure_logged_in()
        except Exception:
            await self._safe_screenshot("login-init-failed")
            raise

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            await self._safe_screenshot(f"error-{exc_type.__name__}")

        if self._context is not None:
            try:
                await self._context.storage_state(path=str(self.storage_state_path))
            except Exception as save_err:
                logger.warning("falha ao persistir storage state: %s", save_err)
            try:
                await self._context.close()
            except Exception as close_err:
                logger.debug("context.close ignorado: %s", close_err)

        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass

    # ── Login flow ──

    async def _ensure_logged_in(self) -> None:
        page = self._require_page()
        # Navega direto para /login. Se já logado via cookies, o SPA redireciona
        # para /inicio. Se não logado, /login renderiza o form (evita o alert
        # "Sua sessão expirou" que aparece quando vamos para /inicio sem cookie).
        try:
            await page.goto(self.login_url, wait_until="domcontentloaded")
        except PlaywrightTimeoutError as exc:
            raise KronosLoginFailed(
                f"timeout navegando para {self.login_url}: {exc}"
            ) from exc

        try:
            await page.wait_for_load_state("networkidle", timeout=self.nav_timeout_ms)
        except PlaywrightTimeoutError:
            logger.debug("networkidle não atingido em /login; prosseguindo")

        if "/inicio" in page.url:
            # Cookie da storage_state já validou — pulamos login.
            logger.debug("já autenticado via storage state — login skipado")
            await self.dismiss_known_modals()
            return

        if "/login" not in page.url:
            await self._safe_screenshot("login-unexpected-url")
            raise KronosLoginFailed(
                f"esperava /login ou /inicio, mas estamos em {page.url}"
            )

        await self._do_login()
        try:
            await page.wait_for_url(
                re.compile(r"/inicio"), timeout=self.nav_timeout_ms
            )
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot("login-no-redirect")
            raise KronosLoginFailed(
                "após submit do login, não redirecionou para /inicio"
            ) from exc

        await self.dismiss_known_modals()

    async def _do_login(self) -> None:
        page = self._require_page()
        try:
            # Aguarda o form renderizar (SPA pode demorar a montar)
            await page.wait_for_selector(INPUT_EMAIL, state="visible", timeout=10_000)
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot("login-form-not-rendered")
            raise KronosLoginFailed(
                f"form de login não renderizou: {exc}"
            ) from exc

        try:
            await page.fill(INPUT_EMAIL, self.email)
            await page.fill(INPUT_PASSWORD, self.password)
            submit = page.locator('button[type="submit"]').first
            await submit.click()
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot("login-submit-failed")
            raise KronosLoginFailed(f"falha ao preencher/submeter login: {exc}") from exc

    # ── Helpers públicos ──

    async def dismiss_known_modals(self) -> None:
        """Fecha modais conhecidos se estiverem abertos. Idempotente."""
        page = self._require_page()
        await self._dismiss_premium_modal(page)

    async def wait_for_loading_overlay(
        self, timeout: int = DEFAULT_OVERLAY_TIMEOUT_MS
    ) -> None:
        """Aguarda o overlay de loading do Planner sumir."""
        page = self._require_page()
        try:
            await page.locator(SELECTOR_LOADING_OVERLAY).first.wait_for(
                state="hidden", timeout=timeout
            )
        except PlaywrightTimeoutError:
            logger.warning(
                "loading overlay ainda visível após %dms — seguindo mesmo assim",
                timeout,
            )

    async def wait_for_save_toast(
        self, timeout: int = DEFAULT_TOAST_TIMEOUT_MS
    ) -> str:
        """Aguarda toast de sucesso aparecer; retorna o texto.

        Levanta `KronosSaveTimeout` se nem o success nem o error toast aparecerem.
        Levanta `KronosSaveTimeout` (com mensagem do erro) se um error toast surgir.
        """
        page = self._require_page()
        success = page.locator(SELECTOR_TOAST_SUCCESS).first
        error = page.locator(SELECTOR_TOAST_ERROR).first

        try:
            await success.wait_for(state="visible", timeout=timeout)
        except PlaywrightTimeoutError as exc:
            if await error.count() > 0 and await error.is_visible():
                err_text = (
                    await error.locator(SELECTOR_TOAST_BODY).text_content()
                ) or "erro sem texto"
                raise KronosSaveTimeout(
                    f"backend retornou erro: {err_text.strip()}"
                ) from exc
            raise KronosSaveTimeout(
                f"toast de sucesso não apareceu em {timeout}ms"
            ) from exc

        body_text = (
            await success.locator(SELECTOR_TOAST_BODY).text_content()
        ) or ""
        return body_text.strip()

    async def screenshot(self, label: str) -> Path:
        """Salva screenshot full-page em `audit-results/kronos-<label>-<ts>.png`."""
        page = self._require_page()
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.SCREENSHOT_DIR / f"kronos-{_safe_label(label)}-{ts}.png"
        await page.screenshot(path=str(path), full_page=True)
        logger.info("screenshot: %s", path)
        return path

    # ── Internos ──

    def _require_page(self) -> Page:
        if self.page is None:
            raise KronosBrowserError(
                "KronosPlannerSession não está dentro de um `async with` ativo."
            )
        return self.page

    async def _safe_screenshot(self, label: str) -> None:
        if self.page is None:
            return
        try:
            await self.screenshot(label)
        except Exception as exc:
            logger.warning("screenshot %s falhou: %s", label, exc)

    async def _dismiss_premium_modal(self, page: Page) -> None:
        try:
            modal = page.locator(
                'dialog:has(h2:has-text("Upgrade para Plano Premium"))'
            )
            if await modal.count() == 0:
                return
            visible = await modal.first.is_visible()
            if not visible:
                return
            close_btn = modal.first.locator('button:has-text("✕")').first
            if await close_btn.count() > 0:
                await close_btn.click(timeout=2_000)
                logger.debug("modal Upgrade Premium fechado")
        except PlaywrightTimeoutError:
            logger.debug("timeout fechando modal Premium — não bloqueante")
        except Exception as exc:
            logger.debug("dismiss premium modal ignorado: %s", exc)


__all__ = [
    "KronosBrowserError",
    "KronosBrowserConfigError",
    "KronosLoginFailed",
    "KronosSaveTimeout",
    "KronosPlannerSession",
    "PLANNER_BASE_URL",
    "PLANNER_HOME_URL",
    "PLANNER_LOGIN_URL",
    "SELECTOR_LOADING_OVERLAY",
    "SELECTOR_TOAST_SUCCESS",
    "SELECTOR_TOAST_ERROR",
    "SELECTOR_TOAST_BODY",
]
