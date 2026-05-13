from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal, Any, Dict, List
from pydantic import BaseModel, Field, root_validator, validator

def to_camel(string: str) -> str:
    words = string.split('_')
    return words[0] + ''.join(word.capitalize() for word in words[1:])

class CamelModel(BaseModel):
    class Config:
        alias_generator = to_camel
        validate_by_name = True  # pydantic v2.13+ (replaces allow_population_by_field_name)

class Agent(CamelModel):
    id: str
    company_id: str
    name: str
    role: str
    reports_to_id: Optional[str] = None
    status: Literal["idle", "working", "offline", "error", "paused"]
    token_budget: int
    current_burn_rate: float
    adapter_type: str
    # Task #2 — agente pode ter N specialties (relação 1:N via agent_specialty_configs).
    # `specialty_id` mantido por backcompat (primeira da lista); `specialty_ids` é o
    # array canônico. Frontend novo consome specialtyIds; antigo continua com specialtyId.
    specialty_id: Optional[str] = None
    specialty_ids: List[str] = Field(default_factory=list)
    system_prompt: Optional[str] = None
    requires_approval: bool = False
    platform_url: Optional[str] = None
    is_system: bool = False
    created_at: datetime
    updated_at: datetime

    @validator('current_burn_rate', pre=True)
    def parse_burn_rate(cls, v):
        if v is not None:
            return float(v)
        return v

    @validator('reports_to_id', pre=True)
    def empty_to_none(cls, v):
        if v == "":
            return None
        return v

    @validator('status', pre=True)
    def map_status(cls, v):
        if v == "errored":
            return "error"
        return v

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        if isinstance(self.created_at, datetime):
            d["createdAt"] = self.created_at.isoformat().replace("+00:00", "Z")
        else:
            d["createdAt"] = str(self.created_at).replace("+00:00", "Z")

        # Excluir updatedAt para paridade Zod (VEC-193/VEC-192 Cleanup)
        if "updatedAt" in d:
            del d["updatedAt"]

        # Reverse-map DB-internal values to Zod enum values.
        # 'internal' (Oracle system agent) maps to claude_code in the Zod schema.
        _adapter_reverse = {
            "cursor": "codex",
            "bot": "shell",
            "claude": "claude_code",
            "internal": "claude_code",
        }
        if d.get("adapterType") in _adapter_reverse:
            d["adapterType"] = _adapter_reverse[d["adapterType"]]

        # Zod expects string (not null) for optional text fields
        if d.get("systemPrompt") is None:
            d["systemPrompt"] = ""
        if d.get("platformUrl") is None:
            d["platformUrl"] = ""

        # Ensure numeric types are correct (guards against DB returning strings)
        d["tokenBudget"] = int(d.get("tokenBudget") or 0)
        d["currentBurnRate"] = float(d.get("currentBurnRate") or 0)

        # reportsToId: null is intentionally left nullable — 6th residual Zod issue lives in dashboard schema

        return d

