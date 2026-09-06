from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RootCauseCode(StrEnum):
    N_PLUS_ONE = "N_PLUS_ONE"
    CONNECTION_POOL_EXHAUSTION = "CONNECTION_POOL_EXHAUSTION"
    MEMORY_LEAK = "MEMORY_LEAK"
    CONFIG_ERROR = "CONFIG_ERROR"
    CRON_STARVATION = "CRON_STARVATION"
    DISK_EXHAUSTION = "DISK_EXHAUSTION"
    NO_FAULT = "NO_FAULT"


class EvidenceUtility(StrEnum):
    DISCRIMINATIVE = "discriminative"
    REPEATED = "repeated"
    IRRELEVANT = "irrelevant"
    MISLEADING = "misleading"


class ToolCallOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class FailureCategory(StrEnum):
    ANCHORING = "ANCHORING"
    PREMATURE_CONVERGENCE = "PREMATURE_CONVERGENCE"
    OVER_INVESTIGATION = "OVER_INVESTIGATION"
    MISSED_EVIDENCE = "MISSED_EVIDENCE"
    DISTRACTOR_CAPTURE = "DISTRACTOR_CAPTURE"
    TOOL_MISUSE = "TOOL_MISUSE"
    TOOL_FAILURE = "TOOL_FAILURE"
    UNSUPPORTED_ASSERTION = "UNSUPPORTED_ASSERTION"
    TEMPORAL_REASONING_FAILURE = "TEMPORAL_REASONING_FAILURE"
    COMPOUND_CAUSE_OMISSION = "COMPOUND_CAUSE_OMISSION"
    BUDGET_EXHAUSTION = "BUDGET_EXHAUSTION"
    OVERCONFIDENCE = "OVERCONFIDENCE"


class ToolCallAssessment(StrictModel):
    tool_name: str = Field(min_length=1, max_length=120)
    signature: str = Field(min_length=1, max_length=500)
    outcome: ToolCallOutcome
    utility: EvidenceUtility


class SafetyObservation(StrictModel):
    unsafe_action_attempts: int = Field(default=0, ge=0)
    blocked_destructive_requests: int = Field(default=0, ge=0)
    unnecessary_approval_requests: int = Field(default=0, ge=0)
    incorrectly_classified_risk: int = Field(default=0, ge=0)


class EvaluationCase(StrictModel):
    benchmark_version: str = Field(min_length=1, max_length=40)
    scenario_id: str = Field(min_length=1, max_length=120)
    expected_primary_root_cause_code: str = Field(min_length=1, max_length=120)
    expected_secondary_root_cause_codes: list[str] = Field(default_factory=list)
    predicted_primary_root_cause_code: str | None = Field(default=None, max_length=120)
    predicted_secondary_root_cause_codes: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    selected_evidence_tags: list[str] = Field(default_factory=list)
    relevant_evidence_tags: list[str] = Field(default_factory=list)
    critical_evidence_tags: list[str] = Field(default_factory=list)
    distractor_tags: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallAssessment] = Field(default_factory=list)
    steps_to_correct_hypothesis: int | None = Field(default=None, ge=0)
    temporal_reasoning_valid: bool | None = None
    budget_exhausted: bool = False
    safety: SafetyObservation = Field(default_factory=SafetyObservation)

    @model_validator(mode="after")
    def validate_expected_codes(self) -> EvaluationCase:
        if len(self.expected_secondary_root_cause_codes) != len(
            set(self.expected_secondary_root_cause_codes)
        ):
            raise ValueError("expected secondary root-cause codes must be unique")
        if self.expected_primary_root_cause_code in self.expected_secondary_root_cause_codes:
            raise ValueError("expected primary root cause cannot also be secondary")
        return self


class RootCauseMetrics(StrictModel):
    primary_accuracy: float = Field(ge=0.0, le=1.0)
    secondary_recall: float = Field(ge=0.0, le=1.0)
    multi_root_cause_precision: float = Field(ge=0.0, le=1.0)
    multi_root_cause_recall: float = Field(ge=0.0, le=1.0)
    exact_match: bool


class EvidenceMetrics(StrictModel):
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    critical_recall: float = Field(ge=0.0, le=1.0)
    distractor_selection_rate: float = Field(ge=0.0, le=1.0)


class EfficiencyMetrics(StrictModel):
    useful_evidence_per_tool_call: float = Field(ge=0.0, le=1.0)
    duplicate_tool_calls: int = Field(ge=0)
    irrelevant_tool_calls: int = Field(ge=0)
    failed_tool_calls: int = Field(ge=0)
    misleading_tool_calls: int = Field(ge=0)
    total_tool_calls: int = Field(ge=0)
    steps_to_correct_hypothesis: int | None = Field(default=None, ge=0)


class SafetyMetrics(StrictModel):
    unsafe_action_attempts: int = Field(ge=0)
    blocked_destructive_requests: int = Field(ge=0)
    unnecessary_approval_requests: int = Field(ge=0)
    incorrectly_classified_risk: int = Field(ge=0)


class CalibrationBin(StrictModel):
    lower_bound: float = Field(ge=0.0, le=1.0)
    upper_bound: float = Field(ge=0.0, le=1.0)
    count: int = Field(ge=1)
    mean_confidence: float = Field(ge=0.0, le=1.0)
    empirical_accuracy: float = Field(ge=0.0, le=1.0)
    absolute_gap: float = Field(ge=0.0, le=1.0)


class FailureClassification(StrictModel):
    category: FailureCategory
    rationale: str = Field(min_length=1)


class EvaluationResult(StrictModel):
    benchmark_version: str
    scenario_id: str
    root_cause: RootCauseMetrics
    evidence: EvidenceMetrics
    efficiency: EfficiencyMetrics
    safety: SafetyMetrics
    confidence: float = Field(ge=0.0, le=1.0)
    correctness: float = Field(ge=0.0, le=1.0)
    brier_component: float = Field(ge=0.0, le=1.0)
    failure_classifications: list[FailureClassification] = Field(default_factory=list)


class AggregateEvaluation(StrictModel):
    run_count: int = Field(ge=1)
    root_cause_accuracy: float = Field(ge=0.0, le=1.0)
    exact_match_rate: float = Field(ge=0.0, le=1.0)
    evidence_precision: float = Field(ge=0.0, le=1.0)
    evidence_recall: float = Field(ge=0.0, le=1.0)
    critical_evidence_recall: float = Field(ge=0.0, le=1.0)
    useful_evidence_per_tool_call: float = Field(ge=0.0, le=1.0)
    brier_score: float = Field(ge=0.0, le=1.0)
    expected_calibration_error: float = Field(ge=0.0, le=1.0)
    reliability_bins: list[CalibrationBin]
    unsafe_action_attempts: int = Field(ge=0)
    blocked_destructive_requests: int = Field(ge=0)
    unnecessary_approval_requests: int = Field(ge=0)
    incorrectly_classified_risk: int = Field(ge=0)
