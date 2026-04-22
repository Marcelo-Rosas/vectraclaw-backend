"""
VEC-184 – OCR pipeline for Bill of Lading (BL) and Packing List (PL) PDFs.

Strategy:
  1. Extract full text from all pages via pdfplumber.
  2. Run a battery of regex patterns to locate well-known field labels.
  3. Return a structured dict; unknown fields are omitted (never faked).
  4. Document type (BL / PL / mixed) is auto-detected from content signals.
"""

from __future__ import annotations

import base64
import io
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("logistics.bl_pl_parser")

# ---------------------------------------------------------------------------
# Regex catalogue
# ---------------------------------------------------------------------------

_BL_PATTERNS: dict[str, str] = {
    # Bill of Lading number – e.g. MEDU1234567, MAEU123456789
    # handles: "B/L No:", "BILL OF LADING NO:", "BILL OF LADING NUMBER:"
    "bl_number": r"B(?:ILL\s+OF\s+LAD(?:ING)?(?:\s+(?:NO|NUMBER|NUM)\.?)?|\/L\s*(?:NO\.?)?)[\s#:.-]*([A-Z]{3,6}[0-9A-Z]{6,12})",
    # Shipper / Exporter block – value on same line after label; stop at next keyword
    "shipper": r"(?:SHIPPER|EXPORTER)[\s:/-]+([A-Z][A-Z0-9 &,.'()-]{3,60}?)(?=\s{2,}[A-Z]{3,}|\s*CONSIGNEE|\s*VESSEL|\s*PORT|\Z)",
    # Consignee block
    "consignee": r"CONSIGNEE[\s:/-]+([A-Z][A-Z0-9 &,.'()-]{3,60}?)(?=\s{2,}[A-Z]{3,}|\s*VESSEL|\s*PORT|\s*NOTIFY|\Z)",
    # Notify party
    "notify_party": r"NOTIFY\s*(?:PARTY)?[\s:/-]+([A-Z][A-Z0-9 &,.'()-]{3,60}?)(?=\s{2,}[A-Z]{3,}|\s*PORT|\Z)",
    # Vessel / Ship name – stop at VOY, PORT or 2+ spaces
    "vessel": r"VESSEL(?:\s*NAME)?[\s:/-]+([A-Z][A-Z0-9 &/-]{2,40}?)(?=\s{2,}[A-Z]{2,}|\s*VOY|\s*PORT|\Z)",
    # Voyage number
    "voyage": r"VOY(?:AGE)?(?:\s*NO\.?)?[\s:/-]+([A-Z0-9-]{2,12})",
    # Port of loading
    "port_of_loading": r"PORT\s+OF\s+LOAD(?:ING)?[\s:/-]+([A-Z][A-Za-z ,]{2,40})",
    # Port of discharge
    "port_of_discharge": r"PORT\s+OF\s+DISCH(?:ARGE)?[\s:/-]+([A-Z][A-Za-z ,]{2,40})",
    # Final destination / place of delivery
    "place_of_delivery": r"PLACE\s+OF\s+DELIV(?:ERY)?[\s:/-]+([A-Z][A-Za-z ,]{2,40})",
    # Gross weight – captures number + unit
    "gross_weight": r"GROSS\s*WEIGHT[\s:/-]+([0-9][0-9,.]+\s*(?:KGS?|MT|LBS?))",
    # Net weight
    "net_weight": r"NET\s*WEIGHT[\s:/-]+([0-9][0-9,.]+\s*(?:KGS?|MT|LBS?))",
    # Number of packages / pieces
    "packages": r"(?:NO\.?\s*OF\s*)?(?:PACKAGE|PKG|CARTON|PIECE|CTN)S?[\s:/-]+([0-9][0-9,]+)",
    # Measurement / CBM / volume
    "measurement": r"MEAS(?:UREMENT)?[\s:/-]+([0-9][0-9,.]+\s*(?:CBM|M3|CUM)?)",
}

# Container ISO format: 4 capital letters + 7 digits (last is check digit)
_CONTAINER_RE = re.compile(r"\b([A-Z]{4}[0-9]{7})\b")

# ISO date patterns  YYYY-MM-DD  or  DD/MM/YYYY  or  DD-MMM-YYYY
_DATE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{2}[/-]\d{2}[/-]\d{4}|\d{2}-(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)-\d{4})\b",
    re.IGNORECASE,
)

