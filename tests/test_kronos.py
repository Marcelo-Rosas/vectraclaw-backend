"""
Testes unitários do módulo Kronos (VEC-330).
Cobre: parse OFX, parse planilha, categorização, reconciliação, formatter, dispatch.
"""
import json
import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures & helpers
# ──────────────────────────────────────────────────────────────────────────────

MINIMAL_OFX = b"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1>
<SONRS><STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
<DTSERVER>20240401000000</DTSERVER>
<LANGUAGE>POR</LANGUAGE></SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1><STMTTRNRS><TRNUID>1</TRNUID>
<STMTRS>
<CURDEF>BRL</CURDEF>
<BANKACCTFROM><BANKID>336</BANKID><ACCTID>404363881</ACCTID><ACCTTYPE>CHECKING</ACCTTYPE></BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20240401000000</DTSTART><DTEND>20240430000000</DTEND>
<STMTTRN>
<TRNTYPE>DEBIT</TRNTYPE>
<DTPOSTED>20240405000000</DTPOSTED>
<TRNAMT>-500.00</TRNAMT>
<FITID>FIT001</FITID>
<MEMO>TRANSF ENVIADA PIX C6</MEMO>
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT</TRNTYPE>
<DTPOSTED>20240410000000</DTPOSTED>
<TRNAMT>2000.00</TRNAMT>
<FITID>FIT002</FITID>
<MEMO>PIX RECEBIDO frete empresa X</MEMO>
</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>5000.00</BALAMT><DTASOF>20240430000000</DTASOF></LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
"""

MINIMAL_CSV = """data,descricao,valor,tipo,categoria,subcategoria
05/04/2024,Transferencia PIX saida,500.00,debito,Transf. entre Contas - Saída,
10/04/2024,Frete empresa X,2000.00,credito,Receita Operacional – Frete,
"""


def _write_temp(content: bytes, suffix: str) -> str:
    tf = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tf.write(content)
    tf.flush()
    tf.close()
    return tf.name


# ──────────────────────────────────────────────────────────────────────────────
# parse_ofx
# ──────────────────────────────────────────────────────────────────────────────

def test_parse_ofx_minimal():
    pytest.importorskip("ofxparse")
    from src.agents.kronos import parse_ofx
    path = _write_temp(MINIMAL_OFX, ".ofx")
    try:
        txns = parse_ofx(path)
        assert len(txns) == 2
        debito = next(t for t in txns if t.trnamt < 0)
        credito = next(t for t in txns if t.trnamt > 0)
        assert debito.fitid == "FIT001"
        assert debito.trnamt == Decimal("-500.00")
        assert credito.trnamt == Decimal("2000.00")
        assert debito.dtposted == date(2024, 4, 5)
    finally:
        os.unlink(path)


# ──────────────────────────────────────────────────────────────────────────────
# parse_planner_export
# ──────────────────────────────────────────────────────────────────────────────

def test_parse_planner_csv():
    pytest.importorskip("pandas")
    from src.agents.kronos import parse_planner_export
    path = _write_temp(MINIMAL_CSV.encode(), ".csv")
    try:
        entries = parse_planner_export(path)
        assert len(entries) == 2
        debit = next(e for e in entries if e.valor == Decimal("500.00"))
        assert debit.data == date(2024, 4, 5)
        assert "Transf" in (debit.categoria or "")
    finally:
        os.unlink(path)


def test_parse_planner_xlsx():
    pytest.importorskip("pandas")
    pytest.importorskip("openpyxl")
    import pandas as pd
    from src.agents.kronos import parse_planner_export

    df = pd.DataFrame({
        "data": ["05/04/2024", "10/04/2024"],
        "descricao": ["Transferencia PIX saida", "Frete empresa X"],
        "valor": ["500,00", "2000,00"],
        "tipo": ["debito", "credito"],
        "categoria": ["Transf. entre Contas - Saída", "Receita Operacional – Frete"],
        "subcategoria": ["", ""],
    })
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tf:
        path = tf.name
    df.to_excel(path, index=False)
    try:
        entries = parse_planner_export(path)
        assert len(entries) == 2
    finally:
        os.unlink(path)


def test_parse_planner_missing_header():
    pytest.importorskip("pandas")
    from src.agents.kronos import parse_planner_export
    bad_csv = b"coluna_a,coluna_b\nfoo,bar\n"
    path = _write_temp(bad_csv, ".csv")
    try:
        with pytest.raises(ValueError, match="Colunas obrigatórias ausentes"):
            parse_planner_export(path)
    finally:
        os.unlink(path)


# ──────────────────────────────────────────────────────────────────────────────
# categorize_expense / categorize_revenue
# ──────────────────────────────────────────────────────────────────────────────

def test_categorize_expense_pix():
    from src.agents.kronos import categorize_expense
    cat, sub, conf = categorize_expense("TRANSF ENVIADA PIX C6 2024")
    assert cat == "Transferências / Movimentações Internas"
    # PIX intencionalmente com confiança baixa (0.55): C6 Bank não exporta
    # beneficiário no memo; cabe revisão humana antes de classificar definitivo.
    assert 0.4 <= conf <= 0.7


def test_categorize_expense_default_low_confidence():
    from src.agents.kronos import categorize_expense
    cat, sub, conf = categorize_expense("PAGAMENTO ALEATÓRIO XYZ")
    assert cat == "Despesas Operacionais Eventuais"
    assert conf < 0.70


def test_categorize_revenue_frete():
    from src.agents.kronos import categorize_revenue
    cat, sub, conf = categorize_revenue("PIX RECEBIDO frete cliente Vectra")
    assert "Frete" in cat
    assert conf >= 0.80


# ──────────────────────────────────────────────────────────────────────────────
# format_amount_centavos
# ──────────────────────────────────────────────────────────────────────────────

def test_format_amount_centavos():
    from src.agents.kronos import format_amount_centavos
    assert format_amount_centavos(Decimal("1234.56")) == "R$ 1.234,56"
    assert format_amount_centavos(Decimal("-500.00")) == "-R$ 500,00"
    assert format_amount_centavos(Decimal("0.01")) == "R$ 0,01"


# ──────────────────────────────────────────────────────────────────────────────
# reconcile
# ──────────────────────────────────────────────────────────────────────────────

def _make_ofx(fitid, dt, amt, memo=""):
    from src.agents.kronos import OFXTransaction
    return OFXTransaction(fitid=fitid, dtposted=dt, trnamt=Decimal(str(amt)), trntype="DEBIT" if amt < 0 else "CREDIT", memo=memo)


def _make_entry(dt, descricao, valor):
    from src.agents.kronos import PlannerEntry
    return PlannerEntry(data=dt, descricao=descricao, valor=Decimal(str(valor)), tipo="debito" if valor < 0 else "credito", categoria=None, subcategoria=None, raw_row={})


def test_reconcile_perfect_match():
    from src.agents.kronos import reconcile
    ofx = [_make_ofx("F1", date(2024, 4, 5), -500, "PIX C6")]
    planner = [_make_entry(date(2024, 4, 5), "PIX saida", 500)]
    report = reconcile(ofx, planner)
    assert report.totais["matched"] == 1
    assert report.totais["faltantes"] == 0
    assert report.totais["excedentes"] == 0


def test_reconcile_missing_in_planner():
    from src.agents.kronos import reconcile
    ofx = [_make_ofx("F1", date(2024, 4, 5), -500, "TRANSF ENVIADA PIX")]
    planner = []
    report = reconcile(ofx, planner)
    assert report.totais["matched"] == 0
    assert report.totais["faltantes"] + report.totais["ambiguos"] == 1


def test_reconcile_excess_in_planner():
    from src.agents.kronos import reconcile
    ofx = [_make_ofx("F1", date(2024, 4, 5), -500, "PIX C6")]
    planner = [
        _make_entry(date(2024, 4, 5), "PIX saida", 500),
        _make_entry(date(2024, 4, 6), "Extra entry", 100),
    ]
    report = reconcile(ofx, planner)
    assert report.totais["matched"] == 1
    assert report.totais["excedentes"] == 1


def test_reconcile_value_divergence():
    from src.agents.kronos import reconcile
    ofx = [_make_ofx("F1", date(2024, 4, 5), -500, "TRANSF ENVIADA PIX")]
    planner = [_make_entry(date(2024, 4, 5), "TRANSF ENVIADA PIX", 450)]  # valor difere
    report = reconcile(ofx, planner)
    assert report.totais["matched"] == 0
    assert report.totais["divergencias"] >= 1


def test_reconcile_date_tolerance():
    from src.agents.kronos import reconcile
    ofx = [_make_ofx("F1", date(2024, 4, 5), -500, "PIX C6")]
    planner = [_make_entry(date(2024, 4, 7), "PIX saida", 500)]  # 2 dias depois
    report = reconcile(ofx, planner, tolerance_days=2)
    assert report.totais["matched"] == 1


# ──────────────────────────────────────────────────────────────────────────────
# dispatch_to_hermes_reporter
# ──────────────────────────────────────────────────────────────────────────────

def test_dispatch_to_hermes_reporter_creates_task():
    from src.agents.kronos import dispatch_to_hermes_reporter, HERMES_REPORTER_UUID

    mock_client = MagicMock()
    mock_client.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "child-task-uuid"}
    ]

    child_id = dispatch_to_hermes_reporter(
        mock_client,
        company_id="company-123",
        kronos_task_id="kronos-task-456",
        markdown="# Relatório\n\nConteúdo.",
        recipient="marcelo.rosas@vectracargo.com.br",
        period_label="Abril 2024",
    )

    assert child_id == "child-task-uuid"
    call_args = mock_client.table.return_value.insert.call_args[0][0]
    assert call_args["operation_type"] == "oracle-report"
    assert call_args["assigned_to_agent_id"] == HERMES_REPORTER_UUID
    assert call_args["status"] == "queued"
    assert "RECIPIENT: marcelo.rosas@vectracargo.com.br" in call_args["description"]
