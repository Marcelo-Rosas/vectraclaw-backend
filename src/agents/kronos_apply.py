"""
KronosApply — marca lançamentos reconciliados como Concluído no Meu Planner Financeiro.

Recebe uma lista de matches (saída de AuditReport.matches) e, para cada entrada
do Planner que foi confirmada no OFX, navega até /controle/pendencias e clica
"Pendente" → confirma a mudança para "Concluído".

Dependência: playwright (pip install playwright && python -m playwright install chromium)
Env vars obrigatórias: PLANNER_EMAIL, PLANNER_PASSWORD
"""
from __future__ import annotations

import difflib
import logging
import os
import re
import unicodedata
from decimal import Decimal
from typing import Optional

logger = logging.getLogger("KronosApply")

PLANNER_URL_LOGIN = "https://web.meuplannerfinanceiro.com.br/login"
PLANNER_URL_PEND  = "https://web.meuplannerfinanceiro.com.br/controle/pendencias"


def _normalize(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()


def _parse_valor_brl(s: str) -> Optional[Decimal]:
    """Converte 'R$\xa02.100,00' para Decimal('2100.00')."""
    s = re.sub(r"[R$\s\xa0]", "", s).strip()
    if not s:
        return None
    if re.search(r",\d{1,2}$", s):
        s = s.replace(".", "").replace(",", ".")
    return Decimal(s)


def _score_match(planner_desc: str, planner_valor_str: str,
                 row_desc: str, row_valor_str: str) -> float:
    """
    Retorna score 0-1 de similaridade entre o match do relatório e uma linha da página.
    Score ≥ 0.6 é considerado match.
    """
    # Valor: deve bater exatamente
    v_planner = _parse_valor_brl(planner_valor_str.replace("R$ ", "R$"))
    v_row     = _parse_valor_brl(row_valor_str)
    if v_planner is None or v_row is None:
        return 0.0
    if abs(v_planner - v_row) > Decimal("0.01"):
        return 0.0

    # Descrição: similaridade de texto (normalizada)
    sim = difflib.SequenceMatcher(
        None,
        _normalize(planner_desc),
        _normalize(row_desc),
    ).ratio()
    return sim


def apply_baixa(
    matches: list[dict],
    email: Optional[str] = None,
    password: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """
    Marca cada item em `matches` como Concluído no Meu Planner.

    Args:
        matches: lista de dicts com chaves 'planner_descricao', 'planner_valor_fmt'.
        email: login do Meu Planner (default: env PLANNER_EMAIL).
        password: senha (default: env PLANNER_PASSWORD).
        dry_run: se True, apenas simula sem clicar em Confirmar.

    Returns:
        dict com 'confirmados', 'nao_encontrados', 'erros'.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    email    = email    or os.environ.get("PLANNER_EMAIL", "")
    password = password or os.environ.get("PLANNER_PASSWORD", "")

    if not email or not password:
        raise ValueError("PLANNER_EMAIL / PLANNER_PASSWORD não configurados")

    if not matches:
        logger.info("KronosApply: nenhum match para dar baixa")
        return {"confirmados": [], "nao_encontrados": [], "erros": []}

    confirmados: list[dict] = []
    nao_encontrados: list[dict] = []
    erros: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_default_timeout(20000)

            # ── Login ─────────────────────────────────────────────────────────
            logger.info("KronosApply: fazendo login em Meu Planner")
            page.goto(PLANNER_URL_LOGIN, timeout=30000)
            page.wait_for_load_state("networkidle")
            page.fill("#email", email)
            page.fill("input[type=password]", password)
            page.click("button[type=submit]")
            page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
            logger.info("KronosApply: login OK — %s", page.url)

            # ── Navega para /pendencias ────────────────────────────────────────
            page.goto(PLANNER_URL_PEND, timeout=30000)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            for match in matches:
                desc_target = match.get("planner_descricao", "")
                valor_target = match.get("planner_valor_fmt", match.get("planner_valor", ""))

                logger.info("KronosApply: tentando dar baixa em '%s' %s",
                            desc_target, valor_target)

                try:
                    _dar_baixa_item(
                        page, desc_target, valor_target,
                        dry_run, confirmados, nao_encontrados,
                    )
                except PWTimeout as e:
                    erros.append({"descricao": desc_target, "erro": f"timeout: {e}"})
                    logger.error("KronosApply: timeout em '%s' — %s", desc_target, e)
                    # Reload para recuperar estado limpo
                    try:
                        page.goto(PLANNER_URL_PEND, timeout=30000)
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(1500)
                    except Exception:
                        pass
                except Exception as e:
                    erros.append({"descricao": desc_target, "erro": str(e)})
                    logger.error("KronosApply: erro em '%s' — %s", desc_target, e)

        finally:
            browser.close()

    logger.info(
        "KronosApply: concluído — confirmados=%d nao_encontrados=%d erros=%d",
        len(confirmados), len(nao_encontrados), len(erros),
    )
    return {
        "confirmados": confirmados,
        "nao_encontrados": nao_encontrados,
        "erros": erros,
    }


def _dar_baixa_item(
    page,
    desc_target: str,
    valor_target: str,
    dry_run: bool,
    confirmados: list,
    nao_encontrados: list,
) -> None:
    """Localiza a linha na tabela e confirma a mudança de status."""
    from playwright.sync_api import TimeoutError as PWTimeout

    # Busca todas as linhas de pendência
    rows = page.query_selector_all("tr#fourth-layer-row")

    best_score = 0.0
    best_btn   = None
    best_row_desc = ""

    for row in rows:
        tds = row.query_selector_all("td")
        if len(tds) < 3:
            continue

        row_desc  = tds[0].inner_text().strip()
        row_valor = tds[1].inner_text().strip()
        btn       = tds[2].query_selector("button.bg-warning-light")

        if btn is None:
            continue  # já marcado como Concluído ou outro status

        score = _score_match(desc_target, valor_target, row_desc, row_valor)
        if score > best_score:
            best_score    = score
            best_btn      = btn
            best_row_desc = row_desc

    THRESHOLD = 0.55
    if best_score < THRESHOLD or best_btn is None:
        logger.warning(
            "KronosApply: '%s' não encontrado (best_score=%.2f, best_match=%r)",
            desc_target, best_score, best_row_desc,
        )
        nao_encontrados.append({
            "descricao": desc_target,
            "valor": valor_target,
            "best_score": round(best_score, 3),
            "best_match": best_row_desc,
        })
        return

    logger.info(
        "KronosApply: match (score=%.2f) '%s' → '%s'",
        best_score, desc_target, best_row_desc,
    )

    if dry_run:
        confirmados.append({
            "descricao": desc_target,
            "row_match": best_row_desc,
            "score": round(best_score, 3),
            "dry_run": True,
        })
        logger.info("KronosApply: [dry_run] SKIP confirmar")
        return

    # Clica no badge Pendente → abre modal de confirmação
    best_btn.click()

    # Aguarda o botão "Confirmar" no modal ficar visível
    confirmar_btn = page.wait_for_selector(
        "button:text('Confirmar'):visible", timeout=8000
    )

    # Clica em Confirmar
    confirmar_btn.click()

    # Aguarda o modal fechar (botão Confirmar desaparece)
    try:
        page.wait_for_selector("button:text('Confirmar')", state="hidden", timeout=8000)
    except Exception:
        pass

    # Pequena pausa para o estado atualizar
    page.wait_for_timeout(600)

    confirmados.append({
        "descricao": desc_target,
        "row_match": best_row_desc,
        "score": round(best_score, 3),
    })
    logger.info("KronosApply: baixa confirmada em '%s'", best_row_desc)
