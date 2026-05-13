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
from src.agents.kronos_pdf_enricher import (
    build_pdf_lookup,
    find_enriched_description,
    parse_brl_amount_to_centavos,
    parse_c6_pdf,
)


logger = logging.getLogger("KronosPlanner")


# ── Selectors mapeados na recon (VEC-416, 2026-05-12) ─────────────────────

PLANNER_LANCAMENTOS_URL = (
    "https://web.meuplannerfinanceiro.com.br/controle/lancamentos"
)
# Task #43 — Default recipient mantido como fallback do shared_config.
# `_HERMESREPORTER_AGENT_ID` REMOVIDO — handoff agora é Step 3 do workflow
# kronos-planner-flow (relacional, via specialty_slug='oracle-report').
_DEFAULT_REPORT_RECIPIENT = "marcelo.rosas@vectracargo.com.br"

# VEC-423: categorização inline pós-import
_DEFAULT_RULES_PATH = Path(__file__).parent / "kronos_category_rules.yaml"
_CATEGORIA_CELL_INDEX = 3       # 0-indexed: Categoria
_SUBCATEGORIA_CELL_INDEX = 4    # 0-indexed: Subcategoria
_DESC_CELL_INDEX = 7            # 0-indexed: Descrição
_DATA_EVENTO_CELL_INDEX = 1     # 0-indexed: Data do evento
_VALOR_CELL_INDEX = 8           # 0-indexed: Valor
_SELECT_CATEGORY = 'select#category'
_SELECT_SUBCATEGORY = 'select#subcategory'
# VEC-426 fix #3: quando o user clica no edit-btn, Vue substitui a <tr>
# original por uma TR especial com a class abaixo, que contém os <select>
# de categoria/subcategoria/status/etc. Os `id`s dos selects são estáveis
# (`category`, `subcategory`, ...). Como a TR original é destruída no
# swap, o `pinned_row.locator(...)` antigo falhava — precisa buscar na
# edit row global.
_EDIT_ROW_SELECTOR = "tr.EditTransactionRow_editRow__fNWmG"
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


