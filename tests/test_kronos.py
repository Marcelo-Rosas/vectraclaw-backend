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

import pytest  # pyright: ignore[reportMissingImports]


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
    import pandas as pd  # pyright: ignore[reportMissingImports]
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


def test_resolve_kronos_inputs_prefers_input_json_over_description():
    from src.agents.kronos import resolve_kronos_inputs

    inputs = resolve_kronos_inputs({
        "input_json": {"OFX_PATH": r"C:\ofx\abril.ofx"},
        "description": "OFX_PATH=C:\\ofx\\fallback.ofx",
    })

    assert inputs["OFX_PATH"] == r"C:\ofx\abril.ofx"


# ════════════════════════════════════════════════════════════════════════════
# VEC-XXX PR4 — _resolved_config (specialty config) tem maior precedência
# ════════════════════════════════════════════════════════════════════════════


def test_resolve_kronos_inputs_prefers_resolved_config_over_input_json():
    """specialty config (PR3 hook) > input_json > description > env."""
    from src.agents.kronos import resolve_kronos_inputs

    inputs = resolve_kronos_inputs({
        "_resolved_config": {"ofx_path": r"C:\ofx\specialty.ofx"},
        "input_json": {"OFX_PATH": r"C:\ofx\input_json.ofx"},
        "description": "OFX_PATH=C:\\ofx\\desc.ofx",
    })

    assert inputs["OFX_PATH"] == r"C:\ofx\specialty.ofx"


def test_resolve_kronos_inputs_normalizes_snake_case_from_resolved_config():
    """`agent_specialties.config_schema` usa snake_case (JSON Schema). Resolver
    deve normalizar para UPPER_SNAKE consumido internamente."""
    from src.agents.kronos import resolve_kronos_inputs

    inputs = resolve_kronos_inputs({
        "_resolved_config": {
            "ofx_path": "/data/abril.ofx",
            "recipient": "ops@vectra.com",
            "planner_instituicao": "C6",
        },
    })

    assert inputs["OFX_PATH"] == "/data/abril.ofx"
    assert inputs["RECIPIENT"] == "ops@vectra.com"
    assert inputs["PLANNER_INSTITUICAO"] == "C6"


def test_resolve_kronos_inputs_resolved_config_partial_fallback_to_input_json():
    """specialty config preenche o que tem; resto cai pro input_json/desc/env."""
    from src.agents.kronos import resolve_kronos_inputs

    inputs = resolve_kronos_inputs({
        "_resolved_config": {"ofx_path": "/data/abril.ofx"},
        "input_json": {"RECIPIENT": "ops@vectra.com"},
        "description": "PERIODO_INICIO=2026-04-01",
    })

    assert inputs["OFX_PATH"] == "/data/abril.ofx"      # specialty
    assert inputs["RECIPIENT"] == "ops@vectra.com"       # input_json
    assert inputs["PERIODO_INICIO"] == "2026-04-01"      # description


def test_resolve_kronos_inputs_resolved_config_none_value_skipped():
    """None em `_resolved_config[key]` deve cair pro próximo nível."""
    from src.agents.kronos import resolve_kronos_inputs

    inputs = resolve_kronos_inputs({
        "_resolved_config": {"ofx_path": None},
        "input_json": {"OFX_PATH": "/from-input.ofx"},
    })

    assert inputs["OFX_PATH"] == "/from-input.ofx"


def test_resolve_kronos_inputs_backcompat_no_resolved_config():
    """Tasks sem `_resolved_config` (legacy) seguem cadeia antiga sem mudança."""
    from src.agents.kronos import resolve_kronos_inputs

    inputs = resolve_kronos_inputs({
        "input_json": {"OFX_PATH": r"C:\ofx\abril.ofx"},
        "description": "RECIPIENT=fallback@x.com",
    })

    assert inputs["OFX_PATH"] == r"C:\ofx\abril.ofx"
    assert inputs["RECIPIENT"] == "fallback@x.com"
    assert "_resolved_config" not in inputs  # internal field não vaza


def test_resolve_kronos_inputs_resolved_config_ignores_unknown_keys():
    """Chaves fora de _KRONOS_INPUT_KEYS não devem virar entradas espúrias."""
    from src.agents.kronos import resolve_kronos_inputs

    inputs = resolve_kronos_inputs({
        "_resolved_config": {
            "ofx_path": "/data/x.ofx",
            "completely_unknown_field": "ignore me",
            "downloads_dir": "/downloads",  # não é _KRONOS_INPUT_KEYS
        },
    })

    assert inputs["OFX_PATH"] == "/data/x.ofx"
    assert "completely_unknown_field" not in inputs
    assert "DOWNLOADS_DIR" not in inputs


# ════════════════════════════════════════════════════════════════════════════
# PR-C (Modelo C) — _resolved_shared entre input_json e description
# ════════════════════════════════════════════════════════════════════════════


