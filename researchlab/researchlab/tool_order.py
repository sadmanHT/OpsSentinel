from __future__ import annotations

import json
from collections import Counter
from statistics import fmean

from benchmarklab.catalog import scenario_by_id
from benchmarklab.models import BenchmarkCatalog
from pydantic import BaseModel, ConfigDict, Field

from researchlab.benchmark_adapter import scenario_ref_from_benchmark
from researchlab.models import (
    ArchitectureVariant,
    Difficulty,
    EvidenceMode,
    ExperimentPlan,
    ExperimentSplit,
    ScenarioRef,
    StoppingStrategy,
    TemporalReasoningVariant,
    ToolOrderVariant,
    TrialRecord,
    TrialStatus,
)
from researchlab.plans import build_phase8_plans

TOOL_ORDER_SCENARIO_IDS = (
    "ops-v1-021",
    "ops-v1-022",
    "ops-v1-033",
    "ops-v1-034",
    "ops-v1-035",
    "ops-v1-036",
    "ops-v1-037",
    "ops-v1-038",
    "ops-v1-039",
    "ops-v1-040",
)
TOOL_ORDER_NEGATIVE_CONTROL = "ops-v1-040"
DATASET_POLICY_VERSION = "phase8-tool-order-cohort-v1"
ORDERING_VARIANTS = (
    ToolOrderVariant.FREE,
    ToolOrderVariant.DEPLOYMENT_FIRST,
    ToolOrderVariant.SYMPTOM_FIRST,
    ToolOrderVariant.ADAPTIVE,
)


class ToolOrderReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolOrderObservation(ToolOrderReportModel):
    trial_id: str
    scenario_id: str
    difficulty: Difficulty
    tool_order: ToolOrderVariant
    root_cause_accuracy: float
    exact_match: float
    confidence: float
    tool_calls: float
    latency_seconds: float
    estimated_cost: float
    false_positive: bool | None = None
    first_planned_tool: str | None = None
    first_executed_tool: str | None = None
    planned_order: list[str]
    planned_invocation_set: list[str]
    failure_categories: list[str] = Field(default_factory=list)


class ToolOrderAggregate(ToolOrderReportModel):
    tool_order: ToolOrderVariant
    n: int = Field(ge=1)
    mean_root_cause_accuracy: float
    exact_match_rate: float
    mean_confidence: float
    mean_tool_calls: float
    mean_latency_seconds: float
    mean_estimated_cost: float
    adversarial_n: int = Field(ge=0)
    adversarial_root_cause_accuracy: float | None = None
    adversarial_exact_match_rate: float | None = None
    negative_control_n: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_positive_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    first_planned_tool_counts: dict[str, int]
    first_executed_tool_counts: dict[str, int]
    failure_mode_counts: dict[str, int]


class ToolOrderPairDelta(ToolOrderReportModel):
    scenario_id: str
    comparison: ToolOrderVariant
    root_cause_accuracy_delta_vs_free: float
    exact_match_delta_vs_free: float
    confidence_delta_vs_free: float
    tool_calls_delta_vs_free: float


class ToolOrderReport(ToolOrderReportModel):
    experiment: str = "tool_order"
    interpretation: str = "descriptive_only"
    dataset_policy: str = DATASET_POLICY_VERSION
    benchmark_version: str
    scenario_ids: list[str]
    observations: list[ToolOrderObservation]
    aggregates: list[ToolOrderAggregate]
    paired_deltas: list[ToolOrderPairDelta]


