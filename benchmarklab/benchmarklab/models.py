from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    ADVERSARIAL = "adversarial"
    COMPOUND = "compound"


class BenchmarkSplit(StrEnum):
    DEV = "dev"
    VALIDATION = "validation"
    HIDDEN_TEST = "hidden_test"


class ScenarioKind(StrEnum):
    STANDARD = "standard"
    TEMPORAL = "temporal"
    ADVERSARIAL = "adversarial"
    COMPOUND = "compound"
    COUNTERFACTUAL = "counterfactual"


class ServiceName(StrEnum):
    GATEWAY = "gateway"
    CHECKOUT = "checkout"
    INVENTORY = "inventory"
    PAYMENT = "payment"
    WORKER = "worker"


class FaultKind(StrEnum):
    N_PLUS_ONE = "n_plus_one"
    CONNECTION_LEAK = "connection_leak"
    DISK_EXHAUSTION = "disk_exhaustion"
    BROKEN_CONFIG = "broken_config"
    MEMORY_LEAK = "memory_leak"


class IncidentSeverity(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class CausalRole(StrEnum):
    CAUSE = "cause"
    EFFECT = "effect"
    DISTRACTOR = "distractor"
    CONTEXT = "context"


FAULT_TARGETS: dict[FaultKind, set[ServiceName]] = {
    FaultKind.N_PLUS_ONE: {ServiceName.CHECKOUT},
    FaultKind.CONNECTION_LEAK: {ServiceName.CHECKOUT, ServiceName.INVENTORY},
    FaultKind.DISK_EXHAUSTION: set(ServiceName),
    FaultKind.BROKEN_CONFIG: {ServiceName.PAYMENT},
    FaultKind.MEMORY_LEAK: set(ServiceName),
}

FAULT_RCA_CODES: dict[FaultKind, str] = {
    FaultKind.N_PLUS_ONE: "n_plus_one_query",
    FaultKind.CONNECTION_LEAK: "database_connection_leak",
    FaultKind.DISK_EXHAUSTION: "disk_exhaustion",
    FaultKind.BROKEN_CONFIG: "broken_payment_configuration",
    FaultKind.MEMORY_LEAK: "memory_leak",
}

LEAKAGE_ALIASES: dict[FaultKind, tuple[str, ...]] = {
    FaultKind.N_PLUS_ONE: ("n_plus_one", "n+1", "n plus one"),
    FaultKind.CONNECTION_LEAK: ("connection_leak", "connection leak"),
    FaultKind.DISK_EXHAUSTION: ("disk_exhaustion", "disk exhaustion"),
    FaultKind.BROKEN_CONFIG: ("broken_config", "broken config", "broken configuration"),
    FaultKind.MEMORY_LEAK: ("memory_leak", "memory leak"),
}


class PublicIncident(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    severity: IncidentSeverity
    service: ServiceName
    start_time: datetime
    scenario_id: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def require_timezone(self) -> PublicIncident:
        if self.start_time.tzinfo is None or self.start_time.utcoffset() is None:
            raise ValueError("public incident start_time must be timezone-aware")
        return self


class FaultInjection(StrictModel):
    fault: FaultKind
    service: ServiceName
    severity: IncidentSeverity = IncidentSeverity.P2
    seed: int = Field(default=42, ge=0)
    configuration: dict[str, Any] = Field(default_factory=dict)
    offset_seconds: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def validate_fault_target(self) -> FaultInjection:
        if self.service not in FAULT_TARGETS[self.fault]:
            raise ValueError(f"{self.fault.value} is not supported for {self.service.value}")
        return self


class Stimulus(StrictModel):
    service: ServiceName
    method: Literal["GET", "POST"]
    path: str = Field(min_length=1, max_length=240, pattern=r"^/")
    count: int = Field(default=1, ge=1, le=100)
    expected_status: int | None = Field(default=None, ge=100, le=599)
    offset_seconds: float = Field(default=0.0, ge=0.0)


class TimelineEvent(StrictModel):
    event_id: str = Field(min_length=1, max_length=80)
    offset_seconds: float = Field(ge=0.0)
    role: CausalRole
    summary: str = Field(min_length=1)
    root_cause_code: str | None = Field(default=None, max_length=120)


class StructuralIdentity(StrictModel):
    failure_structure: str = Field(min_length=1, max_length=120)
    template_family: str = Field(min_length=1, max_length=120)
    combination_family: str | None = Field(default=None, max_length=120)
    counterfactual_family: str | None = Field(default=None, max_length=120)
    counterfactual_variant: str | None = Field(default=None, max_length=80)


class GroundTruth(StrictModel):
    primary_root_cause_code: str = Field(min_length=1, max_length=120)
    secondary_root_cause_codes: list[str] = Field(default_factory=list)
    causal_attribution: str = Field(min_length=1)
    critical_evidence_tags: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_secondary_codes(self) -> GroundTruth:
        if len(self.secondary_root_cause_codes) != len(set(self.secondary_root_cause_codes)):
            raise ValueError("secondary_root_cause_codes must be unique")
        if self.primary_root_cause_code in self.secondary_root_cause_codes:
            raise ValueError("primary root cause cannot also be secondary")
        return self


class AgentBudgetSpec(StrictModel):
    max_steps: int = Field(default=20, ge=1, le=200)
    max_tool_calls: int = Field(default=15, ge=1, le=200)
    time_limit_seconds: float = Field(default=120.0, gt=0.0, le=3600.0)


class ScenarioSpec(StrictModel):
    scenario_id: str = Field(min_length=1, max_length=120)
    scenario_version: str = Field(default="1.0.0", min_length=1, max_length=40)
    difficulty: Difficulty
    split: BenchmarkSplit
    kind: ScenarioKind
    seed: int = Field(default=42, ge=0)
    public_incident: PublicIncident
    structure: StructuralIdentity
    faults: list[FaultInjection] = Field(default_factory=list)
    stimuli: list[Stimulus] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(min_length=1)
    ground_truth: GroundTruth
    distractor_tags: list[str] = Field(default_factory=list)
    budget: AgentBudgetSpec = Field(default_factory=AgentBudgetSpec)

    @model_validator(mode="after")
    def validate_scenario_contract(self) -> ScenarioSpec:
        if self.public_incident.scenario_id != self.scenario_id:
            raise ValueError("public incident scenario_id must match scenario_id")

        expected_codes = {
            self.ground_truth.primary_root_cause_code,
            *self.ground_truth.secondary_root_cause_codes,
        }
        if self.faults:
            fault_codes = {FAULT_RCA_CODES[item.fault] for item in self.faults}
            if not expected_codes.issubset(fault_codes):
                raise ValueError("ground-truth RCA codes must be explained by injected faults")
        elif self.kind != ScenarioKind.COUNTERFACTUAL:
            raise ValueError("only counterfactual scenarios may omit injected faults")
        elif expected_codes != {"no_fault"}:
            raise ValueError("fault-free counterfactual scenarios must use no_fault ground truth")

        if self.difficulty == Difficulty.COMPOUND or self.kind == ScenarioKind.COMPOUND:
            if self.difficulty != Difficulty.COMPOUND or self.kind != ScenarioKind.COMPOUND:
                raise ValueError("compound difficulty and kind must be used together")
            if len(self.faults) < 2:
                raise ValueError("compound scenarios require at least two injected faults")
            if not self.ground_truth.secondary_root_cause_codes:
                raise ValueError("compound scenarios require at least one secondary root cause")

        if self.difficulty == Difficulty.ADVERSARIAL and not self.distractor_tags:
            raise ValueError("adversarial scenarios require at least one distractor")
        if self.difficulty == Difficulty.MEDIUM and not self.distractor_tags:
            raise ValueError("medium scenarios require at least one distractor")
        if self.difficulty == Difficulty.EASY and self.distractor_tags:
            raise ValueError("easy scenarios must not contain distractors")

        event_ids = [event.event_id for event in self.timeline]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("timeline event_id values must be unique")

        effect_offsets = [
            event.offset_seconds for event in self.timeline if event.role == CausalRole.EFFECT
        ]
        if not effect_offsets:
            raise ValueError("scenario timeline requires at least one effect event")
        first_effect = min(effect_offsets)
        for event in self.timeline:
            if event.role == CausalRole.CAUSE and event.offset_seconds > first_effect:
                raise ValueError("causal events must not occur after the first effect")

        visible = f"{self.public_incident.title} {self.public_incident.description}".casefold()
        forbidden = {code.casefold() for code in expected_codes if code != "no_fault"}
        for fault in self.faults:
            forbidden.update(alias.casefold() for alias in LEAKAGE_ALIASES[fault.fault])
        leaked = sorted(token for token in forbidden if token and token in visible)
        if leaked:
            raise ValueError(f"public incident leaks hidden ground truth: {', '.join(leaked)}")

        if self.kind == ScenarioKind.COUNTERFACTUAL:
            if (
                not self.structure.counterfactual_family
                or not self.structure.counterfactual_variant
            ):
                raise ValueError("counterfactual scenarios require family and variant metadata")
        return self

    def agent_payload(self) -> dict[str, Any]:
        """Return only the incident contract allowed to cross into the agent API."""
        return self.public_incident.model_dump(mode="json")


class BenchmarkCatalog(StrictModel):
    benchmark_name: str = "OpsSentinel BenchmarkLab"
    benchmark_version: str = Field(default="1.0.0", min_length=1, max_length=40)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    scenarios: list[ScenarioSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog_identity(self) -> BenchmarkCatalog:
        ids = [scenario.scenario_id for scenario in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario_id values must be unique")
        return self


class ScenarioLaunchRecord(StrictModel):
    scenario_id: str
    injected_fault_count: int = Field(ge=0)
    stimulus_count: int = Field(ge=0)
    final_statuses: list[int] = Field(default_factory=list)


class BenchmarkRunArtifact(StrictModel):
    benchmark_version: str
    scenario_id: str
    scenario_version: str
    split: BenchmarkSplit
    difficulty: Difficulty
    seed: int
    agent_run_id: UUID | None = None
    agent_status: str
    diagnosis_code: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    tool_call_count: int = Field(default=0, ge=0)
    expected_primary_root_cause_code: str
    expected_secondary_root_cause_codes: list[str] = Field(default_factory=list)
    raw_agent_run: dict[str, Any] = Field(default_factory=dict)
