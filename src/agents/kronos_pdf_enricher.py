"""
Kronos PDF Enricher — extrai descrições ricas do extrato PDF do C6 Bank
e oferece lookup por (data, valor) pra enriquecer linhas do OFX que vêm
genéricas (tipo `TRANSF ENVIADA PIX`).

VEC-425 (sub-PR5 do VEC-416). O OFX C6 não traz destinatário/origem do
PIX — só "TRANSF ENVIADA PIX". O PDF do mesmo banco traz:

    Pix enviado para SAO JOAO FARMACIAS -R$ 271,80
    Pagamento COND ED VILA IMPERIAL -R$ 873,49
    Débito de Cartão IFD*RAIA DROGASIL -R$ 296,87

Cruzamento por (data, valor absoluto) → descrição enriquecida → match_rule
do kronos_categorizer cobre muito mais casos.

Uso:

    entries = parse_c6_pdf(Path("extrato.pdf"))
    lookup = build_pdf_lookup(entries)
    desc = find_enriched_description(lookup, "10/05/2026", 1998)
    # → "Pix enviado para FAST MARKET"
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

try:
    import pdfplumber  # pyright: ignore[reportMissingImports]
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "pdfplumber não instalado. Rode `pip install pdfplumber`."
    ) from exc


logger = logging.getLogger("KronosPdfEnricher")


# ── Tipos ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PdfEntry:
    """Uma transação extraída do PDF do extrato."""

    date: date
    amount_centavos: int  # signed (negativo = saída)
    description: str
    tipo: str  # "Saída PIX", "Entrada PIX", "Pagamento", "Débito de Cartão"


# ── Regex pra parsing ─────────────────────────────────────────────────

# Header com período do extrato: "01/05/2026 - 10/05/2026"
_PERIOD_RE = re.compile(
    r"(?P<start>\d{2}/\d{2}/\d{4})\s*-\s*(?P<end>\d{2}/\d{2}/\d{4})"
)

# Linha de transação single-line:
#   01/05 04/05 Saída PIX Pix enviado para SAO JOAO FARMACIAS -R$ 271,80
#   05/05 05/05 Pagamento COND ED VILA IMPERIAL -R$ 873,49
#   05/05 05/05 Entrada PIX Pix recebido de VECTRA HUB LTDA R$ 1.890,00
_LINE_RE = re.compile(
    r"^(?P<dlanc>\d{2}/\d{2})\s+"
    r"(?P<dcont>\d{2}/\d{2})\s+"
    r"(?P<tipo>Sa[íi]da PIX|Entrada PIX|Pagamento|D[éee]bito de Cart[ãa]o)\s+"
    r"(?P<desc>.+?)\s+"
    r"(?P<sign>-?)R\$\s*(?P<val>[\d.,]+)\s*$"
)


# ── API pública ──────────────────────────────────────────────────────


def parse_c6_pdf(pdf_path: Path | str) -> list[PdfEntry]:
    """Extrai todas as transações de um extrato PDF do C6 Bank.

    Levanta `FileNotFoundError` se o arquivo não existe.
    Devolve lista vazia se nenhum padrão de transação foi encontrado.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF não encontrado: {path}")

    full_text = _extract_full_text(path)
    period = _extract_period(full_text)
    if period is None:
        logger.warning(
            "período não encontrado no PDF — assumindo ano corrente (%s)",
            path.name,
        )
        year = date.today().year
    else:
        year = period[0].year

    entries: list[PdfEntry] = []
    for raw_line in full_text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        match = _LINE_RE.match(line)
        if not match:
            continue
        entry = _build_entry(match, year)
        if entry is not None:
            entries.append(entry)

    logger.info("parse_c6_pdf: %d transações extraídas de %s", len(entries), path.name)
    return entries


def build_pdf_lookup(
    entries: list[PdfEntry],
) -> dict[tuple[str, int], str]:
    """Constrói mapa `(data_iso, |valor_centavos|) → descrição`.

    Em caso de chaves duplicadas (transações com mesma data + mesmo valor),
    preserva a primeira encontrada — falso positivo aceito (raro).
    """
    lookup: dict[tuple[str, int], str] = {}
    for entry in entries:
        key = (entry.date.isoformat(), abs(entry.amount_centavos))
        if key not in lookup:
            lookup[key] = entry.description
    return lookup


def find_enriched_description(
    lookup: dict[tuple[str, int], str],
    date_str: str,
    amount_centavos: int,
) -> Optional[str]:
    """Procura no lookup. `date_str` aceita ISO (`2026-05-10`) ou pt-BR (`10/05/2026`).

    Retorna `None` se não bater.
    """
    iso = _to_iso_date(date_str)
    if iso is None:
        return None
    return lookup.get((iso, abs(amount_centavos)))


def parse_brl_amount_to_centavos(text: str) -> int:
    """Converte 'R$ 1.234,56' / '-R$ 1.234,56' / '1234,56' → centavos signed.

    Devolve 0 se não conseguir parsear.
    """
    if not text:
        return 0
    cleaned = text.replace("R$", "").replace(" ", "").replace("\xa0", "")
    sign = 1
    if cleaned.startswith("-"):
        sign = -1
        cleaned = cleaned[1:]
    cleaned = cleaned.replace(".", "").replace(",", ".")
    if not cleaned:
        return 0
    try:
        return sign * int(round(float(cleaned) * 100))
    except ValueError:
        return 0


# ── Internos ─────────────────────────────────────────────────────────


def _extract_full_text(pdf_path: Path) -> str:
    parts: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            parts.append(text)
    return "\n".join(parts)


def _extract_period(text: str) -> Optional[tuple[date, date]]:
    match = _PERIOD_RE.search(text)
    if not match:
        return None
    try:
        start = datetime.strptime(match.group("start"), "%d/%m/%Y").date()
        end = datetime.strptime(match.group("end"), "%d/%m/%Y").date()
        return start, end
    except ValueError:
        return None


def _build_entry(match: re.Match[str], year: int) -> Optional[PdfEntry]:
    d_lanc = match.group("dlanc")
    try:
        day, month = (int(x) for x in d_lanc.split("/"))
        dt = date(year, month, day)
    except (ValueError, IndexError):
        return None

    sign = match.group("sign") or ""
    centavos = parse_brl_amount_to_centavos(f"{sign}R$ {match.group('val')}")
    return PdfEntry(
        date=dt,
        amount_centavos=centavos,
        description=match.group("desc").strip(),
        tipo=match.group("tipo").strip(),
    )


def _to_iso_date(s: str) -> Optional[str]:
    s = (s or "").strip()
    if not s:
        return None
    # Tenta ISO primeiro (mais comum em API)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


__all__ = [
    "PdfEntry",
    "parse_c6_pdf",
    "build_pdf_lookup",
    "find_enriched_description",
    "parse_brl_amount_to_centavos",
]