def tool_order_plan(
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
    plan = next(item for item in plans if item.id == "phase8-tool-order")
    variants = tuple(cell.configuration.tool_order for cell in plan.cells)
    if variants != ORDERING_VARIANTS:
        raise ValueError("Tool Order cells do not match the preregistered four strategies")
    for cell in plan.cells:
        configuration = cell.configuration
        if configuration.architecture != ArchitectureVariant.EXPLICIT_PLANNER:
            raise ValueError("Tool Order must hold architecture fixed at explicit_planner")
        if configuration.tool_budget != 15:
            raise ValueError("Tool Order must hold tool budget fixed at 15")
        if configuration.evidence_mode != EvidenceMode.PASSIVE_ONLY:
            raise ValueError("Tool Order must hold evidence mode fixed at passive_only")
        if configuration.temporal_reasoning != TemporalReasoningVariant.STANDARD:
            raise ValueError("Tool Order must hold temporal reasoning fixed at standard")
        if configuration.stopping_strategy != StoppingStrategy.CONFIDENCE_THRESHOLD:
            raise ValueError("Tool Order must hold stopping strategy fixed")
    return plan


def tool_order_scenarios(catalog: BenchmarkCatalog) -> list[ScenarioRef]:
    scenarios = [
        scenario_by_id(catalog, scenario_id) for scenario_id in TOOL_ORDER_SCENARIO_IDS
    ]
    if any(scenario.split.value != ExperimentSplit.VALIDATION.value for scenario in scenarios):
        raise ValueError("Tool Order cohort must contain only validation scenarios")
    adversarial = [
        scenario
        for scenario in scenarios
        if scenario.difficulty.value == Difficulty.ADVERSARIAL.value
    ]
    if len(adversarial) != 6:
        raise ValueError("Tool Order cohort must retain exactly six adversarial scenarios")
    control = scenarios[-1]
    if control.scenario_id != TOOL_ORDER_NEGATIVE_CONTROL:
        raise ValueError("Tool Order negative-control identity changed")
    if control.ground_truth.primary_root_cause_code != "no_fault" or control.faults:
        raise ValueError("Tool Order negative control must remain fault-free with no_fault truth")
    return [scenario_ref_from_benchmark(scenario) for scenario in scenarios]


def _dict(record: TrialRecord, key: str) -> dict[str, object]:
    value = record.raw_trajectory.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Tool Order trial {record.identity.trial_id} is missing {key}")
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


def _planned_invocations(raw_run: dict[str, object]) -> tuple[list[str], list[str]]:
    plan = raw_run.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("Tool Order raw agent run is missing its investigation plan")
    raw_steps = plan.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("Tool Order investigation plan contains no steps")
    order: list[str] = []
    invocations: list[str] = []
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            raise ValueError("Tool Order investigation plan contains a malformed step")
        tool = raw_step.get("tool")
        arguments = raw_step.get("arguments")
        if not isinstance(tool, str) or not isinstance(arguments, dict):
            raise ValueError("Tool Order plan step is missing tool or arguments")
        order.append(tool)
        invocations.append(
            json.dumps(
                {"tool": tool, "arguments": arguments},
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        )
    if len(invocations) != len(set(invocations)):
        raise ValueError("Tool Order controlled plan contains duplicate invocations")
    return order, sorted(invocations)


def _first_executed_tool(raw_run: dict[str, object]) -> str | None:
    raw_history = raw_run.get("tool_history", [])
    if not isinstance(raw_history, list) or not raw_history:
        return None
    first = raw_history[0]
    if not isinstance(first, dict):
        return None
    value = first.get("tool_name")
    return str(value) if isinstance(value, str) else None


def observation_from_record(record: TrialRecord) -> ToolOrderObservation:
    if record.status != TrialStatus.COMPLETED:
        raise ValueError("Tool Order reporting requires completed trials")
    configuration = record.identity.configuration
    if configuration.architecture != ArchitectureVariant.EXPLICIT_PLANNER:
        raise ValueError("Tool Order reporting requires explicit_planner trials")
    case = _dict(record, "evaluation_case")
    result = _dict(record, "evaluation_result")
    artifact = _dict(record, "benchmark_artifact")
    raw_run = artifact.get("raw_agent_run")
    if not isinstance(raw_run, dict):
        raise ValueError("Tool Order benchmark artifact is missing the raw agent run")
    expected = case.get("expected_primary_root_cause_code")
    predicted = case.get("predicted_primary_root_cause_code")
    false_positive: bool | None = None
    if isinstance(expected, str) and expected.casefold() == "no_fault":
        false_positive = not (
            isinstance(predicted, str) and predicted.casefold() == "no_fault"
        )
    planned_order, planned_invocation_set = _planned_invocations(raw_run)
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
        raise ValueError(f"Tool Order trial is missing scores: {', '.join(missing)}")
    return ToolOrderObservation(
        trial_id=str(record.identity.trial_id),
        scenario_id=record.identity.scenario_id,
        difficulty=record.identity.difficulty,
        tool_order=configuration.tool_order,
        root_cause_accuracy=record.scores["root_cause_accuracy"],
        exact_match=record.scores["exact_match"],
        confidence=record.scores["confidence"],
        tool_calls=record.scores["tool_calls"],
        latency_seconds=record.scores["latency_seconds"],
        estimated_cost=record.scores["estimated_cost"],
        false_positive=false_positive,
        first_planned_tool=planned_order[0] if planned_order else None,
        first_executed_tool=_first_executed_tool(raw_run),
        planned_order=planned_order,
        planned_invocation_set=planned_invocation_set,
        failure_categories=_failure_categories(result),
    )


def _aggregate(
    observations: list[ToolOrderObservation],
    variant: ToolOrderVariant,
) -> ToolOrderAggregate:
    group = [item for item in observations if item.tool_order == variant]
    if not group:
        raise ValueError(f"Tool Order is missing the {variant.value} treatment")
    adversarial = [item for item in group if item.difficulty == Difficulty.ADVERSARIAL]
    controls = [item for item in group if item.false_positive is not None]
    false_positive_count = sum(bool(item.false_positive) for item in controls)
    failures = Counter(category for item in group for category in item.failure_categories)
    planned = Counter(item.first_planned_tool or "none" for item in group)
    executed = Counter(item.first_executed_tool or "none" for item in group)
    return ToolOrderAggregate(
        tool_order=variant,
        n=len(group),
        mean_root_cause_accuracy=fmean(item.root_cause_accuracy for item in group),
        exact_match_rate=fmean(item.exact_match for item in group),
        mean_confidence=fmean(item.confidence for item in group),
        mean_tool_calls=fmean(item.tool_calls for item in group),
        mean_latency_seconds=fmean(item.latency_seconds for item in group),
        mean_estimated_cost=fmean(item.estimated_cost for item in group),
        adversarial_n=len(adversarial),
        adversarial_root_cause_accuracy=(
            fmean(item.root_cause_accuracy for item in adversarial) if adversarial else None
        ),
        adversarial_exact_match_rate=(
            fmean(item.exact_match for item in adversarial) if adversarial else None
        ),
        negative_control_n=len(controls),
        false_positive_count=false_positive_count,
        false_positive_rate=(false_positive_count / len(controls) if controls else None),
        first_planned_tool_counts=dict(sorted(planned.items())),
        first_executed_tool_counts=dict(sorted(executed.items())),
        failure_mode_counts=dict(sorted(failures.items())),
    )


def build_tool_order_report(
    *,
    benchmark_version: str,
    records: list[TrialRecord],
) -> ToolOrderReport:
    observations = sorted(
        (observation_from_record(record) for record in records),
        key=lambda item: (item.scenario_id, item.tool_order.value),
    )
    expected_count = len(TOOL_ORDER_SCENARIO_IDS) * len(ORDERING_VARIANTS)
    if len(observations) != expected_count:
        raise ValueError(
            f"Tool Order requires exactly {expected_count} completed observations"
        )
    if len({item.trial_id for item in observations}) != expected_count:
        raise ValueError("Tool Order contains duplicate trial identities")

    by_key = {(item.scenario_id, item.tool_order): item for item in observations}
    paired: list[ToolOrderPairDelta] = []
    for scenario_id in TOOL_ORDER_SCENARIO_IDS:
        group = [by_key.get((scenario_id, variant)) for variant in ORDERING_VARIANTS]
        if any(item is None for item in group):
            raise ValueError(f"Tool Order is missing a treatment arm for {scenario_id}")
        resolved = [item for item in group if item is not None]
        invocation_sets = {tuple(item.planned_invocation_set) for item in resolved}
        if len(invocation_sets) != 1:
            raise ValueError(
                f"Tool Order changed the legal planned invocation set for {scenario_id}"
            )
        free = by_key[(scenario_id, ToolOrderVariant.FREE)]
        for variant in ORDERING_VARIANTS[1:]:
            comparison = by_key[(scenario_id, variant)]
            paired.append(
                ToolOrderPairDelta(
                    scenario_id=scenario_id,
                    comparison=variant,
                    root_cause_accuracy_delta_vs_free=(
                        comparison.root_cause_accuracy - free.root_cause_accuracy
                    ),
                    exact_match_delta_vs_free=comparison.exact_match - free.exact_match,
                    confidence_delta_vs_free=comparison.confidence - free.confidence,
                    tool_calls_delta_vs_free=comparison.tool_calls - free.tool_calls,
                )
            )

    return ToolOrderReport(
        benchmark_version=benchmark_version,
        scenario_ids=list(TOOL_ORDER_SCENARIO_IDS),
        observations=observations,
        aggregates=[_aggregate(observations, variant) for variant in ORDERING_VARIANTS],
        paired_deltas=paired,
    )
