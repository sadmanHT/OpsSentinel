from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

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


class OperationStage(StrEnum):
    NONE = "none"
    ASSESS_ACTION = "assess_action"
    WAIT_APPROVAL = "wait_approval"
    EXECUTE_ACTION = "execute_action"
    VERIFY = "verify"
    COMPLETE = "complete"


class ApprovalDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ABANDONED = "abandoned"


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
    tool: str | None = Field(default=None, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)
    expected_benefit: str = "Restore the affected sandbox service to a healthy state."
    possible_risk: str = "The reversible sandbox action may interrupt in-flight test traffic."
    rollback_strategy: str = "Restore the previous sandbox state or reinject the scenario if needed."


class ApprovalRequest(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    action: ProposedAction
    why_proposed: str = Field(min_length=1)
    evidence_ids: list[UUID] = Field(min_length=1)
    expected_benefit: str = Field(min_length=1)
    possible_risk: str = Field(min_length=1)
    rollback_strategy: str = Field(min_length=1)
    decision: ApprovalDecision = ApprovalDecision.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    decided_at: datetime | None = None
    decided_by: str | None = Field(default=None, max_length=120)


class ApprovalDecisionRequest(StrictModel):
    decision: ApprovalDecision
    actor: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def reject_pending_decision(self) -> ApprovalDecisionRequest:
        if self.decision == ApprovalDecision.PENDING:
            raise ValueError("approval decision must be approved, rejected, or abandoned")
        return self


class ToolFailureRecord(StrictModel):
    tool: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False
    attempt: int = Field(default=1, ge=1)
    recorded_at: datetime = Field(default_factory=utc_now)


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
    operational_mode: bool = False
    operation_stage: OperationStage = OperationStage.NONE
    plan: InvestigationPlan | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    tool_history: list[ToolCall] = Field(default_factory=list)
    current_hypothesis: UUID | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    budget: AgentBudget
    proposed_action: ProposedAction | None = None
    approval: ApprovalRequest | None = None
    verification: VerificationResult = Field(
        default_factory=lambda: VerificationResult(summary="No verification has been run.")
    )
    action_response: ToolResponse | None = None
    failures: list[ToolFailureRecord] = Field(default_factory=list)
    retry_counts: dict[str, int] = Field(default_factory=dict)
    non_progress_count: int = Field(default=0, ge=0)
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
    operational_mode: bool = False

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
    operational_mode: bool
    operation_stage: OperationStage
    plan: InvestigationPlan | None
    evidence: list[Evidence]
    hypotheses: list[Hypothesis]
    tool_history: list[ToolCall]
    confidence: float
    budget: AgentBudget
    proposed_action: ProposedAction | None
    approval: ApprovalRequest | None
    verification: VerificationResult
    failures: list[ToolFailureRecord]
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
            operational_mode=state.operational_mode,
            operation_stage=state.operation_stage,
            plan=state.plan,
            evidence=state.evidence,
            hypotheses=state.hypotheses,
            tool_history=state.tool_history,
            confidence=state.confidence,
            budget=state.budget,
            proposed_action=state.proposed_action,
            approval=state.approval,
            verification=state.verification,
            failures=state.failures,
            diagnosis_code=state.diagnosis_code,
            final_diagnosis=state.final_diagnosis,
            report=state.report,
            stop_reason=state.stop_reason,
        )
