from __future__ import annotations

from collections import Counter
from statistics import fmean

from benchmarklab.models import BenchmarkCatalog
from pydantic import BaseModel, ConfigDict, Field

from researchlab.benchmark_adapter import scenario_refs_from_benchmark
from researchlab.models import (
    ArchitectureVariant,
    Difficulty,
    ExperimentPlan,
    ExperimentSplit,
    ScenarioRef,
    TrialRecord,
    TrialStatus,
)
from researchlab.plans import build_phase8_plans

BUDGETS = (5, 10, 15, 20)
DATASET_POLICY_VERSION = "phase8-h2-full-validation-v1"


class BudgetReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvestigationBudgetObservation(BudgetReportModel):
    trial_id: str
    scenario_id: str
    difficulty: Difficulty
    tool_budget: int
    root_cause_accuracy: float
    exact_match: float
    false_positive: bool | None = None
    distractor_selection_rate: float
    confidence: float
    tool_calls: float
    budget_utilization: float
    budget_exhausted: bool
    latency_seconds: float
    estimated_cost: float
    failure_categories: list[str] = Field(default_factory=list)


class InvestigationBudgetAggregate(BudgetReportModel):
    tool_budget: int
    n: int = Field(ge=1)
    mean_root_cause_accuracy: float
    exact_match_rate: float
    negative_control_n: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_positive_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_distractor_selection_rate: float
    mean_confidence: float
    mean_tool_calls: float
    mean_budget_utilization: float
    budget_exhaustion_count: int = Field(ge=0)
    mean_latency_seconds: float
    mean_estimated_cost: float
    failure_mode_counts: dict[str, int]


class InvestigationBudgetDifficultyAggregate(BudgetReportModel):
    tool_budget: int
    difficulty: Difficulty
    n: int = Field(ge=1)
    mean_root_cause_accuracy: float
    exact_match_rate: float
    mean_distractor_selection_rate: float
    mean_confidence: float
    mean_tool_calls: float
    budget_exhaustion_count: int = Field(ge=0)
    failure_mode_counts: dict[str, int]


class InvestigationBudgetReport(BudgetReportModel):
    experiment: str = "investigation_budget"
    hypothesis_id: str = "H2"
    interpretation: str = "descriptive_only"
    dataset_policy: str = DATASET_POLICY_VERSION
    benchmark_version: str
    architecture: ArchitectureVariant
    budgets: list[int]
    scenario_ids: list[str]
    observations: list[InvestigationBudgetObservation]
    aggregates: list[InvestigationBudgetAggregate]
    by_difficulty: list[InvestigationBudgetDifficultyAggregate]


def validation_scenarios(catalog: BenchmarkCatalog) -> list[ScenarioRef]:
    refs = scenario_refs_from_benchmark(catalog.scenarios, split=ExperimentSplit.VALIDATION)
    if len(refs) != 10:
        raise ValueError(
            f"H2 requires the complete 10-scenario validation split; found {len(refs)}"
        )
    return refs


def investigation_budget_plan(
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
    plan = next(item for item in plans if item.id == "phase8-investigation-budget")
    if [cell.configuration.tool_budget for cell in plan.cells] != list(BUDGETS):
        raise ValueError("H2 investigation-budget cells do not match the preregistered budgets")
    if any(
        cell.configuration.architecture != ArchitectureVariant.EXPLICIT_PLANNER
        for cell in plan.cells
    ):
        raise ValueError("H2 must hold architecture fixed at explicit_planner")
    return plan


def _trajectory_dict(record: TrialRecord, key: str) -> dict[str, object]:
    value = record.raw_trajectory.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"trial {record.identity.trial_id} is missing {key}")
    return value


def _failure_categories(result: dict[str, object]) -> list[str]:
    raw = result.get("failure_classifications", [])
    if not isinstance(raw, list):
        return []
    categories: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        category = item.get("category")
        if isinstance(category, str) and category:
            categories.append(category)
    return sorted(set(categories))


def _number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    return float(value)


def observation_from_record(record: TrialRecord) -> InvestigationBudgetObservation:
    if record.status != TrialStatus.COMPLETED:
        raise ValueError("H2 reporting requires completed trials")
    if record.identity.configuration.architecture != ArchitectureVariant.EXPLICIT_PLANNER:
        raise ValueError("H2 reporting requires explicit_planner trials")
    if record.identity.configuration.tool_budget not in BUDGETS:
        raise ValueError("H2 reporting received an unregistered tool budget")

    case = _trajectory_dict(record, "evaluation_case")
    result = _trajectory_dict(record, "evaluation_result")
    evidence_raw = result.get("evidence")
    if not isinstance(evidence_raw, dict):
        raise ValueError("H2 evaluation result is missing evidence metrics")

    expected = case.get("expected_primary_root_cause_code")
    predicted = case.get("predicted_primary_root_cause_code")
    if not isinstance(expected, str):
        raise ValueError("H2 evaluation case is missing expected root cause")
    if predicted is not None and not isinstance(predicted, str):
        raise ValueError("H2 predicted root cause must be a string or null")
    false_positive: bool | None = None
    if expected.casefold() == "no_fault":
        false_positive = predicted is None or predicted.casefold() != "no_fault"

    budget_exhausted_raw = case.get("budget_exhausted")
    if not isinstance(budget_exhausted_raw, bool):
        raise ValueError("H2 evaluation case is missing budget_exhausted")

    required_scores = {
        "root_cause_accuracy",
        "exact_match",
        "confidence",
        "tool_calls",
        "latency_seconds",
        "estimated_cost",
    }
    missing = sorted(required_scores - set(record.scores))
    if missing:
        raise ValueError(f"H2 trial is missing scores: {', '.join(missing)}")

    tool_calls = record.scores["tool_calls"]
    tool_budget = record.identity.configuration.tool_budget
    return InvestigationBudgetObservation(
        trial_id=str(record.identity.trial_id),
        scenario_id=record.identity.scenario_id,
        difficulty=record.identity.difficulty,
        tool_budget=tool_budget,
        root_cause_accuracy=record.scores["root_cause_accuracy"],
        exact_match=record.scores["exact_match"],
        false_positive=false_positive,
        distractor_selection_rate=_number(
            evidence_raw.get("distractor_selection_rate"),
            name="distractor_selection_rate",
        ),
        confidence=record.scores["confidence"],
        tool_calls=tool_calls,
        budget_utilization=tool_calls / tool_budget,
        budget_exhausted=budget_exhausted_raw,
        latency_seconds=record.scores["latency_seconds"],
        estimated_cost=record.scores["estimated_cost"],
        failure_categories=_failure_categories(result),
    )


