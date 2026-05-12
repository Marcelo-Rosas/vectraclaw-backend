"""Tests for `src.agents.kronos_pdf_enricher` (VEC-425 / sub-PR5 of VEC-416)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]


# ── parse_brl_amount_to_centavos ──────────────────────────────────────


def test_parse_amount_handles_positive_brl():
    from src.agents.kronos_pdf_enricher import parse_brl_amount_to_centavos

    assert parse_brl_amount_to_centavos("R$ 271,80") == 27180
    assert parse_brl_amount_to_centavos("R$ 1.234,56") == 123456
    assert parse_brl_amount_to_centavos("R$ 0,01") == 1


def test_parse_amount_handles_negative_brl():
    from src.agents.kronos_pdf_enricher import parse_brl_amount_to_centavos

    assert parse_brl_amount_to_centavos("-R$ 271,80") == -27180
    assert parse_brl_amount_to_centavos("-R$ 13.000,00") == -1300000


def test_parse_amount_handles_no_currency_symbol():
    from src.agents.kronos_pdf_enricher import parse_brl_amount_to_centavos

    assert parse_brl_amount_to_centavos("271,80") == 27180
    assert parse_brl_amount_to_centavos("-271,80") == -27180


def test_parse_amount_returns_zero_for_invalid():
    from src.agents.kronos_pdf_enricher import parse_brl_amount_to_centavos

    assert parse_brl_amount_to_centavos("") == 0
    assert parse_brl_amount_to_centavos("xxx") == 0
    assert parse_brl_amount_to_centavos("R$ -") == 0


# ── build_pdf_lookup ──────────────────────────────────────────────────


def test_build_lookup_uses_abs_centavos():
    from src.agents.kronos_pdf_enricher import PdfEntry, build_pdf_lookup

    entries = [
        PdfEntry(date(2026, 5, 10), -1998, "Pix enviado para FAST MARKET", "Saída PIX"),
        PdfEntry(date(2026, 5, 10), 13000, "Pix recebido de SMARTFIT", "Entrada PIX"),
    ]
    lookup = build_pdf_lookup(entries)

    assert ("2026-05-10", 1998) in lookup
    assert ("2026-05-10", 13000) in lookup
    assert lookup[("2026-05-10", 1998)] == "Pix enviado para FAST MARKET"


def test_build_lookup_preserves_first_on_collision():
    from src.agents.kronos_pdf_enricher import PdfEntry, build_pdf_lookup

    entries = [
        PdfEntry(date(2026, 5, 5), -87349, "Pagamento COND ED VILA IMPERIAL", "Pagamento"),
        PdfEntry(date(2026, 5, 5), -87349, "Outro pagamento mesma data e valor", "Pagamento"),
    ]
    lookup = build_pdf_lookup(entries)
    assert lookup[("2026-05-05", 87349)] == "Pagamento COND ED VILA IMPERIAL"


# ── find_enriched_description ────────────────────────────────────────


def _sample_lookup() -> dict:
    return {
        ("2026-05-10", 1998): "Pix enviado para FAST MARKET",
        ("2026-05-05", 87349): "Pagamento COND ED VILA IMPERIAL",
    }


def test_find_enriched_accepts_iso_date():
    from src.agents.kronos_pdf_enricher import find_enriched_description

    desc = find_enriched_description(_sample_lookup(), "2026-05-10", 1998)
    assert desc == "Pix enviado para FAST MARKET"


def test_find_enriched_accepts_brazilian_date():
    from src.agents.kronos_pdf_enricher import find_enriched_description

    desc = find_enriched_description(_sample_lookup(), "10/05/2026", 1998)
    assert desc == "Pix enviado para FAST MARKET"


def test_find_enriched_uses_abs_centavos():
    from src.agents.kronos_pdf_enricher import find_enriched_description

    # Mesmo se passar negativo, deve casar
    desc = find_enriched_description(_sample_lookup(), "10/05/2026", -1998)
    assert desc == "Pix enviado para FAST MARKET"


def test_find_enriched_returns_none_on_miss():
    from src.agents.kronos_pdf_enricher import find_enriched_description

    assert find_enriched_description(_sample_lookup(), "01/01/2030", 100) is None
    assert find_enriched_description(_sample_lookup(), "10/05/2026", 9999) is None


def test_find_enriched_returns_none_on_invalid_date():
    from src.agents.kronos_pdf_enricher import find_enriched_description

    assert find_enriched_description(_sample_lookup(), "data inválida", 1998) is None
    assert find_enriched_description(_sample_lookup(), "", 1998) is None


# ── parse_c6_pdf (integration com PDF real do user) ──────────────────


_REAL_PDF = Path(
    r"C:/Users/marce/OFX-C6/Extrato_Conta_Corrente_C6Bank_12_05_202612-05-2026-3_02_00.pdf"
)


@pytest.mark.skipif(not _REAL_PDF.exists(), reason="PDF de fixture do user não disponível")
def test_parse_c6_pdf_real_file_extracts_transactions():
    from src.agents.kronos_pdf_enricher import parse_c6_pdf

    entries = parse_c6_pdf(_REAL_PDF)
    # PDF cobre semana 1 de maio (01-10/05) com ~50 transações
    assert len(entries) > 40, f"esperado >40 transações, vi {len(entries)}"

    # Sanity: pelo menos uma com SAO JOAO FARMACIAS
    has_farmacia = any(
        "SAO JOAO FARMACIAS" in e.description for e in entries
    )
    assert has_farmacia, "transação SAO JOAO FARMACIAS não foi extraída"

    # Sanity: pelo menos uma com COND ED VILA IMPERIAL
    has_condominio = any(
        "COND ED VILA IMPERIAL" in e.description for e in entries
    )
    assert has_condominio, "transação COND ED VILA IMPERIAL não foi extraída"


@pytest.mark.skipif(not _REAL_PDF.exists(), reason="PDF de fixture do user não disponível")
def test_parse_c6_pdf_real_file_dates_correct():
    """Confirma que ano vem do header (2026), não do default (today)."""
    from src.agents.kronos_pdf_enricher import parse_c6_pdf

    entries = parse_c6_pdf(_REAL_PDF)
    years = {e.date.year for e in entries}
    assert years == {2026}, f"todos devem ser 2026, vi: {years}"


def test_parse_c6_pdf_raises_when_missing(tmp_path: Path):
    from src.agents.kronos_pdf_enricher import parse_c6_pdf

    with pytest.raises(FileNotFoundError):
        parse_c6_pdf(tmp_path / "nope.pdf")
