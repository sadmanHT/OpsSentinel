from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ExperimentKind(StrEnum):
    PLANNING_DIFFICULTY = "planning_difficulty"
    INVESTIGATION_BUDGET = "investigation_budget"
    TOOL_ORDER = "tool_order"
    PASSIVE_VS_VERIFICATION = "passive_vs_verification"
    TEMPORAL_REASONING = "temporal_reasoning"
    COMPOUND_HANDLING = "compound_handling"


class ExperimentSplit(StrEnum):
    DEV = "dev"
    VALIDATION = "validation"
    HIDDEN_TEST = "hidden_test"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    ADVERSARIAL = "adversarial"
    COMPOUND = "compound"


class ArchitectureVariant(StrEnum):
    REACTIVE_REACT = "reactive_react"
    EXPLICIT_PLANNER = "explicit_planner"


class ToolOrderVariant(StrEnum):
    FREE = "free"
    DEPLOYMENT_FIRST = "deployment_first"
    SYMPTOM_FIRST = "symptom_first"
    ADAPTIVE = "adaptive"


class EvidenceMode(StrEnum):
    PASSIVE_ONLY = "passive_only"
    VERIFICATION_ENABLED = "verification_enabled"


class TemporalReasoningVariant(StrEnum):
    STANDARD = "standard"
    EXPLICIT_CAUSE_EFFECT = "explicit_cause_effect"


class StoppingStrategy(StrEnum):
    CONFIDENCE_THRESHOLD = "confidence_threshold"
    UNRESOLVED_EVIDENCE = "unresolved_evidence"


class ResearchConfiguration(StrictModel):
    architecture: ArchitectureVariant = ArchitectureVariant.EXPLICIT_PLANNER
    tool_budget: int = Field(default=15, ge=1, le=200)
    tool_order: ToolOrderVariant = ToolOrderVariant.FREE
    evidence_mode: EvidenceMode = EvidenceMode.PASSIVE_ONLY
    temporal_reasoning: TemporalReasoningVariant = TemporalReasoningVariant.STANDARD
    stopping_strategy: StoppingStrategy = StoppingStrategy.CONFIDENCE_THRESHOLD
    provider: str = Field(default="local", min_length=1, max_length=80)
    model: str = Field(default="local-placeholder", min_length=1, max_length=120)
    prompt_version: str = Field(default="phase8-v1", min_length=1, max_length=80)

    def isolation_payload(self) -> dict[str, object]:
        return self.model_dump(mode="python")


EXPERIMENT_DIMENSION: dict[ExperimentKind, str] = {
    ExperimentKind.PLANNING_DIFFICULTY: "architecture",
    ExperimentKind.INVESTIGATION_BUDGET: "tool_budget",
    ExperimentKind.TOOL_ORDER: "tool_order",
    ExperimentKind.PASSIVE_VS_VERIFICATION: "evidence_mode",
    ExperimentKind.TEMPORAL_REASONING: "temporal_reasoning",
    ExperimentKind.COMPOUND_HANDLING: "stopping_strategy",
}


class ExperimentCell(StrictModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=160)
    configuration: ResearchConfiguration
    difficulties: list[Difficulty] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_difficulties(self) -> ExperimentCell:
        if len(self.difficulties) != len(set(self.difficulties)):
            raise ValueError("experiment cell difficulties must be unique")
        return self


class ExperimentPlan(StrictModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    experiment: ExperimentKind
    hypothesis_id: str = Field(min_length=2, max_length=20)
    dataset_version: str = Field(min_length=1, max_length=80)
    split: ExperimentSplit
    cells: list[ExperimentCell] = Field(min_length=2)
    repeat_count: int = Field(default=1, ge=1, le=100)
    seed_base: int = Field(default=8000, ge=0)

    @model_validator(mode="after")
    def validate_controlled_comparison(self) -> ExperimentPlan:
        ids = [cell.id for cell in self.cells]
        if len(ids) != len(set(ids)):
            raise ValueError("experiment cell ids must be unique")

        target = EXPERIMENT_DIMENSION[self.experiment]
        first = self.cells[0].configuration.isolation_payload()
        target_values: set[object] = set()

        for cell in self.cells:
            payload = cell.configuration.isolation_payload()
            target_values.add(payload[target])
            for key, value in first.items():
                if key == target:
                    continue
                if payload[key] != value:
                    raise ValueError(
                        f"{self.experiment.value} may vary only {target}; "
                        f"cell {cell.id} also changes {key}"
                    )

        if len(target_values) < 2:
            raise ValueError(
                f"{self.experiment.value} must contain at least two distinct {target} values"
            )

        if self.experiment == ExperimentKind.COMPOUND_HANDLING:
            if any(cell.difficulties != [Difficulty.COMPOUND] for cell in self.cells):
                raise ValueError("compound handling cells must target only compound incidents")
        return self


class ScenarioRef(StrictModel):
    scenario_id: str = Field(min_length=1, max_length=120)
    split: ExperimentSplit
    difficulty: Difficulty


class TrialIdentity(StrictModel):
    trial_id: UUID
    plan_id: str
    experiment: ExperimentKind
    cell_id: str
    scenario_id: str
    repeat_index: int = Field(ge=0)
    seed: int = Field(ge=0)


def _stable_seed(seed_base: int, key: str) -> int:
    digest = hashlib.sha256(f"{seed_base}:{key}".encode()).digest()
    return seed_base + int.from_bytes(digest[:4], "big")


def make_trial_identity(
    plan: ExperimentPlan,
    cell: ExperimentCell,
    scenario: ScenarioRef,
    repeat_index: int,
) -> TrialIdentity:
    if repeat_index < 0 or repeat_index >= plan.repeat_count:
        raise ValueError("repeat_index is outside the plan repeat_count")
    if scenario.split != plan.split:
        raise ValueError(
            f"scenario {scenario.scenario_id} belongs to {scenario.split.value}, "
            f"not plan split {plan.split.value}"
        )
    if scenario.difficulty not in cell.difficulties:
        raise ValueError(
            f"scenario {scenario.scenario_id} difficulty {scenario.difficulty.value} "
            f"is not enabled for cell {cell.id}"
        )
    key = f"{plan.id}:{cell.id}:{scenario.scenario_id}:{repeat_index}"
    return TrialIdentity(
        trial_id=uuid5(NAMESPACE_URL, f"opssentinel:phase8:{key}"),
        plan_id=plan.id,
        experiment=plan.experiment,
        cell_id=cell.id,
        scenario_id=scenario.scenario_id,
        repeat_index=repeat_index,
        seed=_stable_seed(plan.seed_base, key),
    )


class TrialStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class TrialOutcome(StrictModel):
    evaluation_run_id: UUID | None = None
    agent_run_id: UUID | None = None
    raw_trajectory: dict[str, Any] = Field(default_factory=dict)
    scores: dict[str, float] = Field(default_factory=dict)


class TrialRecord(StrictModel):
    identity: TrialIdentity
    status: TrialStatus = TrialStatus.PENDING
    evaluation_run_id: UUID | None = None
    agent_run_id: UUID | None = None
    raw_trajectory: dict[str, Any] = Field(default_factory=dict)
    scores: dict[str, float] = Field(default_factory=dict)
    error: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_terminal_payload(self) -> TrialRecord:
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("trial record updated_at must be timezone-aware")
        if self.status == TrialStatus.COMPLETED and self.error is not None:
            raise ValueError("completed trials cannot contain an error")
        if self.status in {TrialStatus.FAILED, TrialStatus.INTERRUPTED} and not self.error:
            raise ValueError("failed or interrupted trials must contain an error")
        return self