def entrypoint_categorize_pendings(task: dict, supabase_client: Any) -> dict:
    """Handler sync para `operation_type='planner-categorize-pendings'`.

    Roda **apenas** a categorização sobre linhas já existentes no Meu Planner
    — sem reimportar OFX. Útil pra:
    - Smoke iterativo após adicionar regras no YAML.
    - Categorização retroativa de linhas antigas.
    - Retry após falha parcial.

    Inputs (via executionParams):
    - `PDF_PATH` (opcional): caminho do extrato PDF pra enrichment.
    """
    try:
        return asyncio.run(_run_categorize_only_async(task, supabase_client))
    except Exception as exc:
        logger.exception("entrypoint_categorize_pendings falhou")
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

    # VEC-425: carrega PDF lookup pra enriquecer descrições genéricas (TRANSF
    # ENVIADA PIX → "Pix enviado para NOME") quando PDF_PATH é informado.
    pdf_lookup = _load_pdf_lookup(inputs.get("PDF_PATH"))

    screenshot_path: Optional[str] = None
    toast_text = ""
    categorization_stats: Optional[dict[str, Any]] = None
    try:
        async with KronosPlannerSession() as session:
            await _do_import_flow(session, target_file, instituicao)
            toast_text = await _capture_post_import_toast(session)

            # VEC-423 fix: o Meu Planner mostra um modal "Importação realizada
            # com sucesso!" sobrepondo a tabela. Categorize precisa dele
            # fechado pra acessar as rows recém-importadas.
            await _dismiss_import_success_modal(session)
            await session.wait_for_loading_overlay()
            await _wait_for_lancamentos_populated(session.page)

            # VEC-423: após import OK + modal fechado, categoriza linhas
            if rules:
                try:
                    categorization_stats = await _categorize_pending_lines(
                        session, rules, pdf_lookup=pdf_lookup
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

            # Screenshot DEPOIS da categorização (estado final)
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

    output_json: dict[str, Any] = {
        "file_processed": target_file.name,
        "next_cursor": target_file.name,
        "screenshot_path": screenshot_path,
        "toast": toast_text,
    }
    if categorization_stats is not None:
        output_json["categorization"] = categorization_stats

    # Task #43 — Acordo arquitetural "nada hardcoded": handoff Hermes Reporter
    # NÃO é mais feito aqui via constante _HERMESREPORTER_AGENT_ID.
    # Agora é Step 3 do workflow `kronos-planner-flow` (specialty_slug=
    # 'oracle-report', resolve Hermes Reporter via _find_agent). TaskFactory
    # cria a child Step 3 em backlog na materialização (run_routine_now) e
    # promove para queued via promote_successors_after_completion quando este
    # Step 1 termina (output_json["categorization"] vai pro Step 3 via
    # parent context se necessário no futuro).
    #
    # O markdown do relatório é gerado pelo handler do Hermes Reporter
    # (agents/hermes_reporter.py) consumindo `parent_task.output_json` e o
    # `input_json` do Step 3 — não mais por este handler.
    output_json["handoff"] = "via workflow_step Step 3 (hermes-report)"

    return {"status": "done", "output_json": output_json}


async def _run_categorize_only_async(
    task: dict, supabase_client: Any
) -> dict:
    """Categorize-only flow: roda match_rule + apply via UI sobre as linhas
    existentes em `/controle/lancamentos`. Sem reimportar OFX.

    Reusa `KronosPlannerSession` + `_categorize_pending_lines` + PDF
    enrichment opcional. Devolve `output_json.categorization` com stats.
    """
    task_id = task.get("id", "unknown")
    inputs = resolve_kronos_inputs(task)

    rules = _load_categorization_rules()
    if not rules:
        logger.info("task=%s: sem regras carregadas — done no-op", task_id)
        return {
            "status": "done",
            "output_json": {
                "reason": "no_rules",
                "message": "kronos_category_rules.yaml vazio ou ausente",
            },
        }

    pdf_lookup = _load_pdf_lookup(inputs.get("PDF_PATH"))

    logger.info(
        "task=%s: categorize-only — %d regras carregadas, PDF lookup=%s",
        task_id,
        len(rules),
        "yes" if pdf_lookup else "no",
    )

    screenshot_path: Optional[str] = None
    try:
        async with KronosPlannerSession() as session:
            page = session.page
            assert page is not None, "KronosPlannerSession sem page ativa"

            await page.goto(PLANNER_LANCAMENTOS_URL)
            await session.dismiss_known_modals()
            await session.wait_for_loading_overlay()
            await _wait_for_lancamentos_populated(page)

            categorization_stats = await _categorize_pending_lines(
                session, rules, pdf_lookup=pdf_lookup
            )

            shot = await session.screenshot("categorize-only")
            screenshot_path = str(shot)
    except KronosLoginFailed as exc:
        return _errored(str(exc), exception="KronosLoginFailed")

    return {
        "status": "done",
        "output_json": {
            "categorization": categorization_stats,
            "screenshot_path": screenshot_path,
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


def _build_kronos_report_markdown(
    file_processed: str,
    stats: Optional[dict[str, Any]],
    screenshot_path: Optional[str],
    toast_text: str,
) -> str:
    """Constrói o markdown do relatório que vai pro HermesReporter.

    Formato esperado pelo HermesReporter:
    - Seção `## Resumo` com tabela markdown (vira tabela de badges no HTML).
    - Demais `##` viram seções com tabelas ou parágrafos.
    """
    stats = stats or {}
    details = stats.get("details") or []
    cat = int(stats.get("lines_categorized", 0))
    un = int(stats.get("lines_unclassified", 0))
    failed = int(stats.get("lines_failed", 0))

    categorized_rows: list[str] = []
    pending_rows: list[str] = []
    failed_rows: list[str] = []
    for d in details:
        desc = (d.get("desc") or "").strip()
        if "categoria" in d:
            categorized_rows.append(
                f"| {desc} | {d.get('categoria', '')} | {d.get('subcategoria', '')} |"
            )
        elif d.get("action") == "skipped":
            pending_rows.append(f"- {desc}")
        elif "error" in d:
            failed_rows.append(f"- {desc} — `{(d.get('error') or '')[:80]}`")

    md_parts: list[str] = []
    md_parts.append("## Resumo")
    md_parts.append("")
    md_parts.append("| Métrica | Valor |")
    md_parts.append("|---------|-------|")
    md_parts.append(f"| Arquivo OFX | {file_processed} |")
    md_parts.append(
        f"| Importação | {toast_text or 'sem confirmação de toast'} |"
    )
    md_parts.append(f"| Linhas categorizadas | {cat} |")
    md_parts.append(f"| Linhas pendentes (sem regra) | {un} |")
    md_parts.append(f"| Linhas com falha | {failed} |")
    if screenshot_path:
        md_parts.append(f"| Screenshot | {screenshot_path} |")
    md_parts.append("")

    if categorized_rows:
        md_parts.append("## Categorizadas")
        md_parts.append("")
        md_parts.append("| Descrição | Categoria | Subcategoria |")
        md_parts.append("|-----------|-----------|--------------|")
        md_parts.extend(categorized_rows)
        md_parts.append("")

    if pending_rows:
        md_parts.append("## Pendentes (sem regra no YAML)")
        md_parts.append("")
        md_parts.extend(pending_rows)
        md_parts.append("")
        md_parts.append(
            "Adicione regras em `src/agents/kronos_category_rules.yaml` "
            "para automatizar essas descrições na próxima rodada."
        )
        md_parts.append("")

    if failed_rows:
        md_parts.append("## Falhas")
        md_parts.append("")
        md_parts.extend(failed_rows)
        md_parts.append("")

    return "\n".join(md_parts)


# Task #43 — `_create_hermesreporter_task` REMOVIDO. Hand-off Hermes Reporter
# agora é declarativo: Step 3 do workflow `kronos-planner-flow` com
# specialty_slug='oracle-report'. TaskFactory.materialize_workflow cria a
# subtask em backlog, MorpheusDispatcher._find_agent resolve dono via
# specialty (= Hermes Reporter), TaskFactory.promote_successors_after_completion
# promove para queued quando Step 2 (categorize-pendings) termina.


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


async def _dismiss_import_success_modal(session: KronosPlannerSession) -> None:
    """Fecha o modal 'Importação realizada com sucesso!' que aparece após
    `_do_import_flow` salvar o OFX.

    Estratégias em ordem:
    1. Botão `X` (close header).
    2. Tecla Escape.
    3. Best-effort log warning.

    Não usar "Categorizar transações" — navega pra `/controle/pendencias`
    que só tem 3 colunas (sem Categoria) e quebra a categorização inline.
    """
    page = session.page
    assert page is not None

    # Detecta presença do modal pelo heading
    heading = page.locator(
        'h2:has-text("Importação realizada com sucesso"):visible'
    ).first
    try:
        if await heading.count() == 0:
            return  # modal já não está aberto
    except Exception:
        return

    # 1. Tenta botão X (close header — pattern daisyUI btn-circle)
    try:
        close_btn = page.locator(
            'div:has(> h2:has-text("Importação realizada com sucesso")) button.btn-circle:visible'
        ).first
        if await close_btn.count() > 0:
            await close_btn.click(timeout=2_000)
            await heading.wait_for(state="hidden", timeout=3_000)
            logger.debug("modal 'Importação realizada' fechado via X")
            return
    except PlaywrightTimeoutError:
        logger.debug("close button X falhou, tentando Escape")
    except Exception as exc:
        logger.debug("close button X exception: %s", exc)

    # 2. Fallback: Escape
    try:
        await page.keyboard.press("Escape")
        await heading.wait_for(state="hidden", timeout=2_000)
        logger.debug("modal 'Importação realizada' fechado via Escape")
        return
    except PlaywrightTimeoutError:
        logger.debug("Escape falhou, tentando dialog.close() JS")

    # 3. Fallback robusto: HTML5 <dialog>.close() via JS.
    # O modal é um `<dialog class="modal w-full z-50" open>` nativo. Escape só
    # funciona se aberto via `dialog.showModal()`; quando aberto via `.show()`
    # ou atribuição direta do attr `open`, Escape é no-op. Native `.close()`
    # remove o atributo `open` independente de como foi aberto.
    try:
        closed = await page.evaluate(
            """() => {
                const dlg = document.querySelector('dialog.modal[open]');
                if (dlg && typeof dlg.close === 'function') {
                    dlg.close();
                    return true;
                }
                return false;
            }"""
        )
        if closed:
            await heading.wait_for(state="hidden", timeout=3_000)
            logger.debug("modal 'Importação realizada' fechado via dialog.close() JS")
            return
    except Exception as exc:
        logger.debug("dialog.close() JS falhou: %s", exc)

    # 4. Fallback final: força remoção do atributo `open`. Funciona mesmo se
    # `close()` não existir (impl Vue customizada, polyfill antigo, etc).
    try:
        await page.evaluate(
            """() => {
                document.querySelectorAll('dialog.modal[open]').forEach(d => {
                    try { d.removeAttribute('open'); } catch (e) {}
                });
            }"""
        )
        await heading.wait_for(state="hidden", timeout=2_000)
        logger.debug("modal 'Importação realizada' fechado via removeAttribute('open')")
        return
    except Exception as exc:
        logger.warning(
            "modal 'Importação realizada' não fechou após 4 estratégias (X/Escape/close/removeAttr) — categorize vai falhar com pointer-event intercept: %s",
            exc,
        )


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
    *,
    pdf_lookup: Optional[dict[tuple[str, int], str]] = None,
    max_lines: int = _MAX_CATEGORIZE_LINES,
) -> dict[str, Any]:
    """Itera linhas com `Categoria='Sem Categoria...'` e aplica match_rule.

    Estratégia:
    - Re-query a cada iteração (tabela re-renderiza após save).
    - Marca rows já processadas com `data-kronos-processed` pra não voltar.
    - Catch per-row: falha de uma linha não para o loop.

    VEC-425: `pdf_lookup` opcional. Quando fornecido, descrições genéricas
    (`TRANSF ENVIADA PIX`) são enriquecidas via (data, valor) → descrição
    PDF antes do `match_rule`.
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

        # VEC-423 fix: pin row com data-attr único antes de qualquer ação
        # subsequente. Tabela do Meu Planner re-renderiza após save (Vue
        # reactivity), invalidando o `tbody tr:not(...).nth(i)` Locator.
        # Re-acquire via `tr[data-kronos-target="..."]` (selector estável).
        marker = f"k{iteration}"
        try:
            await row.evaluate(
                "(el, m) => el.setAttribute('data-kronos-target', m)",
                marker,
            )
        except Exception as mark_exc:
            logger.warning(
                "categorize iter %d: falhou ao marcar row (%s) — pulando",
                iteration,
                mark_exc,
            )
            stats["lines_failed"] += 1
            _append_detail(
                stats,
                {"desc": "(mark_failed)", "error": str(mark_exc)[:100]},
            )
            continue

        pinned_row = page.locator(
            f'tr[data-kronos-target="{marker}"]'
        ).first

        row_data = await _read_row_data(pinned_row)
        original_desc = row_data["desc"]
        enriched_desc = original_desc

        # VEC-425: enrichment via PDF lookup
        if pdf_lookup and row_data["date_str"] and row_data["amount_centavos"]:
            enriched = find_enriched_description(
                pdf_lookup,
                row_data["date_str"],
                row_data["amount_centavos"],
            )
            if enriched:
                enriched_desc = enriched
                if original_desc != enriched:
                    logger.debug(
                        "enriched: '%s' → '%s'",
                        original_desc[:40],
                        enriched[:60],
                    )

        result = match_rule(enriched_desc, rules)

        if result is None:
            await _mark_row(pinned_row, "skipped")
            stats["lines_unclassified"] += 1
            detail: dict[str, Any] = {"desc": enriched_desc[:60], "action": "skipped"}
            if enriched_desc != original_desc:
                detail["original_desc"] = original_desc[:40]
            _append_detail(stats, detail)
            continue

        try:
            await _apply_categorization_to_row(session, pinned_row, result)
            stats["lines_categorized"] += 1
            success_detail: dict[str, Any] = {
                "desc": enriched_desc[:60],
                "categoria": result.categoria,
                "subcategoria": result.subcategoria,
            }
            if enriched_desc != original_desc:
                success_detail["original_desc"] = original_desc[:40]
            _append_detail(stats, success_detail)
        except Exception as exc:
            logger.warning(
                "categorize linha %d falhou (%s): %s",
                iteration,
                enriched_desc[:60],
                exc,
            )
            stats["lines_failed"] += 1
            _append_detail(
                stats, {"desc": enriched_desc[:60], "error": str(exc)[:100]}
            )
            # Cleanup: cancel edit-row global (não na pinned_row, que pode ter
            # sido destruída no swap Vue → edit-row)
            try:
                cancel = page.locator(
                    f'{_EDIT_ROW_SELECTOR} button[type="button"]'
                ).first
                if await cancel.count() > 0:
                    await cancel.click(timeout=2_000)
                # Confirma que a edit-row sumiu antes de continuar
                try:
                    await page.locator(_EDIT_ROW_SELECTOR).first.wait_for(
                        state="hidden", timeout=3_000
                    )
                except Exception:
                    pass
            except Exception:
                pass
            try:
                await _mark_row(pinned_row, "failed")
            except Exception:
                pass

    return stats


_UNCATEGORIZED_CATEGORIA_MARKERS = ("sem categoria", "**", "verificar")


def _is_uncategorized_cell(cat_text: str) -> bool:
    """Detecta se uma célula Categoria está marcada como não-categorizada.

    Cobre 3 casos do Meu Planner:
    - Texto vazio (placeholder default sem texto, só fundo vermelho)
    - "Sem Categoria - Despesas" / "Sem Categoria - Receitas"
    - Marker `**` ou "Verificar" (padrão histórico do usuário)
    """
    stripped = (cat_text or "").strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    return any(marker in lowered for marker in _UNCATEGORIZED_CATEGORIA_MARKERS)


_LANCAMENTOS_TABLE_SELECTOR = "table.w-full"


async def _wait_for_lancamentos_populated(page, timeout_ms: int = 15_000) -> bool:
    """Aguarda a tabela de lançamentos receber a primeira row.

    `wait_for_loading_overlay()` retorna assim que o overlay some, mas a
    `table.w-full` pode ficar mais alguns segundos vazia enquanto Vue
    popula via fetch. Sem este wait, o loop de categorização sai
    imediatamente reportando `lines_categorized=0` mesmo com 30 linhas
    pendentes na lista.

    Retorna `True` se ao menos uma row apareceu; `False` se timeout
    (caso legítimo: filtro de período vazio).
    """
    try:
        await page.locator(
            f"{_LANCAMENTOS_TABLE_SELECTOR} tbody tr"
        ).first.wait_for(state="visible", timeout=timeout_ms)
        return True
    except Exception as exc:
        logger.info(
            "lançamentos: tabela vazia após %dms (%s) — nada a categorizar",
            timeout_ms,
            type(exc).__name__,
        )
        return False


async def _find_next_uncategorized_row(page):
    """Encontra a próxima linha com Categoria não-categorizada e não marcada.

    Como o filtro `:not([data-kronos-processed])` deixa de fora as já tocadas
    nesta execução, o loop sempre avança.

    ⚠️ Importante: o seletor é qualificado por `table.w-full` para evitar
    pegar rows do react-day-picker (`table.rdp-table`) que aparece quando o
    seletor de período do filtro está aberto. Sem essa qualificação, as
    primeiras `tbody tr` da página são células do calendário e o clique no
    botão da última coluna acaba clicando em `<button name="day">` de um
    dia, deixando o fluxo travado.
    """
    rows = page.locator(
        f'{_LANCAMENTOS_TABLE_SELECTOR} tbody tr:not([data-kronos-processed])'
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
        if _is_uncategorized_cell(cat_text):
            return row
    return None


async def _read_row_description(row) -> str:
    """Lê texto da célula 'Descrição' (índice 7).

    Mantida pra compat com tests antigos. Novo código usa `_read_row_data`.
    """
    cells = row.locator("td")
    if await cells.count() <= _DESC_CELL_INDEX:
        return ""
    text = await cells.nth(_DESC_CELL_INDEX).text_content()
    return (text or "").strip()


async def _read_row_data(row) -> dict[str, Any]:
    """Lê células-chave da row pra enrichment via PDF lookup.

    Retorna `{desc, date_str, amount_centavos}`. Campos vêm vazios/zero
    quando a row não tem cells suficientes.
    """
    cells = row.locator("td")
    ncells = await cells.count()
    if ncells <= _DESC_CELL_INDEX:
        return {"desc": "", "date_str": "", "amount_centavos": 0}

    desc = ((await cells.nth(_DESC_CELL_INDEX).text_content()) or "").strip()
    date_str = ""
    if ncells > _DATA_EVENTO_CELL_INDEX:
        date_str = (
            (await cells.nth(_DATA_EVENTO_CELL_INDEX).text_content()) or ""
        ).strip()
    amount_centavos = 0
    if ncells > _VALOR_CELL_INDEX:
        valor_text = (
            (await cells.nth(_VALOR_CELL_INDEX).text_content()) or ""
        ).strip()
        amount_centavos = parse_brl_amount_to_centavos(valor_text)

    return {
        "desc": desc,
        "date_str": date_str,
        "amount_centavos": amount_centavos,
    }


def _load_pdf_lookup(
    pdf_path_str: Optional[str],
) -> Optional[dict[tuple[str, int], str]]:
    """Carrega lookup do PDF do extrato (best-effort).

    Retorna `None` se path ausente, file não existe, ou parse falha. Quando
    `None`, categorize roda sem enrichment (comportamento pré-VEC-425).
    """
    if not pdf_path_str:
        return None
    pdf_path = Path(pdf_path_str)
    if not pdf_path.exists():
        logger.warning("PDF_PATH não existe: %s — sem enrichment", pdf_path)
        return None
    try:
        entries = parse_c6_pdf(pdf_path)
    except Exception as exc:
        logger.warning("parse_c6_pdf falhou (%s) — sem enrichment", exc)
        return None
    if not entries:
        logger.info("PDF sem transações reconhecidas — sem enrichment")
        return None
    lookup = build_pdf_lookup(entries)
    logger.info(
        "PDF lookup carregado: %d transações, %d chaves únicas",
        len(entries),
        len(lookup),
    )
    return lookup


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
    save. Opera na edit-row criada pelo Vue após o click.

    ⚠️ Após click no edit-btn, Vue REMOVE a `row` original do DOM e
    insere uma `tr.EditTransactionRow_editRow__fNWmG` no lugar. Logo, a
    partir do step 2 toda busca DEVE ser feita em `page` (com filtro
    pela edit row), não em `row` (Locator stale).
    """
    page = session.page
    assert page is not None

    # 1. Clicar no edit (último td) — row ainda existe aqui
    cells = row.locator("td")
    ncells = await cells.count()
    edit_btn = cells.nth(ncells - 1).locator("button").first
    await edit_btn.click()

    # 2. Aguardar a edit-row (substituta) aparecer
    edit_row = page.locator(_EDIT_ROW_SELECTOR).first
    await edit_row.wait_for(state="visible", timeout=5_000)

    # 3. Aplicar categoria — select#category dentro da edit-row
    cat_select = edit_row.locator(_SELECT_CATEGORY).first
    await cat_select.wait_for(state="visible", timeout=5_000)
    await _set_select_by_label(cat_select, result.categoria)

    # 4. Aguardar subcategoria repopular (Vue reactivity)
    await asyncio.sleep(0.5)
    sub_select = edit_row.locator(_SELECT_SUBCATEGORY).first
    await sub_select.wait_for(state="visible", timeout=5_000)

    # 5. Aplicar subcategoria
    await _set_select_by_label(sub_select, result.subcategoria)

    # 6. Submit (último td da edit-row, type=submit)
    submit_btn = edit_row.locator('button[type="submit"]').first
    await submit_btn.click()

    # 7. Aguarda save: edit-row some quando Vue volta pra display row
    try:
        await edit_row.wait_for(state="hidden", timeout=10_000)
    except Exception:
        # Toast pode aparecer antes de a edit-row sumir; tenta toast
        try:
            await session.wait_for_save_toast(timeout=3_000)
        except KronosSaveTimeout:
            logger.debug("categorize: sem toast nem edit-row hidden — best-effort OK")

    # Não chama `_mark_row(row, ...)` aqui: a `row` original foi
    # destruída no swap. O loop confia em `_is_uncategorized_cell`
    # (categoria deixa de ser pendente após save) para não revisitar.


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
