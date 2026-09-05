from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class IncidentSeverity(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class IncidentStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class EvidenceType(StrEnum):
    LOG = "log"
    METRIC = "metric"
    DATABASE = "database"
    CODE = "code"
    DEPLOYMENT = "deployment"
    DOCUMENTATION = "documentation"
    DIAGNOSTIC = "diagnostic"
    VERIFICATION = "verification"


class HypothesisStatus(StrEnum):
    ACTIVE = "active"
    REJECTED = "rejected"
    CONFIRMED = "confirmed"


class ToolCallStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class AgentRunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget_exhausted"


class RiskLevel(StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


class VerificationStatus(StrEnum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class Incident(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    severity: IncidentSeverity
    service: str = Field(min_length=1, max_length=120)
    start_time: datetime
    status: IncidentStatus = IncidentStatus.OPEN
    scenario_id: str | None = None


class Evidence(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    source: str = Field(min_length=1, max_length=120)
    evidence_type: EvidenceType
    service: str | None = None
    timestamp: datetime
    observation: str = Field(min_length=1)
    raw_reference: str | None = None
    reliability: float = Field(default=1.0, ge=0.0, le=1.0)


class Hypothesis(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    description: str = Field(min_length=1)
    root_cause_code: str = Field(min_length=1, max_length=120)
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence: list[UUID] = Field(default_factory=list)
    contradicting_evidence: list[UUID] = Field(default_factory=list)
    first_possible_cause_time: datetime | None = None
    effect_time: datetime | None = None
    status: HypothesisStatus = HypothesisStatus.ACTIVE

    @model_validator(mode="after")
    def validate_temporal_order(self) -> "Hypothesis":
        if (
            self.first_possible_cause_time is not None
            and self.effect_time is not None
            and self.first_possible_cause_time > self.effect_time
        ):
            raise ValueError("first_possible_cause_time must not be after effect_time")
        return self


class ToolCall(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    tool_name: str = Field(min_length=1, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    status: ToolCallStatus = ToolCallStatus.PENDING
    result_reference: str | None = None
    risk_level: RiskLevel

    @model_validator(mode="after")
    def validate_completion_time(self) -> "ToolCall":
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at must not be before started_at")
        return self


class AgentRun(StrictModel):
    run_id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    architecture_version: str = Field(min_length=1)
    model: str = Field(min_length=1)
    step_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    token_usage: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0.0, ge=0.0)
    status: AgentRunStatus = AgentRunStatus.CREATED


class Diagnosis(StrictModel):
    primary_root_cause: str = Field(min_length=1)
    secondary_root_causes: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[UUID] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.NOT_RUN