def test_resolve_kronos_inputs_resolved_shared_below_input_json():
    """input_json (override por task) tem precedência sobre shared (defaults
    do agente)."""
    from src.agents.kronos import resolve_kronos_inputs

    inputs = resolve_kronos_inputs({
        "input_json": {"OFX_PATH": "/from-input.ofx"},
        "_resolved_shared": {"ofx_path": "/from-shared.ofx"},
    })

    assert inputs["OFX_PATH"] == "/from-input.ofx"


def test_resolve_kronos_inputs_resolved_shared_above_description():
    """shared (defaults do agente) tem precedência sobre description KEY=VALUE
    (legacy). Substitui hardcoded por config editada via tab Skills."""
    from src.agents.kronos import resolve_kronos_inputs

    inputs = resolve_kronos_inputs({
        "_resolved_shared": {"recipient": "config@vectra.com"},
        "description": "RECIPIENT=hardcoded@x.com",
    })

    assert inputs["RECIPIENT"] == "config@vectra.com"


def test_resolve_kronos_inputs_full_chain_5_levels():
    """Cadeia completa: specialty > input_json > shared > description > env.

    Cada nível preenche um campo distinto pra verificar que todos os 5
    são alcançados quando os anteriores não preenchem."""
    import os
    from src.agents.kronos import resolve_kronos_inputs

    os.environ.pop("KRONOS_PERIODO_FIM", None)
    os.environ["KRONOS_PERIODO_FIM"] = "2026-04-30"
    try:
        inputs = resolve_kronos_inputs({
            "_resolved_config": {"ofx_path": "/specialty.ofx"},      # nível 1
            "input_json": {"PLANNER_INSTITUICAO": "C6"},              # nível 2
            "_resolved_shared": {"recipient": "shared@vectra.com"},   # nível 3
            "description": "PERIODO_INICIO=2026-04-01",               # nível 4
            # nível 5: env KRONOS_PERIODO_FIM
        })

        assert inputs["OFX_PATH"] == "/specialty.ofx"
        assert inputs["PLANNER_INSTITUICAO"] == "C6"
        assert inputs["RECIPIENT"] == "shared@vectra.com"
        assert inputs["PERIODO_INICIO"] == "2026-04-01"
        assert inputs["PERIODO_FIM"] == "2026-04-30"
    finally:
        os.environ.pop("KRONOS_PERIODO_FIM", None)


def test_resolve_kronos_inputs_resolved_shared_normalizes_keys():
    """shared usa snake_case (JSON Schema) → deve normalizar para UPPER_SNAKE."""
    from src.agents.kronos import resolve_kronos_inputs

    inputs = resolve_kronos_inputs({
        "_resolved_shared": {
            "ofx_path": "/data/x.ofx",
            "planner_instituicao": "Inter",
            "pdf_path": "/data/x.pdf",
            "recipient": "ops@vectra.com",
        },
    })

    assert inputs["OFX_PATH"] == "/data/x.ofx"
    assert inputs["PLANNER_INSTITUICAO"] == "Inter"
    assert inputs["PDF_PATH"] == "/data/x.pdf"
    assert inputs["RECIPIENT"] == "ops@vectra.com"


def test_resolve_kronos_inputs_resolved_shared_none_value_skipped():
    """None em _resolved_shared deve cair para description/env."""
    from src.agents.kronos import resolve_kronos_inputs

    inputs = resolve_kronos_inputs({
        "_resolved_shared": {"recipient": None},
        "description": "RECIPIENT=fallback@x.com",
    })

    assert inputs["RECIPIENT"] == "fallback@x.com"


def test_resolve_kronos_inputs_backcompat_no_resolved_shared():
    """Tasks sem _resolved_shared (legacy/sem hook) seguem cadeia 4-nível."""
    from src.agents.kronos import resolve_kronos_inputs

    inputs = resolve_kronos_inputs({
        "input_json": {"OFX_PATH": "/x.ofx"},
        "description": "RECIPIENT=fallback@x.com",
    })

    assert inputs["OFX_PATH"] == "/x.ofx"
    assert inputs["RECIPIENT"] == "fallback@x.com"
    assert "_resolved_shared" not in inputs


def test_build_kronos_input_json_reads_routine_metadata():
    from src.agents.kronos import build_kronos_input_json

    inputs = build_kronos_input_json(
        description="Conciliação mensal",
        metadata={"ofxPath": r"C:\Users\marce\OFX-C6"},
    )

    assert inputs["OFX_PATH"] == r"C:\Users\marce\OFX-C6"


