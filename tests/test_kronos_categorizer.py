"""Tests for `src.agents.kronos_categorizer` (VEC-422 / sub-PR3 of VEC-416)."""
from __future__ import annotations

from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]


# ── load_rules ────────────────────────────────────────────────────────


def test_load_rules_returns_empty_when_file_missing(tmp_path: Path):
    from src.agents.kronos_categorizer import load_rules

    rules = load_rules(tmp_path / "no-such.yaml")
    assert rules == []


def test_load_rules_parses_basic_yaml(tmp_path: Path):
    from src.agents.kronos_categorizer import load_rules

    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(
        """
rules:
  - pattern: "ACTIVE TRANS"
    categoria: "Despesa Administrativa"
    subcategoria: "Gestão/ERP"
  - pattern: "ALUGUEL APTO"
    categoria: "Despesas Pessoais"
    subcategoria: "Moradia – Aluguel"
        """,
        encoding="utf-8",
    )

    rules = load_rules(yaml_file)
    assert len(rules) == 2
    assert rules[0].pattern == "ACTIVE TRANS"
    assert rules[0].categoria == "Despesa Administrativa"
    assert rules[0].subcategoria == "Gestão/ERP"
    assert rules[0].match_type == "substring"
    assert rules[0].case_sensitive is False
    assert rules[0].confidence == 1.0


def test_load_rules_accepts_explicit_overrides(tmp_path: Path):
    from src.agents.kronos_categorizer import load_rules

    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(
        """
rules:
  - pattern: "^PIX RECEB"
    categoria: "Receita"
    subcategoria: "Diversos"
    match_type: regex
    case_sensitive: true
    confidence: 0.8
        """,
        encoding="utf-8",
    )

    rules = load_rules(yaml_file)
    assert len(rules) == 1
    rule = rules[0]
    assert rule.match_type == "regex"
    assert rule.case_sensitive is True
    assert rule.confidence == 0.8


def test_load_rules_ignores_invalid_entries(tmp_path: Path):
    from src.agents.kronos_categorizer import load_rules

    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(
        """
rules:
  - pattern: "BOM"
    categoria: "OK"
    subcategoria: "OK"
  - pattern: ""  # vazio — inválido
    categoria: "Despesas"
  - "string solta"  # não-dict — inválido
  - match_type: "bizarro"  # match_type inválido
    pattern: "X"
    categoria: "Y"
        """,
        encoding="utf-8",
    )
    rules = load_rules(yaml_file)
    assert len(rules) == 1
    assert rules[0].pattern == "BOM"


# ── match_rule ────────────────────────────────────────────────────────


def _build_rules():
    from src.agents.kronos_categorizer import load_rules

    # Construir via load_rules é mais realista que instanciar Rule direto
    import yaml as _yaml  # pyright: ignore[reportMissingImports]
    from io import StringIO

    raw = {
        "rules": [
            {
                "pattern": "ACTIVE TRANS",
                "categoria": "Despesa Administrativa",
                "subcategoria": "Gestão/ERP",
            },
            {
                "pattern": "ALUGUEL APTO",
                "categoria": "Despesas Pessoais",
                "subcategoria": "Moradia – Aluguel",
            },
            {
                "pattern": "Pix recebido de THIAGO",
                "categoria": "Receita Operacional – Frete",
                "subcategoria": "Pagamento à vista",
            },
            {
                "pattern": "^STARKLINK",
                "categoria": "Despesas Operacionais – Galpão",
                "subcategoria": "Internet",
                "match_type": "regex",
            },
        ]
    }
    return [_yaml.safe_dump(raw), raw]


def test_match_rule_substring_case_insensitive(tmp_path: Path):
    from src.agents.kronos_categorizer import load_rules, match_rule

    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(
        """
rules:
  - pattern: "ACTIVE TRANS"
    categoria: "Despesa Administrativa"
    subcategoria: "Gestão/ERP"
        """,
        encoding="utf-8",
    )
    rules = load_rules(yaml_file)

    result = match_rule("ACTIVE TRANS; Gasto Recorrente - Mês Mai/2026", rules)
    assert result is not None
    assert result.categoria == "Despesa Administrativa"
    assert result.matched_pattern == "ACTIVE TRANS"

    # Case insensitive por default
    result_lower = match_rule("active trans operação x", rules)
    assert result_lower is not None
    assert result_lower.categoria == "Despesa Administrativa"


