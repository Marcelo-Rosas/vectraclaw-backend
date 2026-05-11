"""
Schemas Pydantic dos outputs dos handlers Athena.

Esses schemas SÃO a validação do contrato I/T/O PMBOK. Todo handler real
(PRs 3-5 da VEC-388 + PRs da VEC-389 e VEC-390) deve produzir um output
que valida contra o schema correspondente — caso contrário o daemon
rejeita o output.

Princípios:
- Vocabulário de tools é FIXO via Literal[ALLOWED_TOOLS] — Gemini não pode inventar
- Escala P×I do Risk Register é a oficial PMBOK 5ª (Heldman) via Literal
- Score do risco é validado contra round(p*i, 4) com tolerância 0.0001
- Classificação semáforo é validada contra faixas fixas
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ════════════════════════════════════════════════════════════════════════════
# Vocabulário CANÔNICO de tools (PMBOK Inputs/Tools/Outputs)
# ════════════════════════════════════════════════════════════════════════════
ALLOWED_TOOLS = Literal[
    "expert_judgment",           # SEMPRE presente — Athena é o expert
    "rag_retrieval",             # Consulta athena_chunks
    "historical_data_review",    # APO: consulta projects.lessons_learned
    "selection_methods",         # athena-charter (NPV/Payback/Sacred Cow/etc)
    "weighted_scoring",          # athena-prioritize (VEC-390)
    "earned_value_analysis",     # athena-evm
    "stakeholder_analysis",      # athena-stakeholder-map
    "power_interest_grid",       # sub-técnica do stakeholder_analysis
    "risk_analysis",             # athena-risk-register
    "risk_breakdown_structure",  # athena-risk-register (RBS)
    "smart_filter",              # athena-classify, athena-charter
    "business_case_validation",  # athena-classify
    "prompt_quality_scoring",    # athena-audit (VEC-389)
    "gap_analysis",              # athena-audit, athena-recommend, charter skill check
]


# ════════════════════════════════════════════════════════════════════════════
# Bloco comum a TODOS os outputs: validation
# ════════════════════════════════════════════════════════════════════════════
class ValidationBlock(BaseModel):
    schema_version: Literal["v4.1"] = "v4.1"
    all_required_inputs_present: bool
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: List[str] = Field(default_factory=list)
    needs_human_review: bool = False


class Citation(BaseModel):
    chunk_id: str
    page: Optional[int] = None
    source: Optional[str] = None
    topic: Optional[str] = None


# ════════════════════════════════════════════════════════════════════════════
# Base genérica de output PMBOK I/T/O
# Todo handler retorna um subclasse desta — esse é o "contrato"
# ════════════════════════════════════════════════════════════════════════════
class HandlerOutputBase(BaseModel):
    handler_name: str
    execution_id: str
    execution_started_at: datetime
    execution_completed_at: datetime
    inputs_used: Dict[str, Any]
    tools_techniques_applied: List[ALLOWED_TOOLS] = Field(min_length=1)
    outputs: Dict[str, Any]
    validation: ValidationBlock
    citations: List[Citation] = Field(default_factory=list)

    @field_validator("tools_techniques_applied")
    @classmethod
    def expert_judgment_always_present(cls, v: List[str]) -> List[str]:
        if "expert_judgment" not in v:
            raise ValueError(
                "tools_techniques_applied DEVE incluir 'expert_judgment' "
                "(Athena é o expert sintético em todo output)"
            )
        return v


# ════════════════════════════════════════════════════════════════════════════
# RISK REGISTER (athena-risk-register) — escala oficial PMBOK 5ª
# ════════════════════════════════════════════════════════════════════════════

# Escala probabilidade PMBOK 5ª: 5 níveis discretos
ProbabilityPMBOK = Literal[0.1, 0.3, 0.5, 0.7, 0.9]

# Escala impacto PMBOK 5ª: 5 níveis discretos
ImpactPMBOK = Literal[0.05, 0.10, 0.20, 0.40, 0.80]

# Classificação semáforo derivada do score
RiskClassification = Literal["Baixo", "Moderado", "Alto", "Crítico"]
RiskColor = Literal["🟢", "🟡", "🟠", "🔴"]

# Naturezas (Heldman é categórico: riscos são positivos OU negativos)
RiskNature = Literal["threat", "opportunity"]

# Estratégias por natureza
ThreatStrategy = Literal["eliminate", "mitigate", "transfer", "accept_active", "accept_passive"]
OpportunityStrategy = Literal["exploit", "enhance", "share", "accept"]


def _classify_from_score(score: float) -> RiskClassification:
    """Deriva classificação semáforo a partir do score numérico."""
    if score <= 0.0900:
        return "Baixo"
    if score <= 0.1900:
        return "Moderado"
    if score <= 0.3500:
        return "Alto"
    return "Crítico"


def _color_from_classification(c: RiskClassification) -> RiskColor:
    return {"Baixo": "🟢", "Moderado": "🟡", "Alto": "🟠", "Crítico": "🔴"}[c]


class SecondaryRisk(BaseModel):
    """Risco que surge como consequência da response_plan ao risco primário."""
    id: str
    description: str = Field(min_length=20)
    probability: ProbabilityPMBOK
    impact: ImpactPMBOK
    score: float
    classification: RiskClassification

    @field_validator("score")
    @classmethod
    def score_matches_p_times_i(cls, v: float, info) -> float:
        p = info.data.get("probability")
        i = info.data.get("impact")
        if p is not None and i is not None:
            expected = round(p * i, 4)
            if abs(v - expected) > 0.0001:
                raise ValueError(f"score {v} ≠ probability × impact (esperado {expected})")
        return v

    @model_validator(mode="after")
    def classification_matches_score(self) -> "SecondaryRisk":
        expected = _classify_from_score(self.score)
        if self.classification != expected:
            raise ValueError(
                f"classification '{self.classification}' ≠ esperado '{expected}' "
                f"para score {self.score:.4f}"
            )
        return self


class ResidualRisk(BaseModel):
    """Risco remanescente após implementação da response_plan."""
    description: str = Field(min_length=20)
    probability: ProbabilityPMBOK
    impact: ImpactPMBOK
    score: float
    classification: RiskClassification
    acceptance: str = Field(min_length=10)

    @field_validator("score")
    @classmethod
    def score_matches_p_times_i(cls, v: float, info) -> float:
        p = info.data.get("probability")
        i = info.data.get("impact")
        if p is not None and i is not None:
            expected = round(p * i, 4)
            if abs(v - expected) > 0.0001:
                raise ValueError(f"score {v} ≠ probability × impact (esperado {expected})")
        return v

    @model_validator(mode="after")
    def classification_matches_score(self) -> "ResidualRisk":
        expected = _classify_from_score(self.score)
        if self.classification != expected:
            raise ValueError(
                f"classification '{self.classification}' ≠ esperado '{expected}' "
                f"para score {self.score:.4f}"
            )
        return self


class TransferDetails(BaseModel):
    """Obrigatório quando strategy='transfer'. Valida instrumento real, não papel."""
    transferred_to: str = Field(min_length=5)
    instrument: str = Field(min_length=10)
    cost_of_transfer_brl_per_unit: float = Field(ge=0)
    expected_loss_brl_without_transfer: float = Field(ge=0)
    net_savings_brl: float
    counterparty_capacity_validated: bool
    counterparty_validation_method: str = Field(min_length=10)

    @model_validator(mode="after")
    def net_savings_is_consistent(self) -> "TransferDetails":
        expected = round(self.expected_loss_brl_without_transfer - self.cost_of_transfer_brl_per_unit, 2)
        if abs(self.net_savings_brl - expected) > 0.01:
            raise ValueError(
                f"net_savings_brl {self.net_savings_brl} ≠ expected_loss − cost "
                f"(esperado {expected})"
            )
        return self


class Risk(BaseModel):
    """Linha principal do Risk Register."""
    id: str
    nature: RiskNature
    rbs_category: Literal["External", "Organizational", "Project Management", "Technical"]
    rbs_subcategory: str
    description: str = Field(min_length=20)
    probability: ProbabilityPMBOK
    impact: ImpactPMBOK
    score: float
    classification: RiskClassification
    classification_color: RiskColor
    strategy: str   # validado abaixo (depende de nature)
    response_plan: str = Field(min_length=30)
    owner_position_id: Optional[str] = None
    trigger_indicators: List[str] = Field(default_factory=list)
    secondary_risks: List[SecondaryRisk] = Field(default_factory=list)
    residual_risk: ResidualRisk  # obrigatório
    transfer_details: Optional[TransferDetails] = None
    contingency_reserve_brl: float = Field(default=0.0, ge=0)
    review_frequency: Literal["daily", "weekly", "biweekly", "monthly", "quarterly"] = "weekly"

    @field_validator("score")
    @classmethod
    def score_matches_p_times_i(cls, v: float, info) -> float:
        p = info.data.get("probability")
        i = info.data.get("impact")
        if p is not None and i is not None:
            expected = round(p * i, 4)
            if abs(v - expected) > 0.0001:
                raise ValueError(f"score {v} ≠ probability × impact (esperado {expected})")
        return v

    @model_validator(mode="after")
    def validate_consistency(self) -> "Risk":
        # Classification consistente com score
        expected_class = _classify_from_score(self.score)
        if self.classification != expected_class:
            raise ValueError(
                f"classification '{self.classification}' ≠ esperado '{expected_class}' "
                f"para score {self.score:.4f}"
            )

        # Color consistente com classification
        expected_color = _color_from_classification(self.classification)
        if self.classification_color != expected_color:
            raise ValueError(
                f"classification_color '{self.classification_color}' ≠ esperado "
                f"'{expected_color}' para classification '{self.classification}'"
            )

        # Strategy consistente com nature
        if self.nature == "threat":
            valid_strategies = {"eliminate", "mitigate", "transfer", "accept_active", "accept_passive"}
        else:  # opportunity
            valid_strategies = {"exploit", "enhance", "share", "accept"}
        if self.strategy not in valid_strategies:
            raise ValueError(
                f"strategy '{self.strategy}' inválida para nature='{self.nature}'. "
                f"Esperado um de {valid_strategies}"
            )

        # transfer_details OBRIGATÓRIO se strategy=transfer
        if self.strategy == "transfer" and self.transfer_details is None:
            raise ValueError(
                "transfer_details é obrigatório quando strategy='transfer'. "
                "Cláusula sem instrumento financeiro = papel (anti-padrão Athena)."
            )

        return self


class RiskSummary(BaseModel):
    total_risks: int = Field(ge=0)
    critical_count: int = Field(ge=0)
    high_count: int = Field(ge=0)
    moderate_count: int = Field(ge=0)
    low_count: int = Field(ge=0)
    threats: int = Field(ge=0)
    opportunities: int = Field(ge=0)
    highest_score_risk_id: Optional[str] = None
    any_critical_breached: bool


class RiskRegisterOutputs(BaseModel):
    """Bloco 'outputs' dentro de HandlerOutputBase para athena-risk-register."""
    risks: List[Risk] = Field(min_length=5)
    rbs: Dict[str, List[str]]
    risk_summary: RiskSummary
    team_health_assessment: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def must_have_opportunity_and_rbs_coverage(self) -> "RiskRegisterOutputs":
        # Pelo menos 1 opportunity
        natures = [r.nature for r in self.risks]
        if "opportunity" not in natures:
            raise ValueError(
                "Risk Register sem nenhum risco 'opportunity' indica viés cognitivo. "
                "Heldman: riscos têm efeito positivo OU negativo. Adicione pelo menos 1."
            )

        # Pelo menos 1 risk em 3 dos 4 RBS categories
        categories_present = {r.rbs_category for r in self.risks}
        if len(categories_present) < 3:
            raise ValueError(
                f"Risk Register concentrado em apenas {len(categories_present)} "
                f"categorias RBS ({categories_present}). Critério: mínimo 3 de 4."
            )

        return self


# ════════════════════════════════════════════════════════════════════════════
# EVM (athena-evm) — Python calcula, Gemini narra
# ════════════════════════════════════════════════════════════════════════════
class EVMMetrics(BaseModel):
    """Métricas determinísticas. Toda fórmula validada contra a definição PMBOK."""
    pv: float
    ev: float
    ac: float
    bac: float
    sv: float
    cv: float
    spi: Optional[float] = None
    cpi: Optional[float] = None
    eac: Optional[float] = None
    etc: Optional[float] = None
    vac: Optional[float] = None
    tcpi_bac: Optional[float] = None
    tcpi_eac: Optional[float] = None

    @model_validator(mode="after")
    def all_formulas_consistent(self) -> "EVMMetrics":
        # SV = EV − PV
        expected_sv = round(self.ev - self.pv, 4)
        if abs(self.sv - expected_sv) > 0.01:
            raise ValueError(f"sv {self.sv} ≠ EV − PV (esperado {expected_sv})")

        # CV = EV − AC
        expected_cv = round(self.ev - self.ac, 4)
        if abs(self.cv - expected_cv) > 0.01:
            raise ValueError(f"cv {self.cv} ≠ EV − AC (esperado {expected_cv})")

        # SPI = EV/PV (quando PV > 0)
        if self.pv > 0 and self.spi is not None:
            expected_spi = round(self.ev / self.pv, 4)
            if abs(self.spi - expected_spi) > 0.001:
                raise ValueError(f"spi {self.spi} ≠ EV/PV (esperado {expected_spi})")

        # CPI = EV/AC (quando AC > 0)
        if self.ac > 0 and self.cpi is not None:
            expected_cpi = round(self.ev / self.ac, 4)
            if abs(self.cpi - expected_cpi) > 0.001:
                raise ValueError(f"cpi {self.cpi} ≠ EV/AC (esperado {expected_cpi})")

        # EAC = BAC × AC/EV — IMPORTANTE: recalcular usando EV/AC originais (não o CPI arredondado),
        # senão dá drift de até 0.1 com tolerância insuficiente.
        # Fórmula equivalente PMBOK: EAC = BAC × AC/EV (mesma coisa matematicamente)
        if self.ac > 0 and self.ev > 0 and self.eac is not None:
            expected_eac = round(self.bac * self.ac / self.ev, 4)
            if abs(self.eac - expected_eac) > 0.01:
                raise ValueError(f"eac {self.eac} ≠ BAC × AC/EV (esperado {expected_eac})")

        # VAC = BAC − EAC
        if self.eac is not None and self.vac is not None:
            expected_vac = round(self.bac - self.eac, 4)
            if abs(self.vac - expected_vac) > 0.01:
                raise ValueError(f"vac {self.vac} ≠ BAC − EAC (esperado {expected_vac})")

        return self


# ════════════════════════════════════════════════════════════════════════════
# EVM (athena-evm) — VEC-405 PR5b
# Output-only. Python calcula determinístico; Gemini gera apenas narrativa.
# ════════════════════════════════════════════════════════════════════════════
class EVMOutputs(BaseModel):
    """Bloco 'outputs' do athena-evm — métricas determinísticas + narrativa Gemini."""
    metrics: EVMMetrics
    narrative_md: str = Field(min_length=100)
    executive_summary_md: str = Field(min_length=50)
    alerts: List[str] = Field(default_factory=list)
    interpretation_period: str = Field(min_length=4)  # ex: "2026-Q1" ou "2026-05-11"


class EVMOutput(HandlerOutputBase):
    handler_name: Literal["athena-evm"] = "athena-evm"
    outputs: EVMOutputs  # type: ignore[assignment]


# ════════════════════════════════════════════════════════════════════════════
# PRIORITIZE (athena-prioritize) — VEC-406 (slice 2/3 do VEC-390)
# Output-only. Python calcula score ponderado; Gemini pontua e narra.
# ════════════════════════════════════════════════════════════════════════════
class PrioritizationCriterion(BaseModel):
    """Critério ponderado para ranking (Heldman cap.4 weighted scoring)."""
    key: str = Field(min_length=2)
    label: str = Field(min_length=2)
    weight: float = Field(ge=0.0, le=1.0)
    scoring_hints: List[str] = Field(default_factory=list)


class GoalScore(BaseModel):
    """Pontuação de 1 critério para 1 goal — calculado pelo Python a partir
    do rating do Gemini."""
    criterion_key: str = Field(min_length=2)
    rating: int = Field(ge=1, le=5)
    weight: float = Field(ge=0.0, le=1.0)
    weighted_contribution: float = Field(ge=0.0)
    rationale: str = Field(min_length=10)


class RankedGoal(BaseModel):
    rank: int = Field(ge=1)
    goal_id: str = Field(min_length=10)
    goal_title: str = Field(min_length=2)
    total_score: float = Field(ge=0.0)
    breakdown: List[GoalScore] = Field(min_length=1)

    @model_validator(mode="after")
    def total_matches_breakdown(self) -> "RankedGoal":
        expected = round(sum(s.weighted_contribution for s in self.breakdown), 4)
        if abs(self.total_score - expected) > 0.01:
            raise ValueError(
                f"total_score {self.total_score} ≠ sum(weighted_contribution) "
                f"(esperado {expected})"
            )
        return self


class ScoreGapsAnalysis(BaseModel):
    largest_gap: str = Field(min_length=10)
    tightest_competition: str = Field(min_length=10)


class PrioritizeOutputs(BaseModel):
    ranking: List[RankedGoal] = Field(min_length=2, max_length=10)
    narrative_md: str = Field(min_length=100)
    execution_recommendations: List[str] = Field(min_length=1)
    score_gaps: ScoreGapsAnalysis
    criteria_used: List[PrioritizationCriterion] = Field(min_length=2, max_length=8)
    criteria_version: int = Field(default=0, ge=0)  # 0 = default hardcoded fallback

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "PrioritizeOutputs":
        s = round(sum(c.weight for c in self.criteria_used), 4)
        if abs(s - 1.0) > 0.01:
            raise ValueError(
                f"Soma dos weights dos critérios = {s}, esperado 1.0 (±0.01)"
            )
        return self

    @model_validator(mode="after")
    def ranking_ordered_desc(self) -> "PrioritizeOutputs":
        scores = [r.total_score for r in self.ranking]
        if scores != sorted(scores, reverse=True):
            raise ValueError(
                f"ranking deve estar ordenado por total_score DESC. Recebido: {scores}"
            )
        # Ranks consecutivos começando em 1
        ranks = [r.rank for r in self.ranking]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError(
                f"rank deve ser sequencial 1..N. Recebido: {ranks}"
            )
        return self


class PrioritizeOutput(HandlerOutputBase):
    handler_name: Literal["athena-prioritize"] = "athena-prioritize"
    outputs: PrioritizeOutputs  # type: ignore[assignment]


# ════════════════════════════════════════════════════════════════════════════
# CLASSIFY (athena-classify) — gate de entrada
# ════════════════════════════════════════════════════════════════════════════
GoalKind = Literal["project", "operation", "undecided"]
BusinessCaseStrength = Literal["strong", "adequate", "weak", "absent"]


class SmartBreakdown(BaseModel):
    specific: str = Field(min_length=20)
    measurable: str = Field(min_length=10)
    achievable: str = Field(min_length=10)
    relevant: str = Field(min_length=10)
    timebound: str = Field(min_length=10)


class ClassifyOutputs(BaseModel):
    kind: GoalKind
    confidence: float = Field(ge=0.0, le=1.0)
    classification_rationale: str = Field(min_length=50)
    smart_breakdown: SmartBreakdown
    business_case_strength: BusinessCaseStrength
    organizational_calibration: Dict[str, Any]
    next_handler: Optional[Literal["athena-charter", None]] = None


# ════════════════════════════════════════════════════════════════════════════
# Schemas concretos por handler (instanciar HandlerOutputBase com 'outputs' tipado)
# ════════════════════════════════════════════════════════════════════════════
class ClassifyOutput(HandlerOutputBase):
    handler_name: Literal["athena-classify"] = "athena-classify"
    outputs: ClassifyOutputs  # type: ignore[assignment]


class RiskRegisterOutput(HandlerOutputBase):
    handler_name: Literal["athena-risk-register"] = "athena-risk-register"
    outputs: RiskRegisterOutputs  # type: ignore[assignment]


# ════════════════════════════════════════════════════════════════════════════
# CHARTER (athena-charter) — VEC-401 PR4a
# Output-only (sem persistência em projects ainda — fica para PR4b).
# ════════════════════════════════════════════════════════════════════════════
SelectionModel = Literal[
    "npv",                    # Net Present Value
    "payback",                # Payback period
    "weighted_scoring",       # Modelo de scoring ponderado
    "sacred_cow",             # Projeto político/estratégico (sem ROI mensurável)
    "discounted_cash_flow",   # DCF
]


class SmartGoal(BaseModel):
    """Meta SMART concreta dentro do charter."""
    goal: str = Field(min_length=20)
    specific: str = Field(min_length=10)
    measurable: str = Field(min_length=10)
    achievable: str = Field(min_length=10)
    relevant: str = Field(min_length=10)
    timebound: str = Field(min_length=10)


class CharterOutputs(BaseModel):
    """Bloco 'outputs' do athena-charter — 5 elementos PMBOK + SMART + selection."""
    charter_md: str = Field(min_length=200)
    business_need: str = Field(min_length=50)
    scope_description: str = Field(min_length=50)
    strategic_alignment: str = Field(min_length=30)
    human_resources_assessment: str = Field(min_length=30)
    stakeholder_risk_tolerance: str = Field(min_length=30)
    smart_goals: List[SmartGoal] = Field(min_length=1)
    red_flags: List[str] = Field(default_factory=list)
    selection_model: SelectionModel
    next_steps: List[str] = Field(min_length=1)


class CharterOutput(HandlerOutputBase):
    handler_name: Literal["athena-charter"] = "athena-charter"
    outputs: CharterOutputs  # type: ignore[assignment]


# ════════════════════════════════════════════════════════════════════════════
# STAKEHOLDER MAP (athena-stakeholder-map) — VEC-403 PR4c
# Output-only. Sem persistência (tabela `stakeholders` não existe).
# ════════════════════════════════════════════════════════════════════════════
class Stakeholder(BaseModel):
    """Stakeholder identificado no projeto."""
    name: str = Field(min_length=2)
    role: str = Field(min_length=2)
    influence: float = Field(ge=0.0, le=1.0)
    interest: float = Field(ge=0.0, le=1.0)
    expectations: str = Field(min_length=15)


class PowerInterestQuadrant(BaseModel):
    """Matriz Power × Interest (Heldman cap.13). Cada lista contém nomes de stakeholders.
    high_power_high_interest = Manage Closely (gestão estreita)
    high_power_low_interest  = Keep Satisfied (manter satisfeito)
    low_power_high_interest  = Keep Informed (manter informado)
    low_power_low_interest   = Monitor (apenas monitorar)
    """
    high_power_high_interest: List[str] = Field(default_factory=list)
    high_power_low_interest: List[str] = Field(default_factory=list)
    low_power_high_interest: List[str] = Field(default_factory=list)
    low_power_low_interest: List[str] = Field(default_factory=list)


class CommunicationEntry(BaseModel):
    """Entrada do communication plan PMBOK."""
    stakeholder_name: str = Field(min_length=2)
    channel: Literal["email", "whatsapp", "1on1", "reuniao", "report", "dashboard", "outro"]
    frequency: Literal["realtime", "diario", "semanal", "quinzenal", "mensal", "trimestral", "on_demand"]
    message_focus: str = Field(min_length=15)


class TeamHealthAssessment(BaseModel):
    """Avaliação de saúde do time / capacidade humana — input para charter HR assessment futuro."""
    maturity_level: Literal["initial", "managed", "defined", "quantitatively_managed", "optimizing"]
    gaps_identified: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(min_length=1)


class StakeholderMapOutputs(BaseModel):
    """Bloco 'outputs' do athena-stakeholder-map."""
    stakeholders: List[Stakeholder] = Field(min_length=1)
    matrix_power_interest: PowerInterestQuadrant
    communication_plan: List[CommunicationEntry] = Field(min_length=1)
    team_health_assessment: TeamHealthAssessment
    risk_alerts: List[str] = Field(default_factory=list)


class StakeholderMapOutput(HandlerOutputBase):
    handler_name: Literal["athena-stakeholder-map"] = "athena-stakeholder-map"
    outputs: StakeholderMapOutputs  # type: ignore[assignment]


# EVM, Audit, Recommend, Prioritize:
# schemas detalhados nos PRs respectivos. Por ora, todos validam contra
# HandlerOutputBase (versão genérica).


# ════════════════════════════════════════════════════════════════════════════
# Mapeamento operation_type → schema class
# Usado por src/agent_daemon.py para escolher o validator certo após o handler
# ════════════════════════════════════════════════════════════════════════════
SCHEMA_BY_OPERATION_TYPE: Dict[str, type[HandlerOutputBase]] = {
    "athena-classify":         ClassifyOutput,
    "athena-charter":          CharterOutput,
    "athena-stakeholder-map":  StakeholderMapOutput,
    "athena-risk-register":    RiskRegisterOutput,
    "athena-evm":              EVMOutput,
    "athena-rag-ingest":       HandlerOutputBase,
    "athena-audit":            HandlerOutputBase,
    "athena-recommend":        HandlerOutputBase,
    "athena-prioritize":       PrioritizeOutput,
}


def validate_handler_output(operation_type: str, output: Dict[str, Any]) -> HandlerOutputBase:
    """
    Valida o output de um handler Athena contra o schema apropriado.
    Levanta pydantic.ValidationError em caso de inconsistência.

    Uso típico (no daemon, após handler retornar):
        try:
            parsed = validate_handler_output(op_type, result["output_json"])
        except ValidationError as e:
            # Output rejeitado — marcar task como failed com detalhes
            ...
    """
    schema_cls = SCHEMA_BY_OPERATION_TYPE.get(operation_type, HandlerOutputBase)
    return schema_cls.model_validate(output)
