"""
VEC-184 Smoke Test – extract_bl_pl OCR pipeline.

Testa:
  T1 – parse_pdf_bytes com PDF sintético contendo dados de BL → extrai campos esperados
  T2 – parse_pdf_bytes com dados de PL → detecta doc_type="pl"
  T3 – parse_pdf_bytes com dados mistos → doc_type="mixed" + cross_reference
  T4 – extract_bl_pl (m3_tools) via base64 → success=True, extracted_data presente
  T5 – extract_bl_pl sem payload → success=False, error informativo
  T6 – POST /api/tools/extract-bl-pl com upload de PDF sintético → 200 OK
  T7 – POST /api/tools/extract-bl-pl com arquivo não-PDF → 422
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import base64
import io
import json
import struct
import zlib

BASE_URL = "http://localhost:3100"


# ---------------------------------------------------------------------------
# Minimal PDF builder (raw bytes, no external deps)
# ---------------------------------------------------------------------------

def _build_pdf(text: str) -> bytes:
    """
    Constrói um PDF mínimo (1 página) que o pdfplumber consegue ler.
    Usa apenas a stdlib — sem reportlab.
    """
    # Compress the content stream
    stream_content = f"BT /F1 12 Tf 50 750 Td ({text}) Tj ET".encode()
    compressed = zlib.compress(stream_content)

    # We'll build the PDF objects as byte strings
    # Object 1: catalog
    # Object 2: pages
    # Object 3: page
    # Object 4: font resource
    # Object 5: content stream

    def obj(n: int, content: bytes) -> tuple[int, bytes]:
        blob = (f"{n} 0 obj\n").encode() + content + b"\nendobj\n"
        return blob

    catalog    = b"<< /Type /Catalog /Pages 2 0 R >>"
    pages      = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    page       = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 5 0 R /Resources << /Font << /F1 4 0 R >> >> >>"
    font       = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    stream_hdr = (
        f"<< /Filter /FlateDecode /Length {len(compressed)} >>\n"
        f"stream\n"
    ).encode()
    stream_body = compressed + b"\nendstream"

    bodies = [
        catalog,
        pages,
        page,
        font,
        stream_hdr + stream_body,
    ]

    header = b"%PDF-1.4\n"
    offsets: list[int] = []
    buf = bytearray(header)

    for i, body in enumerate(bodies, start=1):
        offsets.append(len(buf))
        chunk = (f"{i} 0 obj\n").encode() + body + b"\nendobj\n"
        buf.extend(chunk)

    xref_offset = len(buf)
    xref = f"xref\n0 {len(bodies)+1}\n0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n"
    trailer = (
        f"trailer\n<< /Size {len(bodies)+1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    )
    buf.extend(xref.encode())
    buf.extend(trailer.encode())
    return bytes(buf)


BL_TEXT = (
    "BILL OF LADING NO: MAEU1234567  "
    "SHIPPER: VECTRA CARGO ASIA LTD  "
    "CONSIGNEE: VECTRA BRASIL LTDA  "
    "VESSEL NAME: MSC GULSUN  "
    "PORT OF LOADING: SHANGHAI CN  "
    "PORT OF DISCHARGE: NAVEGANTES BR  "
    "GROSS WEIGHT: 45000 KGS  "
    "CONTAINER: MSCU9999999 MSCU8888888"
)

PL_TEXT = (
    "PACKING LIST  "
    "PO NO: PO-2026-001  "
    "TOTAL CARTONS: 120  "
    "TOTAL GROSS: 4500 KGS  "
    "TOTAL NET: 4200 KGS  "
    "TOTAL CBM: 28.50  "
    "CARTON NO 1: ITEM-A QTY 12"
)

MIXED_TEXT = BL_TEXT + "  " + PL_TEXT

BL_PDF    = _build_pdf(BL_TEXT)
PL_PDF    = _build_pdf(PL_TEXT)
MIXED_PDF = _build_pdf(MIXED_TEXT)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def ok(label: str):
    print(f"  PASS  {label}")

def fail(label: str, info: str):
    print(f"  FAIL  {label}: {info}")
    sys.exit(1)

def check(condition: bool, label: str, info: str = ""):
    if condition:
        ok(label)
    else:
        fail(label, info or "assertion failed")


# ---------------------------------------------------------------------------
# T1 – BL parsing
# ---------------------------------------------------------------------------
print("\n[T1] parse_pdf_bytes – Bill of Lading")
from src.services.logistics.bl_pl_parser import parse_pdf_bytes, cross_reference

res = parse_pdf_bytes(BL_PDF)
check(res["doc_type"] == "bl", "doc_type = bl", str(res.get("doc_type")))
bl = res.get("bl", {})
check("bl_number" in bl, "bl_number extraído", str(bl))
check(len(res.get("containers", [])) >= 1, "containers detectados", str(res.get("containers")))


# ---------------------------------------------------------------------------
# T2 – PL parsing
# ---------------------------------------------------------------------------
print("\n[T2] parse_pdf_bytes – Packing List")
res = parse_pdf_bytes(PL_PDF)
check(res["doc_type"] == "pl", "doc_type = pl", str(res.get("doc_type")))
pl = res.get("pl", {})
check("total_cartons" in pl or "total_cbm" in pl, "campo PL extraído", str(pl))


# ---------------------------------------------------------------------------
# T3 – Mixed BL+PL + cross_reference
# ---------------------------------------------------------------------------
print("\n[T3] parse_pdf_bytes – Mixed + cross_reference")
res = parse_pdf_bytes(MIXED_PDF)
check(res["doc_type"] == "mixed", "doc_type = mixed", str(res.get("doc_type")))
xref = cross_reference(res.get("bl", {}), res.get("pl", {}))
check(isinstance(xref, dict), "cross_reference retorna dict")


# ---------------------------------------------------------------------------
# T4 – extract_bl_pl via m3_tools (base64)
# ---------------------------------------------------------------------------
print("\n[T4] extract_bl_pl (m3_tools) via base64_content")
from src.m3_tools import extract_bl_pl

b64 = base64.b64encode(BL_PDF).decode()
payload = json.dumps({"base64_content": b64})
out = json.loads(extract_bl_pl(payload))
check(out.get("success") is True, "success=True", str(out))
check("extracted_data" in out, "extracted_data presente")


# ---------------------------------------------------------------------------
# T5 – extract_bl_pl sem payload → erro informativo
# ---------------------------------------------------------------------------
print("\n[T5] extract_bl_pl sem file_path nem base64")
out = json.loads(extract_bl_pl("{}"))
check(out.get("success") is False, "success=False para payload vazio")
check("error" in out, "error presente")


# ---------------------------------------------------------------------------
# T6 – POST /api/tools/extract-bl-pl (multipart upload)
# ---------------------------------------------------------------------------
print("\n[T6] POST /api/tools/extract-bl-pl")
import urllib.request
import urllib.error
import requests as _requests

BOUNDARY = b"----VEC184Boundary"

def _multipart_body(filename: str, pdf_bytes: bytes) -> tuple[bytes, str]:
    body = (
        b"--" + BOUNDARY + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="' + filename.encode() + b'"\r\n'
        b"Content-Type: application/pdf\r\n\r\n"
        + pdf_bytes
        + b"\r\n--" + BOUNDARY + b"--\r\n"
    )
    ct = f"multipart/form-data; boundary={BOUNDARY.decode()}"
    return body, ct

def _get_token() -> str:
    r = _requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "marcelo.rosas@vectracargo.com.br", "password": "vectra123"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["accessToken"]

tok = _get_token()
auth_hdr = {"Authorization": f"Bearer {tok}"}

resp = _requests.post(
    f"{BASE_URL}/api/tools/extract-bl-pl",
    files={"file": ("test_bl.pdf", BL_PDF, "application/pdf")},
    headers=auth_hdr,
    timeout=10,
)
check(resp.status_code == 200, "HTTP 200", str(resp.status_code))
res = resp.json()
check(res.get("success") is True, "success=True", str(res))
check(res.get("doc_type") == "bl", "doc_type=bl via HTTP")


# ---------------------------------------------------------------------------
# T7 – POST com arquivo não-PDF → 422
# ---------------------------------------------------------------------------
print("\n[T7] POST /api/tools/extract-bl-pl com .txt → 422")
resp = _requests.post(
    f"{BASE_URL}/api/tools/extract-bl-pl",
    files={"file": ("document.txt", b"not a pdf", "text/plain")},
    headers=auth_hdr,
    timeout=10,
)
check(resp.status_code == 422, "422 para arquivo não-PDF", str(resp.status_code))

print("\n✓ Todos os testes passaram (VEC-184)\n")
