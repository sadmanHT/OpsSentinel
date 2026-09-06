from __future__ import annotations

from collections import Counter
from statistics import fmean

from benchmarklab.models import BenchmarkCatalog
from pydantic import BaseModel, ConfigDict, Field

from researchlab.benchmark_adapter import scenario_ref_from_benchmark
from researchlab.models import (
    ArchitectureVariant,
    Difficulty,
    ExperimentCell,
    ExperimentKind,
    ExperimentPlan,
    ExperimentSplit,
    ResearchConfiguration,
    ScenarioRef,
    TrialRecord,
    TrialStatus,
)

SELECTION_POLICY_VERSION = "phase8-h1-two-per-tier-v1"

SPLIT_BY_DIFFICULTY: dict[Difficulty, ExperimentSplit] = {
    Difficulty.EASY: ExperimentSplit.DEV,
    Difficulty.MEDIUM: ExperimentSplit.VALIDATION,
    Difficulty.HARD: ExperimentSplit.VALIDATION,
    Difficulty.ADVERSARIAL: ExperimentSplit.VALIDATION,
    Difficulty.COMPOUND: ExperimentSplit.HIDDEN_TEST,
}

CELL_BY_ARCHITECTURE: dict[ArchitectureVariant, str] = {
    ArchitectureVariant.REACTIVE_REACT: "reactive",
    ArchitectureVariant.EXPLICIT_PLANNER: "planner",
}


class ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanningDifficultyTrialObservation(ReportModel):
    trial_id: str
    architecture: ArchitectureVariant
    scenario_id: str
    split: ExperimentSplit
    difficulty: Difficulty
    root_cause_accuracy: float
    exact_match: float
    tool_calls: float
    latency_seconds: float
    estimated_cost: float
    confidence: float
    failure_categories: list[str] = Field(default_factory=list)


class PlanningDifficultyAggregate(ReportModel):
    architecture: ArchitectureVariant
    difficulty: Difficulty
    n: int = Field(ge=1)
    mean_root_cause_accuracy: float
    exact_match_rate: float
    mean_tool_calls: float
    mean_latency_seconds: float
    mean_estimated_cost: float
    mean_confidence: float
    failure_mode_counts: dict[str, int]


class PlanningDifficultyDelta(ReportModel):
    difficulty: Difficulty
    planner_minus_reactive_accuracy: float
    planner_minus_reactive_exact_match: float
    planner_minus_reactive_tool_calls: float
    planner_minus_reactive_latency_seconds: float
    planner_minus_reactive_estimated_cost: float


class PlanningDifficultyReport(ReportModel):
    experiment: str = "planning_difficulty"
    hypothesis_id: str = "H1"
    interpretation: str = "descriptive_only"
    selection_policy: str = SELECTION_POLICY_VERSION
    benchmark_version: str
    per_tier: int
    selected_scenarios: dict[str, list[str]]
    observations: list[PlanningDifficultyTrialObservation]
    aggregates: list[PlanningDifficultyAggregate]
    deltas: list[PlanningDifficultyDelta]


def select_planning_difficulty_scenarios(
    catalog: BenchmarkCatalog,
    *,
    per_tier: int = 2,
) -> dict[Difficulty, list[ScenarioRef]]:
    if per_tier < 1:
        raise ValueError("per_tier must be at least 1")
    selected: dict[Difficulty, list[ScenarioRef]] = {}
    for difficulty in Difficulty:
        split = SPLIT_BY_DIFFICULTY[difficulty]
        candidates = sorted(
            (
                scenario
                for scenario in catalog.scenarios
                if scenario.difficulty.value == difficulty.value
                and scenario.split.value == split.value
            ),
            key=lambda scenario: scenario.scenario_id,
        )
        if len(candidates) < per_tier:
            raise ValueError(
                f"planning/difficulty selection requires {per_tier} {difficulty.value} "
                f"scenarios in split {split.value}; found {len(candidates)}"
            )
        selected[difficulty] = [
            scenario_ref_from_benchmark(scenario) for scenario in candidates[:per_tier]
        ]
    return selected


def build_planning_difficulty_tier_plans(
    *,
    dataset_version: str = "ops-v1",
    provider: str = "local",
    model: str = "local-placeholder",
    prompt_version: str = "phase8-v1",
    tool_budget: int = 15,
) -> dict[Difficulty, ExperimentPlan]:
    plans: dict[Difficulty, ExperimentPlan] = {}
    for index, difficulty in enumerate(Difficulty):
        baseline = ResearchConfiguration(
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            tool_budget=tool_budget,
        )
        split = SPLIT_BY_DIFFICULTY[difficulty]
        plans[difficulty] = ExperimentPlan(
            id=f"phase8-planning-difficulty-{difficulty.value}",
            experiment=ExperimentKind.PLANNING_DIFFICULTY,
            hypothesis_id="H1",
            dataset_version=dataset_version,
            split=split,
            repeat_count=1,
            seed_base=8_700 + index * 100,
            cells=[
                ExperimentCell(
                    id="reactive",
                    label="Reactive ReAct",
                    configuration=baseline.model_copy(
                        update={"architecture": ArchitectureVariant.REACTIVE_REACT}
                    ),
                    difficulties=[difficulty],
                ),
                ExperimentCell(
                    id="planner",
                    label="Explicit planner",
                    configuration=baseline.model_copy(
                        update={"architecture": ArchitectureVariant.EXPLICIT_PLANNER}
                    ),
                    difficulties=[difficulty],
                ),
            ],
        )
    return plans


