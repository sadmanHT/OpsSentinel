from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from app.models.domain import StrictModel, utc_now


class ModelOperation(StrEnum):
    PLAN = "plan"
    UPDATE_HYPOTHESES = "update_hypotheses"
    ENOUGH_EVIDENCE = "enough_evidence"
    DIAGNOSE = "diagnose"
    RECOMMEND = "recommend"


class ModelExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ModelExecutionEvent(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    operation: ModelOperation
    provider: str = Field(min_length=1, max_length=160)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0.0, ge=0.0)
    latency_ms: float = Field(ge=0.0)
    status: ModelExecutionStatus = ModelExecutionStatus.SUCCEEDED
    error_type: str | None = Field(default=None, max_length=160)
    recorded_at: datetime = Field(default_factory=utc_now)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LatencyDistribution(StrictModel):
    count: int = Field(ge=0)
    p50_ms: float | None = Field(default=None, ge=0.0)
    p95_ms: float | None = Field(default=None, ge=0.0)


class RunCostSummary(StrictModel):
    run_id: UUID
    status: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    model_execution_count: int = Field(ge=0)
    failed_model_execution_count: int = Field(ge=0)
    usage_breakdown_available: bool
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    provider_estimated_cost: float = Field(ge=0.0)
    total_estimated_cost: float = Field(ge=0.0)
    tool_call_count: int = Field(ge=0)
    retrieval_depth: int = Field(ge=0)
    model_latency: LatencyDistribution
    tool_latency: LatencyDistribution
    time_to_first_investigation_step_ms: float | None = Field(default=None, ge=0.0)
    time_to_diagnosis_ms: float | None = Field(default=None, ge=0.0)
    time_to_verified_resolution_ms: float | None = Field(default=None, ge=0.0)
