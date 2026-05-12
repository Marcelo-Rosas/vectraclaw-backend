"""
Kronos Categorizer — engine local de classificação de lançamentos OFX.

VEC-422 (sub-PR3 do VEC-416). Mapeia descrição → (categoria, subcategoria)
usando um rule map em YAML editável, com matching case-insensitive por
substring (ou regex opcional).

API pública:
    load_rules(yaml_path)            → list[Rule]
    match_rule(description, rules)   → MatchResult | None
    bootstrap_rules_from_csv(...)    → cria YAML inicial do CSV histórico

CLI:
    python -m src.agents.kronos_categorizer bootstrap \\
        --csv path/to/lancamentos.csv \\
        --out src/agents/kronos_category_rules.yaml

Consumido pelo PR4 (VEC-416) para categorizar via UI Playwright após import.
"""
from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

try:
    import yaml  # pyright: ignore[reportMissingImports]
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "PyYAML não instalado. Rode `pip install PyYAML>=6.0`."
    ) from exc


logger = logging.getLogger("KronosCategorizer")


# ── Dataclasses ──────────────────────────────────────────────────────


@dataclass
class Rule:
    """Regra de mapeamento descrição → (categoria, subcategoria)."""

    pattern: str
    categoria: str
    subcategoria: str
    match_type: Literal["substring", "regex"] = "substring"
    case_sensitive: bool = False
    confidence: float = 1.0
    # Compilado lazily quando match_type=regex
    _compiled_regex: Optional[re.Pattern] = field(
        default=None, init=False, repr=False, compare=False
    )

    def matches(self, description: str) -> bool:
        if not description:
            return False
        haystack = description if self.case_sensitive else description.lower()
        needle = self.pattern if self.case_sensitive else self.pattern.lower()

        if self.match_type == "regex":
            if self._compiled_regex is None:
                flags = 0 if self.case_sensitive else re.IGNORECASE
                self._compiled_regex = re.compile(self.pattern, flags)
            return self._compiled_regex.search(description) is not None

        return needle in haystack


@dataclass
class MatchResult:
    """Resultado de `match_rule` — sempre devolve a regra que casou."""

    categoria: str
    subcategoria: str
    confidence: float
    matched_pattern: str


# ── API pública ──────────────────────────────────────────────────────


def load_rules(yaml_path: Path | str) -> list[Rule]:
    """Carrega regras de um arquivo YAML.

    Formato esperado:

        rules:
          - pattern: "ACTIVE TRANS"
            categoria: "Despesa Administrativa"
            subcategoria: "Despesa Administrativa – Gestão/ERP"
            match_type: substring   # opcional, default substring
            case_sensitive: false   # opcional, default false
            confidence: 1.0         # opcional, default 1.0
    """
    path = Path(yaml_path)
    if not path.exists():
        logger.warning("YAML de regras não existe: %s — devolvendo lista vazia", path)
        return []
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    raw_rules = data.get("rules") or []
    rules: list[Rule] = []
    for idx, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            logger.warning("regra %d ignorada — não é dict: %r", idx, raw)
            continue
        try:
            rules.append(_rule_from_dict(raw))
        except Exception as exc:
            logger.warning("regra %d inválida (%s) — ignorada: %s", idx, exc, raw)
    return rules


def match_rule(
    description: str, rules: list[Rule]
) -> Optional[MatchResult]:
    """Devolve a **primeira** regra cujo `pattern` casa na descrição.

    Retorna `None` se nenhuma regra bater. Ordem do YAML define prioridade.
    """
    if not description or not rules:
        return None
    for rule in rules:
        try:
            if rule.matches(description):
                return MatchResult(
                    categoria=rule.categoria,
                    subcategoria=rule.subcategoria,
                    confidence=rule.confidence,
                    matched_pattern=rule.pattern,
                )
        except re.error as exc:
            logger.warning(
                "regex inválida no rule pattern=%r: %s — pulando regra",
                rule.pattern,
                exc,
            )
            continue
    return None


