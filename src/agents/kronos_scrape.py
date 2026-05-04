"""
KronosScrape — extrai lançamentos pendentes do Meu Planner Financeiro via Playwright.
URL: /controle/lancamentos filtrado por período e status=Pendente.
Env: PLANNER_EMAIL, PLANNER_PASSWORD
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Optional

logger = logging.getLogger("KronosScrape")

PLANNER_URL_LOGIN = "https://web.meuplannerfinanceiro.com.br/login"
PLANNER_URL_LANC  = "https://web.meuplannerfinanceiro.com.br/controle/lancamentos"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()


def _parse_date_br(s: str) -> Optional[str]:
    """
    Converte datas em formato DD/MM/YYYY ou YYYY-MM-DD para 'YYYY-MM-DD'.
    Retorna None se não conseguir interpretar.
    """
    s = s.strip()
    # Tenta DD/MM/YYYY
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        day, month, year = m.group(1), m.group(2), m.group(3)
        try:
            datetime(int(year), int(month), int(day))
            return f"{year}-{month}-{day}"
        except ValueError:
            return None
    # Tenta YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return s
    return None


def _parse_valor_brl(s: str) -> Optional[str]:
    """
    Converte 'R$\xa02.100,00' ou '2.100,00' para string decimal '2100.00'.
    Retorna None se não conseguir interpretar.
    """
    s = re.sub(r"[R$\s\xa0]", "", s).strip()
    if not s:
        return None
    # Formato BRL: ponto como separador de milhar, vírgula como decimal
    if re.search(r",\d{1,2}$", s):
        s = s.replace(".", "").replace(",", ".")
    try:
        d = Decimal(s)
        # Retorna sem sinal negativo para uniformidade (valor absoluto)
        return str(abs(d))
    except InvalidOperation:
        return None


def _date_in_range(date_iso: str, inicio: str, fim: str) -> bool:
    """Verifica se date_iso (YYYY-MM-DD) está dentro de [inicio, fim]."""
    try:
        d     = date.fromisoformat(date_iso)
        start = date.fromisoformat(inicio)
        end   = date.fromisoformat(fim)
        return start <= d <= end
    except ValueError:
        return False


# ── Login ─────────────────────────────────────────────────────────────────────

def _login(page, email: str, password: str) -> None:
    """Faz login no Meu Planner Financeiro e aguarda redirecionamento."""
    logger.info("KronosScrape: fazendo login em Meu Planner")
    page.goto(PLANNER_URL_LOGIN, timeout=30000)
    page.wait_for_load_state("networkidle")
    page.fill("#email", email)
    page.fill("input[type=password]", password)
    page.click("button[type=submit]")
    page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
    logger.info("KronosScrape: login OK — %s", page.url)


# ── Filtros ───────────────────────────────────────────────────────────────────

def _try_fill_date(page, selector: str, value_br: str) -> bool:
    """
    Tenta preencher campo de data; retorna True se conseguir.
    Tenta triple-click para selecionar tudo antes de digitar.
    """
    try:
        el = page.query_selector(selector)
        if el and el.is_visible():
            el.triple_click()
            el.fill(value_br)
            return True
    except Exception:
        pass
    return False


def _apply_filters(page, inicio: str, fim: str) -> bool:
    """
    Tenta abrir o painel de filtros e preencher período + status=Pendente.
    Retorna True se conseguiu aplicar, False caso contrário (fallback Python).
    """
    # Converte datas para formato BR
    inicio_br = datetime.fromisoformat(inicio).strftime("%d/%m/%Y")
    fim_br    = datetime.fromisoformat(fim).strftime("%d/%m/%Y")

    # ── Tenta abrir painel de filtros ─────────────────────────────────────────
    filter_opened = False
    filter_selectors = [
        "button[data-testid*='filter']",
        "button.filter-btn",
        "button[aria-label*='filtro' i]",
        "button[aria-label*='filter' i]",
    ]
    for sel in filter_selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(800)
                filter_opened = True
                logger.info("KronosScrape: painel de filtros aberto via '%s'", sel)
                break
        except Exception:
            continue

    # Fallback: botão por role/name
    if not filter_opened:
        try:
            btn = page.get_by_role("button", name=re.compile(r"filtro|filter|funil", re.I)).first
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(800)
                filter_opened = True
                logger.info("KronosScrape: painel de filtros aberto via get_by_role")
        except Exception:
            pass

    # Fallback: procura botão com SVG próximo a texto de filtro
    if not filter_opened:
        try:
            btns = page.query_selector_all("button:has(svg)")
            for btn in btns:
                txt = _normalize(btn.inner_text())
                if "filtro" in txt or "filter" in txt or "funil" in txt:
                    btn.click()
                    page.wait_for_timeout(800)
                    filter_opened = True
                    logger.info("KronosScrape: painel de filtros aberto via button:has(svg)")
                    break
        except Exception:
            pass

    if not filter_opened:
        logger.warning("KronosScrape: não conseguiu abrir painel de filtros — usará fallback Python")
        return False

    # ── Preenche data início ───────────────────────────────────────────────────
    inicio_filled = False
    date_start_selectors = [
        "input[placeholder*='início' i]",
        "input[placeholder*='inicio' i]",
        "input[name*='start' i]",
        "input[name*='inicio' i]",
        "input[placeholder*='de' i]",
    ]
    for sel in date_start_selectors:
        if _try_fill_date(page, sel, inicio_br):
            inicio_filled = True
            logger.info("KronosScrape: data início preenchida via '%s'", sel)
            break

    # Fallback: primeiro input de data visível
    if not inicio_filled:
        try:
            inputs = page.query_selector_all("input[type='date'], input[type='text']")
            visible = [i for i in inputs if i.is_visible()]
            if visible:
                visible[0].triple_click()
                visible[0].fill(inicio_br)
                inicio_filled = True
                logger.info("KronosScrape: data início preenchida via primeiro input visível")
        except Exception:
            pass

    # ── Preenche data fim ──────────────────────────────────────────────────────
    fim_filled = False
    date_end_selectors = [
        "input[placeholder*='fim' i]",
        "input[placeholder*='até' i]",
        "input[placeholder*='ate' i]",
        "input[name*='end' i]",
        "input[name*='fim' i]",
    ]
    for sel in date_end_selectors:
        if _try_fill_date(page, sel, fim_br):
            fim_filled = True
            logger.info("KronosScrape: data fim preenchida via '%s'", sel)
            break

    # Fallback: segundo input de data visível
    if not fim_filled:
        try:
            inputs = page.query_selector_all("input[type='date'], input[type='text']")
            visible = [i for i in inputs if i.is_visible()]
            if len(visible) >= 2:
                visible[1].triple_click()
                visible[1].fill(fim_br)
                fim_filled = True
                logger.info("KronosScrape: data fim preenchida via segundo input visível")
        except Exception:
            pass

    # ── Seleciona status Pendente ──────────────────────────────────────────────
    status_set = False
    try:
        status_sel = page.query_selector("select[name*='status' i]")
        if status_sel and status_sel.is_visible():
            page.select_option("select[name*='status' i]", "Pendente")
            status_set = True
            logger.info("KronosScrape: status=Pendente selecionado via select")
    except Exception:
        pass

    # Fallback: checkbox/radio com texto "Pendente"
    if not status_set:
        try:
            pendente_el = page.get_by_label(re.compile(r"pendente", re.I)).first
            if pendente_el and pendente_el.is_visible():
                pendente_el.check()
                status_set = True
                logger.info("KronosScrape: status=Pendente via get_by_label")
        except Exception:
            pass

    if not status_set:
        logger.warning("KronosScrape: não conseguiu definir status=Pendente — filtrará via Python")

    # ── Clica em Filtrar / Aplicar ────────────────────────────────────────────
    applied = False
    apply_selectors = [
        "button:text('Filtrar')",
        "button:text('Aplicar')",
        "input[type='submit']",
        "button[type='submit']",
    ]
    for sel in apply_selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2000)
                applied = True
                logger.info("KronosScrape: filtro aplicado via '%s'", sel)
                break
        except Exception:
            continue

    if not applied:
        logger.warning("KronosScrape: não conseguiu clicar em Filtrar/Aplicar — usará fallback Python")
        return False

    return True


# ── Extração de linhas ────────────────────────────────────────────────────────

def _find_date_in_tds(tds) -> Optional[str]:
    """Procura em tds uma célula cujo texto pareça data (DD/MM/YYYY ou YYYY-MM-DD)."""
    for td in tds:
        txt = td.inner_text().strip()
        if re.match(r"\d{2}/\d{2}/\d{4}", txt) or re.match(r"\d{4}-\d{2}-\d{2}", txt):
            return _parse_date_br(txt[:10])
    return None


def _find_valor_in_tds(tds) -> Optional[str]:
    """Procura em tds uma célula cujo texto pareça valor monetário."""
    for td in tds:
        txt = td.inner_text().strip()
        if re.search(r"R\$|[\d]+,\d{2}", txt):
            parsed = _parse_valor_brl(txt)
            if parsed:
                return parsed
    return None


def _extract_rows(page, inicio: str, fim: str) -> list[dict]:
    """
    Extrai linhas da tabela de lançamentos.
    Tenta múltiplos seletores de linha; filtra por status=Pendente e período [inicio, fim].
    """
    rows_data: list[dict] = []

    # Seletores de linha em ordem de preferência
    row_selectors = [
        "tr#fourth-layer-row",
        "tr[data-row]",
        "tbody tr",
    ]

    rows = []
    used_sel = None
    for sel in row_selectors:
        try:
            found = page.query_selector_all(sel)
            if found:
                rows = found
                used_sel = sel
                logger.info("KronosScrape: %d linhas encontradas via '%s'", len(found), sel)
                break
        except Exception:
            continue

    if not rows:
        logger.warning("KronosScrape: nenhuma linha encontrada na tabela")
        return []

    for row in rows:
        try:
            tds = row.query_selector_all("td")
            if len(tds) < 2:
                continue

            # Coleta textos de todas as colunas
            td_texts = [td.inner_text().strip() for td in tds]

            # ── Extrai data ────────────────────────────────────────────────────
            data_iso = _find_date_in_tds(tds)
            if not data_iso:
                # Tenta o primeiro td diretamente (posição 0 = coluna data)
                data_iso = _parse_date_br(td_texts[0][:10]) if td_texts else None

            # ── Extrai descrição ───────────────────────────────────────────────
            # Heurística: td sem data e sem valor monetário → é descrição
            descricao: str = ""
            for i, txt in enumerate(td_texts):
                if not re.match(r"\d{2}/\d{2}/\d{4}", txt) and not re.search(r"R\$|[\d]+,\d{2}", txt):
                    if len(txt) > 2:  # evita células vazias ou de ícone
                        descricao = txt
                        break
            if not descricao and len(td_texts) > 1:
                descricao = td_texts[1]

            # ── Extrai valor ───────────────────────────────────────────────────
            valor = _find_valor_in_tds(tds)

            # ── Extrai categoria / subcategoria ────────────────────────────────
            categoria: Optional[str] = None
            subcategoria: Optional[str] = None
            # Procura colunas que não são data, valor nem status
            cat_candidates = []
            for txt in td_texts:
                if (not re.match(r"\d{2}/\d{2}/\d{4}", txt)
                        and not re.search(r"R\$|[\d]+,\d{2}", txt)
                        and txt != descricao
                        and len(txt) > 1
                        and not re.search(r"pendente|conclu[ií]do|cancelado", txt, re.I)):
                    cat_candidates.append(txt)
            if cat_candidates:
                categoria = cat_candidates[0]
            if len(cat_candidates) >= 2:
                subcategoria = cat_candidates[1]

            # ── Extrai status ──────────────────────────────────────────────────
            status = "Pendente"  # default assumido na página de lançamentos
            # Procura badge/button de status
            status_el = (
                row.query_selector("button.bg-warning-light")
                or row.query_selector("[class*='status']")
                or row.query_selector("[class*='badge']")
                or row.query_selector("[class*='tag']")
            )
            if status_el:
                status_txt = status_el.inner_text().strip()
                if status_txt:
                    status = status_txt
            else:
                # Tenta encontrar texto de status nos tds
                for txt in td_texts:
                    if re.search(r"pendente|conclu[ií]do|cancelado|pago|recebido", txt, re.I):
                        status = txt
                        break

            # ── Filtra: apenas Pendente e dentro do período ────────────────────
            is_pendente = bool(re.search(r"pendente", status, re.I))
            in_period   = _date_in_range(data_iso, inicio, fim) if data_iso else False

            if not is_pendente:
                continue
            if data_iso and not in_period:
                continue
            if not data_iso:
                logger.warning(
                    "KronosScrape: linha sem data detectável — incluindo mesmo sem filtro de período: %r",
                    td_texts,
                )

            rows_data.append({
                "data": data_iso or "",
                "descricao": descricao,
                "valor": valor or "",
                "categoria": categoria,
                "subcategoria": subcategoria,
                "status": status,
            })

        except Exception as e:
            logger.error("KronosScrape: erro ao processar linha — %s", e)
            continue

    logger.info("KronosScrape: %d lançamentos Pendente extraídos no período", len(rows_data))
    return rows_data


# ── Função pública ─────────────────────────────────────────────────────────────

def scrape_pendentes(
    inicio: str,
    fim: str,
    email: Optional[str] = None,
    password: Optional[str] = None,
) -> list[dict]:
    """
    Extrai lançamentos pendentes do Meu Planner Financeiro para o período [inicio, fim].

    Args:
        inicio:   Data de início no formato "YYYY-MM-DD".
        fim:      Data de fim no formato "YYYY-MM-DD".
        email:    Login do Meu Planner (default: env PLANNER_EMAIL).
        password: Senha (default: env PLANNER_PASSWORD).

    Returns:
        Lista de dicts com chaves:
            data        — "YYYY-MM-DD"
            descricao   — str
            valor       — str  (ex: "1234.56")
            categoria   — str | None
            subcategoria— str | None
            status      — str  (ex: "Pendente")
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    email    = email    or os.environ.get("PLANNER_EMAIL", "")
    password = password or os.environ.get("PLANNER_PASSWORD", "")

    if not email or not password:
        raise ValueError("PLANNER_EMAIL / PLANNER_PASSWORD não configurados")

    # Valida formato das datas
    try:
        date.fromisoformat(inicio)
        date.fromisoformat(fim)
    except ValueError as exc:
        raise ValueError(f"inicio/fim devem estar no formato YYYY-MM-DD: {exc}") from exc

    result: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_default_timeout(20000)

            # ── Login ──────────────────────────────────────────────────────────
            try:
                _login(page, email, password)
            except Exception as e:
                logger.error("KronosScrape: falha no login — %s", e)
                return []

            # ── Navega para /lancamentos ───────────────────────────────────────
            logger.info("KronosScrape: navegando para %s", PLANNER_URL_LANC)
            page.goto(PLANNER_URL_LANC, timeout=30000)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            # ── Aplica filtros via UI ──────────────────────────────────────────
            filters_ok = False
            try:
                filters_ok = _apply_filters(page, inicio, fim)
            except Exception as e:
                logger.warning("KronosScrape: _apply_filters lançou exceção — %s", e)

            if not filters_ok:
                logger.info("KronosScrape: filtros via UI falharam — carregando todas as linhas e filtrando via Python")
                # Aguarda página estabilizar mesmo sem filtro
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2000)

            # ── Extrai linhas ──────────────────────────────────────────────────
            try:
                result = _extract_rows(page, inicio, fim)
            except Exception as e:
                logger.error("KronosScrape: falha na extração de linhas — %s", e)
                result = []

        except PWTimeout as e:
            logger.error("KronosScrape: timeout geral — %s", e)
            result = []
        except Exception as e:
            logger.error("KronosScrape: erro inesperado — %s", e)
            result = []
        finally:
            browser.close()

    logger.info(
        "KronosScrape: finalizado — %d lançamentos pendentes retornados (período %s a %s)",
        len(result), inicio, fim,
    )
    return result
