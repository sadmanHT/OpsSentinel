from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from statistics import fmean

from benchmarklab.catalog import scenario_by_id
from benchmarklab.models import BenchmarkCatalog, BenchmarkRunArtifact, ScenarioSpec
from benchmarklab.runner import BenchmarkRunner
from pydantic import BaseModel, ConfigDict, Field

from researchlab.benchmark_adapter import scenario_ref_from_benchmark
from researchlab.models import (
    ArchitectureVariant,
    ExperimentPlan,
    ExperimentSplit,
    ScenarioRef,
    TemporalReasoningVariant,
    TrialRecord,
    TrialStatus,
)
from researchlab.plans import build_phase8_plans

H3_SCENARIO_IDS = (
    "ops-v1-035",
    "ops-v1-036",
    "ops-v1-037",
    "ops-v1-038",
    "ops-v1-040",
)
H3_NEGATIVE_CONTROL = "ops-v1-040"
DATASET_POLICY_VERSION = "phase8-h3-temporal-cohort-v1"


class TemporalReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TemporalObservation(TemporalReportModel):
    trial_id: str
    scenario_id: str
    temporal_reasoning: TemporalReasoningVariant
    root_cause_accuracy: float
    exact_match: float
    confidence: float
    tool_calls: float
    latency_seconds: float
    estimated_cost: float
    false_positive: bool | None = None
    hypothesis_count: int = Field(ge=0)
    temporally_stamped_hypotheses: int = Field(ge=0)
    temporal_order_violations: int = Field(ge=0)
    failure_categories: list[str] = Field(default_factory=list)


class TemporalAggregate(TemporalReportModel):
    temporal_reasoning: TemporalReasoningVariant
    n: int = Field(ge=1)
    mean_root_cause_accuracy: float
    exact_match_rate: float
    mean_confidence: float
    mean_tool_calls: float
    mean_latency_seconds: float
    mean_estimated_cost: float
    negative_control_n: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_positive_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_temporally_stamped_hypotheses: float
    temporal_order_violation_count: int = Field(ge=0)
    failure_mode_counts: dict[str, int]


class TemporalPairDelta(TemporalReportModel):
    scenario_id: str
    root_cause_accuracy_delta: float
    exact_match_delta: float
    confidence_delta: float
    tool_calls_delta: float
    temporally_stamped_hypotheses_delta: int


class TemporalReasoningReport(TemporalReportModel):
    experiment: str = "temporal_reasoning"
    hypothesis_id: str = "H3"
    interpretation: str = "descriptive_only"
    dataset_policy: str = DATASET_POLICY_VERSION
    benchmark_version: str
    scenario_ids: list[str]
    observations: list[TemporalObservation]
    aggregates: list[TemporalAggregate]
    paired_deltas: list[TemporalPairDelta]


class RuntimeOnsetBenchmarkRunner(BenchmarkRunner):
    """Give both H3 arms the same live public onset without exposing hidden chronology."""

    async def _start_agent(self, scenario: ScenarioSpec) -> dict[str, object]:
        runtime_scenario = scenario.model_copy(deep=True)
        runtime_scenario.public_incident = runtime_scenario.public_incident.model_copy(
            update={"start_time": datetime.now(UTC)}
        )
        return await super()._start_agent(runtime_scenario)


def temporal_reasoning_plan(
    *,
    dataset_version: str,
    provider: str = "local",
    model: str = "local-placeholder",
    prompt_version: str = "phase8-v1",
) -> ExperimentPlan:
    plans = build_phase8_plans(
        dataset_version=dataset_version,
        split=ExperimentSplit.VALIDATION,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        repeat_count=1,
    )
    plan = next(item for item in plans if item.id == "phase8-temporal-reasoning")
    if any(
        cell.configuration.architecture != ArchitectureVariant.EXPLICIT_PLANNER
        for cell in plan.cells
    ):
        raise ValueError("H3 must hold architecture fixed at explicit_planner")
    variants = [cell.configuration.temporal_reasoning for cell in plan.cells]
    if variants != [
        TemporalReasoningVariant.STANDARD,
        TemporalReasoningVariant.EXPLICIT_CAUSE_EFFECT,
    ]:
        raise ValueError("H3 temporal cells do not match the preregistered treatment pair")
    return plan


