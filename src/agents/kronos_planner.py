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
from src.agents.kronos_categorizer import (
    MatchResult,
    Rule,
    load_rules,
    match_rule,
)


logger = logging.getLogger("KronosPlanner")


# ── Selectors mapeados na recon (VEC-416, 2026-05-12) ─────────────────────

PLANNER_LANCAMENTOS_URL = (
    "https://web.meuplannerfinanceiro.com.br/controle/lancamentos"
)
# VEC-423: categorização inline pós-import
_DEFAULT_RULES_PATH = Path(__file__).parent / "kronos_category_rules.yaml"
_CATEGORIA_CELL_INDEX = 3       # 0-indexed: Categoria
_SUBCATEGORIA_CELL_INDEX = 4    # 0-indexed: Subcategoria
_DESC_CELL_INDEX = 7            # 0-indexed: Descrição
_SELECT_CATEGORY = 'select[name="category"]'
_SELECT_SUBCATEGORY = 'select[name="subcategory"]'
_MAX_CATEGORIZE_LINES = 200
_CATEGORIZATION_DETAILS_CAP = 30  # output_json fica enxuto
# Botão de abrir o modal de import é um ícone com tooltip — texto não está
# no DOM, só em `data-tip`. Usar o id estável é mais robusto.
SELECTOR_IMPORT_BUTTON = "#import-file-btn"
# Todos os selectors do modal usam `:visible` porque o Meu Planner (Vue+
# daisyUI) renderiza um container "fantasma" off-screen permanentemente,
# além do modal ativo. `.first` sem `:visible` pegava o fantasma e dava
# timeout em "element is not visible". Confirmado via DOM probe 2026-05-12.
SELECTOR_IMPORT_MODAL_HEADING = 'h2:has-text("Importar Arquivo"):visible'
SELECTOR_INSTITUICAO_COMBOBOX = 'select[name="partitionId"]:visible'
SELECTOR_FILE_TYPE_STATEMENT = 'input[name="fileType"][value="statement"]:visible'
SELECTOR_FILE_EXTENSION_OFX = 'input[name="fileExtension"][value="ofx"]:visible'
# File input fica display:none por padrão (wrapper visual cuida) — não usar `:visible`.
SELECTOR_FILE_INPUT = 'input[type="file"][accept*="ofx"]'
SELECTOR_IMPORTAR_SUBMIT = 'button[type="submit"]:has-text("Importar"):visible'


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

    # VEC-423: carrega regras de categorização (best-effort — vazio é OK)
    rules = _load_categorization_rules()

    screenshot_path: Optional[str] = None
    toast_text = ""
    categorization_stats: Optional[dict[str, Any]] = None
    try:
        async with KronosPlannerSession() as session:
            await _do_import_flow(session, target_file, instituicao)
            toast_text = await _capture_post_import_toast(session)
            shot = await session.screenshot(f"import-{target_file.stem}")
            screenshot_path = str(shot)

            # VEC-423: após import OK, categoriza linhas com "Sem Categoria"
            if rules:
                try:
                    categorization_stats = await _categorize_pending_lines(
                        session, rules
                    )
                except Exception as exc:
                    logger.warning(
                        "categorization falhou (não fatal): %s", exc
                    )
                    categorization_stats = {
                        "lines_categorized": 0,
                        "lines_unclassified": 0,
                        "lines_failed": 0,
                        "error": str(exc)[:200],
                    }
    except KronosSaveTimeout as exc:
        return _errored(
            str(exc),
            exception="KronosSaveTimeout",
            extra={"file": target_file.name},
        )
    except KronosLoginFailed as exc:
        return _errored(str(exc), exception="KronosLoginFailed")

    _write_cursor(supabase_client, routine_id, target_file.name)

    output_json: dict[str, Any] = {
        "file_processed": target_file.name,
        "next_cursor": target_file.name,
        "screenshot_path": screenshot_path,
        "toast": toast_text,
    }
    if categorization_stats is not None:
        output_json["categorization"] = categorization_stats

    return {"status": "done", "output_json": output_json}


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