def test_merge_routine_execution_params_updates_metadata():
    from src.agents.kronos import merge_routine_execution_params

    merged = merge_routine_execution_params(
        {"blueprint": "kronos_backlog"},
        {"OFX_PATH": r"C:\Users\marce\OFX-C6", "RECIPIENT": "ops@example.com"},
    )

    assert merged["blueprint"] == "kronos_backlog"
    assert merged["OFX_PATH"] == r"C:\Users\marce\OFX-C6"
    assert merged["RECIPIENT"] == "ops@example.com"


def test_extract_routine_execution_params_ignores_apply_baixa():
    from src.agents.kronos import extract_routine_execution_params

    params = extract_routine_execution_params(
        {"OFX_PATH": r"C:\ofx", "APPLY_BAIXA": "true", "blueprint": "x"},
    )

    assert params == {"OFX_PATH": r"C:\ofx"}


# ──────────────────────────────────────────────────────────────────────────────
# VEC-415: parser + selector de OFX por semana
# ──────────────────────────────────────────────────────────────────────────────


def test_parse_semana_filename_valid_2digit_year():
    from src.agents.kronos import parse_semana_filename

    assert parse_semana_filename("semana-2-maio-26.ofx") == (2026, 5, 2)


def test_parse_semana_filename_valid_4digit_year():
    from src.agents.kronos import parse_semana_filename

    assert parse_semana_filename("semana-12-março-2026.ofx") == (2026, 3, 12)


def test_parse_semana_filename_tolerates_no_accent():
    from src.agents.kronos import parse_semana_filename

    # "marco" sem cedilha
    assert parse_semana_filename("semana-3-marco-26.ofx") == (2026, 3, 3)


def test_parse_semana_filename_case_insensitive():
    from src.agents.kronos import parse_semana_filename

    assert parse_semana_filename("SEMANA-1-DEZEMBRO-25.OFX") == (2025, 12, 1)


def test_parse_semana_filename_rejects_invalid_patterns():
    from src.agents.kronos import parse_semana_filename

    cases = [
        "abril-2026.ofx",                # sem prefixo `semana-`
        "semana-1-maio-26.csv",          # extensão errada
        "semana-1-maio.ofx",             # sem ano
        "semana-mês-26.ofx",             # sem número de semana
        "semana-1-junio-26.ofx",         # espanhol, não pt-BR
        "extrato-maio.ofx",              # padrão arbitrário
    ]
    for case in cases:
        assert parse_semana_filename(case) is None, f"esperava None para {case!r}"


def test_list_ofx_files_sorted_orders_cross_month(tmp_path):
    from src.agents.kronos import list_ofx_files_sorted

    for name in [
        "semana-4-maio-26.ofx",
        "semana-1-junho-26.ofx",
        "semana-2-maio-26.ofx",
        "semana-3-maio-26.ofx",
        "semana-1-maio-26.ofx",
    ]:
        (tmp_path / name).write_text("dummy")

    names = [p.name for p in list_ofx_files_sorted(tmp_path)]
    assert names == [
        "semana-1-maio-26.ofx",
        "semana-2-maio-26.ofx",
        "semana-3-maio-26.ofx",
        "semana-4-maio-26.ofx",
        "semana-1-junho-26.ofx",
    ]


def test_list_ofx_files_sorted_puts_unmatched_at_end(tmp_path):
    from src.agents.kronos import list_ofx_files_sorted

    (tmp_path / "semana-1-maio-26.ofx").write_text("")
    (tmp_path / "semana-2-maio-26.ofx").write_text("")
    (tmp_path / "z-arquivo-arbitrario.ofx").write_text("")
    (tmp_path / "a-outro-extrato.ofx").write_text("")
    (tmp_path / "nao-e-ofx.csv").write_text("")

    names = [p.name for p in list_ofx_files_sorted(tmp_path)]
    assert names == [
        "semana-1-maio-26.ofx",
        "semana-2-maio-26.ofx",
        "a-outro-extrato.ofx",
        "z-arquivo-arbitrario.ofx",
    ]


def test_list_ofx_files_sorted_returns_empty_for_missing_dir(tmp_path):
    from src.agents.kronos import list_ofx_files_sorted

    assert list_ofx_files_sorted(tmp_path / "nao-existe") == []


def test_pick_next_ofx_file_returns_first_when_no_cursor(tmp_path):
    from src.agents.kronos import pick_next_ofx_file

    (tmp_path / "semana-2-maio-26.ofx").write_text("")
    (tmp_path / "semana-1-maio-26.ofx").write_text("")

    picked = pick_next_ofx_file(tmp_path, None)
    assert picked is not None
    assert picked.name == "semana-1-maio-26.ofx"


def test_pick_next_ofx_file_advances_from_cursor(tmp_path):
    from src.agents.kronos import pick_next_ofx_file

    for name in [
        "semana-1-maio-26.ofx",
        "semana-2-maio-26.ofx",
        "semana-3-maio-26.ofx",
        "semana-1-junho-26.ofx",
    ]:
        (tmp_path / name).write_text("")

    picked = pick_next_ofx_file(tmp_path, "semana-2-maio-26.ofx")
    assert picked is not None
    assert picked.name == "semana-3-maio-26.ofx"


