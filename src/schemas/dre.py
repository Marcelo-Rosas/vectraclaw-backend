from typing import List, Literal, Optional
from pydantic import BaseModel, Field

# ─── Types and Enums ──────────────────────────────────────────────────────────

DreLineCode = Literal[
    "faturamento_bruto",
    "impostos",
    "das",
    "icms",
    "pis",
    "cofins",
    "csll",
    "irpj",
    "receita_liquida",
    "overhead",
    "custos_diretos",
    "custo_motorista",
    "pedagio",
    "carga_descarga",
    "espera",
    "taxas_condicionais",
    "aluguel_maquinas",
    "mao_de_obra",
    "outros_custos",
    "resultado_liquido",
    "margem_liquida",
]

DreLineGroup = Literal["receita", "impostos", "custos", "resultado"]
SignType = Literal["positive", "negative"]
BadgeDirection = Literal["up", "down", "neutral"]
BadgeColor = Literal["green", "red", "neutral"]
PeriodType = Literal["detail", "month", "quarter", "year"]


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class DreLineMapping(BaseModel):
    line_code: DreLineCode
    line_label: str
    line_group: DreLineGroup
    sort_order: int
    indent_level: Literal[0, 1]
    is_group: bool
    is_subline: bool
    sign_type: SignType
    formula: str
    presumed_source: str
    real_source: str


class DreCanonicalRow(BaseModel):
    """
    Linha canônica de saída da camada de dados.
    """
    period_type: PeriodType
    period_key: str
    quote_code: Optional[str] = None
    os_number: Optional[str] = None
    line_code: DreLineCode
    line_label: str
    sort_order: int
    indent_level: Literal[0, 1]
    presumed_value: float
    real_value: float
    variance_value: float
    variance_percent: float
    badge_direction: BadgeDirection
    badge_color: BadgeColor
    has_formula_warning: bool
    missing_real_cost_flag: bool


class DreTable(BaseModel):
    period_type: PeriodType
    period_key: str
    quote_code: Optional[str] = None
    os_number: Optional[str] = None
    
    # Base temporal única para filtros e agrupamentos
    reference_date: str
    
    status: Optional[Literal["ok", "sem_os_vinculada"]] = None
    status_detail: Optional[Literal["ok", "legacy_quote_breakdown", "os_without_quote"]] = None
    
    rows: List[DreCanonicalRow] = Field(default_factory=list)
