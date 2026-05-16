"""src.services.sipoc_diagnose_pdf — geração de PDF executivo do diagnóstico SIPOC.

Renderiza o output de POST /api/sipoc/diagnose/{sector_id} (PR9) num PDF
seguindo a identidade visual Vectra Cargo (skill vectra-pdf).

Layout simplificado pra MVP (ver SKILL.md pra spec completa):
- Header navy com título + página
- Title block com tipo + nome do setor + data
- Summary box (KPIs)
- Tabelas: status counts, gaps, candidatos, hire suggestions
- Footer com confidencial
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Any, Dict

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

logger = logging.getLogger("services.sipoc_diagnose_pdf")

# === Paleta Vectra ===
NAVY = HexColor("#1B2A4A")
ORANGE = HexColor("#E8751A")
ORANGE_LIGHT = HexColor("#FFF3E8")
DARK_TEXT = HexColor("#2D2D2D")
MEDIUM_TEXT = HexColor("#555555")
SECTION_BAR = HexColor("#3A3A3A")
TABLE_HEADER = HexColor("#E8751A")
TABLE_ALT = HexColor("#F9F9F9")
TABLE_GRID = HexColor("#DDDDDD")
RED_CONF = HexColor("#CC0000")
FOOTER_LINE = HexColor("#CCCCCC")

PAGE_W, PAGE_H = A4
MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 20 * mm, 20 * mm, 28 * mm, 22 * mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R

styles = getSampleStyleSheet()

_style_doc_type = ParagraphStyle(
    "DocType", fontSize=11, leading=14,
    textColor=ORANGE, fontName="Helvetica-Bold", spaceAfter=1 * mm,
)
_style_doc_title = ParagraphStyle(
    "DocTitle", fontSize=22, leading=26,
    textColor=DARK_TEXT, fontName="Helvetica-Bold", spaceAfter=3 * mm,
)
_style_doc_meta = ParagraphStyle(
    "DocMeta", fontSize=9, leading=12,
    textColor=MEDIUM_TEXT, fontName="Helvetica", spaceAfter=4 * mm,
)
_style_body = ParagraphStyle(
    "Body", fontSize=9.5, leading=13,
    textColor=DARK_TEXT, fontName="Helvetica", spaceAfter=3 * mm,
)
_style_section = ParagraphStyle(
    "Section", fontSize=12, leading=15,
    textColor=white, fontName="Helvetica-Bold", spaceAfter=0,
)
_style_summary = ParagraphStyle(
    "Summary", fontSize=10, leading=14,
    textColor=DARK_TEXT, fontName="Helvetica", spaceAfter=3 * mm,
)
_style_cell = ParagraphStyle(
    "Cell", fontSize=8.5, leading=11,
    textColor=DARK_TEXT, fontName="Helvetica",
)
_style_cell_white = ParagraphStyle(
    "CellWhite", parent=_style_cell, textColor=white, fontName="Helvetica-Bold",
)


def _draw_header_footer(canvas, doc, sector_name: str):
    """Header navy + footer com Confidencial em cada página."""
    canvas.saveState()
    # Header
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - 18 * mm, PAGE_W, 18 * mm, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont("Helvetica-Bold", 13)
    canvas.drawString(MARGIN_L, PAGE_H - 11 * mm, "VECTRA HUB  *  CARGO")
    canvas.setFillColor(HexColor("#AABBCC"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(MARGIN_L, PAGE_H - 14.5 * mm, f"Diagnóstico SIPOC — {sector_name[:60]}")
    canvas.setFillColor(ORANGE)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 11 * mm, f"Pag. {doc.page}")

    # Footer
    canvas.setStrokeColor(FOOTER_LINE)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN_L, 14 * mm, PAGE_W - MARGIN_R, 14 * mm)
    canvas.setFillColor(MEDIUM_TEXT)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(
        MARGIN_L, 10 * mm,
        "Vectra Cargo Transportes e Logistica  |  Navegantes / Itajai - SC  |  www.vectracargo.com.br",
    )
    canvas.setFillColor(RED_CONF)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawRightString(PAGE_W - MARGIN_R, 10 * mm, "CONFIDENCIAL")
    canvas.restoreState()


def _section_header(num: str, title: str) -> Table:
    """Section header estilo Vectra: badge laranja + barra escura."""
    badge = Table(
        [[Paragraph(f"<b>[{num}]</b>", _style_section)]],
        colWidths=[10 * mm], rowHeights=[8 * mm],
    )
    badge.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ORANGE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    bar = Table(
        [[Paragraph(title, _style_section)]],
        colWidths=[CONTENT_W - 10 * mm], rowHeights=[8 * mm],
    )
    bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SECTION_BAR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    outer = Table([[badge, bar]], colWidths=[10 * mm, CONTENT_W - 10 * mm])
    outer.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return outer


def _kpis_table(kpis: Dict[str, Any]) -> Table:
    """Tabela 2×2 com KPIs principais."""
    rows = [
        [Paragraph("<b>Total Processos</b>", _style_cell_white),
         Paragraph("<b>Total Atividades</b>", _style_cell_white)],
        [Paragraph(f"{kpis.get('totalProcesses', 0)}", _style_cell),
         Paragraph(f"{kpis.get('totalActivities', 0)}", _style_cell)],
        [Paragraph("<b>Cobertura 5W2H</b>", _style_cell_white),
         Paragraph("<b>Cobertura RACI</b>", _style_cell_white)],
        [Paragraph(f"{kpis.get('coverage5w2hPct', 0)}%", _style_cell),
         Paragraph(f"{kpis.get('responsibleCoveragePct', 0)}%", _style_cell)],
    ]
    t = Table(rows, colWidths=[CONTENT_W / 2, CONTENT_W / 2])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER),
        ("BACKGROUND", (0, 2), (-1, 2), TABLE_HEADER),
        ("BACKGROUND", (0, 1), (-1, 1), TABLE_ALT),
        ("BACKGROUND", (0, 3), (-1, 3), TABLE_ALT),
        ("GRID", (0, 0), (-1, -1), 0.5, TABLE_GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _activities_table(activities: list, caption: str) -> Table:
    """Tabela genérica de activities (nome + coverage + status + op_type)."""
    header = [
        Paragraph("<b>Atividade</b>", _style_cell_white),
        Paragraph("<b>5W2H</b>", _style_cell_white),
        Paragraph("<b>Status</b>", _style_cell_white),
        Paragraph("<b>Operation Type</b>", _style_cell_white),
    ]
    rows = [header]
    for a in activities[:20]:  # cap em 20 pra não explodir página
        rows.append([
            Paragraph(a.get("name", "")[:80], _style_cell),
            Paragraph(f"{int(a.get('coverage5w2h', 0) * 100)}%", _style_cell),
            Paragraph(a.get("automationStatus") or "—", _style_cell),
            Paragraph(a.get("suggestedOperationType") or "—", _style_cell),
        ])
    t = Table(rows, colWidths=[CONTENT_W * 0.45, CONTENT_W * 0.12, CONTENT_W * 0.18, CONTENT_W * 0.25])
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER),
        ("GRID", (0, 0), (-1, -1), 0.5, TABLE_GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.add("BACKGROUND", (0, i), (-1, i), TABLE_ALT)
    t.setStyle(style)
    return t


def _hire_table(suggestions: list) -> Table:
    """Tabela de hire suggestions."""
    header = [
        Paragraph("<b>Operation Type</b>", _style_cell_white),
        Paragraph("<b># Atividades</b>", _style_cell_white),
        Paragraph("<b>Rationale</b>", _style_cell_white),
    ]
    rows = [header]
    for s in suggestions[:10]:
        rows.append([
            Paragraph(s.get("operationType", ""), _style_cell),
            Paragraph(str(s.get("activitiesCount", 0)), _style_cell),
            Paragraph(s.get("rationale", "")[:200], _style_cell),
        ])
    t = Table(rows, colWidths=[CONTENT_W * 0.30, CONTENT_W * 0.15, CONTENT_W * 0.55])
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER),
        ("GRID", (0, 0), (-1, -1), 0.5, TABLE_GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.add("BACKGROUND", (0, i), (-1, i), TABLE_ALT)
    t.setStyle(style)
    return t


def render_diagnose_pdf(diagnose: Dict[str, Any]) -> bytes:
    """Renderiza o output do endpoint diagnose em PDF (bytes).

    `diagnose` deve seguir o shape do POST /api/sipoc/diagnose/{sector_id}.
    """
    sector = diagnose.get("sector", {})
    sector_name = sector.get("name") or "(sem nome)"
    kpis = diagnose.get("kpis", {})
    status_counts = diagnose.get("automationStatusCounts", {})
    candidates = diagnose.get("automationCandidates", [])
    gaps_5w2h = diagnose.get("gaps5w2h", [])
    gaps_resp = diagnose.get("gapsResponsible", [])
    hire = diagnose.get("hireSuggestions", [])
    warning = diagnose.get("warning")
    rationale = diagnose.get("recommendation", {}).get("rationale", "")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN_L, rightMargin=MARGIN_R,
        topMargin=MARGIN_T, bottomMargin=MARGIN_B,
        title=f"Diagnóstico SIPOC — {sector_name}",
        author="Vectra Cargo (Athena PMO)",
    )

    story = []

    # Title block
    story.append(Paragraph("DIAGNÓSTICO SIPOC — RELATÓRIO EXECUTIVO", _style_doc_type))
    story.append(Paragraph(f"Setor: {sector_name}", _style_doc_title))
    story.append(Paragraph(
        f"Data: {datetime.now().strftime('%d/%m/%Y')}  |  "
        f"Classificação: Uso Interno  |  "
        f"Gerado por: Athena PMO",
        _style_doc_meta,
    ))

    # Summary box
    summary_text = rationale or "Análise estatística agregada das atividades do setor."
    summary = Table(
        [[Paragraph(f"<b>Resumo:</b> {summary_text}", _style_summary)]],
        colWidths=[CONTENT_W],
    )
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ORANGE_LIGHT),
        ("LINEBEFORE", (0, 0), (0, -1), 3, ORANGE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(summary)
    story.append(Spacer(1, 4 * mm))

    # Warning (se houver — sector vazio)
    if warning:
        warn = Table(
            [[Paragraph(f"⚠ {warning}", _style_body)]],
            colWidths=[CONTENT_W],
        )
        warn.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#FFF8E1")),
            ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#F0A050")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(warn)
        story.append(Spacer(1, 4 * mm))

    # Section 1: KPIs
    story.append(_section_header("1", "Indicadores-chave (KPIs)"))
    story.append(Spacer(1, 3 * mm))
    story.append(_kpis_table(kpis))
    story.append(Spacer(1, 4 * mm))

    # Section 2: Status de Automação
    story.append(_section_header("2", "Status de Automação"))
    story.append(Spacer(1, 3 * mm))
    status_text = (
        f"Automated: {status_counts.get('automated', 0)}  |  "
        f"Hybrid: {status_counts.get('hybrid', 0)}  |  "
        f"Manual: {status_counts.get('manual', 0)}  |  "
        f"Undefined: {status_counts.get('undefined', 0)}"
    )
    story.append(Paragraph(status_text, _style_body))
    story.append(Spacer(1, 3 * mm))

    # Section 3: Candidatos a Automação
    story.append(_section_header("3", "Candidatos a Automação"))
    story.append(Spacer(1, 3 * mm))
    if candidates:
        story.append(_activities_table(candidates, "Candidatos"))
    else:
        story.append(Paragraph("Nenhum candidato identificado nesta análise.", _style_body))
    story.append(Spacer(1, 4 * mm))

    # Section 4: Gaps 5W2H
    story.append(_section_header("4", "Atividades com 5W2H Incompleto"))
    story.append(Spacer(1, 3 * mm))
    if gaps_5w2h:
        story.append(_activities_table(gaps_5w2h, "Gaps 5W2H"))
    else:
        story.append(Paragraph("Todas atividades têm 5W2H ≥ 50%.", _style_body))
    story.append(Spacer(1, 4 * mm))

    # Section 5: Gaps Responsável
    story.append(_section_header("5", "Atividades sem Responsável"))
    story.append(Spacer(1, 3 * mm))
    if gaps_resp:
        story.append(_activities_table(gaps_resp, "Sem Responsável"))
    else:
        story.append(Paragraph("Todas atividades têm responsável atribuído.", _style_body))
    story.append(Spacer(1, 4 * mm))

    # Section 6: Hire Suggestions
    story.append(_section_header("6", "Sugestões Athena de Contratação"))
    story.append(Spacer(1, 3 * mm))
    if hire:
        story.append(_hire_table(hire))
    else:
        story.append(Paragraph("Nenhuma sugestão de agente derivada do snapshot atual.", _style_body))

    # Build
    sector_for_header = sector_name
    def _on_each_page(canvas, doc):
        _draw_header_footer(canvas, doc, sector_for_header)

    doc.build(story, onFirstPage=_on_each_page, onLaterPages=_on_each_page)
    return buf.getvalue()
