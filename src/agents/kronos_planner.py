"""
Kronos Planner Import — handler do `operation_type='planner-import-ofx'`.

VEC-419 (sub-PR2 do VEC-416). Substitui o pipeline legacy (OFX × planner local
+ SMTP de conciliação via HermesReporter) pelo fluxo novo: upload de OFX no
webapp Meu Planner Financeiro via Playwright. Sem categorização ainda — as
linhas importadas ficam "Pendente" pro VEC-420 (PR4) tratar.

Consome:
- `KronosPlannerSession` (VEC-418) pra browser automation.
- `pick_next_ofx_file` + cursor helpers (VEC-415) pra escolher o próximo arquivo.
- `resolve_kronos_inputs` (VEC-413) pra ler params da task / rotina.

Dispatched por `src/agent_daemon.py` quando `operation_type='planner-import-ofx'`.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Optional

try:
    from playwright.async_api import (  # pyright: ignore[reportMissingImports]
        TimeoutError as PlaywrightTimeoutError,
    )
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "playwright não instalado. Rode `pip install playwright>=1.40.0` e "
        "`playwright install chromium`."
    ) from exc

from src.agents.kronos import (
    get_routine_ofx_cursor,
    pick_next_ofx_file,
    resolve_kronos_inputs,
    update_routine_ofx_cursor,
)
from src.agents.kronos_browser import (
    KronosLoginFailed,
    KronosPlannerSession,
    KronosSaveTimeout,
)


logger = logging.getLogger("KronosPlanner")


# ── Selectors mapeados na recon (VEC-416, 2026-05-12) ─────────────────────

PLANNER_LANCAMENTOS_URL = (
    "https://web.meuplannerfinanceiro.com.br/controle/lancamentos"
)
# Botão de abrir o modal de import é um ícone com tooltip — texto não está
# no DOM, só em `data-tip`. Usar o id estável é mais robusto.
SELECTOR_IMPORT_BUTTON = "#import-file-btn"
SELECTOR_IMPORT_MODAL_HEADING = 'h2:has-text("Importar Arquivo")'
SELECTOR_INSTITUICAO_COMBOBOX = 'select[name="partitionId"]'
SELECTOR_FILE_TYPE_STATEMENT = 'input[name="fileType"][value="statement"]'
SELECTOR_FILE_EXTENSION_OFX = 'input[name="fileExtension"][value="ofx"]'
SELECTOR_FILE_INPUT = 'input[type="file"][accept*="ofx"]'
SELECTOR_IMPORTAR_SUBMIT = 'button[type="submit"]:has-text("Importar")'


# ── Entry point (sync wrapper) ────────────────────────────────────────────


def entrypoint_planner_import(task: dict, supabase_client: Any) -> dict:
    """Handler sync chamado pelo agent_daemon.

    Wrap de `_run_planner_import_async` via `asyncio.run`. Captura qualquer
    exceção inesperada e devolve `status='errored'` com `error_detail`
    estruturado — daemon propaga pro `output_json.error_detail.message`.
    """
    try:
        return asyncio.run(_run_planner_import_async(task, supabase_client))
    except Exception as exc:
        logger.exception("entrypoint_planner_import falhou")
        return {
            "status": "errored",
            "error": str(exc),
            "output_json": {
                "error_detail": {
                    "message": str(exc),
                    "exception": type(exc).__name__,
                }
            },
        }


# ── Flow real ─────────────────────────────────────────────────────────────


async def _run_planner_import_async(
    task: dict, supabase_client: Any
) -> dict:
    task_id = task.get("id", "unknown")
    inputs = resolve_kronos_inputs(task)

    ofx_path_str = inputs.get("OFX_PATH", "")
    if not ofx_path_str:
        return _errored("OFX_PATH ausente em input_json/metadata/description/env")

    instituicao = (
        inputs.get("PLANNER_INSTITUICAO")
        or os.getenv("PLANNER_INSTITUICAO", "")
    ).strip()
    routine_id = (task.get("input_json") or {}).get("routine_id")

    ofx_path = Path(ofx_path_str)
    if not ofx_path.exists():
        return _errored(f"OFX_PATH não existe: {ofx_path}")

    cursor = _read_cursor(supabase_client, routine_id)
    target_file = _pick_target_file(ofx_path, cursor)

    if target_file is None:
        logger.info(
            "task=%s: nenhum OFX novo desde cursor=%r — done no-op",
            task_id,
            cursor,
        )
        return {
            "status": "done",
            "output_json": {
                "reason": "no_new_files",
                "cursor": cursor,
                "directory": str(ofx_path),
            },
        }

    logger.info(
        "task=%s: importando %s no Meu Planner (instituicao=%r)",
        task_id,
        target_file.name,
        instituicao or "(default)",
    )

    screenshot_path: Optional[str] = None
    toast_text = ""
    try:
        async with KronosPlannerSession() as session:
            await _do_import_flow(session, target_file, instituicao)
            toast_text = await _capture_post_import_toast(session)
            shot = await session.screenshot(f"import-{target_file.stem}")
            screenshot_path = str(shot)
    except KronosSaveTimeout as exc:
        return _errored(
            str(exc),
            exception="KronosSaveTimeout",
            extra={"file": target_file.name},
        )
    except KronosLoginFailed as exc:
        return _errored(str(exc), exception="KronosLoginFailed")

    _write_cursor(supabase_client, routine_id, target_file.name)

    return {
        "status": "done",
        "output_json": {
            "file_processed": target_file.name,
            "next_cursor": target_file.name,
            "screenshot_path": screenshot_path,
            "toast": toast_text,
        },
    }


# ── Helpers ──────────────────────────────────────────────────────────────


def _read_cursor(
    supabase_client: Any, routine_id: Optional[str]
) -> Optional[str]:
    if not routine_id or supabase_client is None:
        return None
    try:
        return get_routine_ofx_cursor(supabase_client, routine_id)
    except ValueError as exc:
        logger.warning("get_routine_ofx_cursor falhou: %s", exc)
        return None


def _write_cursor(
    supabase_client: Any, routine_id: Optional[str], basename: str
) -> None:
    if not routine_id or supabase_client is None:
        return
    try:
        update_routine_ofx_cursor(supabase_client, routine_id, basename)
    except Exception as exc:
        logger.warning("update_routine_ofx_cursor falhou: %s", exc)


def _pick_target_file(
    ofx_path: Path, cursor: Optional[str]
) -> Optional[Path]:
    """Se `OFX_PATH` aponta pra arquivo único, processa direto.
    Se diretório, usa `pick_next_ofx_file` com cursor.
    """
    if ofx_path.is_file():
        return ofx_path
    return pick_next_ofx_file(ofx_path, cursor)


def _errored(
    message: str,
    *,
    exception: str = "Error",
    extra: Optional[dict[str, Any]] = None,
) -> dict:
    error_detail: dict[str, Any] = {
        "message": message,
        "exception": exception,
    }
    if extra:
        error_detail.update(extra)
    return {
        "status": "errored",
        "error": message,
        "output_json": {"error_detail": error_detail},
    }


async def _select_first_real_partition(combobox_locator) -> None:
    """Seleciona a primeira opção real do combobox de Instituição
    (skipando placeholder 'Selecione' / opções vazias).

    Útil quando o user tem uma única instituição cadastrada — evita exigir
    `PLANNER_INSTITUICAO` na rotina pra uso single-conta.
    """
    options = await combobox_locator.evaluate(
        """(el) => Array.from(el.options).map(o => ({
            value: o.value || '',
            text: (o.textContent || '').trim()
        }))"""
    )
    candidates = [
        o
        for o in options
        if o["value"] and o["text"] and o["text"].lower() != "selecione"
    ]
    if not candidates:
        logger.warning(
            "combobox Instituição sem opções reais — pulando seleção (submit pode falhar)"
        )
        return
    first = candidates[0]
    await _set_select_value_robust(combobox_locator, first["value"])
    logger.info(
        "Instituição auto-selecionada (default): %s",
        first["text"],
    )


async def _set_select_value_robust(combobox_locator, value: str) -> None:
    """Seleciona um `<option>` num `<select>` de forma robusta.

    O Meu Planner usa daisyUI, que renderiza overlay custom em cima do
    `<select>` nativo — Playwright reporta o elemento como "not visible".
    Estratégia:
    1. `select_option` com `force=True` (Playwright bypassa o visible check).
    2. Se falhar, JS direto: set `value` + dispatch `change`/`input` events.
    """
    try:
        await combobox_locator.select_option(value=value, force=True)
        return
    except Exception as exc:
        logger.debug("select_option(force=True) falhou (%s) — fallback via JS", exc)
    await combobox_locator.evaluate(
        """(el, val) => {
            el.value = val;
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('input', { bubbles: true }));
        }""",
        value,
    )


async def _do_import_flow(
    session: KronosPlannerSession,
    target_file: Path,
    instituicao: str,
) -> None:
    """Sequência de cliques no Meu Planner pra importar um OFX. Levanta
    `KronosSaveTimeout` se o modal não fechar dentro do timeout.
    """
    page = session.page
    assert page is not None, "KronosPlannerSession sem page ativa"

    await page.goto(PLANNER_LANCAMENTOS_URL)
    await session.dismiss_known_modals()
    await session.wait_for_loading_overlay()

    # 1. Abre modal de import
    await page.locator(SELECTOR_IMPORT_BUTTON).first.click()
    try:
        await page.locator(SELECTOR_IMPORT_MODAL_HEADING).first.wait_for(
            state="visible", timeout=5_000
        )
    except PlaywrightTimeoutError as exc:
        raise KronosSaveTimeout(
            "modal 'Importar Arquivo' não abriu após click no botão"
        ) from exc

    # 2. Aba "Extrato bancário" é default. Skip.

    # 3. Combobox Instituição (obrigatório — campo com asterisco).
    #    Por padrão vem em "Selecione" (placeholder vazio). Se a rotina não
    #    informou `PLANNER_INSTITUICAO`, escolhemos a primeira opção real
    #    (skipando o placeholder) — single-conta o user normalmente só tem
    #    uma instituição cadastrada.
    modal_select = page.locator(SELECTOR_INSTITUICAO_COMBOBOX).first
    if instituicao:
        try:
            await modal_select.select_option(label=instituicao, force=True)
        except Exception as exc:
            logger.warning(
                "não foi possível selecionar Instituição %r: %s — caindo no default",
                instituicao,
                exc,
            )
            await _select_first_real_partition(modal_select)
    else:
        await _select_first_real_partition(modal_select)

    # 4. Radio OFX é default. Skip.

    # 5. Upload do arquivo
    file_input = page.locator(SELECTOR_FILE_INPUT).first
    await file_input.set_input_files(str(target_file))

    # 6. Submit — backend valida o OFX após upload e só então habilita o
    #    botão. Esperamos ele ficar enabled (não-disabled) antes do click.
    submit_btn = page.locator(SELECTOR_IMPORTAR_SUBMIT).first
    await submit_btn.wait_for(state="visible", timeout=15_000)
    enabled = False
    for _ in range(30):  # até 15s (30 × 500ms)
        if not await submit_btn.is_disabled():
            enabled = True
            break
        await asyncio.sleep(0.5)
    if not enabled:
        raise KronosSaveTimeout(
            "botão Importar do modal ficou disabled após upload do OFX"
        )
    await submit_btn.click()

    # 7. Aguarda modal fechar — sinal primário de sucesso
    try:
        await page.locator(SELECTOR_IMPORT_MODAL_HEADING).wait_for(
            state="hidden", timeout=30_000
        )
    except PlaywrightTimeoutError as exc:
        raise KronosSaveTimeout(
            "modal de import não fechou após 30s — provável erro do backend"
        ) from exc

    await session.wait_for_loading_overlay()


async def _capture_post_import_toast(
    session: KronosPlannerSession,
) -> str:
    """Captura o texto do toast pós-import. Toast não é estritamente
    obrigatório (modal pode fechar sem toast), então erro não é fatal.
    """
    try:
        return await session.wait_for_save_toast(timeout=3_000)
    except KronosSaveTimeout:
        return ""


__all__ = [
    "entrypoint_planner_import",
    "PLANNER_LANCAMENTOS_URL",
    "SELECTOR_IMPORT_BUTTON",
    "SELECTOR_IMPORT_MODAL_HEADING",
    "SELECTOR_FILE_INPUT",
    "SELECTOR_IMPORTAR_SUBMIT",
]