def bootstrap_rules_from_csv(
    csv_path: Path | str,
    out_yaml: Path | str,
    *,
    skip_uncategorized: bool = True,
) -> int:
    """Gera um YAML inicial agregando o CSV histórico do Meu Planner.

    Estratégia:
    1. Lê CSV (separador `;`, colunas: Descrição, Categoria, Subcategoria).
    2. Filtra linhas com `Categoria=** ` ou `"Sem Categoria"` (uncategorized).
    3. Para cada (categoria, subcategoria), pega as descrições e extrai um
       **prefixo canônico** (tudo até `;`, `-` ou `(` — primeiro separador).
    4. Conta frequência dos prefixos. Pega o mais frequente como `pattern`
       da regra. Se houver empate, fica o primeiro encontrado.
    5. Ordena por frequência decrescente (regras mais comuns primeiro).
    6. Escreve em `out_yaml`.

    Retorna o número de regras geradas.
    """
    csv_p = Path(csv_path)
    out_p = Path(out_yaml)
    if not csv_p.exists():
        raise FileNotFoundError(f"CSV de bootstrap não encontrado: {csv_p}")

    rows = _read_planner_csv(csv_p)

    # group: (categoria, subcategoria) -> Counter[pattern]
    groups: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    group_total: Counter[tuple[str, str]] = Counter()

    for row in rows:
        cat = (row.get("Categoria") or "").strip()
        sub = (row.get("Subcategoria") or "").strip()
        desc = (row.get("Descrição") or "").strip()
        if not desc or not cat:
            continue
        if skip_uncategorized and _is_uncategorized(cat):
            continue
        pattern = _extract_canonical_pattern(desc)
        if not pattern:
            continue
        groups[(cat, sub)][pattern] += 1
        group_total[(cat, sub)] += 1

    rules_dicts: list[dict[str, Any]] = []
    # Ordena (categoria, subcategoria) por frequência total desc
    for (cat, sub), _count in group_total.most_common():
        pattern_counter = groups[(cat, sub)]
        for pattern, _hits in pattern_counter.most_common():
            rules_dicts.append(
                {
                    "pattern": pattern,
                    "categoria": cat,
                    "subcategoria": sub,
                }
            )

    out_p.parent.mkdir(parents=True, exist_ok=True)
    with out_p.open("w", encoding="utf-8") as fh:
        fh.write(
            "# Kronos category rules — gerado por bootstrap_rules_from_csv.\n"
            "# Edite à vontade: ordem importa (primeiro match wins).\n"
            "# Comportamento default: match_type=substring, case_sensitive=false.\n"
            "\n"
        )
        yaml.safe_dump(
            {"rules": rules_dicts},
            fh,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )

    logger.info("bootstrap gerou %d regras em %s", len(rules_dicts), out_p)
    return len(rules_dicts)


# ── Internos ─────────────────────────────────────────────────────────


_UNCATEGORIZED_MARKERS = (
    "**",
    "sem categoria",
    "verificar",
)


def _is_uncategorized(value: str) -> bool:
    lowered = value.strip().lower()
    return any(marker in lowered for marker in _UNCATEGORIZED_MARKERS)


_SEPARATORS = re.compile(r"[;\-(]")


def _extract_canonical_pattern(description: str) -> str:
    """Extrai um prefixo canônico da descrição: tudo até o primeiro separador
    significativo (`;`, `-`, `(`). Útil pra agrupar transações que
    compartilham o mesmo identificador inicial mas variam no resto.

    Exemplos:
        "ACTIVE TRANS; Gasto Recorrente"        → "ACTIVE TRANS"
        "STARKLINK - INTERNET GALPÃO; Mês Mai"  → "STARKLINK"
        "SALÁRIO - LENON (CHEFE)"               → "SALÁRIO"
        "Pix recebido de THIAGO"                → "Pix recebido de THIAGO"
    """
    cleaned = description.strip()
    match = _SEPARATORS.search(cleaned)
    if match:
        cleaned = cleaned[: match.start()].strip()
    # Remove trailing whitespace artifacts
    return cleaned or description.strip()


def _read_planner_csv(csv_path: Path) -> list[dict[str, str]]:
    """Lê um CSV exportado pelo Meu Planner Financeiro (separador `;`)."""
    rows: list[dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for row in reader:
            rows.append({k.strip(): (v or "").strip() for k, v in row.items()})
    return rows


def _rule_from_dict(raw: dict[str, Any]) -> Rule:
    pattern = raw.get("pattern")
    if not pattern or not isinstance(pattern, str):
        raise ValueError("regra sem 'pattern' string")
    categoria = raw.get("categoria") or ""
    subcategoria = raw.get("subcategoria") or ""
    if not categoria:
        raise ValueError("regra sem 'categoria'")
    match_type = raw.get("match_type", "substring")
    if match_type not in ("substring", "regex"):
        raise ValueError(f"match_type inválido: {match_type}")
    return Rule(
        pattern=pattern,
        categoria=str(categoria),
        subcategoria=str(subcategoria),
        match_type=match_type,
        case_sensitive=bool(raw.get("case_sensitive", False)),
        confidence=float(raw.get("confidence", 1.0)),
    )


# ── CLI ───────────────────────────────────────────────────────────────


def _cli_bootstrap(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    count = bootstrap_rules_from_csv(
        csv_path=args.csv,
        out_yaml=args.out,
        skip_uncategorized=not args.keep_uncategorized,
    )
    print(f"OK: {count} regras escritas em {args.out}")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kronos_categorizer",
        description="Engine de categorização local do Kronos (VEC-422).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    bs = sub.add_parser("bootstrap", help="Gera YAML inicial do CSV histórico")
    bs.add_argument("--csv", required=True, type=Path, help="CSV exportado do Meu Planner")
    bs.add_argument("--out", required=True, type=Path, help="Caminho do YAML de saída")
    bs.add_argument(
        "--keep-uncategorized",
        action="store_true",
        help="Não filtrar linhas marcadas como 'Sem Categoria' / '**' / 'Verificar'",
    )
    bs.set_defaults(func=_cli_bootstrap)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "Rule",
    "MatchResult",
    "load_rules",
    "match_rule",
    "bootstrap_rules_from_csv",
    "main",
]
