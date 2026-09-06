from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from app.mcp.models import ToolInvocation, ToolResponse
from app.models.domain import (
    AgentRunStatus,
    Diagnosis,
    Evidence,
    Hypothesis,
    Incident,
    RiskLevel,
    StrictModel,
    ToolCall,
    VerificationStatus,
    utc_now,
)


class AgentNode(StrEnum):
    TRIAGE = "triage"
    PLAN = "plan"
    SELECT_TOOL = "select_tool"
    EXECUTE_TOOL = "execute_tool"
    STORE_EVIDENCE = "store_evidence"
    UPDATE_HYPOTHESIS = "update_hypothesis"
    ENOUGH_EVIDENCE = "enough_evidence"
    DIAGNOSE = "diagnose"
    RECOMMEND = "recommend"
    REPORT = "report"
    END = "end"


class PlanStep(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    objective: str = Field(min_length=1)
    tool: str = Field(min_length=1, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(min_length=1)
    required: bool = True
    completed: bool = False


class InvestigationPlan(StrictModel):
    summary: str = Field(min_length=1)
    steps: list[PlanStep] = Field(min_length=1)


class AgentBudget(StrictModel):
    max_steps: int = Field(default=20, ge=1, le=200)
    max_tool_calls: int = Field(default=15, ge=1, le=200)
    max_repeated_identical_calls: int = Field(default=2, ge=1, le=20)
    time_limit_seconds: float = Field(default=120.0, gt=0.0, le=3600.0)
    token_budget: int = Field(default=32_000, ge=0)
    cost_budget: float = Field(default=0.0, ge=0.0)
    steps_used: int = Field(default=0, ge=0)
    tool_calls_used: int = Field(default=0, ge=0)
    tokens_used: int = Field(default=0, ge=0)
    cost_used: float = Field(default=0.0, ge=0.0)
    repeated_calls: dict[str, int] = Field(default_factory=dict)
    exhausted_reason: str | None = None


class ProviderUsage(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0.0, ge=0.0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ProposedAction(StrictModel):
    description: str = Field(min_length=1)
    risk_level: RiskLevel
    rationale: str = Field(min_length=1)
    evidence_ids: list[UUID] = Field(min_length=1)


class VerificationResult(StrictModel):
    status: VerificationStatus = VerificationStatus.NOT_RUN
    summary: str = Field(min_length=1)
    evidence_ids: list[UUID] = Field(default_factory=list)


class GroundedClaim(StrictModel):
    statement: str = Field(min_length=1)
    evidence_ids: list[UUID] = Field(min_length=1)


class AgentReport(StrictModel):
    run_id: UUID
    status: AgentRunStatus
    root_cause_code: str = Field(min_length=1, max_length=120)
    diagnosis: Diagnosis
    claims: list[GroundedClaim]
    proposed_action: ProposedAction | None = None
    verification: VerificationResult
    generated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def require_grounded_factual_claims(self) -> AgentReport:
        if self.status == AgentRunStatus.COMPLETED and not self.claims:
            raise ValueError("completed reports must contain at least one grounded claim")
        diagnosis_evidence = set(self.diagnosis.evidence_ids)
        for claim in self.claims:
            if not set(claim.evidence_ids).issubset(diagnosis_evidence):
                raise ValueError("claim evidence must be included in diagnosis evidence")
        return self


class AgentState(StrictModel):
    run_id: UUID
    incident: Incident
    status: AgentRunStatus = AgentRunStatus.CREATED
    next_node: AgentNode = AgentNode.TRIAGE
    plan: InvestigationPlan | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    tool_history: list[ToolCall] = Field(default_factory=list)
    current_hypothesis: UUID | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    budget: AgentBudget
    proposed_action: ProposedAction | None = None
    verification: VerificationResult = Field(
        default_factory=lambda: VerificationResult(
            summary="No verification has been run in Phase 4."
        )
    )
    diagnosis_code: str | None = None
    final_diagnosis: Diagnosis | None = None
    report: AgentReport | None = None
    pending_tool: ToolInvocation | None = None
    pending_response: ToolResponse | None = None
    started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    stop_reason: str | None = None


class StartInvestigationRequest(StrictModel):
    incident: Incident
    budget: AgentBudget | None = None
    pause_after: AgentNode | None = None

    @model_validator(mode="after")
    def validate_pause_target(self) -> StartInvestigationRequest:
        if self.pause_after == AgentNode.END:
            raise ValueError("pause_after must name an executable graph node")
        return self


class AgentRunView(StrictModel):
    run_id: UUID
    incident: Incident
    status: AgentRunStatus
    next_node: AgentNode
    plan: InvestigationPlan | None
    evidence: list[Evidence]
    hypotheses: list[Hypothesis]
    tool_history: list[ToolCall]
    confidence: float
    budget: AgentBudget
    diagnosis_code: str | None
    final_diagnosis: Diagnosis | None
    report: AgentReport | None
    stop_reason: str | None

    @classmethod
    def from_state(cls, state: AgentState) -> AgentRunView:
        return cls(
            run_id=state.run_id,
            incident=state.incident,
            status=state.status,
            next_node=state.next_node,
            plan=state.plan,
            evidence=state.evidence,
            hypotheses=state.hypotheses,
            tool_history=state.tool_history,
            confidence=state.confidence,
            budget=state.budget,
            diagnosis_code=state.diagnosis_code,
            final_diagnosis=state.final_diagnosis,
            report=state.report,
            stop_reason=state.stop_reason,
        )