def _failure_categories(record: TrialRecord) -> list[str]:
    evaluation_result = record.raw_trajectory.get("evaluation_result")
    if not isinstance(evaluation_result, dict):
        return []
    raw = evaluation_result.get("failure_classifications", [])
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


def observation_from_record(record: TrialRecord) -> PlanningDifficultyTrialObservation:
    if record.status != TrialStatus.COMPLETED:
        raise ValueError("planning/difficulty reporting requires completed trials")
    scores = record.scores
    required = {
        "root_cause_accuracy",
        "exact_match",
        "tool_calls",
        "latency_seconds",
        "estimated_cost",
        "confidence",
    }
    missing = sorted(required - set(scores))
    if missing:
        raise ValueError(f"planning/difficulty trial is missing scores: {', '.join(missing)}")
    return PlanningDifficultyTrialObservation(
        trial_id=str(record.identity.trial_id),
        architecture=record.identity.configuration.architecture,
        scenario_id=record.identity.scenario_id,
        split=record.identity.split,
        difficulty=record.identity.difficulty,
        root_cause_accuracy=scores["root_cause_accuracy"],
        exact_match=scores["exact_match"],
        tool_calls=scores["tool_calls"],
        latency_seconds=scores["latency_seconds"],
        estimated_cost=scores["estimated_cost"],
        confidence=scores["confidence"],
        failure_categories=_failure_categories(record),
    )


def _aggregate(
    observations: list[PlanningDifficultyTrialObservation],
    architecture: ArchitectureVariant,
    difficulty: Difficulty,
) -> PlanningDifficultyAggregate:
    group = [
        item
        for item in observations
        if item.architecture == architecture and item.difficulty == difficulty
    ]
    if not group:
        raise ValueError(
            f"missing observations for {architecture.value}/{difficulty.value}"
        )
    failures = Counter(category for item in group for category in item.failure_categories)
    return PlanningDifficultyAggregate(
        architecture=architecture,
        difficulty=difficulty,
        n=len(group),
        mean_root_cause_accuracy=fmean(item.root_cause_accuracy for item in group),
        exact_match_rate=fmean(item.exact_match for item in group),
        mean_tool_calls=fmean(item.tool_calls for item in group),
        mean_latency_seconds=fmean(item.latency_seconds for item in group),
        mean_estimated_cost=fmean(item.estimated_cost for item in group),
        mean_confidence=fmean(item.confidence for item in group),
        failure_mode_counts=dict(sorted(failures.items())),
    )


def build_planning_difficulty_report(
    *,
    benchmark_version: str,
    selected: dict[Difficulty, list[ScenarioRef]],
    records: list[TrialRecord],
    per_tier: int = 2,
) -> PlanningDifficultyReport:
    observations = sorted(
        (observation_from_record(record) for record in records),
        key=lambda item: (item.difficulty.value, item.architecture.value, item.scenario_id),
    )
    expected_count = len(Difficulty) * len(ArchitectureVariant) * per_tier
    if len(observations) != expected_count:
        raise ValueError(
            f"planning/difficulty report requires {expected_count} observations; "
            f"found {len(observations)}"
        )

    aggregates = [
        _aggregate(observations, architecture, difficulty)
        for difficulty in Difficulty
        for architecture in ArchitectureVariant
    ]
    lookup = {(item.architecture, item.difficulty): item for item in aggregates}
    deltas: list[PlanningDifficultyDelta] = []
    for difficulty in Difficulty:
        planner = lookup[(ArchitectureVariant.EXPLICIT_PLANNER, difficulty)]
        reactive = lookup[(ArchitectureVariant.REACTIVE_REACT, difficulty)]
        deltas.append(
            PlanningDifficultyDelta(
                difficulty=difficulty,
                planner_minus_reactive_accuracy=(
                    planner.mean_root_cause_accuracy - reactive.mean_root_cause_accuracy
                ),
                planner_minus_reactive_exact_match=(
                    planner.exact_match_rate - reactive.exact_match_rate
                ),
                planner_minus_reactive_tool_calls=(
                    planner.mean_tool_calls - reactive.mean_tool_calls
                ),
                planner_minus_reactive_latency_seconds=(
                    planner.mean_latency_seconds - reactive.mean_latency_seconds
                ),
                planner_minus_reactive_estimated_cost=(
                    planner.mean_estimated_cost - reactive.mean_estimated_cost
                ),
            )
        )

    selected_scenarios: dict[str, list[str]] = {
        difficulty.value: [item.scenario_id for item in selected[difficulty]]
        for difficulty in Difficulty
    }
    return PlanningDifficultyReport(
        benchmark_version=benchmark_version,
        per_tier=per_tier,
        selected_scenarios=selected_scenarios,
        observations=observations,
        aggregates=aggregates,
        deltas=deltas,
    )