def temporal_scenarios(catalog: BenchmarkCatalog) -> list[ScenarioRef]:
    scenarios = [scenario_by_id(catalog, scenario_id) for scenario_id in H3_SCENARIO_IDS]
    for scenario in scenarios:
        if scenario.split.value != ExperimentSplit.VALIDATION.value:
            raise ValueError(f"H3 scenario {scenario.scenario_id} is not in validation")
    for scenario in scenarios[:4]:
        if scenario.difficulty.value != "adversarial":
            raise ValueError(f"H3 misleading case {scenario.scenario_id} is not adversarial")
        if not scenario.distractor_tags:
            raise ValueError(f"H3 misleading case {scenario.scenario_id} lacks a distractor")
    control = scenarios[-1]
    if control.scenario_id != H3_NEGATIVE_CONTROL:
        raise ValueError("H3 negative-control identity changed")
    if control.ground_truth.primary_root_cause_code != "no_fault" or control.faults:
        raise ValueError("H3 negative control must remain fault-free with no_fault truth")
    return [scenario_ref_from_benchmark(scenario) for scenario in scenarios]


def _dict(record: TrialRecord, key: str) -> dict[str, object]:
    value = record.raw_trajectory.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"H3 trial {record.identity.trial_id} is missing {key}")
    return value


def _failure_categories(result: dict[str, object]) -> list[str]:
    raw = result.get("failure_classifications", [])
    if not isinstance(raw, list):
        return []
    values: set[str] = set()
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("category"), str):
            values.add(str(item["category"]))
    return sorted(values)


def _temporal_counts(raw_run: dict[str, object]) -> tuple[int, int, int]:
    raw = raw_run.get("hypotheses", [])
    if not isinstance(raw, list):
        return 0, 0, 0
    hypothesis_count = 0
    stamped = 0
    violations = 0
    for item in raw:
        if not isinstance(item, dict):
            continue
        hypothesis_count += 1
        cause = item.get("first_possible_cause_time")
        effect = item.get("effect_time")
        if effect is not None:
            stamped += 1
        if isinstance(cause, str) and isinstance(effect, str):
            cause_time = datetime.fromisoformat(cause.replace("Z", "+00:00"))
            effect_time = datetime.fromisoformat(effect.replace("Z", "+00:00"))
            if cause_time > effect_time:
                violations += 1
    return hypothesis_count, stamped, violations


def observation_from_record(record: TrialRecord) -> TemporalObservation:
    if record.status != TrialStatus.COMPLETED:
        raise ValueError("H3 reporting requires completed trials")
    if record.identity.configuration.architecture != ArchitectureVariant.EXPLICIT_PLANNER:
        raise ValueError("H3 reporting requires explicit_planner trials")
    case = _dict(record, "evaluation_case")
    result = _dict(record, "evaluation_result")
    artifact = _dict(record, "benchmark_artifact")
    raw_run = artifact.get("raw_agent_run")
    if not isinstance(raw_run, dict):
        raise ValueError("H3 benchmark artifact is missing the raw agent run")
    expected = case.get("expected_primary_root_cause_code")
    predicted = case.get("predicted_primary_root_cause_code")
    false_positive: bool | None = None
    if isinstance(expected, str) and expected.casefold() == "no_fault":
        false_positive = not (
            isinstance(predicted, str) and predicted.casefold() == "no_fault"
        )
    hypothesis_count, stamped, violations = _temporal_counts(raw_run)
    required = {
        "root_cause_accuracy",
        "exact_match",
        "confidence",
        "tool_calls",
        "latency_seconds",
        "estimated_cost",
    }
    missing = sorted(required - set(record.scores))
    if missing:
        raise ValueError(f"H3 trial is missing scores: {', '.join(missing)}")
    return TemporalObservation(
        trial_id=str(record.identity.trial_id),
        scenario_id=record.identity.scenario_id,
        temporal_reasoning=record.identity.configuration.temporal_reasoning,
        root_cause_accuracy=record.scores["root_cause_accuracy"],
        exact_match=record.scores["exact_match"],
        confidence=record.scores["confidence"],
        tool_calls=record.scores["tool_calls"],
        latency_seconds=record.scores["latency_seconds"],
        estimated_cost=record.scores["estimated_cost"],
        false_positive=false_positive,
        hypothesis_count=hypothesis_count,
        temporally_stamped_hypotheses=stamped,
        temporal_order_violations=violations,
        failure_categories=_failure_categories(result),
    )