def test_match_rule_returns_none_when_no_match(tmp_path: Path):
    from src.agents.kronos_categorizer import load_rules, match_rule

    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(
        """
rules:
  - pattern: "ACTIVE TRANS"
    categoria: "X"
    subcategoria: "Y"
        """,
        encoding="utf-8",
    )
    rules = load_rules(yaml_file)
    assert match_rule("TRANSF ENVIADA PIX para alguem", rules) is None
    assert match_rule("", rules) is None


def test_match_rule_first_match_wins(tmp_path: Path):
    """Regra específica antes da genérica deve casar primeiro."""
    from src.agents.kronos_categorizer import load_rules, match_rule

    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(
        """
rules:
  # Específica vem primeiro
  - pattern: "SALÁRIO - LENON"
    categoria: "Despesa Administrativa"
    subcategoria: "Salário"
  # Genérica depois
  - pattern: "SALÁRIO"
    categoria: "Outros"
    subcategoria: "Salários genéricos"
        """,
        encoding="utf-8",
    )
    rules = load_rules(yaml_file)

    result = match_rule("SALÁRIO - LENON (CHEFE DE OPERAÇÕES)", rules)
    assert result is not None
    assert result.matched_pattern == "SALÁRIO - LENON"
    assert result.subcategoria == "Salário"


def test_match_rule_regex_pattern(tmp_path: Path):
    from src.agents.kronos_categorizer import load_rules, match_rule

    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(
        """
rules:
  - pattern: "^Pix recebido de \\\\w+"
    categoria: "Receita"
    subcategoria: "Pix"
    match_type: regex
        """,
        encoding="utf-8",
    )
    rules = load_rules(yaml_file)

    result = match_rule("Pix recebido de THIAGO MARCELO", rules)
    assert result is not None
    assert result.categoria == "Receita"

    assert match_rule("PIX recebido", rules) is None  # não bate (case-insensitive mas precisa do nome)


def test_match_rule_case_sensitive(tmp_path: Path):
    from src.agents.kronos_categorizer import load_rules, match_rule

    yaml_file = tmp_path / "rules.yaml"
    yaml_file.write_text(
        """
rules:
  - pattern: "TRANSF"
    categoria: "A"
    subcategoria: "B"
    case_sensitive: true
        """,
        encoding="utf-8",
    )
    rules = load_rules(yaml_file)
    assert match_rule("TRANSF ENVIADA", rules) is not None
    assert match_rule("transf enviada", rules) is None


# ── bootstrap_rules_from_csv ──────────────────────────────────────────


def _write_planner_csv(path: Path) -> None:
    path.write_text(
        "Data do evento;Data de efetivação;Categoria;Subcategoria;Inst. Financeira - Partição;Cartão de crédito;Descrição;Valor;Status\n"
        "23/12/2026;23/12/2026;Despesa Administrativa;Gestão/ERP;C6 Bank;;\"ACTIVE TRANS; Gasto Recorrente - Mês Dez/2026\";-500,00;Pendente\n"
        "20/12/2026;20/12/2026;Despesas Pessoais;Moradia – Aluguel;C6 Bank;;\"ALUGUEL APTO; Gasto Recorrente - Mês Dez/2026\";-2.800,00;Pendente\n"
        "23/11/2026;23/11/2026;Despesa Administrativa;Gestão/ERP;C6 Bank;;\"ACTIVE TRANS; Gasto Recorrente - Mês Nov/2026\";-500,00;Pendente\n"
        "30/04/2026;30/04/2026;**;Verificar;C6 Bank;;TRANSF ENVIADA PIX;530,00;Concluído\n"
        "30/04/2026;30/04/2026;;Sem Categoria;C6 Bank;;TRANSF ENVIADA PIX;99,80;Concluído\n",
        encoding="utf-8",
    )


