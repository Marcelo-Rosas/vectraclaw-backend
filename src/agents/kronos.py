"""
Kronos — Auditor de Lançamentos Financeiros (modo AUDIT read-only).

Reconcilia um extrato OFX do C6 Bank contra uma planilha CSV/Excel
exportada do Meu Planner Financeiro e gera relatório de gaps.
Ao final, cria uma task derivada para HermesReporter enviar o relatório por e-mail.

Inputs via task.description:
  OFX_PATH=<caminho absoluto .ofx>
  PLANNER_PATH=<caminho absoluto .csv ou .xlsx>
  PERIODO_INICIO=YYYY-MM-DD   (opcional)
  PERIODO_FIM=YYYY-MM-DD      (opcional)
  RECIPIENT=email@ex.com      (opcional, default: marcelo.rosas@vectracargo.com.br)
"""
from __future__ import annotations

import difflib
import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("Kronos")

from src.agent_ids import HERMES_REPORTER_AGENT_ID as HERMES_REPORTER_UUID  # SSOT (alias preserva nome local)

# F5 N5: email pessoal era literal hardcoded em 3 callsites (default param +
# 2 fallbacks `.get("RECIPIENT", DEFAULT_RECIPIENT)`). Mover pra env var.
# Idealmente recipient vem de agent_specialty_configs.values.recipient (mesmo
# pattern de HermesReporter) — env é fallback dev/test.
DEFAULT_RECIPIENT = os.getenv(
    "KRONOS_DEFAULT_RECIPIENT",
    "marcelo.rosas@vectracargo.com.br",  # fallback dev
)

# ──────────────────────────────────────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class OFXTransaction:
    fitid: str
    dtposted: date
    trnamt: Decimal
    trntype: str
    memo: str


@dataclass
class PlannerEntry:
    data: date
    descricao: str
    valor: Decimal
    tipo: str
    categoria: Optional[str]
    subcategoria: Optional[str]
    raw_row: dict


@dataclass
class AuditReport:
    periodo: tuple
    faltantes: list = field(default_factory=list)     # OFX sem match no Planner
    excedentes: list = field(default_factory=list)    # Planner sem match no OFX
    divergencias: list = field(default_factory=list)  # valor difere mas desc similar
    ambiguos: list = field(default_factory=list)      # faltantes com baixa confiança
    matches: list = field(default_factory=list)       # pares Planner↔OFX confirmados → dar baixa
    totais: dict = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Parsers
# ──────────────────────────────────────────────────────────────────────────────

def parse_ofx(path: str) -> list:
    """
    Lê arquivo OFX e retorna lista de OFXTransaction.
    Pré-processa o header para corrigir variações do C6 Bank (ex: 'UTF - 8' → 'UTF-8').
    """
    import io
    import re as _re
    import ofxparse  # pyright: ignore[reportMissingImports]  # lazy import — evita custo na subida do daemon

    with open(path, "rb") as f:
        raw = f.read()

    # Corrige header SGML: remove espaços em torno do '-' no valor de ENCODING
    # Ex: "ENCODING: UTF - 8" → "ENCODING:UTF-8"
    text = raw.decode("latin-1")
    text = _re.sub(r"^(ENCODING)\s*:\s*(.+)$",
                   lambda m: f"{m.group(1)}:{m.group(2).replace(' ', '')}",
                   text, flags=_re.M)
    # Também remove espaços após ':' nos outros campos de header SGML
    text = _re.sub(r"^([A-Z]+)\s*:\s+", r"\1:", text, flags=_re.M)

    ofx = ofxparse.OfxParser.parse(io.BytesIO(text.encode("latin-1")))
    txns = []
    for account in [ofx.account]:
        if account is None:
            continue
        for t in account.statement.transactions:
            dt = t.date.date() if isinstance(t.date, datetime) else t.date
            txns.append(OFXTransaction(
                fitid=str(t.id),
                dtposted=dt,
                trnamt=Decimal(str(t.amount)),
                trntype=str(t.type).upper(),
                memo=str(t.memo or "").strip(),
            ))
    return txns


def infer_period_from_ofx_path(path: str) -> tuple[str, str]:
    """Deriva PERIODO_INICIO/FIM (YYYY-MM-DD) a partir das datas do extrato OFX."""
    txns = scan_ofx_directory(path)
    if not txns:
        raise ValueError(f"Nenhuma transação OFX em {path}")
    dates = sorted(txn.dtposted for txn in txns)
    return dates[0].isoformat(), dates[-1].isoformat()


# ── VEC-415: parser + selector de OFX por semana ─────────────────────
#
# Padrão de nome de arquivo: `semana-N-mês-AA.ofx`
#   N      → número da semana (inteiro positivo)
#   mês    → nome pt-BR (janeiro..dezembro), tolerante a `marco`/`março`
#   AA     → ano com 2 ou 4 dígitos
#
# Exemplos válidos:
#   semana-1-maio-26.ofx
#   semana-12-março-2026.ofx
#   semana-3-MARCO-26.OFX  (case-insensitive)

_PT_BR_MONTHS: dict[str, int] = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

_SEMANA_FILENAME_RE = re.compile(
    r"^semana-(\d+)-(janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|"
    r"setembro|outubro|novembro|dezembro)-(\d{2,4})\.ofx$",
    re.IGNORECASE,
)


def parse_semana_filename(name: str) -> Optional[tuple[int, int, int]]:
    """Extrai `(year, month, week)` de `semana-N-mês-AA.ofx`. Retorna `None` se
    o nome não bate no padrão (não levanta — caller decide o que fazer).

    Ano de 2 dígitos vira `2000 + N` (26 → 2026).
    """
    match = _SEMANA_FILENAME_RE.match(name.strip())
    if not match:
        return None
    week_str, month_str, year_str = match.groups()
    month = _PT_BR_MONTHS.get(month_str.lower())
    if month is None:
        return None
    year = int(year_str)
    if year < 100:
        year += 2000
    return year, month, int(week_str)


def list_ofx_files_sorted(directory: str | Path) -> list[Path]:
    """Lista todos os `.ofx` de um diretório, ordenados por `(year, month, week)`.

    Arquivos que NÃO batem no padrão `semana-N-mês-AA.ofx` vão pro fim da lista,
    em ordem alfabética. Não recursivo. Não levanta se o diretório não existe —
    devolve lista vazia.
    """
    base = Path(directory)
    if not base.is_dir():
        return []
    matched: list[tuple[tuple[int, int, int], Path]] = []
    unmatched: list[Path] = []
    for entry in base.iterdir():
        if not entry.is_file() or entry.suffix.lower() != ".ofx":
            continue
        key = parse_semana_filename(entry.name)
        if key is not None:
            matched.append((key, entry))
        else:
            unmatched.append(entry)
    matched.sort(key=lambda pair: pair[0])
    unmatched.sort(key=lambda p: p.name.lower())
    return [p for _, p in matched] + unmatched


def pick_next_ofx_file(
    directory: str | Path,
    last_processed: Optional[str],
) -> Optional[Path]:
    """Retorna o próximo `.ofx` a processar, dado o último processado.

    Regras:
    - Se `last_processed` é `None` ou vazio → devolve o primeiro arquivo da
      lista ordenada (ou `None` se diretório vazio).
    - Se `last_processed` está no padrão `semana-N-mês-AA.ofx`: devolve o
      primeiro arquivo cujo `(year, month, week)` é estritamente maior.
    - Se `last_processed` NÃO está no padrão (ou não é encontrado): fallback
      pra comparação alfabética case-insensitive — devolve o primeiro nome
      ordenado lexicograficamente maior.
    - Sem próximo → `None`.

    `last_processed` deve ser apenas o **basename** (ex: `semana-2-maio-26.ofx`),
    não o path completo.
    """
    files = list_ofx_files_sorted(directory)
    if not files:
        return None

    if not last_processed:
        return files[0]

    cursor_key = parse_semana_filename(last_processed)

    if cursor_key is not None:
        for entry in files:
            entry_key = parse_semana_filename(entry.name)
            if entry_key is not None and entry_key > cursor_key:
                return entry
        return None

    # Fallback alfabético quando o cursor não bate no padrão.
    cursor_lower = last_processed.strip().lower()
    for entry in files:
        if entry.name.lower() > cursor_lower:
            return entry
    return None


# ── VEC-415: helpers de cursor em routines.metadata ──────────────────

_OFX_CURSOR_METADATA_KEY = "lastProcessedOfx"