def test_pick_next_ofx_file_crosses_month_boundary(tmp_path):
    from src.agents.kronos import pick_next_ofx_file

    (tmp_path / "semana-4-maio-26.ofx").write_text("")
    (tmp_path / "semana-1-junho-26.ofx").write_text("")

    picked = pick_next_ofx_file(tmp_path, "semana-4-maio-26.ofx")
    assert picked is not None
    assert picked.name == "semana-1-junho-26.ofx"


def test_pick_next_ofx_file_returns_none_when_caught_up(tmp_path):
    from src.agents.kronos import pick_next_ofx_file

    (tmp_path / "semana-1-maio-26.ofx").write_text("")
    (tmp_path / "semana-2-maio-26.ofx").write_text("")

    picked = pick_next_ofx_file(tmp_path, "semana-2-maio-26.ofx")
    assert picked is None


def test_pick_next_ofx_file_returns_none_for_empty_dir(tmp_path):
    from src.agents.kronos import pick_next_ofx_file

    assert pick_next_ofx_file(tmp_path, None) is None


# ──────────────────────────────────────────────────────────────────────────────
# VEC-415: helpers de cursor em routines.metadata
# ──────────────────────────────────────────────────────────────────────────────


def _mock_routines_select(metadata):
    """Cria mock do supabase_client com .table('routines').select(...).eq(...).limit(...).execute()."""
    mock_client = MagicMock()
    chain = mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value
    chain.execute.return_value.data = [{"metadata": metadata}]
    return mock_client


def test_get_routine_ofx_cursor_reads_metadata_field():
    from src.agents.kronos import get_routine_ofx_cursor

    client = _mock_routines_select(
        {"lastProcessedOfx": "semana-2-maio-26.ofx", "OFX_PATH": "/x"}
    )
    assert get_routine_ofx_cursor(client, "routine-id") == "semana-2-maio-26.ofx"


def test_get_routine_ofx_cursor_returns_none_when_absent():
    from src.agents.kronos import get_routine_ofx_cursor

    client = _mock_routines_select({"OFX_PATH": "/x"})
    assert get_routine_ofx_cursor(client, "routine-id") is None


def test_get_routine_ofx_cursor_returns_none_when_metadata_null():
    from src.agents.kronos import get_routine_ofx_cursor

    client = _mock_routines_select(None)
    assert get_routine_ofx_cursor(client, "routine-id") is None


def test_get_routine_ofx_cursor_raises_when_routine_missing():
    from src.agents.kronos import get_routine_ofx_cursor

    client = MagicMock()
    chain = client.table.return_value.select.return_value.eq.return_value.limit.return_value
    chain.execute.return_value.data = []
    with pytest.raises(ValueError, match="não encontrada"):
        get_routine_ofx_cursor(client, "missing-id")


def test_update_routine_ofx_cursor_preserves_other_keys():
    from src.agents.kronos import update_routine_ofx_cursor

    client = _mock_routines_select({"OFX_PATH": "/extratos", "RECIPIENT": "ops@x"})

    merged = update_routine_ofx_cursor(client, "routine-id", "semana-3-maio-26.ofx")

    assert merged["lastProcessedOfx"] == "semana-3-maio-26.ofx"
    assert merged["OFX_PATH"] == "/extratos"
    assert merged["RECIPIENT"] == "ops@x"
    update_call = client.table.return_value.update.call_args[0][0]
    assert update_call == {"metadata": merged}


def test_update_routine_ofx_cursor_rejects_empty_basename():
    from src.agents.kronos import update_routine_ofx_cursor

    client = _mock_routines_select({})
    with pytest.raises(ValueError, match="processed_basename"):
        update_routine_ofx_cursor(client, "routine-id", "   ")


def test_clear_routine_ofx_cursor_removes_field_only():
    from src.agents.kronos import clear_routine_ofx_cursor

    client = _mock_routines_select(
        {"lastProcessedOfx": "semana-1-maio-26.ofx", "OFX_PATH": "/x"}
    )

    merged = clear_routine_ofx_cursor(client, "routine-id")

    assert "lastProcessedOfx" not in merged
    assert merged["OFX_PATH"] == "/x"
    update_call = client.table.return_value.update.call_args[0][0]
    assert update_call == {"metadata": merged}


def test_clear_routine_ofx_cursor_noop_when_already_clear():
    from src.agents.kronos import clear_routine_ofx_cursor

    client = _mock_routines_select({"OFX_PATH": "/x"})
    merged = clear_routine_ofx_cursor(client, "routine-id")

    assert merged == {"OFX_PATH": "/x"}
    client.table.return_value.update.assert_not_called()