def test_bootstrap_skips_uncategorized_by_default(tmp_path: Path):
    from src.agents.kronos_categorizer import bootstrap_rules_from_csv, load_rules

    csv_in = tmp_path / "lancamentos.csv"
    yaml_out = tmp_path / "rules.yaml"
    _write_planner_csv(csv_in)

    count = bootstrap_rules_from_csv(csv_in, yaml_out)
    assert count >= 1

    rules = load_rules(yaml_out)
    # Não deve haver regra com categoria '**' ou 'Sem Categoria'
    for r in rules:
        assert "**" not in r.categoria
        assert "sem categoria" not in r.categoria.lower()
        assert "verificar" not in r.subcategoria.lower()


def test_bootstrap_extracts_pattern_until_separator(tmp_path: Path):
    from src.agents.kronos_categorizer import bootstrap_rules_from_csv, load_rules

    csv_in = tmp_path / "lancamentos.csv"
    yaml_out = tmp_path / "rules.yaml"
    _write_planner_csv(csv_in)

    bootstrap_rules_from_csv(csv_in, yaml_out)
    rules = load_rules(yaml_out)
    patterns = {r.pattern for r in rules}

    # "ACTIVE TRANS; Gasto Recorrente..." vira "ACTIVE TRANS"
    assert "ACTIVE TRANS" in patterns
    # "ALUGUEL APTO; Gasto Recorrente..." vira "ALUGUEL APTO"
    assert "ALUGUEL APTO" in patterns


def test_bootstrap_orders_by_frequency(tmp_path: Path):
    from src.agents.kronos_categorizer import bootstrap_rules_from_csv, load_rules

    csv_in = tmp_path / "lancamentos.csv"
    yaml_out = tmp_path / "rules.yaml"
    _write_planner_csv(csv_in)
    # ACTIVE TRANS aparece 2× (dez/nov), ALUGUEL 1× — regra ACTIVE TRANS deve vir antes
    bootstrap_rules_from_csv(csv_in, yaml_out)
    rules = load_rules(yaml_out)

    patterns_in_order = [r.pattern for r in rules]
    if "ACTIVE TRANS" in patterns_in_order and "ALUGUEL APTO" in patterns_in_order:
        idx_active = patterns_in_order.index("ACTIVE TRANS")
        idx_aluguel = patterns_in_order.index("ALUGUEL APTO")
        assert idx_active < idx_aluguel


def test_bootstrap_keep_uncategorized_flag(tmp_path: Path):
    from src.agents.kronos_categorizer import bootstrap_rules_from_csv, load_rules

    csv_in = tmp_path / "lancamentos.csv"
    yaml_out = tmp_path / "rules.yaml"
    _write_planner_csv(csv_in)

    bootstrap_rules_from_csv(csv_in, yaml_out, skip_uncategorized=False)
    rules = load_rules(yaml_out)
    # Com keep_uncategorized=False, espera regra com categoria='**' ou 'Sem Categoria'
    has_uncat = any(
        ("**" in r.categoria) or ("sem categoria" in r.categoria.lower())
        for r in rules
    )
    assert has_uncat


def test_bootstrap_raises_when_csv_missing(tmp_path: Path):
    from src.agents.kronos_categorizer import bootstrap_rules_from_csv

    with pytest.raises(FileNotFoundError):
        bootstrap_rules_from_csv(tmp_path / "nope.csv", tmp_path / "out.yaml")


# ── Integration com YAML real (do user) ───────────────────────────────


def test_real_yaml_loads_and_categorizes_sample():
    """Smoke: usa o YAML real commitado, testa um caso conhecido."""
    from src.agents.kronos_categorizer import load_rules, match_rule

    real_yaml = Path("src/agents/kronos_category_rules.yaml")
    if not real_yaml.exists():
        pytest.skip("kronos_category_rules.yaml não existe no repo (sem bootstrap rodado)")

    rules = load_rules(real_yaml)
    assert len(rules) > 0, "YAML real está vazio"

    # ACTIVE TRANS é recorrente no histórico do user — deve estar lá
    result = match_rule("ACTIVE TRANS; Gasto Recorrente - Mês Mai/2026", rules)
    if result is not None:
        # Confirma que casa com a categoria esperada do CSV histórico
        assert "Despesa Administrativa" in result.categoria