def _aggregate(
    observations: list[TemporalObservation],
    variant: TemporalReasoningVariant,
) -> TemporalAggregate:
    group = [item for item in observations if item.temporal_reasoning == variant]
    if not group:
        raise ValueError(f"H3 is missing the {variant.value} treatment")
    controls = [item for item in group if item.false_positive is not None]
    false_positive_count = sum(bool(item.false_positive) for item in controls)
    failures = Counter(category for item in group for category in item.failure_categories)
    return TemporalAggregate(
        temporal_reasoning=variant,
        n=len(group),
        mean_root_cause_accuracy=fmean(item.root_cause_accuracy for item in group),
        exact_match_rate=fmean(item.exact_match for item in group),
        mean_confidence=fmean(item.confidence for item in group),
        mean_tool_calls=fmean(item.tool_calls for item in group),
        mean_latency_seconds=fmean(item.latency_seconds for item in group),
        mean_estimated_cost=fmean(item.estimated_cost for item in group),
        negative_control_n=len(controls),
        false_positive_count=false_positive_count,
        false_positive_rate=(false_positive_count / len(controls) if controls else None),
        mean_temporally_stamped_hypotheses=fmean(
            item.temporally_stamped_hypotheses for item in group
        ),
        temporal_order_violation_count=sum(item.temporal_order_violations for item in group),
        failure_mode_counts=dict(sorted(failures.items())),
    )


def build_temporal_reasoning_report(
    *,
    benchmark_version: str,
    records: list[TrialRecord],
) -> TemporalReasoningReport:
    observations = sorted(
        (observation_from_record(record) for record in records),
        key=lambda item: (item.scenario_id, item.temporal_reasoning.value),
    )
    expected_count = len(H3_SCENARIO_IDS) * 2
    if len(observations) != expected_count:
        raise ValueError(f"H3 requires exactly {expected_count} completed observations")
    if len({item.trial_id for item in observations}) != expected_count:
        raise ValueError("H3 contains duplicate trial identities")
    by_key = {(item.scenario_id, item.temporal_reasoning): item for item in observations}
    paired: list[TemporalPairDelta] = []
    for scenario_id in H3_SCENARIO_IDS:
        standard = by_key.get((scenario_id, TemporalReasoningVariant.STANDARD))
        explicit = by_key.get((scenario_id, TemporalReasoningVariant.EXPLICIT_CAUSE_EFFECT))
        if standard is None or explicit is None:
            raise ValueError(f"H3 is missing a treatment pair for {scenario_id}")
        paired.append(
            TemporalPairDelta(
                scenario_id=scenario_id,
                root_cause_accuracy_delta=(
                    explicit.root_cause_accuracy - standard.root_cause_accuracy
                ),
                exact_match_delta=explicit.exact_match - standard.exact_match,
                confidence_delta=explicit.confidence - standard.confidence,
                tool_calls_delta=explicit.tool_calls - standard.tool_calls,
                temporally_stamped_hypotheses_delta=(
                    explicit.temporally_stamped_hypotheses
                    - standard.temporally_stamped_hypotheses
                ),
            )
        )
    return TemporalReasoningReport(
        benchmark_version=benchmark_version,
        scenario_ids=list(H3_SCENARIO_IDS),
        observations=observations,
        aggregates=[
            _aggregate(observations, TemporalReasoningVariant.STANDARD),
            _aggregate(observations, TemporalReasoningVariant.EXPLICIT_CAUSE_EFFECT),
        ],
        paired_deltas=paired,
    )