class Task(CamelModel):
    id: str
    company_id: str
    assigned_to_agent_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    goal_id: Optional[str] = None
    title: str
    description: str
    status: Literal["backlog", "queued", "in_progress", "review", "done", "blocked", "skipped"]
    operation_type: Literal[
        "orchestration",
        "code_generation",
        "code_review",
        "research",
        "document_generation",
        "qa_testing",
        "email_lead",
        "freight-quotation",
        "freight-quotation-approval",
        "route-cost-calculation",
        "crm-fill-precheck",
        "crm-fill-finalize",
        "crm-fill",
        "oracle-research",
        "oracle-extract",
        "oracle-report",
        "oracle-rag",
        "oracle-vision",
        "oracle-summarize",
        "dispatch-research",
        "financial-audit",
        "financial-bookkeeping",
        "conciliacao-backlog",
        "rag-ingest",
        # VEC-388 PR1: 9 novos operation types da Athena (PMOia Heldman/PMBOK)
        "athena-classify",
        "athena-charter",
        "athena-stakeholder-map",
        "athena-risk-register",
        "athena-evm",
        "athena-rag-ingest",
        "athena-audit",
        "athena-recommend",
        "athena-prioritize",
        # VEC-416: Kronos pivot — Meu Planner Financeiro via Playwright
        "planner-import-ofx",
        "planner-categorize-pendings",
        "other",
    ] = "other"
    budget_limit: int
    spent: float
    cost_usd: float = 0.0
    claimed_at: Optional[datetime] = None
    workflow_step_id: Optional[str] = None
    dependency_step_codes: List[str] = Field(default_factory=list)
    successor_step_codes: List[str] = Field(default_factory=list)
    is_critical_path: bool = False
    output_json: Optional[Dict[str, Any]] = None
    input_json: Optional[Dict[str, Any]] = None
    approved_at: Optional[datetime] = None
    approved_by_user_id: Optional[str] = None
    # CMA fields (VEC — Claude Managed Agents)
    executor_type: Literal["harness", "managed_agent", "auto"] = "auto"
    managed_agent_session_id: Optional[str] = None
    executor_selected_at: Optional[datetime] = None
    executor_rationale: Optional[str] = None
    # Semana 2: avaliação de qualidade da execução.
    evaluation_score: Optional[int] = None
    evaluation_notes: Optional[str] = None
    evaluated_by: Optional[Literal["agent", "human", "auto"]] = None
    evaluated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @validator('spent', pre=True)
    def parse_spent(cls, v):
        if v is not None:
            return float(v)
        return v

    @validator('cost_usd', pre=True)
    def parse_cost_usd(cls, v):
        if v is None:
            return 0.0
        return float(v)

    @validator('assigned_to_agent_id', 'parent_task_id', 'goal_id',
               'managed_agent_session_id', 'executor_rationale', 'workflow_step_id',
               'approved_by_user_id', 'evaluation_notes', 'evaluated_by', pre=True)
    def empty_to_none(cls, v):
        if v == "":
            return None
        return v

    @validator('dependency_step_codes', 'successor_step_codes', pre=True)
    def coerce_step_code_lists(cls, v):
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v if x is not None]
        return v

    def to_zod_dict(self):
        """
        Dumping Customizado.
        IMPORTANTE: Zod no frontend não tolera 'updatedAt' na Task.
        Removendo explicitamente.
        """
        d = self.dict(by_alias=True)
        # Formatação ISO Z
        for attr, key in [
            ("claimed_at", "claimedAt"),
            ("created_at", "createdAt"),
            ("executor_selected_at", "executorSelectedAt"),
            ("approved_at", "approvedAt"),
            ("evaluated_at", "evaluatedAt"),
        ]:
            val = getattr(self, attr, None)
            if val:
                d[key] = val.isoformat().replace("+00:00", "Z") if isinstance(val, datetime) else str(val).replace("+00:00", "Z")

        # Excluir updatedAt para não quebrar o frontend (VEC-192 §3)
        if "updatedAt" in d:
            del d["updatedAt"]

        return d


