"""
KronosScrape — extrai lançamentos pendentes do Meu Planner Financeiro via Playwright.
URL: /controle/lancamentos filtrado por período e status=Pendente.
Env: PLANNER_EMAIL, PLANNER_PASSWORD

Seletores confirmados via exploração (2026-05-04):
  - Botão filtros:    [data-tip="Filtros"]
  - Select status:    select[name="status"]  (value "2" = Pendente)
  - Date input:       input[readonly][type=text]  (readonly, clique via label pai)
  - Botão Filtrar:    button[type=submit].btn-primary  (texto "Filtrar")
  - Linhas de dados:  tbody tr.h-10  (evita linhas rdp-row do calendário)
  - Items/página:     select que tem option[value='150']  (pai: "Mostrar N lançamentos")
  - Próxima página:   button.join-item:not([disabled])  (último dos join-items visíveis)
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
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        day, month, year = m.group(1), m.group(2), m.group(3)
        try:
            datetime(int(year), int(month), int(day))
            return f"{year}-{month}-{day}"
        except ValueError:
            return None
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
    if re.search(r",\d{1,2}$", s):
        s = s.replace(".", "").replace(",", ".")
    try:
        d = Decimal(s)
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


# ── Paginação: maximiza items/página ─────────────────────────────────────────

def _set_max_page_size(page) -> None:
    """
    Seta o select de items-por-página para 150 (máximo), reduzindo o número
    de páginas a navegar.
    O select correto é o que tem options 30/50/100/150 (parent: "Mostrar N lançamentos").
    """
    try:
        # Encontra o select correto por suas options características
        selects = page.query_selector_all("select")
        for sel in selects:
            opts = [o.get_attribute("value") for o in sel.query_selector_all("option")]
            if "150" in opts and "30" in opts and sel.is_visible():
                current = sel.evaluate("el => el.value")
                if current != "150":
                    sel.select_option("150")
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(1500)
                    logger.info("KronosScrape: items/página setado para 150")
                else:
                    logger.info("KronosScrape: items/página já é 150")
                return
        logger.warning("KronosScrape: select de items/página não encontrado")
    except Exception as e:
        logger.warning("KronosScrape: erro ao setar items/página — %s", e)


# ── Filtros ───────────────────────────────────────────────────────────────────

def _navigate_rdp_to_month(page, target_year: int, target_month: int) -> bool:
    """
    Navega o calendário rdp até o mês/ano alvo clicando nos botões prev/next.
    Retorna True se conseguiu chegar ao mês correto.
    """
    MAX_CLICKS = 36  # até 3 anos de navegação
    for _ in range(MAX_CLICKS):
        # Lê o mês/ano atual do calendário
        caption = page.query_selector(".rdp-caption_label")
        if not caption:
            return False
        caption_text = caption.inner_text().strip().lower()
        # Formato esperado: "maio 2026" ou "january 2026"
        month_map = {
            "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
            "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
            "outubro": 10, "novembro": 11, "dezembro": 12,
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8, "september": 9,
            "october": 10, "november": 11, "december": 12,
        }
        cur_year = None
        cur_month = None
        for name, num in month_map.items():
            if name in caption_text:
                cur_month = num
                break
        year_match = re.search(r"\d{4}", caption_text)
        if year_match:
            cur_year = int(year_match.group(0))

        if cur_year == target_year and cur_month == target_month:
            return True

        # Decide direção
        if cur_year is None or cur_month is None:
            return False
        cur_total  = cur_year * 12 + cur_month
        tgt_total  = target_year * 12 + target_month
        if tgt_total > cur_total:
            nav_btn = page.query_selector("button.rdp-nav_button_next")
        else:
            nav_btn = page.query_selector("button.rdp-nav_button_previous")

        if not nav_btn:
            return False
        # Usa JS click para ignorar visibilidade (botões ficam hidden após seleção de data)
        selector = "button.rdp-nav_button_next" if tgt_total > cur_total else "button.rdp-nav_button_previous"
        page.evaluate(f"document.querySelector('{selector}').click()")
        page.wait_for_timeout(300)

    return False


def _click_rdp_day(page, target_day: int) -> bool:
    """Clica no dia específico do calendário rdp aberto."""
    day_btns = page.query_selector_all("button.rdp-day:not([disabled])")
    for btn in day_btns:
        try:
            txt = btn.inner_text().strip()
            if txt == str(target_day):
                btn.click(timeout=3000)
                page.wait_for_timeout(400)
                return True
        except Exception:
            pass
    return False


def _open_date_picker(page) -> bool:
    """
    Tenta abrir o date range picker da toolbar (input readonly com "DD/MM/YYYY - DD/MM/YYYY").
    O rdp calendário da toolbar é diferente do rdp interno da tabela.

    NOTA: Esta funcionalidade é melhor-esforço. O período também é filtrado via Python
    (campo 'data' de cada linha). Retornar False aqui é seguro.
    """
    def _picker_is_open() -> bool:
        """Retorna True se o date range popup (com caption de mês) estiver visível."""
        caption = page.query_selector(".rdp-caption_label")
        return caption is not None and caption.is_visible()

    if _picker_is_open():
        return True

    # Estratégia 1: click(force=True) — bypassa elementos sobrepostos em headless
    try:
        date_input = page.query_selector("input[readonly][type=text]")
        if date_input:
            date_input.click(force=True)
            page.wait_for_timeout(600)
            if _picker_is_open():
                logger.info("KronosScrape: date picker aberto via click(force=True)")
                return True
    except Exception:
        pass

    # Estratégia 2: dispatch_event no input
    try:
        date_input = page.query_selector("input[readonly][type=text]")
        if date_input:
            date_input.dispatch_event("click")
            page.wait_for_timeout(600)
            if _picker_is_open():
                logger.info("KronosScrape: date picker aberto via dispatch_event('click')")
                return True
    except Exception:
        pass

    return False


def _apply_filters(page, inicio: str, fim: str) -> bool:
    """
    Aplica filtros de período e status=Pendente no Meu Planner Financeiro.

    ORDEM correta (confirmada por exploração):
    1. Seta período no date picker da TOOLBAR PRINCIPAL (antes de abrir o modal).
       O input readonly fica na toolbar e fica coberto pelo modal ao abrir.
    2. Abre o modal de filtros via [data-tip='Filtros'].
    3. Seta status=Pendente via React Select (css-b62m3t-container) dentro do modal.
    4. Clica em Filtrar.

    Retorna True se conseguiu aplicar os filtros (ao menos o modal abriu e Filtrar foi clicado).
    """
    inicio_dt = datetime.fromisoformat(inicio)
    fim_dt    = datetime.fromisoformat(fim)

    # ── PASSO 1: Seta período no date picker da toolbar (ANTES do modal) ─────
    # O date input readonly (value="DD/MM/YYYY - DD/MM/YYYY") está na toolbar principal.
    # DEVE ser interagido ANTES de abrir o modal de filtros.
    date_set = False
    try:
        if _open_date_picker(page):
            if _navigate_rdp_to_month(page, inicio_dt.year, inicio_dt.month):
                if _click_rdp_day(page, inicio_dt.day):
                    logger.info("KronosScrape: data início selecionada no rdp (%s)", inicio)
                    page.wait_for_timeout(300)
                    if _navigate_rdp_to_month(page, fim_dt.year, fim_dt.month):
                        if _click_rdp_day(page, fim_dt.day):
                            logger.info("KronosScrape: data fim selecionada no rdp (%s)", fim)
                            date_set = True
                            page.wait_for_timeout(500)
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(400)
    except Exception as e:
        logger.warning("KronosScrape: erro ao setar período no rdp — %s", e)
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass

    if not date_set:
        logger.warning(
            "KronosScrape: não conseguiu setar período via rdp — "
            "filtrará por Python. Período atual da página será usado."
        )

    # ── PASSO 2: Abre o modal de filtros ─────────────────────────────────────
    filter_opened = False

    # Seletor primário confirmado por exploração: [data-tip="Filtros"]
    try:
        btn = page.query_selector("[data-tip='Filtros']")
        if btn and btn.is_visible():
            btn.click()
            page.wait_for_timeout(1200)
            filter_opened = True
            logger.info("KronosScrape: painel de filtros aberto via [data-tip='Filtros']")
    except Exception:
        pass

    # Fallback: botão com data-tip contendo "filtro"
    if not filter_opened:
        try:
            btns = page.query_selector_all("[data-tip]")
            for btn in btns:
                tip = btn.get_attribute("data-tip") or ""
                if "filtro" in tip.lower() or "filter" in tip.lower():
                    if btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(1200)
                        filter_opened = True
                        logger.info("KronosScrape: painel de filtros aberto via data-tip='%s'", tip)
                        break
        except Exception:
            pass

    if not filter_opened:
        logger.warning("KronosScrape: não conseguiu abrir painel de filtros")
        return False

    # ── PASSO 3: Seta status=Pendente no modal (React Select) ────────────────
    # O Status usa React Select (class css-b62m3t-container).
    # Localização: label com span "Status" > div.css-b62m3t-container > div[class*='control']
    status_set = False

    try:
        # Encontra o label "Status" no modal
        status_label_el = None
        for label in page.query_selector_all("label"):
            try:
                span = label.query_selector("span")
                if span and span.inner_text().strip() == "Status":
                    status_label_el = label
                    break
            except Exception:
                pass

        if status_label_el:
            control = status_label_el.query_selector("[class*='control']")
            if control and control.is_visible():
                control.click(timeout=3000)
                page.wait_for_timeout(600)
                # Procura a opção "Pendente" no dropdown aberto
                for opt in page.query_selector_all("[class*='option']"):
                    try:
                        txt = opt.inner_text().strip()
                        if "pendente" in txt.lower() and opt.is_visible():
                            opt.click(timeout=3000)
                            page.wait_for_timeout(300)
                            status_set = True
                            logger.info("KronosScrape: status=Pendente selecionado via React Select")
                            break
                    except Exception:
                        pass
                if not status_set:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(200)
    except Exception as e:
        logger.warning("KronosScrape: erro ao setar React Select status — %s", e)

    # Fallback: radio button name=status value=2
    if not status_set:
        try:
            radio = page.query_selector("input[type=radio][name=status][value='2']")
            if radio:
                if not radio.is_checked():
                    radio.click(timeout=3000)
                    page.wait_for_timeout(300)
                status_set = True
                logger.info("KronosScrape: status=Pendente via radio name=status value=2")
        except Exception as e:
            logger.warning("KronosScrape: erro ao setar radio status — %s", e)

    # Fallback: select nativo
    if not status_set:
        try:
            status_sel = page.query_selector("select[name='status']")
            if status_sel and status_sel.is_visible():
                status_sel.select_option("2")
                status_set = True
                logger.info("KronosScrape: status=Pendente via select[name='status']")
        except Exception as e:
            logger.warning("KronosScrape: erro ao setar select status — %s", e)

    if not status_set:
        logger.warning("KronosScrape: não conseguiu setar status=Pendente — filtrará via Python")

    # ── Clica em Filtrar ─────────────────────────────────────────────────────
    # Confirmado por exploração: button[type='submit'] com texto 'Filtrar'
    applied = False

    # Seletor primário confirmado
    try:
        btn = page.query_selector("button[type='submit'].btn-primary")
        if btn and btn.is_visible():
            btn.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)
            applied = True
            logger.info("KronosScrape: filtro aplicado via button[type='submit'].btn-primary")
    except Exception:
        pass

    # Fallbacks
    if not applied:
        for sel in [
            "button[type='submit']:text('Filtrar')",
            "button:text('Filtrar')",
            "button[type='submit']",
        ]:
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
        logger.warning("KronosScrape: não conseguiu clicar em Filtrar")
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


def _extract_rows_from_page(page, inicio: str, fim: str) -> list[dict]:
    """
    Extrai linhas de dados da tabela na página atual.

    Seletor confirmado: 'tbody tr.h-10' — linhas reais de lançamento.
    As linhas do calendário rdp têm class 'rdp-row' e NÃO têm 'h-10'.

    Estrutura de colunas confirmada (11 colunas):
      0: checkbox
      1: data (DD/MM/YYYY)
      2: data2 (repete ou data de competência)
      3: categoria pai
      4: subcategoria
      5: instituição financeira / conta
      6: (vazio ou ícone)
      7: descrição
      8: valor (R$ X.XXX,XX)
      9: status (texto "Pendente", "Concluído")
     10: ações
    """
    rows_data: list[dict] = []

    # Seletor primário: linhas com classe h-10 (confirma que são linhas de dados)
    rows = page.query_selector_all("tbody tr.h-10")
    if not rows:
        # Fallback: qualquer tr que contenha odd:bg-table-odd no class
        rows = [
            r for r in page.query_selector_all("tbody tr")
            if "rdp-row" not in (r.get_attribute("class") or "")
            and (r.get_attribute("class") or "")
            and "h-10" in (r.get_attribute("class") or "")
        ]
    if not rows:
        # Segundo fallback: tbody tr sem rdp-row
        rows = [
            r for r in page.query_selector_all("tbody tr")
            if "rdp-row" not in (r.get_attribute("class") or "")
        ]

    logger.info("KronosScrape: %d linhas encontradas na página atual", len(rows))

    for row in rows:
        try:
            tds = row.query_selector_all("td")
            if len(tds) < 3:
                continue

            td_texts = [td.inner_text().strip() for td in tds]

            # ── Extrai data (coluna 1 confirmada como data) ────────────────
            data_iso: Optional[str] = None
            # Coluna 1 é a data principal (DD/MM/YYYY)
            if len(td_texts) > 1:
                data_iso = _parse_date_br(td_texts[1][:10])
            # Fallback: busca qualquer coluna com data
            if not data_iso:
                data_iso = _find_date_in_tds(tds)
            # Fallback final: coluna 0
            if not data_iso and td_texts:
                data_iso = _parse_date_br(td_texts[0][:10])

            # ── Extrai descrição (coluna 7 confirmada) ─────────────────────
            descricao: str = ""
            if len(td_texts) > 7:
                descricao = td_texts[7]
            if not descricao or len(descricao) < 2:
                # Fallback: td sem data e sem valor monetário
                for txt in td_texts:
                    if (not re.match(r"\d{2}/\d{2}/\d{4}", txt)
                            and not re.search(r"R\$|[\d]+,\d{2}", txt)
                            and len(txt) > 2
                            and not re.search(r"pendente|conclu[ií]do|cancelado|pago|recebido", txt, re.I)):
                        descricao = txt
                        break
            if not descricao and len(td_texts) > 1:
                descricao = td_texts[1]

            # ── Extrai valor (coluna 8 confirmada) ─────────────────────────
            valor: Optional[str] = None
            if len(td_texts) > 8:
                valor = _parse_valor_brl(td_texts[8])
            if not valor:
                valor = _find_valor_in_tds(tds)

            # ── Extrai categoria / subcategoria (colunas 3 e 4) ────────────
            categoria: Optional[str] = None
            subcategoria: Optional[str] = None
            if len(td_texts) > 3 and td_texts[3]:
                categoria = td_texts[3] or None
            if len(td_texts) > 4 and td_texts[4]:
                subcategoria = td_texts[4] or None

            # ── Extrai status (coluna 9 confirmada) ────────────────────────
            status = "Pendente"  # default
            if len(td_texts) > 9 and td_texts[9]:
                status = td_texts[9]
            else:
                # Busca badge/elemento de status
                status_el = (
                    row.query_selector("[class*='bg-warning-light']")
                    or row.query_selector("[class*='status']")
                    or row.query_selector("[class*='badge']")
                )
                if status_el:
                    txt = status_el.inner_text().strip()
                    if txt:
                        status = txt
                else:
                    for txt in td_texts:
                        if re.search(r"pendente|conclu[ií]do|cancelado|pago|recebido", txt, re.I):
                            status = txt
                            break

            # ── Filtra por status=Pendente e período ───────────────────────
            is_pendente = bool(re.search(r"pendente", status, re.I))
            in_period   = _date_in_range(data_iso, inicio, fim) if data_iso else False

            if not is_pendente:
                continue
            if data_iso and not in_period:
                continue
            if not data_iso:
                logger.debug(
                    "KronosScrape: linha sem data detectável — td_texts=%r",
                    td_texts[:4],
                )
                continue  # ignora linhas sem data (provavelmente lixo)

            rows_data.append({
                "data": data_iso,
                "descricao": descricao,
                "valor": valor or "",
                "categoria": categoria,
                "subcategoria": subcategoria,
                "status": status,
            })

        except Exception as e:
            logger.error("KronosScrape: erro ao processar linha — %s", e)
            continue

    return rows_data


# ── Paginação ─────────────────────────────────────────────────────────────────

def _go_to_next_page(page) -> bool:
    """
    Clica no botão de próxima página da tabela se ele existir e estiver habilitado.
    Os botões de paginação têm class 'join-item' — o primeiro é Anterior, o segundo é Próxima.
    Retorna True se navegou para a próxima página, False se não há próxima.
    """
    try:
        join_btns = page.query_selector_all("button.join-item")
        # Filtra apenas os visíveis
        visible_join = [b for b in join_btns if b.is_visible()]
        if not visible_join:
            return False

        # O último join-item visível sem [disabled] é o botão "Próxima"
        next_btn = None
        for btn in reversed(visible_join):
            disabled = btn.get_attribute("disabled")
            if disabled is None:
                next_btn = btn
                break

        if not next_btn:
            logger.info("KronosScrape: sem botão próxima página ativo")
            return False

        # Verifica que o botão realmente leva à próxima página
        # (não é o botão Anterior que ficou habilitado)
        # O botão anterior é o primeiro, próximo é o último
        if next_btn == visible_join[0] and len(visible_join) > 1:
            # Só tem um botão habilitado e é o primeiro (Anterior) — não avança
            return False

        next_btn.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)
        logger.info("KronosScrape: navegou para próxima página")
        return True

    except Exception as e:
        logger.warning("KronosScrape: erro ao navegar para próxima página — %s", e)
        return False


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

            # ── Maximiza items por página (150) ────────────────────────────────
            try:
                _set_max_page_size(page)
            except Exception as e:
                logger.warning("KronosScrape: erro ao setar items/página — %s", e)

            # ── Aplica filtros via UI ──────────────────────────────────────────
            filters_ok = False
            try:
                filters_ok = _apply_filters(page, inicio, fim)
            except Exception as e:
                logger.warning("KronosScrape: _apply_filters lançou exceção — %s", e)

            if not filters_ok:
                logger.info(
                    "KronosScrape: filtros via UI falharam ou incompletos — "
                    "carregando todas as linhas e filtrando via Python"
                )
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1500)

            # ── Extrai linhas com paginação ────────────────────────────────────
            MAX_PAGES = 50  # limite de segurança
            page_num = 1
            seen_rows: set[str] = set()  # evita duplicatas entre páginas

            while page_num <= MAX_PAGES:
                logger.info("KronosScrape: extraindo página %d", page_num)
                try:
                    page_rows = _extract_rows_from_page(page, inicio, fim)
                except Exception as e:
                    logger.error("KronosScrape: falha na extração da página %d — %s", page_num, e)
                    break

                new_count = 0
                for row in page_rows:
                    # Chave de deduplicação
                    key = f"{row['data']}|{row['descricao'][:30]}|{row['valor']}"
                    if key not in seen_rows:
                        seen_rows.add(key)
                        result.append(row)
                        new_count += 1

                logger.info(
                    "KronosScrape: página %d — %d novos lançamentos Pendente (%d total)",
                    page_num, new_count, len(result),
                )

                # Se não há linhas novas nesta página, para
                if new_count == 0 and page_num > 1:
                    logger.info("KronosScrape: sem novos lançamentos — fim da paginação")
                    break

                # Tenta navegar para a próxima página
                try:
                    has_next = _go_to_next_page(page)
                except Exception as e:
                    logger.warning("KronosScrape: erro na paginação — %s", e)
                    break

                if not has_next:
                    logger.info("KronosScrape: sem próxima página — fim da paginação")
                    break

                page_num += 1

        except PWTimeout as e:
            logger.error("KronosScrape: timeout geral — %s", e)
        except Exception as e:
            logger.error("KronosScrape: erro inesperado — %s", e)
        finally:
            browser.close()

    logger.info(
        "KronosScrape: finalizado — %d lançamentos pendentes retornados (período %s a %s)",
        len(result), inicio, fim,
    )
    return result