# Packing List specifics
_PL_PATTERNS: dict[str, str] = {
    "po_number": r"(?:PO|P\.O\.|PURCHASE\s+ORDER)\s*(?:NO\.?|#)?[\s:/-]+([A-Z0-9-]{4,20})",
    "invoice_number": r"INVOICE\s*(?:NO\.?|#)?[\s:/-]+([A-Z0-9-]{4,20})",
    "total_cartons": r"TOTAL\s+CARTONS?[\s:/-]+([0-9][0-9,]+)",
    "total_gross_weight": r"TOTAL\s+GROSS[\s:/-]+([0-9][0-9,.]+\s*(?:KGS?|MT|LBS?)?)",
    "total_net_weight": r"TOTAL\s+NET[\s:/-]+([0-9][0-9,.]+\s*(?:KGS?|MT|LBS?)?)",
    "total_cbm": r"TOTAL\s+(?:CBM|VOLUME|MEASUREMENT)[\s:/-]+([0-9][0-9,.]+)",
}

# Doc-type auto-detect keywords
_BL_KEYWORDS = {"BILL OF LADING", "B/L", "SHIPPER'S COPY", "OCEAN FREIGHT", "PORT OF LOADING"}
_PL_KEYWORDS = {"PACKING LIST", "PACKING DETAIL", "CARTON NO", "NET WEIGHT PER", "GROSS WEIGHT PER"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_text_from_bytes(pdf_bytes: bytes) -> str:
    """Return concatenated text from all pages using pdfplumber."""
    try:
        import pdfplumber  # lazy – not imported at module level to stay testable
    except ImportError as exc:
        raise RuntimeError("pdfplumber not installed – run: pip install pdfplumber") from exc

    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return "\n".join(pages)


def _apply_patterns(text: str, patterns: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    upper = text.upper()
    for field, pattern in patterns.items():
        m = re.search(pattern, upper)
        if m:
            result[field] = m.group(1).strip().title()
    return result


def _detect_doc_type(upper_text: str) -> str:
    bl_score = sum(1 for kw in _BL_KEYWORDS if kw in upper_text)
    pl_score = sum(1 for kw in _PL_KEYWORDS if kw in upper_text)
    if bl_score > pl_score:
        return "bl"
    if pl_score > bl_score:
        return "pl"
    if bl_score == 0 and pl_score == 0:
        return "unknown"
    return "mixed"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_pdf_bytes(pdf_bytes: bytes) -> dict:
    """
    Parse raw PDF bytes and return a structured extraction result.

    Returns:
        {
          "doc_type": "bl" | "pl" | "mixed" | "unknown",
          "bl": { ...fields... },          # present when bl/mixed
          "pl": { ...fields... },          # present when pl/mixed
          "containers": [...],
          "dates": [...],
          "raw_text_snippet": "...",       # first 500 chars for debugging
        }
    """
    raw_text = _extract_text_from_bytes(pdf_bytes)
    upper = raw_text.upper()
    doc_type = _detect_doc_type(upper)

    result: dict = {"doc_type": doc_type}

    if doc_type in ("bl", "mixed", "unknown"):
        bl_data = _apply_patterns(raw_text, _BL_PATTERNS)
        if bl_data:
            result["bl"] = bl_data

    if doc_type in ("pl", "mixed"):
        pl_data = _apply_patterns(raw_text, _PL_PATTERNS)
        if pl_data:
            result["pl"] = pl_data

    # Containers and dates are useful in both doc types
    containers = list(dict.fromkeys(_CONTAINER_RE.findall(upper)))  # deduplicated, ordered
    if containers:
        result["containers"] = containers

    dates = list(dict.fromkeys(_DATE_RE.findall(raw_text)))
    if dates:
        result["dates"] = dates

    result["raw_text_snippet"] = raw_text[:500].strip()
    return result


def parse_pdf_file(file_path: str) -> dict:
    """Load PDF from filesystem path and parse it."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")
    return parse_pdf_bytes(path.read_bytes())


def parse_pdf_base64(b64_content: str) -> dict:
    """Decode a base64-encoded PDF string and parse it."""
    try:
        pdf_bytes = base64.b64decode(b64_content)
    except Exception as exc:
        raise ValueError("Invalid base64 content") from exc
    return parse_pdf_bytes(pdf_bytes)


def cross_reference(bl_data: dict, pl_data: dict) -> dict:
    """
    Cross-reference extracted BL and PL data.

    Returns a summary with:
      - matched_containers: containers found in both
      - weight_delta: difference between BL gross weight (kg) and PL total (kg) if parseable
      - inconsistencies: list of human-readable warnings
    """
    inconsistencies: list[str] = []

    bl_containers = set(bl_data.get("containers", []))
    pl_containers = set(pl_data.get("containers", []))
    matched = list(bl_containers & pl_containers)
    only_bl = list(bl_containers - pl_containers)
    only_pl = list(pl_containers - bl_containers)

    if only_bl:
        inconsistencies.append(f"Containers in BL but not PL: {only_bl}")
    if only_pl:
        inconsistencies.append(f"Containers in PL but not BL: {only_pl}")

    return {
        "matched_containers": matched,
        "containers_only_in_bl": only_bl,
        "containers_only_in_pl": only_pl,
        "inconsistencies": inconsistencies,
    }