# ── VEC-423: categorização inline pós-import ─────────────────────────


def _load_categorization_rules(
    rules_path: Optional[Path] = None,
) -> list[Rule]:
    """Carrega regras do YAML default. Erro de IO/parse não é fatal — devolve [].
    """
    path = rules_path or _DEFAULT_RULES_PATH
    try:
        rules = load_rules(path)
    except Exception as exc:
        logger.warning(
            "load_rules falhou (%s) — categorização será no-op", exc
        )
        return []
    logger.info("regras de categorização carregadas: %d de %s", len(rules), path)
    return rules


async def _set_select_by_label(combobox_locator, label: str) -> None:
    """Seleciona uma `<option>` pelo `textContent` (label visível ao user).

    Estratégia:
    1. Lê todas as options (value + text).
    2. Procura match exato no text.
    3. Fallback: match case-insensitive substring (ex: label tem espaço extra).
    4. Chama `_set_select_value_robust` com o value encontrado.

    Levanta `ValueError` se nenhum label bate.
    """
    options = await combobox_locator.evaluate(
        """(el) => Array.from(el.options).map(o => ({
            value: o.value || '',
            text: (o.textContent || '').trim()
        }))"""
    )
    if not options:
        raise ValueError(f"combobox sem options ao tentar label={label!r}")

    target = (label or "").strip()
    match = next((o for o in options if o["text"] == target), None)
    if match is None:
        target_l = target.lower()
        match = next(
            (o for o in options if o["text"].lower() == target_l), None
        )
    if match is None:
        target_l = target.lower()
        match = next(
            (
                o
                for o in options
                if target_l in o["text"].lower() or o["text"].lower() in target_l
            ),
            None,
        )
    if match is None:
        available = [o["text"] for o in options if o["text"]]
        raise ValueError(
            f"label {label!r} não encontrado no combobox. "
            f"options: {available[:10]}..."
        )

    await _set_select_value_robust(combobox_locator, match["value"])


async def _categorize_pending_lines(
    session: KronosPlannerSession,
    rules: list[Rule],
    max_lines: int = _MAX_CATEGORIZE_LINES,
) -> dict[str, Any]:
    """Itera linhas com `Categoria='Sem Categoria...'` e aplica match_rule.

    Estratégia:
    - Re-query a cada iteração (tabela re-renderiza após save).
    - Marca rows já processadas com `data-kronos-processed` pra não voltar.
    - Catch per-row: falha de uma linha não para o loop.
    """
    page = session.page
    assert page is not None, "KronosPlannerSession sem page ativa"

    stats: dict[str, Any] = {
        "lines_categorized": 0,
        "lines_unclassified": 0,
        "lines_failed": 0,
        "details": [],
    }

    for iteration in range(max_lines):
        row = await _find_next_uncategorized_row(page)
        if row is None:
            logger.info(
                "categorize: sem mais linhas pendentes após %d iterações",
                iteration,
            )
            break

        desc = await _read_row_description(row)
        result = match_rule(desc, rules)

        if result is None:
            await _mark_row(row, "skipped")
            stats["lines_unclassified"] += 1
            _append_detail(
                stats, {"desc": desc[:60], "action": "skipped"}
            )
            continue

        try:
            await _apply_categorization_to_row(session, row, result)
            stats["lines_categorized"] += 1
            _append_detail(
                stats,
                {
                    "desc": desc[:60],
                    "categoria": result.categoria,
                    "subcategoria": result.subcategoria,
                },
            )
        except Exception as exc:
            logger.warning(
                "categorize linha %d falhou (%s): %s",
                iteration,
                desc[:60],
                exc,
            )
            stats["lines_failed"] += 1
            _append_detail(
                stats, {"desc": desc[:60], "error": str(exc)[:100]}
            )
            # Tenta cancelar o edit caso tenha ficado aberto
            try:
                cancel = row.locator('button[type="button"]:visible').first
                if await cancel.count() > 0:
                    await cancel.click(timeout=1_000)
            except Exception:
                pass
            try:
                await _mark_row(row, "failed")
            except Exception:
                pass

    return stats


