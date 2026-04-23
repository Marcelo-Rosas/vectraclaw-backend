from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal, Any, Dict, List
from pydantic import BaseModel, validator

def to_camel(string: str) -> str:
    words = string.split('_')
    return words[0] + ''.join(word.capitalize() for word in words[1:])

class CamelModel(BaseModel):
    class Config:
        alias_generator = to_camel
        allow_population_by_field_name = True

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
        "other",
    ] = "other"
    budget_limit: int
    spent: float
    cost_usd: float = 0.0
    claimed_at: Optional[datetime] = None
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

    @validator('assigned_to_agent_id', 'parent_task_id', 'goal_id', pre=True)
    def empty_to_none(cls, v):
        if v == "":
            return None
        return v

    def to_zod_dict(self):
        """
        Dumping Customizado. 
        IMPORTANTE: Zod no frontend não tolera 'updatedAt' na Task. 
        Removendo explicitamente.
        """
        d = self.dict(by_alias=True)
        # Formatação ISO Z
        if self.claimed_at:
            d["claimedAt"] = self.claimed_at.isoformat().replace("+00:00", "Z")
        if self.created_at:
            d["createdAt"] = self.created_at.isoformat().replace("+00:00", "Z")
        
        # Excluir updatedAt para não quebrar o frontend (VEC-192 §3)
        if "updatedAt" in d:
            del d["updatedAt"]
            
        return d

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
    metadata: Optional[dict] = None
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
        return self.dict(by_alias=True)


class AgentSpecialty(CamelModel):
    id: str
    name: str
    slug: str
    domain: str
    description: Optional[str] = None
    compatible_roles: List[str]
    is_active: bool

    def to_zod_dict(self):
        return self.dict(by_alias=True)


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
