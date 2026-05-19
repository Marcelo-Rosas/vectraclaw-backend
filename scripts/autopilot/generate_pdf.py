"""Converte Markdown → PDF estruturado usando xhtml2pdf (Python puro, sem libs C).

Uso (via Docker ephemeral conforme Regra Ouro #5):
    docker run --rm -v $PWD:/app -w /app python:3.11-slim sh -c "
      pip install xhtml2pdf markdown2 pygments -q &&
      python scripts/autopilot/generate_pdf.py <input.md> <output.pdf>
    "

Sem dependência local (não instala nada na máquina do Marcelo).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import markdown2
from xhtml2pdf import pisa


CSS = """
@page {
  size: A4;
  margin: 2cm 1.8cm 2cm 1.8cm;
  @frame footer {
    -pdf-frame-content: footer-content;
    bottom: 1cm; height: 1cm;
    left: 1.8cm; right: 1.8cm;
  }
}
body { font-family: Helvetica, Arial, sans-serif; font-size: 10pt; color: #1a1a1a; line-height: 1.45; }
h1 { font-size: 18pt; color: #0a4d8c; border-bottom: 2px solid #0a4d8c; padding-bottom: 4px; margin-top: 0; }
h2 { font-size: 13pt; color: #0a4d8c; margin-top: 18px; margin-bottom: 6px; }
h3 { font-size: 11pt; color: #333; margin-top: 12px; margin-bottom: 4px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 9pt; }
th, td { border: 1px solid #ccc; padding: 5px 7px; text-align: left; vertical-align: top; }
th { background: #f0f4f8; color: #0a4d8c; font-weight: bold; }
tr:nth-child(even) { background: #fafafa; }
code { background: #f3f3f3; padding: 1px 4px; border-radius: 3px; font-family: Courier, monospace; font-size: 9pt; }
pre { background: #f8f8f8; border-left: 3px solid #0a4d8c; padding: 8px; font-family: Courier, monospace; font-size: 8.5pt; white-space: pre-wrap; }
ul, ol { margin-top: 4px; margin-bottom: 8px; }
li { margin: 2px 0; }
.alert-red { color: #b00020; font-weight: bold; }
.alert-green { color: #1b7e3d; font-weight: bold; }
.alert-yellow { color: #c07000; }
hr { border: none; border-top: 1px solid #ddd; margin: 14px 0; }
blockquote { border-left: 3px solid #0a4d8c; padding-left: 10px; margin: 8px 0; color: #555; font-style: italic; }
"""

FOOTER_TEMPLATE = """<div id="footer-content" style="font-size:8pt;color:#888;text-align:center;">
  Gerado em {now} BRT · Autopilot VectraClaw · página <pdf:pagenumber/> de <pdf:pagecount/>
</div>"""


def md_to_pdf(md_path: str, pdf_path: str) -> bool:
    """Lê markdown, converte pra HTML estruturado, gera PDF A4."""
    md_content = Path(md_path).read_text(encoding="utf-8")
    body_html = markdown2.markdown(
        md_content,
        extras=["tables", "fenced-code-blocks", "strike", "task_list", "code-friendly"],
    )
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    footer = FOOTER_TEMPLATE.format(now=now)
    full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body>{body_html}{footer}</body></html>"""

    with open(pdf_path, "wb") as out:
        result = pisa.CreatePDF(full_html, dest=out, encoding="utf-8")

    if result.err:
        print(f"ERRO geração PDF: {result.err} erros", file=sys.stderr)
        return False
    print(f"OK: {pdf_path} ({Path(pdf_path).stat().st_size} bytes)")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: generate_pdf.py <input.md> <output.pdf>", file=sys.stderr)
        sys.exit(2)
    success = md_to_pdf(sys.argv[1], sys.argv[2])
    sys.exit(0 if success else 1)