async def _find_next_uncategorized_row(page):
    """Encontra a próxima linha com Categoria 'Sem Categoria' não marcada.

    Como o filtro `:not([data-kronos-processed])` deixa de fora as já tocadas
    nesta execução, o loop sempre avança.
    """
    rows = page.locator(
        'tbody tr:not([data-kronos-processed])'
    )
    count = await rows.count()
    for i in range(count):
        row = rows.nth(i)
        cells = row.locator("td")
        ncells = await cells.count()
        if ncells <= _CATEGORIA_CELL_INDEX:
            continue
        cat_text = (
            await cells.nth(_CATEGORIA_CELL_INDEX).text_content()
        ) or ""
        if "sem categoria" in cat_text.strip().lower():
            return row
    return None


async def _read_row_description(row) -> str:
    """Lê texto da célula 'Descrição' (índice 7)."""
    cells = row.locator("td")
    if await cells.count() <= _DESC_CELL_INDEX:
        return ""
    text = await cells.nth(_DESC_CELL_INDEX).text_content()
    return (text or "").strip()


async def _mark_row(row, status: str) -> None:
    """Adiciona `data-kronos-processed=<status>` na <tr> pra evitar reentrada."""
    await row.evaluate(
        "(el, s) => el.setAttribute('data-kronos-processed', s)", status
    )


async def _apply_categorization_to_row(
    session: KronosPlannerSession,
    row,
    result: MatchResult,
) -> None:
    """Entra em edit mode, seta categoria + subcategoria, submete, aguarda
    toast. Marca row processada ao final.
    """
    page = session.page
    assert page is not None

    # 1. Clicar no edit (último td)
    cells = row.locator("td")
    ncells = await cells.count()
    edit_btn = cells.nth(ncells - 1).locator("button").first
    await edit_btn.click()

    # 2. Aguardar select category aparecer DENTRO da row
    cat_select = row.locator(_SELECT_CATEGORY).first
    await cat_select.wait_for(state="visible", timeout=5_000)

    # 3. Aplicar categoria
    await _set_select_by_label(cat_select, result.categoria)

    # 4. Aguardar subcategoria repopular (delay curto cobre 95%)
    await asyncio.sleep(0.5)

    sub_select = row.locator(_SELECT_SUBCATEGORY).first
    await sub_select.wait_for(state="visible", timeout=5_000)

    # 5. Aplicar subcategoria
    await _set_select_by_label(sub_select, result.subcategoria)

    # 6. Submit (último td, type=submit)
    submit_btn = row.locator('button[type="submit"]:visible').first
    await submit_btn.click()

    # 7. Aguarda toast de sucesso (ou ignora se ausente — modal saindo do edit já é sinal)
    try:
        await session.wait_for_save_toast(timeout=5_000)
    except KronosSaveTimeout:
        logger.debug("categorize: sem toast de success — ignorando")

    # 8. Marca como processada
    await _mark_row(row, "categorized")


def _append_detail(stats: dict[str, Any], entry: dict[str, Any]) -> None:
    """Adiciona entry em stats['details'] respeitando o cap pra output enxuto."""
    details = stats.setdefault("details", [])
    if len(details) < _CATEGORIZATION_DETAILS_CAP:
        details.append(entry)


__all__ = [
    "entrypoint_planner_import",
    "PLANNER_LANCAMENTOS_URL",
    "SELECTOR_IMPORT_BUTTON",
    "SELECTOR_IMPORT_MODAL_HEADING",
    "SELECTOR_FILE_INPUT",
    "SELECTOR_IMPORTAR_SUBMIT",
]