def get_routine_ofx_cursor(
    supabase_client: Any,
    routine_id: str,
) -> Optional[str]:
    """Lê `routines.metadata.lastProcessedOfx` de uma rotina.

    Retorna o basename do último OFX processado, ou `None` se não houver cursor.
    Levanta `ValueError` se a rotina não existe.
    """
    if not routine_id:
        raise ValueError("routine_id é obrigatório")
    if supabase_client is None:
        return None
    try:
        res = (
            supabase_client.table("routines")
            .select("metadata")
            .eq("id", routine_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # pragma: no cover — depende do supabase
        logger.warning("get_routine_ofx_cursor: query falhou: %s", exc)
        return None

    rows = getattr(res, "data", None) or []
    if not rows:
        raise ValueError(f"routine_id={routine_id} não encontrada")
    metadata = rows[0].get("metadata") if isinstance(rows[0], dict) else None
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(_OFX_CURSOR_METADATA_KEY)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def update_routine_ofx_cursor(
    supabase_client: Any,
    routine_id: str,
    processed_basename: str,
) -> dict[str, Any]:
    """Persiste `lastProcessedOfx=<basename>` em `routines.metadata`,
    preservando outros campos do metadata.

    Retorna o metadata atualizado. Levanta `ValueError` se a rotina não
    existe ou se `processed_basename` é vazio.
    """
    if not routine_id:
        raise ValueError("routine_id é obrigatório")
    basename = (processed_basename or "").strip()
    if not basename:
        raise ValueError("processed_basename não pode ser vazio")
    if supabase_client is None:
        raise ValueError("supabase_client é obrigatório")

    res = (
        supabase_client.table("routines")
        .select("metadata")
        .eq("id", routine_id)
        .limit(1)
        .execute()
    )
    rows = getattr(res, "data", None) or []
    if not rows:
        raise ValueError(f"routine_id={routine_id} não encontrada")
    current = rows[0].get("metadata") if isinstance(rows[0], dict) else None
    merged: dict[str, Any] = dict(current) if isinstance(current, dict) else {}
    merged[_OFX_CURSOR_METADATA_KEY] = basename

    supabase_client.table("routines").update({"metadata": merged}).eq(
        "id", routine_id
    ).execute()
    return merged


def clear_routine_ofx_cursor(
    supabase_client: Any,
    routine_id: str,
) -> dict[str, Any]:
    """Remove `lastProcessedOfx` do metadata. Preserva os outros campos.

    Retorna o metadata atualizado (sem o cursor). Levanta `ValueError` se a
    rotina não existe.
    """
    if not routine_id:
        raise ValueError("routine_id é obrigatório")
    if supabase_client is None:
        raise ValueError("supabase_client é obrigatório")

    res = (
        supabase_client.table("routines")
        .select("metadata")
        .eq("id", routine_id)
        .limit(1)
        .execute()
    )
    rows = getattr(res, "data", None) or []
    if not rows:
        raise ValueError(f"routine_id={routine_id} não encontrada")
    current = rows[0].get("metadata") if isinstance(rows[0], dict) else None
    merged: dict[str, Any] = dict(current) if isinstance(current, dict) else {}
    had_cursor = _OFX_CURSOR_METADATA_KEY in merged
    merged.pop(_OFX_CURSOR_METADATA_KEY, None)
    if had_cursor:
        supabase_client.table("routines").update({"metadata": merged}).eq(
            "id", routine_id
        ).execute()
    return merged


def scan_ofx_directory(
    path: str,
    inicio: str = None,
    fim: str = None,
) -> list[OFXTransaction]:
    """
    Lê um arquivo .ofx único OU todos os .ofx de um diretório.
    Filtra por período [inicio, fim] (formato YYYY-MM-DD, ambos inclusive).
    Deduplica por fitid (mantém a primeira ocorrência).
    Retorna lista ordenada por dtposted.
    """
    p = Path(path)

    # 1. Coletar transações brutas
    if p.is_file():
        raw_txns = parse_ofx(str(p))
    elif p.is_dir():
        raw_txns = []
        ofx_files = sorted(p.glob("*.ofx")) + sorted(p.glob("*.OFX"))
        for ofx_file in ofx_files:
            try:
                raw_txns.extend(parse_ofx(str(ofx_file)))
            except Exception as exc:
                logger.warning("scan_ofx_directory: erro ao parsear %s — %s", ofx_file, exc)
    else:
        raise FileNotFoundError(f"scan_ofx_directory: path não é arquivo nem diretório: {path}")

    # 2. Deduplicar por fitid (mantém primeira ocorrência)
    seen: set[str] = set()
    unique: list[OFXTransaction] = []
    for txn in raw_txns:
        if txn.fitid not in seen:
            seen.add(txn.fitid)
            unique.append(txn)

    # 3. Filtrar por período
    dt_inicio = date.fromisoformat(inicio) if inicio else None
    dt_fim = date.fromisoformat(fim) if fim else None

    if dt_inicio is not None or dt_fim is not None:
        filtered: list[OFXTransaction] = []
        for txn in unique:
            if dt_inicio is not None and txn.dtposted < dt_inicio:
                continue
            if dt_fim is not None and txn.dtposted > dt_fim:
                continue
            filtered.append(txn)
        unique = filtered

    # 4. Ordenar por dtposted
    unique.sort(key=lambda t: t.dtposted)
    return unique


def parse_planner_export(path: str) -> list:
    """
    Lê CSV ou XLSX exportado do Meu Planner Financeiro.
    Colunas esperadas (case-insensitive, sem acentos):
      data, descricao, valor, tipo, categoria, subcategoria
    """
    import pandas as pd  # pyright: ignore[reportMissingImports]  # lazy import — evita custo na subida do daemon

    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(p, dtype=str)
    else:
        # Tenta encodings comuns em exportações brasileiras
        for enc in ("utf-8-sig", "latin-1", "cp1252", "utf-8"):
            try:
                df = pd.read_csv(p, dtype=str, sep=None, engine="python", encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError(f"Não foi possível detectar encoding do arquivo: {path}")

    # Normaliza headers: remove acentos, lowercase, strip
    df.columns = [_normalize_text(c) for c in df.columns]

    # Mapeia nomes alternativos comuns nas exportações do Meu Planner
    _aliases = {
        "data": ["data", "data do evento", "data de efetivacao", "date", "dt"],
        "descricao": ["descricao", "descricao_atividade", "description", "historico", "memo"],
        "valor": ["valor", "amount", "value", "vlr"],
        "tipo": ["tipo", "type", "natureza", "status"],
        "categoria": ["categoria", "category", "cat"],
        "subcategoria": ["subcategoria", "subcategory", "subcat"],
    }
    col_map = {}
    for canonical, aliases in _aliases.items():
        for alias in aliases:
            if alias in df.columns:
                col_map[alias] = canonical
                break

    df = df.rename(columns=col_map)

    required = {"data", "descricao", "valor"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Colunas obrigatórias ausentes no arquivo do Planner: {missing}")

    entries = []
    for _, row in df.iterrows():
        raw = row.to_dict()
        try:
            dt = _parse_date(str(row.get("data", "")).strip())
            valor = _parse_valor(str(row.get("valor", "0")).strip())
            entries.append(PlannerEntry(
                data=dt,
                descricao=str(row.get("descricao", "")).strip(),
                valor=valor,
                tipo=str(row.get("tipo", "")).strip().lower(),
                categoria=str(row.get("categoria", "")).strip() or None,
                subcategoria=str(row.get("subcategoria", "")).strip() or None,
                raw_row=raw,
            ))
        except Exception as exc:
            logger.warning("Ignorando linha do Planner inválida: %s — %s", raw, exc)

    return entries


# ──────────────────────────────────────────────────────────────────────────────
# Categorização
# ──────────────────────────────────────────────────────────────────────────────
#
# Padrão de MEMO recomendado no Meu Planner (casamento máximo com OFX):
#
#   [COT-XXXX] Adiantamento Frete — Motorista João
#       → Custos Operacionais - Frete (agregado/frota terceira)
#         / Frete Agregado – Adiantamento de Frete
#
#   [COT-XXXX] Saldo Frete — NF 123 Rota SP-RJ
#       → Custos Operacionais - Frete (agregado/frota terceira)
#         / Frete Agregado – Saldo de Frete
#
#   [OP] Mão de Obra — Carregamento — Local
#       → Custos Oparacionais / Custos Operacionais - Carga e Descarga
#
#   [OP] Descarga — Cliente X — NF 456
#       → Custos Oparacionais / Custos Operacionais - Carga e Descarga
#
#   [OP] Chapas/Ajudantes — Rota SP-RJ
#       → Custos Oparacionais / Custos Operacionais - Chapas/Ajudantes
#
#   [OP] Aluguel Empilhadeira — Galpão 01/05
#       → Despesas Operacionais – Galpão / Despesas Operacionais - Aluguel de empilhadeira
#
#   [OP] Pedágio VPO — Rota SC-SP
#       → Custos Oparacionais / Custos Operacionais - Pedágios – VPO
#
# ──────────────────────────────────────────────────────────────────────────────
# Nota: "Custos Oparacionais" (com typo) é o nome exato da categoria no Planner.
# ──────────────────────────────────────────────────────────────────────────────

_EXPENSE_RULES = [
    # ── Prefixos de MEMO padronizados ─────────────────────────────────────────
    # [COT-XXXX] + Adiantamento → Frete Agregado – Adiantamento
    (re.compile(r"\[COT-.{0,20}adiant", re.I),
     "Custos Operacionais - Frete (agregado/frota terceira)",
     "Frete Agregado – Adiantamento de Frete", 0.98),
    # [COT-XXXX] + Saldo → Frete Agregado – Saldo
    (re.compile(r"\[COT-.{0,20}saldo", re.I),
     "Custos Operacionais - Frete (agregado/frota terceira)",
     "Frete Agregado – Saldo de Frete", 0.98),
    # [COT-XXXX] genérico → Pagamento à Vista
    (re.compile(r"\[COT-", re.I),
     "Custos Operacionais - Frete (agregado/frota terceira)",
     "Frete Agregado – Pagamento à Vista", 0.97),

    # [OP] + Empilhadeira/Aluguel → Galpão
    (re.compile(r"\[OP\].{0,30}(empilhadeira|aluguel.{0,10}maquin)", re.I),
     "Despesas Operacionais – Galpão",
     "Despesas Operacionais - Aluguel de empilhadeira", 0.97),
    # [OP] + Guindaste/Munck
    (re.compile(r"\[OP\].{0,30}(guindaste|munck)", re.I),
     "Despesas Operacionais – Galpão",
     "Despesas Operacionais - Locação Guindaste/Munck", 0.97),
    # [OP] + Chapas/Ajudantes
    (re.compile(r"\[OP\].{0,30}(chapas?|ajudante)", re.I),
     "Custos Oparacionais",
     "Custos Operacionais - Chapas/Ajudantes", 0.97),
    # [OP] + Carga/Descarga/Carregamento
    (re.compile(r"\[OP\].{0,30}(carga|descarga|carregamento)", re.I),
     "Custos Oparacionais",
     "Custos Operacionais - Carga e Descarga", 0.97),
    # [OP] + Pedágio
    (re.compile(r"\[OP\].{0,30}(ped.gio|vpo)", re.I),
     "Custos Oparacionais",
     "Custos Operacionais - Pedágios – VPO", 0.97),
    # [OP] genérico → Terceiros Operacionais
    (re.compile(r"\[OP\]", re.I),
     "Custos Oparacionais",
     "Custos Operacionais - Terceiros Operacionais", 0.95),

    # [REC] → despesa financeira recorrente (tarifa/seguro/assinatura)
    (re.compile(r"\[REC", re.I),
     "Despesas Financeiras",
     "Despesas Financeiras – Tarifa Bancária", 0.92),

    # ── Frete – pagamento a motorista (sem prefixo) ────────────────────────────
    (re.compile(r"adiantamento.{0,15}frete", re.I),
     "Custos Operacionais - Frete (agregado/frota terceira)",
     "Frete Agregado – Adiantamento de Frete", 0.95),
    (re.compile(r"saldo.{0,15}frete", re.I),
     "Custos Operacionais - Frete (agregado/frota terceira)",
     "Frete Agregado – Saldo de Frete", 0.95),
    (re.compile(r"COT[-\s]?\d+", re.I),
     "Custos Operacionais - Frete (agregado/frota terceira)",
     "Frete Agregado – Pagamento à Vista", 0.95),
    # CTE + número → pagamento por CT-e a transportador
    (re.compile(r"\bCTE\s+\d+", re.I),
     "Custos Operacionais - Frete (agregado/frota terceira)",
     "Frete Agregado – Pagamento à Vista", 0.85),
    # Pagamento de lote — batch de motoristas agregados
    (re.compile(r"pagamento.{0,10}lote", re.I),
     "Custos Operacionais - Frete (agregado/frota terceira)",
     "Frete Agregado – Pagamento à Vista", 0.82),
    # Saldo final do motorista (sem prefixo COT)
    (re.compile(r"saldo.{0,10}final", re.I),
     "Custos Operacionais - Frete (agregado/frota terceira)",
     "Frete Agregado – Saldo de Frete", 0.78),
    # Transportadora / Logística LTDA — frota terceirizada
    (re.compile(r"TRANSPORTES\s+LTDA|LOGISTICA\s+LTDA", re.I),
     "Custos Operacionais - Frete (agregado/frota terceira)",
     "Frete Agregado – Pagamento à Vista", 0.78),

    # Frete genérico (debit) → Frete e Transporte
    (re.compile(r"frete", re.I),
     "Custos Operacionais - Frete e Transporte",
     "Frete – Pagamento à Vista", 0.88),

    # ── Mão de obra / Carregamento / Descarga ──────────────────────────────────
    (re.compile(r"chapas?|ajudante", re.I),
     "Custos Oparacionais",
     "Custos Operacionais - Chapas/Ajudantes", 0.92),
    (re.compile(r"mao[\s\-]?de[\s\-]?obra|mão[\s\-]?de[\s\-]?obra", re.I),
     "Custos Oparacionais",
     "Custos Operacionais - Chapas/Ajudantes", 0.92),
    (re.compile(r"carregamento|descarga", re.I),
     "Custos Oparacionais",
     "Custos Operacionais - Carga e Descarga", 0.92),
    (re.compile(r"movimenta.{0,10}carga", re.I),
     "Custos Oparacionais",
     "Custos Operacionais - Carga e Descarga", 0.88),

    # ── Máquinas e aluguel ─────────────────────────────────────────────────────
    (re.compile(r"empilhadeira", re.I),
     "Despesas Operacionais – Galpão",
     "Despesas Operacionais - Aluguel de empilhadeira", 0.90),
    (re.compile(r"guindaste|munck", re.I),
     "Despesas Operacionais – Galpão",
     "Despesas Operacionais - Locação Guindaste/Munck", 0.90),
    (re.compile(r"aluguel.{0,15}maquin|locac.{0,10}maquin", re.I),
     "Despesas Operacionais Eventuais",
     "Despesa – Aluguel de empilhadeira etc", 0.88),

    # ── Pedágio / VPO ──────────────────────────────────────────────────────────
    (re.compile(r"VPO\s+\w|Pagamento\s+VPO|VPO\s+motor", re.I),
     "Custos Oparacionais",
     "Custos Operacionais - Pedágios – VPO", 0.92),
    (re.compile(r"D.?LUCI\s+TRANSPORTADORA|DLUCI", re.I),
     "Custos Operacionais - Frete (agregado/frota terceira)",
     "Frete Agregado – Pagamento à Vista", 0.95),
    (re.compile(r"ped.gio|pedagio|vpo", re.I),
     "Custos Oparacionais",
     "Custos Operacionais - Pedágios – VPO", 0.92),

    # ── Pessoas identificadas pelo nome ──────────────────────────────────────
    # Mãe do Marcelo — requer MARIA ou AUXILIADORA para não capturar o próprio Marcelo
    (re.compile(r"(?:MARIA|AUXILIADORA).{0,30}ABISSULO|ABISSULO.{0,30}(?:MARIA|AUXILIADORA)", re.I),
     "Despesas Financeiras",
     "Despesas Financeiras – Empréstimo Pessoal (Mãe)", 0.95),
    # Sogra — empréstimo pessoal
    (re.compile(r"CRISTINA.{0,20}(?:SERRAN|VIEIRA|AZEVEDO)", re.I),
     "Despesas Financeiras",
     "Despesas Financeiras – Empréstimo Pessoal (Sogra)", 0.95),
    # Cunhada — pagamento cartão pessoal
    (re.compile(r"CAROLINA.{0,20}(?:SERRAN|VIEIRA|AZEVEDO)", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Pagamento Cartão – Cunhada", 0.95),
    # Cônjuge — transferência pessoal
    (re.compile(r"CAMILLA.{0,20}(?:AZEVEDO|SERRAN|VIEIRA)", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Transferência – Cônjuge", 0.95),

    # ── Transferências / Movimentações ─────────────────────────────────────────
    # Confiança baixa: C6 Bank não exporta beneficiário no memo; revisar manualmente
    (re.compile(r"TRANSF ENVIADA PIX", re.I),
     "Transferências / Movimentações Internas",
     "PIX Enviado – Verificar beneficiário no C6 Bank", 0.55),

    # ── Despesas Pessoais ──────────────────────────────────────────────────────
    (re.compile(r"IFD[\s\*]", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Uso Pessoal", 0.92),
    (re.compile(r"SEM PARAR|TAG SEM", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Uso pessoal - TAG Sem Parar", 0.95),

    # ── Financeiras ────────────────────────────────────────────────────────────
    (re.compile(r"FUNDO DE INVESTIMENTO", re.I),
     "Despesas Financeiras",
     "Despesas Financeiras – Empréstimo", 0.88),
    (re.compile(r"\bIOF\b", re.I),
     "Despesas Financeiras",
     "Despesas Financeiras – IOF", 0.93),
    (re.compile(r"TARIFA TED|TARIFA DOC|TARIFA PIX", re.I),
     "Despesas Financeiras",
     "Despesas Financeiras – Tarifa TED/DOC/PIX", 0.93),
    (re.compile(r"TARIFA BOLETO", re.I),
     "Despesas Financeiras",
     "Despesas Financeiras – Tarifa de Boleto", 0.93),
    (re.compile(r"TARIFA", re.I),
     "Despesas Financeiras",
     "Despesas Financeiras – Tarifa Bancária", 0.88),
    (re.compile(r"JUROS.{0,20}CHEQUE|CHEQUE ESPECIAL", re.I),
     "Despesas Financeiras",
     "Despesas Financeiras – Juros (Cheque Especial)", 0.92),
    (re.compile(r"JUROS", re.I),
     "Despesas Financeiras",
     "Despesas Financeiras – Juros (Empréstimos)", 0.82),
    (re.compile(r"EMPRESTIMO|EMPRÉSTIMO|CREDITO PESSOAL|CRÉDITO PESSOAL", re.I),
     "Despesas Financeiras",
     "Despesas Financeiras – Empréstimo", 0.88),
    (re.compile(r"SEGURO.{0,20}(INCEND|OPERAC|CARGA)", re.I),
     "Custos Oparacionais",
     "Custos Operacionais – Seguros Operacionais", 0.88),
    (re.compile(r"SEGURO", re.I),
     "Despesas Financeiras",
     None, 0.80),

    # ── Tributárias / Fiscais ──────────────────────────────────────────────────
    (re.compile(r"\bANTT\b", re.I),
     "Despesas Tributárias/Fiscais/Infrações/Multas",
     "ANTT", 0.95),
    (re.compile(r"\bISS\b", re.I),
     "Despesas Tributárias/Fiscais/Infrações/Multas",
     "ISS", 0.93),
    (re.compile(r"\bICMS\b", re.I),
     "Despesas Tributárias/Fiscais/Infrações/Multas",
     "ICMS sobre serviços", 0.93),
    (re.compile(r"MULTA.{0,15}TRANS(IT|PORT)", re.I),
     "Despesas Tributárias/Fiscais/Infrações/Multas",
     "Multas – Trânsito", 0.90),
    (re.compile(r"MULTA", re.I),
     "Despesas Tributárias/Fiscais/Infrações/Multas",
     "Multa", 0.82),
    (re.compile(r"DAS\b|SIMPLES NACIONAL|PARCELAMENTO FISCAL", re.I),
     "Despesas Tributárias/Fiscais/Infrações/Multas",
     "Parcelamentos Fiscais", 0.88),
    (re.compile(r"PRO.?LABORE|PRÓ.?LABORE", re.I),
     "Distribuição de lucros",
     "Pró labore", 0.93),

    # ── Uber / App de transporte pessoal ──────────────────────────────────────
    (re.compile(r"\bUBER\b|99[\s\*]|CABIFY", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Transporte – Uber/99/Táxi", 0.85),

    # ── Streaming / Assinaturas pessoais ──────────────────────────────────────
    (re.compile(r"DISNEY|NETFLIX|SPOTIFY|AMAZON PRIME|YOUTUBE|DEEZER|GLOBOPLAY|Globo.{0,10}Premiere|HBO", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Uso Pessoal", 0.88),

    # ── Supermercado / Mercado / Conveniência ─────────────────────────────────
    (re.compile(r"FAST MARKET|SUPERMERCADO|HIPERMERCADO|MERCADO.{0,10}(LIVRE|PAGO)", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Uso Pessoal", 0.70),

    # ── Combustível / Posto ───────────────────────────────────────────────────
    (re.compile(r"POSTO|COMBUSTIV|IPIRANGA|SHELL|PETROBRAS", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Uso Pessoal", 0.70),

    # ── Café / Restaurante ────────────────────────────────────────────────────
    (re.compile(r"CAFE|CAFÉ|RESTAURANTE|LANCHONETE|PIZZARIA|DEGUSTA", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Uso Pessoal", 0.70),

    # ── Securitizadora / Antecipação de Recebíveis ────────────────────────────
    (re.compile(r"SECURITIZADORA|OFFICE MONEY", re.I),
     "Despesas Financeiras",
     "Despesas Financeiras – Antecipação de Recebíveis", 0.88),

    # ── Boleto pago (débito) ───────────────────────────────────────────────────
    (re.compile(r"^Boleto$", re.I),
     "Custos Operacionais - Frete e Transporte",
     "Frete - Pagamento via boleto", 0.65),

    # ── Gerenciamento de Risco (empresas de rastreamento/seguro cargo) ─────────
    (re.compile(r"BUONNY|ONTIME|RISCO.{0,10}CARGA|GERENC.{0,10}RISCO|RIS.?SEC", re.I),
     "Custos Oparacionais",
     "Custos Operacionais - Gerenciamento de Risco", 0.80),

    # ── Código CO seguido de dígitos (pagamento via sistema externo) ───────────
    (re.compile(r"^CO\d{6,}", re.I),
     "Custos Operacionais - Frete e Transporte",
     "Frete – Pagamento à Vista", 0.68),

    # ── Caçamba de Lixo / Entulho ─────────────────────────────────────────────
    (re.compile(r"ENTULHO|CA[CÇ]AMBA|CESCON", re.I),
     "Despesas Operacionais – Galpão",
     "Despesas Operacionais – Caçamba", 0.90),

    # ── Empréstimo Pessoal Física (PIX com CPF no memo: 11 dígitos + nome) ────
    (re.compile(r"^\d{11}-", re.I),
     "Despesas Financeiras",
     "Despesas Financeiras – Empréstimo Pessoal Física", 0.78),

    # ── Moradia Pessoal — Aluguel ─────────────────────────────────────────────
    (re.compile(r"aluguel.{0,20}(apartamento|apto|casa|resid)", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Moradia – Aluguel", 0.92),
    (re.compile(r"pagamento.{0,15}aluguel", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Moradia – Aluguel", 0.88),

    # ── Moradia Pessoal — Condomínio ──────────────────────────────────────────
    (re.compile(r"COND.{0,5}ED|CONDOMIN", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Moradia – Condomínio", 0.88),

    # ── Papelaria / Livraria pessoal ───────────────────────────────────────────
    (re.compile(r"PAPELARIA|LIVRARIA", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Uso Pessoal", 0.78),

    # ── Farmácia / Drogaria pessoal ────────────────────────────────────────────
    (re.compile(r"FARMACIA|FARMACIAS|FARMÁCIA|DROGARIA|DROGAO|ULTRAFARMA", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Uso Pessoal", 0.80),

    # ── NTC&Logística / Associação Nacional do Transporte (mensalidade) ────────
    # Regex aceita tanto "Associação" (acentuado) quanto "ASSOCIACAO" (sem acento)
    (re.compile(r"nacional.{0,20}transpo|Associa.{0,20}nacion|NTC.{0,10}LOG|NTCLOG|NTC.TEC", re.I),
     "Despesa Administrativa",
     "Despesa Administrativa – Licenças e Registros", 0.88),

    # ── Uniformes / EPI ───────────────────────────────────────────────────────
    (re.compile(r"\bUNIFORME", re.I),
     "Despesa Administrativa",
     "Despesas Administrativas – EPI's e Uniformes", 0.88),

    # ── Gás de empilhadeira (fornecedores industriais) ────────────────────────
    (re.compile(r"RESCAROLI|TRANSP.{0,5}GAS LTDA", re.I),
     "Despesas Operacionais – Galpão",
     "Despesas Operacionais – Gás (Empilhadeira)", 0.85),

    # ── Gás residencial pessoal ────────────────────────────────────────────────
    (re.compile(r"\bULTRAGAZ\b|\bSUPERGAZ\b|\bCOPAGAZ\b", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Moradia – Gás", 0.85),

    # ── Energia Elétrica (escritório / galpão) ─────────────────────────────────
    (re.compile(r"conta.{0,10}luz", re.I),
     "Despesas Operacionais – Galpão",
     "Despesas Operacionais – Energia Elétrica", 0.92),

    # ── Despesa extraordinária (reforma, piso, obra) ───────────────────────────
    (re.compile(r"despesa.{0,15}extraordin", re.I),
     "Despesas Operacionais – Galpão",
     "Despesas Operacionais – Manutenção", 0.65),

    # ── Excesso de limite bancário ─────────────────────────────────────────────
    (re.compile(r"EXCESSO.{0,5}LIMITE", re.I),
     "Despesas Financeiras",
     "Despesas Financeiras – Tarifa Bancária", 0.88),

    # ── Marmitaria / Refeição pessoal ─────────────────────────────────────────
    (re.compile(r"MARMITAR|MARMITARIA|MARMITA", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Alimentação", 0.78),

    # ── Calçados ──────────────────────────────────────────────────────────────
    (re.compile(r"\bCALCAD\b|CALCADOS", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Uso Pessoal", 0.78),

    # ── Cosméticos / Perfumaria ────────────────────────────────────────────────
    (re.compile(r"COSMETICO|COSM.TICO", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Uso Pessoal", 0.78),

    # ── Lojas de variedades / Esportivas ──────────────────────────────────────
    (re.compile(r"\bMINISO\b|\bCENTAURO\b|\bMILIUM\b", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Uso Pessoal", 0.78),

    # ── Alimentação pessoal (comércio de alimentos) ───────────────────────────
    (re.compile(r"COMERCIO.{0,10}ALIM|MERCEARIA|HORTIFRUT", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Alimentação", 0.72),

    # ── Plano de saúde pessoal ────────────────────────────────────────────────
    (re.compile(r"AmorSaude|AMORSAUDE|amor.{0,5}saude|plano.{0,10}saude", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Saúde – Plano de Saúde", 0.85),

    # ── Lazer / Entretenimento pessoal ────────────────────────────────────────
    (re.compile(r"BETO.{0,5}CARRERO", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Lazer – Lazer e Entretenimento", 0.88),

    # ── Escola dos filhos ─────────────────────────────────────────────────────
    (re.compile(r"\bSINERGIA\b", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Filhos – Mensalidade Escola", 0.85),

    # ── Alvará / Licença de Funcionamento (Município) ─────────────────────────
    (re.compile(r"\bMUNICIPIO\b|\bPREFEITURA\b", re.I),
     "Despesa Administrativa",
     "Despesa Administrativa – Licenças e Registros", 0.82),

    # ── Loja em shopping (formato código + SH CIDADE) ─────────────────────────
    (re.compile(r"\bSH\s+CAMBORIU\b|SH\s+BALNE", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Uso Pessoal", 0.72),

    # ── ZP*C 27961 — estabelecimento não identificado pelo C6 Bank ────────────
    (re.compile(r"ZP\*C\s+27961", re.I),
     "Despesas Pessoais",
     "Despesas Pessoais: Uso Pessoal", 0.65),

    # ── Active Trans — sistema de gestão/ERP de transporte ────────────────────
    (re.compile(r"ACTIVE.{0,10}TRANS", re.I),
     "Despesa Administrativa",
     "Despesa Administrativa – Gestão/ERP", 0.90),

    # ── Starlink — internet via satélite (operacional) ─────────────────────────
    (re.compile(r"STAR.?LINK", re.I),
     "Despesas Operacionais – Galpão",
     "Despesas Operacionais - Internet", 0.90),

    # ── Salário Lenon ─────────────────────────────────────────────────────────
    (re.compile(r"\bLENON\b", re.I),
     "Despesa Administrativa",
     "Despesa Administrativa – Salário", 0.88),
]

_REVENUE_RULES = [
    # IFD* crédito = estorno/chargeback de compra pessoal (iFood, marketplace)
    (re.compile(r"IFD[\s\*]", re.I),
     "Receita - Estorno de valores", "Receita – estorno de valores", 0.85),

    # CNPJ (14 dígitos + nome) → recebimento de frete de PJ
    (re.compile(r"^\d{14}-", re.I),
     "Receita Operacional – Frete", "Receita - Pagamento à vista", 0.80),

    # Adiantamento de cliente
    (re.compile(r"adiantamento.{0,15}client", re.I),
     "Receita Operacional – Frete", "Receita - Adiantamento de cliente", 0.93),
    # Saldo de cliente
    (re.compile(r"saldo.{0,15}client", re.I),
     "Receita Operacional – Frete", "Receita - Saldo de cliente", 0.93),
    # Parcelamento
    (re.compile(r"parcelamento.{0,15}frete|parcela.{0,15}frete", re.I),
     "Receita Operacional – Frete", "Receita - Parcelamento de frete", 0.90),
    # ── Pessoas identificadas pelo nome (antes do PIX RECEBIDO genérico) ─────
    # Vectra Cargo LTDA → transferência interna entre contas
    (re.compile(r"VECTRA CARGO LTDA", re.I),
     "Receita - Movimentações Internas",
     "Receita - Transferência entre C/C", 0.95),
    # Clientes identificados pelo nome
    (re.compile(r"THIAGO.{0,20}(?:GARCIA|RAGASSI|MARCELO)", re.I),
     "Receita Operacional de Frete",
     "Receita - Pagamento à vista", 0.95),
    # Próprio Marcelo transferindo de outra conta sua → entre C/C
    (re.compile(r"MARCELO.{0,15}ABISSULO", re.I),
     "Receita - Movimentações Internas",
     "Receita - Transferência entre C/C (conta própria)", 0.95),
    # Mãe do Marcelo — requer MARIA ou AUXILIADORA para não capturar o próprio Marcelo
    (re.compile(r"(?:MARIA|AUXILIADORA).{0,30}ABISSULO|ABISSULO.{0,30}(?:MARIA|AUXILIADORA)", re.I),
     "Receita - Empréstimo de PF",
     "Receita - Empréstimo (Mãe)", 0.95),
    # Sogra — empréstimo pessoal recebido
    (re.compile(r"CRISTINA.{0,20}(?:SERRAN|VIEIRA|AZEVEDO)", re.I),
     "Receita - Empréstimo de PF",
     "Receita - Empréstimo (Sogra)", 0.95),
    # Cunhada — reembolso de cartão pessoal
    (re.compile(r"CAROLINA.{0,20}(?:SERRAN|VIEIRA|AZEVEDO)", re.I),
     "Receita - Movimentações Internas",
     "Receita - Reembolso (Cunhada)", 0.95),
    # Cônjuge — transferência pessoal recebida
    (re.compile(r"CAMILLA.{0,20}(?:AZEVEDO|SERRAN|VIEIRA)", re.I),
     "Receita - Movimentações Internas",
     "Receita - Transferência Pessoal (Cônjuge)", 0.95),

    # Frete / PIX recebido (genérico)
    (re.compile(r"frete|PIX RECEBIDO", re.I),
     "Receita Operacional – Frete", "Receita - Pagamento à vista", 0.88),
    # Galpão / armazenagem
    (re.compile(r"galpao|galpão|armazena|cross.?dock|paletiz|estadia.{0,10}carga", re.I),
     "Receita Operacional - Galpão", "Receita - Serviços de apoio logístico no galpão", 0.88),
    # CTE / CT-e
    (re.compile(r"\bCT.?E\b|emissao.{0,15}document", re.I),
     "Receita - Serviço terceirizado", "Receita – Emissão De Documentação/CTE", 0.90),
    # Cartão de crédito
    (re.compile(r"cartao.{0,10}cred|cartão.{0,10}créd", re.I),
     "Receita - Recebimento Cartão de Crédito", "Receita - Cartão de Crédito", 0.92),
    # Estorno
    (re.compile(r"estorno", re.I),
     "Receita - Estorno de valores", "Receita – estorno de valores", 0.92),
    # Transferência interna
    (re.compile(r"TRANSF.{0,10}RECEBIDA|transferencia.{0,10}interna|VECTRA HUB|VECTRA CARGO", re.I),
     "Receita - Movimentações Internas", "Receita - Transferência entre C/C", 0.88),
    # PIX QR code recebido (cliente paga via QR)
    (re.compile(r"PIX QR CODE RECEBIDO|PIX.*QR.*RECEBIDO", re.I),
     "Receita Operacional – Frete", "Receita - Pagamento à vista", 0.80),
    # PIX recebido genérico (sem "frete" no memo)
    (re.compile(r"PIX.{0,20}RECEBIDO|RECEBIDO.{0,20}PIX", re.I),
     "Receita Operacional – Frete", "Receita - Pagamento à vista", 0.75),
    # Boleto recebido / cobrança de título
    (re.compile(r"Vlr\.Ref\.Cobr|cobr.{0,15}tit|receb.{0,10}boleto", re.I),
     "Receita Operacional – Frete", "Receita - Pagamento via boleto", 0.78),
    # Contestação / estorno recebido (estorn cobre estorno + estornado)
    (re.compile(r"contestac|contestaç|credito.{0,15}definitivo|estorn|devol.{0,10}recebida|devol.{0,10}pix", re.I),
     "Receita - Estorno de valores", "Receita – estorno de valores", 0.85),

    # CPF (11 dígitos + nome) → Empréstimo Pessoal Física recebido
    (re.compile(r"^\d{11}-", re.I),
     "Receita - Empréstimo de PF", "Receita - Empréstimo", 0.80),

    # VPO – Reembolso via conta IPEF (Lei 10.209/2001): shipper reimbursa pedágio + 2,5%
    (re.compile(r"IPEF|VALE.{0,5}PEDAGIO|VPO.{0,15}RECEBIDO|RECEBID.{0,10}VPO", re.I),
     "Receita Operacional – VPO",
     "VPO – Reembolso de Pedágio (shipper → Vectra)", 0.93),
]


def load_rules_from_db(client) -> dict:
    """
    Carrega regras de categorização da tabela vectraclip.kronos_rules.
    Retorna {'expense': [...], 'revenue': [...]} com tuples (compiled_re, cat, sub, conf).
    Em caso de falha retorna as regras hardcoded como fallback.
    """
    try:
        # Tenta com o client recebido (normalmente já está na schema vectraclip via ClientOptions).
        # Se falhar com PGRST205 (tabela não encontrada), recria o client com schema explícito.
        def _query(c):
            return (
                c.table("kronos_rules")
                .select("type,pattern,category,subcategory,confidence")
                .eq("is_active", True)
                .order("priority")
                .execute()
                .data
            )
        try:
            rows = _query(client)
        except Exception as first_err:
            if "PGRST205" in str(first_err) or "schema cache" in str(first_err).lower():
                import os
                from supabase import create_client, ClientOptions
                schema = os.getenv("SUPABASE_SCHEMA", "vectraclip")
                _c = create_client(
                    os.environ["SUPABASE_URL"],
                    os.environ.get("SUPABASE_SERVICE_ROLE_KEY", os.environ.get("SUPABASE_KEY", "")),
                    options=ClientOptions(schema=schema, persist_session=False),
                )
                rows = _query(_c)
            else:
                raise
        expense, revenue = [], []
        for row in rows:
            compiled = (
                re.compile(row["pattern"], re.I | re.UNICODE),
                row["category"],
                row["subcategory"],
                float(row["confidence"]),
            )
            (expense if row["type"] == "expense" else revenue).append(compiled)
        if not expense and not revenue:
            raise ValueError("DB retornou 0 regras — usando fallback")
        logger.info("Kronos: carregadas %d expense + %d revenue rules do DB",
                    len(expense), len(revenue))
        return {"expense": expense, "revenue": revenue}
    except Exception as exc:
        logger.warning("load_rules_from_db falhou (%s) — usando regras hardcoded", exc)
        return {"expense": _EXPENSE_RULES, "revenue": _REVENUE_RULES}


def categorize_expense(memo: str, rules: list = None) -> tuple:
    """Retorna (categoria, subcategoria|None, confidence). Usa regras do DB se fornecidas."""
    for pattern, cat, sub, conf in (rules if rules is not None else _EXPENSE_RULES):
        if pattern.search(memo):
            return cat, sub, conf
    return "Despesas Operacionais Eventuais", None, 0.50


def categorize_revenue(memo: str, rules: list = None) -> tuple:
    """Retorna (categoria, subcategoria|None, confidence). Usa regras do DB se fornecidas."""
    for pattern, cat, sub, conf in (rules if rules is not None else _REVENUE_RULES):
        if pattern.search(memo):
            return cat, sub, conf
    return "** (humano define)", None, 0.30


def format_amount_centavos(amount: Decimal) -> str:
    """Formata Decimal como moeda BRL. Ex: Decimal('1234.56') → 'R$ 1.234,56'."""
    cents = int(round(abs(amount) * 100))
    reais = cents // 100
    centavos = cents % 100
    reais_fmt = f"{reais:,}".replace(",", ".")
    signal = "-" if amount < 0 else ""
    return f"{signal}R$ {reais_fmt},{centavos:02d}"


# ──────────────────────────────────────────────────────────────────────────────
# Reconciler
# ──────────────────────────────────────────────────────────────────────────────

def reconcile(ofx: list, planner: list, tolerance_days: int = 2,
              db_rules: dict = None) -> AuditReport:
    """
    Cruza transações OFX com entradas do Planner.

    Matching: data±tolerance, valor absoluto idêntico.
    Divergências: desc similar (≥0.8) mas valor difere.
    db_rules: {'expense': [...], 'revenue': [...]} de load_rules_from_db(); None = hardcoded.
    """
    exp_rules = db_rules["expense"] if db_rules else None
    rev_rules = db_rules["revenue"] if db_rules else None
    # Filtra período disponível
    if ofx:
        p_start = min(t.dtposted for t in ofx)
        p_end   = max(t.dtposted for t in ofx)
    else:
        p_start = p_end = date.today()

    report = AuditReport(periodo=(p_start, p_end))

    matched_ofx: set = set()
    matched_planner: set = set()

    for i, txn in enumerate(ofx):
        for j, entry in enumerate(planner):
            if j in matched_planner:
                continue
            date_diff = abs((txn.dtposted - entry.data).days)
            if date_diff > tolerance_days:
                continue
            if abs(abs(txn.trnamt) - abs(entry.valor)) < Decimal("0.01"):
                matched_ofx.add(i)
                matched_planner.add(j)
                report.matches.append({
                    "planner_descricao": entry.descricao,
                    "planner_data": entry.data.isoformat(),
                    "planner_valor": str(entry.valor),
                    "planner_valor_fmt": format_amount_centavos(entry.valor),
                    "ofx_memo": txn.memo,
                    "ofx_data": txn.dtposted.isoformat(),
                })
                break

    # Faltantes: no OFX mas não no Planner
    for i, txn in enumerate(ofx):
        if i in matched_ofx:
            continue
        is_debit = txn.trnamt < 0
        if is_debit:
            cat, sub, conf = categorize_expense(txn.memo, exp_rules)
        else:
            cat, sub, conf = categorize_revenue(txn.memo, rev_rules)

        item = {
            "fitid": txn.fitid,
            "data": txn.dtposted.isoformat(),
            "valor": str(txn.trnamt),
            "valor_fmt": format_amount_centavos(txn.trnamt),
            "memo": txn.memo,
            "tipo": "debito" if is_debit else "credito",
            "categoria_sugerida": cat,
            "subcategoria_sugerida": sub,
            "confidence": conf,
        }

        if conf < 0.60:
            report.ambiguos.append(item)
        else:
            report.faltantes.append(item)

    # Excedentes: no Planner mas não no OFX
    # Usa janela alargada (±tolerance) para não perder entradas ao redor das bordas
    p_start_w = p_start - timedelta(days=tolerance_days)
    p_end_w   = p_end   + timedelta(days=tolerance_days)
    for j, entry in enumerate(planner):
        if j in matched_planner:
            continue
        if not (p_start_w <= entry.data <= p_end_w):
            continue  # fora do período OFX (com tolerância) — ignora
        report.excedentes.append({
            "data": entry.data.isoformat(),
            "descricao": entry.descricao,
            "valor": str(entry.valor),
            "valor_fmt": format_amount_centavos(entry.valor),
            "tipo": entry.tipo,
            "categoria": entry.categoria,
        })

    # Divergências: desc similar mas valor difere (entre não-matchados)
    unmatched_ofx = [ofx[i] for i in range(len(ofx)) if i not in matched_ofx]
    unmatched_pl  = [planner[j] for j in range(len(planner)) if j not in matched_planner]

    for txn in unmatched_ofx:
        for entry in unmatched_pl:
            date_diff = abs((txn.dtposted - entry.data).days)
            if date_diff > tolerance_days:
                continue
            sim = difflib.SequenceMatcher(
                None,
                _normalize_text(txn.memo),
                _normalize_text(entry.descricao),
            ).ratio()
            if sim >= 0.8:
                report.divergencias.append({
                    "data_ofx": txn.dtposted.isoformat(),
                    "memo_ofx": txn.memo,
                    "valor_ofx": str(txn.trnamt),
                    "valor_ofx_fmt": format_amount_centavos(txn.trnamt),
                    "data_planner": entry.data.isoformat(),
                    "descricao_planner": entry.descricao,
                    "valor_planner": str(entry.valor),
                    "valor_planner_fmt": format_amount_centavos(entry.valor),
                    "similaridade": round(sim, 3),
                })
                break

    # Totais
    report.totais = {
        "periodo_inicio": p_start.isoformat(),
        "periodo_fim": p_end.isoformat(),
        "total_ofx": len(ofx),
        "total_planner_no_periodo": len([e for e in planner if p_start <= e.data <= p_end]),
        "matched": len(report.matches),
        "faltantes": len(report.faltantes),
        "excedentes": len(report.excedentes),
        "divergencias": len(report.divergencias),
        "ambiguos": len(report.ambiguos),
    }

    return report


# ──────────────────────────────────────────────────────────────────────────────
# Formatter
# ──────────────────────────────────────────────────────────────────────────────

def format_report_markdown(report: AuditReport) -> str:
    lines = [
        "# Relatório de Auditoria OFX × Meu Planner Financeiro",
        "",
        f"**Período analisado:** {report.totais.get('periodo_inicio')} a {report.totais.get('periodo_fim')}",
        "",
        "## Resumo",
        "",
        "| Item | Qtd |",
        "|------|-----|",
        f"| Transações OFX | {report.totais.get('total_ofx', 0)} |",
        f"| Lançamentos Planner (período) | {report.totais.get('total_planner_no_periodo', 0)} |",
        f"| Matchados | {report.totais.get('matched', 0)} |",
        f"| **Faltando no Planner** | **{report.totais.get('faltantes', 0)}** |",
        f"| Lançamentos Manuais (Contas Recorrentes) | {report.totais.get('excedentes', 0)} |",
        f"| Divergências de valor | {report.totais.get('divergencias', 0)} |",
        f"| Ambíguos (baixa confiança) | {report.totais.get('ambiguos', 0)} |",
        "",
    ]

    if report.faltantes:
        lines += [
            "## Faltando no Meu Planner (lançar)",
            "",
            "| Data | Memo OFX | Valor | Categoria Sugerida | Sub |",
            "|------|----------|-------|--------------------|-----|",
        ]
        for item in report.faltantes:
            cat = item.get("categoria_sugerida", "")
            sub = item.get("subcategoria_sugerida") or "—"
            lines.append(
                f"| {item['data']} | {item['memo']} | {item['valor_fmt']} | {cat} | {sub} |"
            )
        lines.append("")

    if report.ambiguos:
        lines += [
            "## Ambíguos — Categoria Incerta (verificar manualmente)",
            "",
            "| Data | Memo OFX | Valor | Categoria Tentativa | Nota |",
            "|------|----------|-------|---------------------|------|",
        ]
        for item in report.ambiguos:
            sub = item.get("subcategoria_sugerida") or "—"
            lines.append(
                f"| {item['data']} | {item['memo']} | {item['valor_fmt']} | {item.get('categoria_sugerida', '?')} | {sub} |"
            )
        lines.append("")

    if report.divergencias:
        lines += [
            "## Divergências de Valor",
            "",
            "| Data OFX | Memo OFX | Valor OFX | Valor Planner | Similaridade |",
            "|----------|----------|-----------|---------------|--------------|",
        ]
        for item in report.divergencias:
            lines.append(
                f"| {item['data_ofx']} | {item['memo_ofx']} | {item['valor_ofx_fmt']} "
                f"| {item['valor_planner_fmt']} | {item['similaridade']:.0%} |"
            )
        lines.append("")

    if report.excedentes:
        lines += [
            "## Lançamentos Manuais — Contas Recorrentes",
            "",
            "> Estes lançamentos existem no Planner mas não têm correspondência no OFX.",
            "> São tratados como **entradas manuais de contas recorrentes** — não requerem ação.",
            "",
            "| Data | Descrição | Valor | Categoria |",
            "|------|-----------|-------|-----------|",
        ]
        for item in report.excedentes:
            lines.append(
                f"| {item['data']} | {item['descricao']} | {item['valor_fmt']} | {item.get('categoria') or '—'} |"
            )
        lines.append("")

    if not any([report.faltantes, report.ambiguos, report.divergencias, report.excedentes]):
        lines.append("✅ **Nenhuma divergência encontrada — extratos em dia!**\n")

    lines.append("---")
    lines.append("*Gerado automaticamente por Kronos (VectraClaw VEC-330)*")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Dispatch
# ──────────────────────────────────────────────────────────────────────────────

def dispatch_to_hermes_reporter(
    client: Any,
    company_id: str,
    kronos_task_id: str,
    markdown: str,
    recipient: str = DEFAULT_RECIPIENT,
    period_label: str = "",
) -> str:
    """Materializa workflow global `kronos-hermes-handoff` (VEC-334). Retorna ID da subtask oracle-report."""
    try:
        from src.models import TaskBlueprint
        from src.services.task_factory import TaskFactory, TaskFactoryError

        cid = company_id or ""
        factory = TaskFactory(client)
        bp = TaskBlueprint(
            title=f"Audit Kronos {period_label} — enviar para {recipient}".strip(),
            description=(
                f"RECIPIENT: {recipient}\n"
                f"SUBJECT: Audit OFX vs Planner — {period_label}\n"
                f"PARENT_TASK_ID: {kronos_task_id}\n\n"
                f"---\n\n"
                f"{markdown}"
            ),
            budget_limit=0,
        )
        mw = factory.materialize_workflow(
            cid,
            "kronos-hermes-handoff",
            bp,
            step_inputs={
                "hermes-report": {
                    "recipient": recipient,
                    "period_label": period_label,
                    "parent_kronos_task_id": kronos_task_id,
                    "markdown": markdown,
                }
            },
        )
        child_id = mw.subtasks[0].id if mw.subtasks else ""
        if child_id:
            logger.info("Kronos: Hermes task via TaskFactory — id=%s", child_id)
        return child_id
    except Exception as exc:
        logger.warning("Kronos TaskFactory failed, fallback insert: %s", exc)
    payload: dict = {
        "title": f"Audit Kronos {period_label} — enviar para {recipient}".strip(),
        "description": (
            f"RECIPIENT: {recipient}\n"
            f"SUBJECT: Audit OFX vs Planner — {period_label}\n"
            f"PARENT_TASK_ID: {kronos_task_id}\n\n"
            f"---\n\n"
            f"{markdown}"
        ),
        "operation_type": "oracle-report",
        "assigned_to_agent_id": HERMES_REPORTER_UUID,
        "status": "queued",
    }
    if company_id:
        payload["company_id"] = company_id
    res = client.table("tasks").insert(payload).execute()

    if res.data:
        child_id = res.data[0].get("id", "")
        logger.info("Kronos: task derivada criada para HermesReporter — id=%s", child_id)
        return child_id
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────────

def _parse_env_line(desc: str, key: str, default: str = "") -> str:
    """Extrai valor de linha KEY=valor na descrição da task."""
    m = re.search(rf"^{key}=(.+)$", desc, re.M)
    return m.group(1).strip() if m else default


_KRONOS_INPUT_KEYS = (
    "OFX_PATH",
    "PLANNER_PATH",
    "PERIODO_INICIO",
    "PERIODO_FIM",
    "RECIPIENT",
    "APPLY_BAIXA",
    # VEC-419: consumido pelo entrypoint_planner_import pra selecionar a
    # Instituição Financeira no combobox do Meu Planner Financeiro.
    # Default = primeira opção real do combobox (single-conta).
    "PLANNER_INSTITUICAO",
    # VEC-425: caminho do PDF do extrato bancário (mesma janela do OFX)
    # — usado pelo kronos_pdf_enricher pra enriquecer descrição genérica
    # 'TRANSF ENVIADA PIX' com nome do destinatário do PDF.
    "PDF_PATH",
)

# Parâmetros persistidos na rotina (template); APPLY_BAIXA fica só na task.
KRONOS_ROUTINE_PARAM_KEYS = tuple(
    key for key in _KRONOS_INPUT_KEYS if key != "APPLY_BAIXA"
)


def _normalize_kronos_input_key(key: str) -> str:
    raw = str(key).strip()
    if raw in _KRONOS_INPUT_KEYS:
        return raw
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", raw).upper().replace("-", "_")
    return snake if snake in _KRONOS_INPUT_KEYS else raw.upper()


def resolve_kronos_inputs(task: dict) -> dict[str, str]:
    """Resolve parâmetros Kronos com cadeia de precedência.

    Cadeia completa (PR4 + PR-C Modelo C), maior → menor precedência:

        1. task["_resolved_config"]     (specialty config, snake_case)
        2. task.input_json              (override por task)
        3. task["_resolved_shared"]     (agent_shared_config.values — PR-C)
        4. task.description KEY=VALUE   (formato legacy)
        5. env vars                     (default global)

    `_resolved_*` são populados pelo hook `agent_daemon._populate_resolved_specialty`.
    Tasks sem hook executado (testes, dispatchs manuais) caem direto pra
    input_json/description/env — backcompat 100%.
    """
    resolved: dict[str, str] = {}

    # 1. specialty config (PR4)
    resolved_config = task.get("_resolved_config") or {}
    if isinstance(resolved_config, dict):
        for key, value in resolved_config.items():
            if value is None:
                continue
            normalized = _normalize_kronos_input_key(key)
            if normalized in _KRONOS_INPUT_KEYS:
                resolved[normalized] = str(value).strip()

    # 2. input_json
    input_json = task.get("input_json") or {}
    if isinstance(input_json, dict):
        for key, value in input_json.items():
            if value is None:
                continue
            normalized = _normalize_kronos_input_key(key)
            if normalized in _KRONOS_INPUT_KEYS and not resolved.get(normalized):
                resolved[normalized] = str(value).strip()

    # 3. agent_shared_config.values (PR-C)
    shared = task.get("_resolved_shared") or {}
    if isinstance(shared, dict):
        for key, value in shared.items():
            if value is None:
                continue
            normalized = _normalize_kronos_input_key(key)
            if normalized in _KRONOS_INPUT_KEYS and not resolved.get(normalized):
                resolved[normalized] = str(value).strip()

    # 4. description KEY=VALUE
    desc = task.get("description", "") or ""
    for key in _KRONOS_INPUT_KEYS:
        if not resolved.get(key):
            value = _parse_env_line(desc, key)
            if value:
                resolved[key] = value

    # 5. env vars
    for key in _KRONOS_INPUT_KEYS:
        if not resolved.get(key):
            env_value = os.getenv(f"KRONOS_{key}") or (
                os.getenv(key) if key in ("OFX_PATH", "PLANNER_PATH") else ""
            )
            if env_value:
                resolved[key] = env_value.strip()

    return resolved


def extract_routine_execution_params(metadata: Optional[dict[str, Any]]) -> dict[str, str]:
    """Extrai parâmetros Kronos persistidos em routines.metadata."""
    if not isinstance(metadata, dict):
        return {}
    params: dict[str, str] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        normalized = _normalize_kronos_input_key(key)
        if normalized in KRONOS_ROUTINE_PARAM_KEYS:
            params[normalized] = str(value).strip()
    return params


def merge_routine_execution_params(
    metadata: Optional[dict[str, Any]],
    execution_params: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Mescla executionParams do editor de rotina em routines.metadata."""
    merged: dict[str, Any] = dict(metadata) if isinstance(metadata, dict) else {}
    if not isinstance(execution_params, dict):
        return merged
    for key, value in execution_params.items():
        normalized = _normalize_kronos_input_key(key)
        if normalized not in KRONOS_ROUTINE_PARAM_KEYS:
            continue
        if value is None or str(value).strip() == "":
            merged.pop(normalized, None)
            merged.pop(key, None)
            continue
        merged[normalized] = str(value).strip()
    return merged


def build_kronos_input_json(
    description: str = "",
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    """Monta input_json de task Kronos a partir da rotina (metadata + prompt)."""
    source: dict[str, Any] = extract_routine_execution_params(metadata)
    return resolve_kronos_inputs({"description": description, "input_json": source})


def entrypoint(task: dict, supabase_client: Any) -> dict:
    """Ponto de entrada chamado pelo agent_daemon para operation_type='financial-audit'."""
    task_id = task.get("id", "unknown")
    company_id = task.get("company_id", "")
    inputs = resolve_kronos_inputs(task)

    ofx_path     = inputs.get("OFX_PATH", "")
    planner_path = inputs.get("PLANNER_PATH", "")
    recipient    = inputs.get("RECIPIENT", DEFAULT_RECIPIENT)
    apply_baixa  = inputs.get("APPLY_BAIXA", "false").lower() in ("true", "1", "yes")

    if not ofx_path or not planner_path:
        msg = "Kronos: OFX_PATH e/ou PLANNER_PATH ausentes na descrição da task."
        logger.error(msg)
        return {"status": "errored", "error": msg}

    if not Path(ofx_path).exists():
        msg = f"Kronos: arquivo OFX não encontrado: {ofx_path}"
        logger.error(msg)
        return {"status": "errored", "error": msg}

    if not Path(planner_path).exists():
        msg = f"Kronos: arquivo do Planner não encontrado: {planner_path}"
        logger.error(msg)
        return {"status": "errored", "error": msg}

    # Carrega regras do DB (fallback para hardcoded se offline)
    db_rules = load_rules_from_db(supabase_client) if supabase_client else None

    logger.info("Kronos: iniciando audit — OFX=%s PLANNER=%s", ofx_path, planner_path)

    # 1. Parse
    try:
        ofx_txns = parse_ofx(ofx_path)
    except Exception as e:
        logger.error("Kronos: falha ao parsear OFX: %s", e)
        return {"status": "errored", "error": f"parse_ofx failed: {e}"}

    try:
        planner_entries = parse_planner_export(planner_path)
    except Exception as e:
        logger.error("Kronos: falha ao parsear planilha: %s", e)
        return {"status": "errored", "error": f"parse_planner_export failed: {e}"}

    logger.info(
        "Kronos: %d transações OFX, %d entradas Planner",
        len(ofx_txns), len(planner_entries),
    )

    # 2. Reconcile
    report = reconcile(ofx_txns, planner_entries, db_rules=db_rules)

    # 3. Format
    report_md = format_report_markdown(report)
    report_json = {
        "totais": report.totais,
        "faltantes": report.faltantes,
        "excedentes": report.excedentes,
        "divergencias": report.divergencias,
        "ambiguos": report.ambiguos,
    }

    # 4. Persistir em arquivo
    results_dir = Path(os.getenv("AUDIT_RESULTS_DIR", "./audit-results"))
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = results_dir / f"{task_id}.json"
    md_path   = results_dir / f"{task_id}.md"
    json_path.write_text(json.dumps(report_json, indent=2, default=str), encoding="utf-8")
    md_path.write_text(report_md, encoding="utf-8")
    logger.info("Kronos: resultado persistido em %s", results_dir)

    # 5. Dar baixa no Meu Planner (opcional — APPLY_BAIXA=true)
    apply_result: dict = {}
    if apply_baixa and report.matches:
        logger.info(
            "Kronos: iniciando apply_baixa para %d matches", len(report.matches)
        )
        try:
            from src.agents.kronos_apply import apply_baixa as _apply
            apply_result = _apply(report.matches)
            logger.info(
                "Kronos: apply_baixa — confirmados=%d nao_encontrados=%d erros=%d",
                len(apply_result.get("confirmados", [])),
                len(apply_result.get("nao_encontrados", [])),
                len(apply_result.get("erros", [])),
            )
        except ImportError:
            logger.warning("Kronos: playwright não instalado — apply_baixa ignorado")
        except Exception as e:
            logger.error("Kronos: apply_baixa falhou — %s", e)
            apply_result = {"erros": [{"erro": str(e)}]}
    elif apply_baixa and not report.matches:
        logger.info("Kronos: apply_baixa solicitado mas sem matches — nada a fazer")

    # 6. Dispatch para HermesReporter
    period_label = (
        f"{report.totais.get('periodo_inicio')} a {report.totais.get('periodo_fim')}"
    )
    child_task_id = ""
    if supabase_client:
        try:
            child_task_id = dispatch_to_hermes_reporter(
                supabase_client, company_id, task_id, report_md,
                recipient=recipient, period_label=period_label,
            )
        except Exception as e:
            logger.error("Kronos: falha ao criar task derivada para HermesReporter: %s", e)

    return {
        "status": "done",
        "report_summary": report.totais,
        "child_task_id": child_task_id,
        "files": {"json": str(json_path), "md": str(md_path)},
        **({"apply_baixa": apply_result} if apply_baixa else {}),
    }


def entrypoint_backlog(task: dict, supabase_client: Any) -> dict:
    """
    Entrypoint para operation_type='conciliacao-backlog'.

    Modo 1 (primeira execução — output_json.phase ausente):
      - Scrape MPF via kronos_scrape.scrape_pendentes()
      - Lê OFX via scan_ofx_directory()
      - Reconcilia via reconcile()
      - Envia relatório via dispatch_to_hermes_reporter()
      - Retorna {"status_override": "review", "output_json": {"phase": "await_approval", ...}}

    Modo 2 (retomada — output_json.phase == "await_approval"):
      - Lê matches de task["output_json"]["matches"]
      - Filtra por input_json["approved_items"] se presente (senão aplica todos)
      - Aplica baixas via kronos_apply.apply_baixa()
      - Retorna {"output_json": {"phase": "baixas_applied", ...}}
    """
    input_json = task.get("input_json") or {}
    inputs = resolve_kronos_inputs(task)

    ofx_path       = inputs.get("OFX_PATH", "")
    periodo_inicio = inputs.get("PERIODO_INICIO", "")
    periodo_fim    = inputs.get("PERIODO_FIM", "")
    recipient      = inputs.get("RECIPIENT", DEFAULT_RECIPIENT)
    task_id        = task.get("id", "unknown")
    company_id     = task.get("company_id", "")

    # Detecção de modo
    current_output = task.get("output_json") or {}
    phase = current_output.get("phase")
    is_resume = (phase == "await_approval")

    # ── Modo 2: retomada após review ─────────────────────────────────────────
    if is_resume:
        all_matches = current_output.get("matches", [])
        approved_items = input_json.get("approved_items")  # list[str] ou None
        if approved_items:
            matches_to_apply = [
                m for m in all_matches
                if m.get("planner_descricao") in approved_items
            ]
        else:
            matches_to_apply = all_matches

        try:
            from src.agents.kronos_apply import apply_baixa
            apply_result = apply_baixa(matches_to_apply)
        except ImportError:
            logger.error("entrypoint_backlog: kronos_apply não disponível")
            return {"status": "errored", "error": "kronos_apply não disponível"}
        except Exception as e:
            logger.error("entrypoint_backlog: apply_baixa falhou — %s", e)
            return {"status": "errored", "error": f"apply_baixa falhou: {e}"}

        return {
            "output_json": {
                "phase": "baixas_applied",
                "total_aplicados": len(apply_result.get("confirmados", [])),
                "confirmados": apply_result.get("confirmados", []),
                "nao_encontrados": apply_result.get("nao_encontrados", []),
                "erros": apply_result.get("erros", []),
            }
        }

    # ── Modo 1: primeira execução ─────────────────────────────────────────────

    # Validações obrigatórias
    if not ofx_path:
        msg = (
            "entrypoint_backlog: OFX_PATH ausente "
            "(informe em input_json, metadata da rotina, description ou KRONOS_OFX_PATH)"
        )
        logger.error(msg)
        return {"status": "errored", "error": msg}

    if not periodo_inicio or not periodo_fim:
        try:
            periodo_inicio, periodo_fim = infer_period_from_ofx_path(ofx_path)
            logger.info(
                "entrypoint_backlog: período inferido do OFX %s → %s a %s",
                ofx_path,
                periodo_inicio,
                periodo_fim,
            )
        except Exception as exc:
            msg = f"entrypoint_backlog: PERIODO_INICIO/FIM ausentes e inferência falhou: {exc}"
            logger.error(msg)
            return {"status": "errored", "error": msg}

    # 1. Scrape MPF
    try:
        from src.agents.kronos_scrape import scrape_pendentes
        pendentes = scrape_pendentes(periodo_inicio, periodo_fim)
    except ImportError:
        logger.error("entrypoint_backlog: kronos_scrape não disponível — playwright instalado?")
        return {"status": "errored", "error": "kronos_scrape não disponível"}
    except Exception as e:
        logger.error("entrypoint_backlog: scrape_pendentes falhou — %s", e)
        return {"status": "errored", "error": f"scrape_pendentes falhou: {e}"}

    if len(pendentes) == 0:
        logger.warning("entrypoint_backlog: nenhum pendente retornado pelo scrape — período pode estar vazio")

    # 2. Converte pendentes para PlannerEntry
    from datetime import datetime as _dt
    from decimal import Decimal as _D
    planner_entries = []
    for p in pendentes:
        try:
            planner_entries.append(PlannerEntry(
                data=_dt.strptime(p["data"], "%Y-%m-%d").date(),
                descricao=p.get("descricao", ""),
                valor=_D(str(p.get("valor", "0"))),
                tipo="despesa",
                categoria=p.get("categoria"),
                subcategoria=p.get("subcategoria"),
                raw_row=p,
            ))
        except Exception as exc:
            logger.warning("entrypoint_backlog: ignorando pendente inválido: %s — %s", p, exc)

    # 3. Lê OFX
    try:
        ofx_txns = scan_ofx_directory(ofx_path, inicio=periodo_inicio, fim=periodo_fim)
    except Exception as e:
        logger.error("entrypoint_backlog: scan_ofx_directory falhou — %s", e)
        return {"status": "errored", "error": f"scan_ofx_directory falhou: {e}"}

    if len(ofx_txns) == 0:
        msg = "entrypoint_backlog: nenhuma transação OFX encontrada no período"
        logger.error(msg)
        return {"status": "errored", "error": msg}

    # 4. Carrega regras e reconcilia
    db_rules = load_rules_from_db(supabase_client) if supabase_client else None
    report = reconcile(ofx_txns, planner_entries, tolerance_days=10, db_rules=db_rules)

    # 5. Formata e persiste
    report_md = format_report_markdown(report)
    results_dir = Path(os.getenv("AUDIT_RESULTS_DIR", "./audit-results"))
    results_dir.mkdir(parents=True, exist_ok=True)
    md_path = results_dir / f"{task_id}_backlog.md"
    md_path.write_text(report_md, encoding="utf-8")
    logger.info("entrypoint_backlog: relatório persistido em %s", md_path)

    # 6. Envia email via HermesReporter
    period_label = f"{periodo_inicio} a {periodo_fim}"
    child_task_id = ""
    if supabase_client:
        try:
            child_task_id = dispatch_to_hermes_reporter(
                supabase_client, company_id, task_id, report_md,
                recipient=recipient, period_label=period_label,
            )
        except Exception as e:
            logger.error("entrypoint_backlog: falha ao criar task para HermesReporter: %s", e)

    return {
        "status_override": "review",
        "output_json": {
            "phase": "await_approval",
            "matches": report.matches,
            "report_summary": report.totais,
            "report_md_path": str(md_path),
            "hermes_task_id": child_task_id,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _normalize_text(s: str) -> str:
    """Remove acentos, converte para lowercase."""
    nfkd = unicodedata.normalize("NFKD", s)
    return nfkd.encode("ascii", "ignore").decode("ascii").lower().strip()


def _parse_valor(s: str) -> Decimal:
    """
    Converte string de valor monetário para Decimal.
    Suporta formato brasileiro (1.234,56) e internacional (1234.56 ou 500.00).
    Heurística: se termina em ,DD → formato brasileiro; senão → internacional.
    """
    import re as _re
    s = s.strip().lstrip("-").strip()  # valor absoluto para Decimal (sinal vem do trntype)
    if not s:
        return Decimal("0")
    # Formato brasileiro detectado: vírgula com exatamente 2 dígitos no final
    if _re.search(r",\d{1,2}$", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        # Internacional: pode ter ponto decimal ou apenas inteiro
        s = s.replace(",", "")
    return Decimal(s)


def _parse_date(s: str) -> date:
    """Tenta varios formatos de data comuns em exportações brasileiras."""
    # Normaliza: remove hora se presente (ex: '2026-04-30 00:00:00' → '2026-04-30')
    s = s.strip().split(" ")[0].split("T")[0]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Formato de data desconhecido: {s!r}")