class WorkflowStepRich(CamelModel):
    """Rich workflow step (Workflow Builder / manual editor) → DB workflow_steps."""

    step_code: str = ""
    slug: Optional[str] = None
    name: Optional[str] = None
    nome: Optional[str] = None
    descricao: Optional[str] = None
    logic_pattern: Optional[str] = None
    responsavel: Optional[str] = None
    setor: Optional[str] = None
    ferramentas: List[Any] = Field(default_factory=list)
    sla_horas: Optional[int] = None
    alertas: List[Any] = Field(default_factory=list)
    proximo: List[str] = Field(default_factory=list)
    suppliers: Optional[List[Dict[str, Any]]] = None
    inputs: Optional[List[Dict[str, Any]]] = None
    outputs: Optional[List[Dict[str, Any]]] = None
    customers: Optional[List[Dict[str, Any]]] = None
    decisions: Optional[List[Dict[str, Any]]] = None
    five_w2h: Optional[Dict[str, Any]] = None
    default_operation_type: Optional[str] = None
    default_assigned_specialty_slug: Optional[str] = None

    class Config:
        alias_generator = to_camel
        validate_by_name = True
        extra = "ignore"

    @root_validator(pre=True)
    def _normalize_aliases(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(values, dict):
            return values
        if values.get("slaHoras") is not None and values.get("sla_horas") is None:
            values["sla_horas"] = values["slaHoras"]
        code = values.get("step_code") or values.get("stepCode") or values.get("slug")
        if code:
            values["step_code"] = str(code).strip()
        return values

    def resolved_name(self) -> str:
        return (self.name or self.nome or self.step_code or "step").strip()

    def resolved_sla_hours(self) -> int:
        try:
            return int(self.sla_horas) if self.sla_horas is not None else 0
        except (TypeError, ValueError):
            return 0


class TaskBlueprint(CamelModel):
    """Parent task payload for TaskFactory.materialize_workflow."""

    title: str
    description: str = ""
    budget_limit: int = 0
    goal_id: Optional[str] = None

    class Config:
        alias_generator = to_camel
        validate_by_name = True
        extra = "ignore"

    @validator("goal_id", pre=True)
    def _goal(cls, v):
        if v == "":
            return None
        return v


class MaterializedWorkflow(CamelModel):
    parent: Task
    subtasks: List[Task] = Field(default_factory=list)

    class Config:
        alias_generator = to_camel
        validate_by_name = True


# ─── Oracle models (Fase 2) ───────────────────────────────────────────────────

class OracleMetadata(CamelModel):
    model_used: str = ""
    tokens: Dict[str, int] = {}
    duration_ms: int = 0
    tools_used: List[str] = []
    interaction_id: Optional[str] = None


class OracleInput(CamelModel):
    prompt: str
    documents: Optional[List[Dict[str, Any]]] = None
    output_schema: Optional[Dict[str, Any]] = None
    require_human_review: bool = False


class OracleOutput(CamelModel):
    report_markdown: Optional[str] = None
    structured_data: Optional[Dict[str, Any]] = None
    metadata: OracleMetadata = OracleMetadata()
    citations: Optional[List[str]] = None
    error_detail: Optional[Dict[str, Any]] = None

class Goal(CamelModel):
    id: str
    company_id: str
    parent_goal_id: Optional[str] = None
    title: str
    metric: str
    target: float
    current: float

    @validator('parent_goal_id', pre=True)
    def empty_to_none(cls, v):
        if v == "":
            return None
        return v

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        return d


class Heartbeat(CamelModel):
    id: str
    company_id: str
    agent_id: str
    task_id: Optional[str] = None
    status: Literal["idle", "working", "offline", "error", "paused"]
    tokens_used: int
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    model_id: Optional[str] = None
    cost_usd: Optional[float] = None
    log_excerpt: str
    created_at: datetime
    updated_at: datetime

    @validator('task_id', pre=True)
    def empty_to_none(cls, v):
        if v == "":
            return None
        return v

    @validator('status', pre=True)
    def map_status(cls, v):
        if v == "errored":
            return "error"
        return v

    @validator('cost_usd', pre=True)
    def parse_cost_usd(cls, v):
        if v is None:
            return None
        return float(v)

    def to_zod_dict(self):
        """
        Dumping Customizado para VEC-193. 
        IMPORTANTE: Zod não tolera nem 'companyId' nem 'updatedAt'.
        """
        d = self.dict(by_alias=True)
        # Formatação ISO Z
        if self.created_at:
            d["createdAt"] = self.created_at.isoformat().replace("+00:00", "Z")
            
        # Excluir campos denormalizados/extras para não quebrar o frontend
        # (VEC-193 §3)
        if "companyId" in d:
            del d["companyId"]
        if "updatedAt" in d:
            del d["updatedAt"]
            
        return d


class AdapterCatalogItem(CamelModel):
    id: str
    company_id: str
    slug: str
    display_name: str
    provider: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    def to_zod_dict(self):
        return self.dict(by_alias=True)


class AdapterFieldDefinition(CamelModel):
    id: str
    company_id: str
    adapter_id: str
    field_key: str
    field_label: str
    field_type: Literal[
        "text",
        "textarea",
        "number",
        "boolean",
        "select",
        "multiselect",
        "file_upload",
        "secret",
        "url",
    ]
    is_required: bool
    options_json: Optional[dict] = None
    trigger_condition: Optional[dict] = None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    def to_zod_dict(self):
        return self.dict(by_alias=True)


class AgentAdapterConfig(CamelModel):
    id: str
    company_id: str
    agent_id: str
    adapter_id: str
    field_values_json: dict
    is_active: bool
    created_at: datetime
    updated_at: datetime

    def to_zod_dict(self):
        return self.dict(by_alias=True)


class AgentExecutionConfig(CamelModel):
    id: str
    company_id: str
    agent_id: str
    execution_mode: Literal["REALTIME", "CRON", "TRIGGER"]
    trigger_config: Dict[str, Any] = {}
    function_url: Optional[str] = None
    auth_secret_ref: Optional[str] = None
    auth_header_name: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        for k in ("createdAt", "updatedAt"):
            v = d.get(k)
            if isinstance(v, datetime):
                d[k] = v.isoformat().replace("+00:00", "Z")
            elif isinstance(v, str):
                d[k] = v.replace("+00:00", "Z")
        return d

@dataclass(frozen=True)
class Subsystem:
    name: str
    path: str
    file_count: int
    notes: str


@dataclass(frozen=True)
class PortingModule:
    name: str
    responsibility: str
    source_hint: str
    status: str = 'planned'


@dataclass(frozen=True)
class PermissionDenial:
    tool_name: str
    reason: str


@dataclass(frozen=True)
class UsageSummary:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    model_id: Optional[str] = None

    def add_turn(self, prompt: str, output: str) -> 'UsageSummary':
        return UsageSummary(
            input_tokens=self.input_tokens + len(prompt.split()),
            output_tokens=self.output_tokens + len(output.split()),
            cache_read_tokens=self.cache_read_tokens,
            model_id=self.model_id,
        )

class RoutineSchedule(CamelModel):
    cron: str
    timezone: str
    human: str

class Routine(CamelModel):
    id: str
    company_id: str
    name: str
    status: Literal["active", "paused", "error"]
    schedule: RoutineSchedule
    agent_id: Optional[str] = None
    operation_type: Optional[str] = None
    metadata: Optional[dict] = None
    prompt_template: Optional[str] = None
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    created_at: datetime

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        if self.next_run_at:
            d["nextRunAt"] = self.next_run_at.isoformat().replace("+00:00", "Z")
        if self.last_run_at:
            d["lastRunAt"] = self.last_run_at.isoformat().replace("+00:00", "Z")
        if self.created_at:
            d["createdAt"] = self.created_at.isoformat().replace("+00:00", "Z")
        return d

class AuditLogEntry(CamelModel):
    id: str
    company_id: str
    actor_type: Literal["human", "agent", "system"]
    actor_id: str
    action: str
    target: str
    payload: dict
    created_at: datetime

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        if self.created_at:
            d["createdAt"] = self.created_at.isoformat().replace("+00:00", "Z")
        return d

class CouncilApproval(CamelModel):
    id: str
    company_id: str
    request_type: Literal["hire_agent", "strategy", "budget_increase", "task_done"]
    payload: dict
    status: Literal["pending", "approved", "rejected"]
    approved_by_user_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @validator('approved_by_user_id', pre=True)
    def empty_to_none(cls, v):
        if v == "":
            return None
        return v

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        if self.created_at:
            d["createdAt"] = self.created_at.isoformat().replace("+00:00", "Z")
        if "updatedAt" in d:
            del d["updatedAt"]
        return d
class User(CamelModel):
    id: str
    name: str
    email: str
    role: Literal["admin", "member"]
    company_id: str
    avatar_url: Optional[str] = None
    created_at: datetime

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        if self.created_at:
            d["createdAt"] = self.created_at.isoformat().replace("+00:00", "Z")
        return d

class AuthSession(CamelModel):
    access_token: str
    refresh_token: str
    expires_at: datetime
    user: User

    def to_zod_dict(self):
        # O frontend espera camelCase e ISO Z
        return {
            "accessToken": self.access_token,
            "refreshToken": self.refresh_token,
            "expiresAt": self.expires_at.isoformat().replace("+00:00", "Z"),
            "user": self.user.to_zod_dict()
        }

class Incident(CamelModel):
    id: str
    company_id: str
    agent_id: str
    symptom: str
    fix_applied: Optional[str] = None
    severity: Literal["low", "medium", "high"]
    severity_score: int
    agent_snapshot: dict
    decision: Literal["auto_healed", "pending_council", "approved", "rejected", "undone", "manual_fix_required"]
    undo_expires_at: Optional[datetime] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        if self.created_at:
            d["createdAt"] = self.created_at.isoformat().replace("+00:00", "Z")
        if self.undo_expires_at:
            d["undoExpiresAt"] = self.undo_expires_at.isoformat().replace("+00:00", "Z")
        if self.resolved_at:
            d["resolvedAt"] = self.resolved_at.isoformat().replace("+00:00", "Z")
        return d

class IncidentAudit(CamelModel):
    id: str
    incident_id: str
    event: str
    actor: str
    payload: Optional[dict] = None
    created_at: datetime

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        if self.created_at:
            d["createdAt"] = self.created_at.isoformat().replace("+00:00", "Z")
        return d


class LlmModel(CamelModel):
    id: str
    provider: str
    display_name: str
    input_cost_per_1m: float
    output_cost_per_1m: float
    cache_read_cost_per_1m: float
    context_window_k: int
    is_active: bool
    effective_from: str

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        # to_camel turns _1m → 1m (no capitalize on digit), but Zod expects 1M
        for wrong, right in [
            ("inputCostPer1m", "inputCostPer1M"),
            ("outputCostPer1m", "outputCostPer1M"),
            ("cacheReadCostPer1m", "cacheReadCostPer1M"),
        ]:
            if wrong in d:
                d[right] = d.pop(wrong)
        return d


class AgentSpecialty(CamelModel):
    id: str
    name: str
    slug: str
    domain: str
    description: Optional[str] = None
    compatible_roles: List[str]
    system_prompt_template: Optional[str] = None
    config_schema: Optional[List[Dict[str, Any]]] = None
    is_active: bool = True

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        if d.get("systemPromptTemplate") is None:
            d["systemPromptTemplate"] = ""
        if d.get("description") is None:
            d["description"] = ""
        return d


class AgentDomain(CamelModel):
    """PR-DA/DB — categorização canônica de skills.

    Substitui o campo texto livre `agent_specialties.domain` por catálogo
    com FK. Lido pela tab Skills (UI agrupa por domínio) e pelo NAV ADMIN
    (filtros + dropdowns nos formulários de specialty).
    """

    id: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    display_order: int = 100
    is_active: bool = True

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        for key in ("description", "icon", "color"):
            if d.get(key) is None:
                d[key] = ""
        return d


class WorkflowLogicPattern(CamelModel):
    """Task #49 — catálogo canônico dos logic_patterns para workflow_steps.

    Espelha o conteúdo do FlowLogic.tsx do frontend (que era hardcoded em
    MOCK_PATTERNS). Backend passa a ser fonte de verdade; UI lê via
    GET /api/workflow-logic-patterns.

    Campos:
    - taxonomy: chave canônica (SIMPLE, SPLIT-IF, SPLIT-SWITCH, MERGE,
      LOOP-BATCH, WAIT-EVENT, SUBFLOW, ERROR-HANDLER). FK em
      workflow_steps.logic_pattern.
    - category: agrupamento UI (splitting, merging, looping, waiting,
      subworkflows, error-handling, simple).
    - engine_handler: nome do módulo Python que interpreta o pattern em
      runtime. Hoje só SIMPLE tem handler real (WorkflowEngine.advance);
      demais ficam 'pending' até Engine v2 implementar.
    - json_skeleton: skeleton n8n para referência educativa.
    """

    id: str
    category: str
    taxonomy: str
    name: str
    description: Optional[str] = None
    heuristics: List[str] = Field(default_factory=list)
    icon: Optional[str] = None
    color: Optional[str] = None
    display_order: int = 100
    json_skeleton: Optional[Dict[str, Any]] = None
    engine_handler: str = "pending"
    is_active: bool = True

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        for key in ("description", "icon", "color"):
            if d.get(key) is None:
                d[key] = ""
        return d


class AgentExecutionMode(CamelModel):
    """PR-EA/EB — catálogo canônico de modos de execução.

    Substitui CHECK hardcoded `('REALTIME','CRON','TRIGGER')` por tabela
    com `config_schema` declarado por modo (field descriptors). UI da tab
    Configuration lê e renderiza form condicional: ao selecionar modo, lê
    `config_schema` daquele modo e renderiza os campos filhos.
    """

    id: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    display_order: int = 100
    config_schema: List[Dict[str, Any]] = []
    is_active: bool = True

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        for key in ("description", "icon", "color"):
            if d.get(key) is None:
                d[key] = ""
        if d.get("configSchema") is None:
            d["configSchema"] = []
        return d


class AgentSpecialtyConfig(CamelModel):
    id: str
    company_id: str
    agent_id: str
    specialty_id: str
    values: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AgentSharedConfig(CamelModel):
    """Modelo C — PR-A/B: campos compartilhados entre specialties do agente.

    1 row por (company_id, agent_id). Substitui duplicação de fields
    `ofx_path`, `recipient`, `pdf_path`, `planner_instituicao` entre as
    specialties do Kronos (e padrão para os demais agentes futuramente).

    Cadeia de precedência no resolver (PR-C):
        payload (task.input_json)
            > specialty.values
            > agent_shared_config.values   ← este model
            > task.description KEY=VALUE
            > env vars

    `schema_` é o nome Python (sufixo evita colisão com BaseModel.schema()).
    O CamelModel.alias_generator converte automaticamente `schema_` → `schema`
    para entrada/saída JSON, alinhado com a coluna jsonb `schema` no DB.
    """

    id: str
    company_id: str
    agent_id: str
    values: Dict[str, Any]
    schema_: List[Dict[str, Any]] = []
    created_at: datetime
    updated_at: datetime

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        # `schema` jsonb pode vir None do DB se não foi seedado
        if d.get("schema") is None:
            d["schema"] = []
        if d.get("values") is None:
            d["values"] = {}
        return d


@dataclass(frozen=True)
class PortingBacklog:
    title: str
    modules: list[PortingModule] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        return [
            f'- {module.name} [{module.status}] — {module.responsibility} (from {module.source_hint})'
            for module in self.modules
        ]

# =====================================================================
# SIPOC Builder Models (VEC-246)
# =====================================================================

# =====================================================================
# Claude Managed Agents (CMA) Models
# =====================================================================

class ManagedAgentTurn(CamelModel):
    turn_number: int
    tool_used: Optional[str] = None
    tool_input: Optional[dict] = None
    output: str
    stop_reason: str
    created_at: datetime

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        if self.created_at:
            d["createdAt"] = self.created_at.isoformat().replace("+00:00", "Z")
        return d


class ExecutionMetadata(CamelModel):
    executor_type: str
    session_id: Optional[str] = None
    turns_executed: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    execution_time_seconds: float = 0.0
    started_at: datetime
    completed_at: Optional[datetime] = None

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        if self.started_at:
            d["startedAt"] = self.started_at.isoformat().replace("+00:00", "Z")
        if self.completed_at:
            d["completedAt"] = self.completed_at.isoformat().replace("+00:00", "Z")
        return d


class SipocCompany(CamelModel):
    id: str
    name: str
    logo_url: Optional[str] = None
    website: Optional[str] = None
    metadata: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime

    def to_zod_dict(self):
        return self.dict(by_alias=True)

class SipocSector(CamelModel):
    id: str
    company_id: str
    name: str
    slug: str
    icon: Optional[str] = None
    parent_sector_id: Optional[str] = None
    metadata: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime

    def to_zod_dict(self):
        return self.dict(by_alias=True)

class SipocPosition(CamelModel):
    id: str
    company_id: str
    sector_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    reports_to_id: Optional[str] = None
    metadata: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime

    def to_zod_dict(self):
        return self.dict(by_alias=True)

class SipocProcess(CamelModel):
    id: str
    sector_id: str
    position_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    status: Literal["rascunho", "em_revisao", "aprovado", "arquivado"] = "rascunho"
    version: int = 1
    responsible_id: Optional[str] = None
    metadata: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime

    def to_zod_dict(self):
        return self.dict(by_alias=True)

class SipocComponent(CamelModel):
    id: str
    process_id: str
    type: Literal["supplier", "input", "activity", "output", "customer"]
    content: Dict[str, Any]
    order: int = 0
    validation_status: Literal["verde", "amarelo", "vermelho"] = "verde"
    validation_notes: Optional[str] = None
    metadata: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime

    def to_zod_dict(self):
        return self.dict(by_alias=True)


class Project(CamelModel):
    id: str
    company_id: str
    name: str
    mission: Optional[str] = None
    status: str = "backlog"
    lead_agent_id: Optional[str] = None
    target_date: Optional[str] = None
    issue_completion_pct: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_zod_dict(self):
        return self.dict(by_alias=True)


class Run(CamelModel):
    id: str
    company_id: str
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    status: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0

    @validator('cost_usd', pre=True)
    def coerce_cost(cls, v):
        try:
            return float(v) if v is not None else 0.0
        except Exception:
            return 0.0

    def to_zod_dict(self):
        return self.dict(by_alias=True)


class RunTranscriptEntry(CamelModel):
    id: str
    run_id: str
    role: Optional[str] = None
    content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_output: Optional[str] = None
    created_at: Optional[datetime] = None

    def to_zod_dict(self):
        return self.dict(by_alias=True)


# =====================================================================
# Prospect Profiles (VEC-334)
# =====================================================================

class DecisionMaker(BaseModel):
    nome: str
    cargo: Optional[str] = None
    email: Optional[str] = None
    linkedin: Optional[str] = None
    instagram: Optional[str] = None
    fonte: Optional[str] = None


class ProspectProfile(CamelModel):
    id: str
    company_id: str
    nome_razao_social: Optional[str] = None
    cnpj: Optional[str] = None
    website: Optional[str] = None
    setor: Optional[str] = None
    endereco: Optional[Dict[str, Any]] = None
    telefone: Optional[str] = None
    email_contato: Optional[str] = None
    decisores: Optional[List[Dict[str, Any]]] = None
    source_task_id: Optional[str] = None
    enriched_at: Optional[str] = None
    raw_research: Optional[str] = None
    artifacts: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # Pesquisa Oracle (VEC-XXX)
    tipo: Optional[str] = None
    linkedin_url: Optional[str] = None
    instagram_handle: Optional[str] = None
    extra_urls: Optional[List[Dict[str, Any]]] = None
    cnpj_lookup_data: Optional[Dict[str, Any]] = None
    qsa: Optional[List[Dict[str, Any]]] = None
    research_template_id: Optional[str] = None
    research_status: Optional[str] = None
    research_progress: Optional[Dict[str, Any]] = None
    research_cron_expr: Optional[str] = None
    next_research_at: Optional[str] = None
    last_research_at: Optional[str] = None

    def to_zod_dict(self):
        d = self.dict(by_alias=True)
        return d


# =====================================================================
# Research Templates (VEC-XXX) — prompts editáveis para oracle-research
# =====================================================================

class ResearchTemplate(CamelModel):
    id: str
    company_id: Optional[str] = None  # NULL = template global default
    slug: str
    name: str
    description: Optional[str] = None
    prompt_template: str
    output_sections: List[str] = []
    default_urls: List[str] = []
    require_review: bool = True
    active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_zod_dict(self):
        return self.dict(by_alias=True)
