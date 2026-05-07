"""Testes do extractor (TXT/HTML/JSON sem rede; PDF/XLSX usam fixtures geradas)."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from src.services.rag.extractor import extract_text


def _write_temp(content: str | bytes, suffix: str) -> str:
    mode = "wb" if isinstance(content, bytes) else "w"
    f = tempfile.NamedTemporaryFile(mode=mode, suffix=suffix, delete=False, encoding=None if mode == "wb" else "utf-8")
    f.write(content)
    f.close()
    return f.name


def test_extract_txt():
    path = _write_temp("linha um\nlinha dois", ".txt")
    try:
        doc = extract_text(path)
        assert doc.mime_type == "text/plain"
        assert doc.page_count == 1
        assert "linha um" in doc.full_text
        assert doc.pages[0].page_number == 1
    finally:
        os.unlink(path)


def test_extract_html_strips_tags_and_unescapes():
    html = "<html><body><h1>T&iacute;tulo</h1><script>x=1</script><p>Par&aacute;grafo &amp; texto</p></body></html>"
    path = _write_temp(html, ".html")
    try:
        doc = extract_text(path)
        assert doc.mime_type == "text/html"
        assert "Título" in doc.full_text
        assert "Parágrafo & texto" in doc.full_text
        # script content removido
        assert "x=1" not in doc.full_text
    finally:
        os.unlink(path)


def test_extract_json_pretty_prints():
    data = {"chave": "valor", "lista": [1, 2, 3]}
    path = _write_temp(json.dumps(data), ".json")
    try:
        doc = extract_text(path)
        assert doc.mime_type == "application/json"
        # Pretty-print preserva chaves e usa indent
        assert '"chave"' in doc.full_text
        assert "valor" in doc.full_text
        assert doc.full_text != json.dumps(data)  # foi reformatado
    finally:
        os.unlink(path)


def test_extract_json_invalid_falls_back_to_raw():
    path = _write_temp("not a valid json {[", ".json")
    try:
        doc = extract_text(path)
        assert "not a valid json" in doc.full_text
    finally:
        os.unlink(path)


def test_extract_unsupported_extension_raises():
    path = _write_temp("hi", ".xyz")
    try:
        with pytest.raises(ValueError, match="extensão não suportada"):
            extract_text(path)
    finally:
        os.unlink(path)


def test_extract_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        extract_text("/nope/nao/existe.txt")


def test_extract_xlsx_reads_sheets_as_pages():
    """XLSX via openpyxl: cada sheet vira página."""
    from openpyxl import Workbook
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Vendas"
    ws1.append(["Mes", "Total"])
    ws1.append(["Jan", 1000])
    ws1.append(["Fev", 1500])
    ws2 = wb.create_sheet("Custos")
    ws2.append(["Categoria", "Valor"])
    ws2.append(["Frete", 500])
    path = _write_temp(b"placeholder", ".xlsx")
    wb.save(path)
    try:
        doc = extract_text(path)
        assert "spreadsheetml" in doc.mime_type
        assert doc.page_count == 2
        # Página 1 = Vendas, Página 2 = Custos
        assert "Vendas" in doc.pages[0].content
        assert "Jan\t1000" in doc.pages[0].content
        assert "Custos" in doc.pages[1].content
        assert "Frete\t500" in doc.pages[1].content
        assert doc.metadata.get("sheet_names") == ["Vendas", "Custos"]
    finally:
        os.unlink(path)