def _aggregate(
    observations: list[InvestigationBudgetObservation],
    budget: int,
) -> InvestigationBudgetAggregate:
    group = [item for item in observations if item.tool_budget == budget]
    if not group:
        raise ValueError(f"H2 is missing observations for budget {budget}")
    controls = [item for item in group if item.false_positive is not None]
    false_positive_count = sum(bool(item.false_positive) for item in controls)
    failures = Counter(category for item in group for category in item.failure_categories)
    return InvestigationBudgetAggregate(
        tool_budget=budget,
        n=len(group),
        mean_root_cause_accuracy=fmean(item.root_cause_accuracy for item in group),
        exact_match_rate=fmean(item.exact_match for item in group),
        negative_control_n=len(controls),
        false_positive_count=false_positive_count,
        false_positive_rate=(false_positive_count / len(controls) if controls else None),
        mean_distractor_selection_rate=fmean(
            item.distractor_selection_rate for item in group
        ),
        mean_confidence=fmean(item.confidence for item in group),
        mean_tool_calls=fmean(item.tool_calls for item in group),
        mean_budget_utilization=fmean(item.budget_utilization for item in group),
        budget_exhaustion_count=sum(item.budget_exhausted for item in group),
        mean_latency_seconds=fmean(item.latency_seconds for item in group),
        mean_estimated_cost=fmean(item.estimated_cost for item in group),
        failure_mode_counts=dict(sorted(failures.items())),
    )


def _difficulty_aggregate(
    observations: list[InvestigationBudgetObservation],
    budget: int,
    difficulty: Difficulty,
) -> InvestigationBudgetDifficultyAggregate | None:
    group = [
        item
        for item in observations
        if item.tool_budget == budget and item.difficulty == difficulty
    ]
    if not group:
        return None
    failures = Counter(category for item in group for category in item.failure_categories)
    return InvestigationBudgetDifficultyAggregate(
        tool_budget=budget,
        difficulty=difficulty,
        n=len(group),
        mean_root_cause_accuracy=fmean(item.root_cause_accuracy for item in group),
        exact_match_rate=fmean(item.exact_match for item in group),
        mean_distractor_selection_rate=fmean(
            item.distractor_selection_rate for item in group
        ),
        mean_confidence=fmean(item.confidence for item in group),
        mean_tool_calls=fmean(item.tool_calls for item in group),
        budget_exhaustion_count=sum(item.budget_exhausted for item in group),
        failure_mode_counts=dict(sorted(failures.items())),
    )


def build_investigation_budget_report(
    *,
    benchmark_version: str,
    scenarios: list[ScenarioRef],
    records: list[TrialRecord],
) -> InvestigationBudgetReport:
    scenario_ids = sorted(item.scenario_id for item in scenarios)
    if len(scenario_ids) != 10 or len(set(scenario_ids)) != 10:
        raise ValueError("H2 reporting requires the complete unique validation split")

    observations = sorted(
        (observation_from_record(record) for record in records),
        key=lambda item: (item.tool_budget, item.scenario_id),
    )
    expected_count = len(BUDGETS) * len(scenario_ids)
    if len(observations) != expected_count:
        raise ValueError(
            f"H2 report requires {expected_count} observations; "
            f"found {len(observations)}"
        )
    if len({item.trial_id for item in observations}) != expected_count:
        raise ValueError("H2 report contains duplicate trial identities")

    for budget in BUDGETS:
        observed_ids = sorted(
            item.scenario_id for item in observations if item.tool_budget == budget
        )
        if observed_ids != scenario_ids:
            raise ValueError(f"H2 budget {budget} does not cover the complete validation split")

    by_difficulty = [
        aggregate
        for budget in BUDGETS
        for difficulty in Difficulty
        if (aggregate := _difficulty_aggregate(observations, budget, difficulty)) is not None
    ]
    return InvestigationBudgetReport(
        benchmark_version=benchmark_version,
        architecture=ArchitectureVariant.EXPLICIT_PLANNER,
        budgets=list(BUDGETS),
        scenario_ids=scenario_ids,
        observations=observations,
        aggregates=[_aggregate(observations, budget) for budget in BUDGETS],
        by_difficulty=by_difficulty,
    )
