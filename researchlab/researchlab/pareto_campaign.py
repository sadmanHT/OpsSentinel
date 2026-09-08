from __future__ import annotations

from collections import Counter, defaultdict
from html import escape
from statistics import fmean
from uuid import UUID

from benchmarklab.models import BenchmarkCatalog, ScenarioSpec
from pydantic import Field

from researchlab.models import ArchitectureVariant, EvidenceMode, StrictModel
from researchlab.pareto import (
    ParetoConfiguration,
    ParetoObservation,
    ParetoReport,
    build_pareto_report,
)

SELECTION_POLICY_VERSION = "phase9-validation-balanced-half-fraction-v1"
CAMPAIGN_INTERPRETATION = "multi_factor_optimization_not_causal"
MODEL_DIMENSION_STATUS = "unsampled_fixed_local_placeholder"
PARETO_VALIDATION_SCENARIO_IDS = (
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
NO_FAULT_SCENARIO_ID = "ops-v1-040"


def _configuration(
    config_id: str,
    *,
    architecture: ArchitectureVariant,
    tool_budget: int,
    retrieval_depth: int,
    evidence_mode: EvidenceMode,
) -> ParetoConfiguration:
    return ParetoConfiguration(
        id=config_id,
        provider="local",
        model="local-placeholder",
        architecture=architecture,
        tool_budget=tool_budget,
        retrieval_depth=retrieval_depth,
        evidence_mode=evidence_mode,
    )


PARETO_CONFIGURATIONS = (
    _configuration(
        "p9-c01",
        architecture=ArchitectureVariant.REACTIVE_REACT,
        tool_budget=5,
        retrieval_depth=5,
        evidence_mode=EvidenceMode.PASSIVE_ONLY,
    ),
    _configuration(
        "p9-c02",
        architecture=ArchitectureVariant.REACTIVE_REACT,
        tool_budget=5,
        retrieval_depth=20,
        evidence_mode=EvidenceMode.VERIFICATION_ENABLED,
    ),
    _configuration(
        "p9-c03",
        architecture=ArchitectureVariant.REACTIVE_REACT,
        tool_budget=15,
        retrieval_depth=5,
        evidence_mode=EvidenceMode.VERIFICATION_ENABLED,
    ),
    _configuration(
        "p9-c04",
        architecture=ArchitectureVariant.REACTIVE_REACT,
        tool_budget=15,
        retrieval_depth=20,
        evidence_mode=EvidenceMode.PASSIVE_ONLY,
    ),
    _configuration(
        "p9-c05",
        architecture=ArchitectureVariant.EXPLICIT_PLANNER,
        tool_budget=5,
        retrieval_depth=5,
        evidence_mode=EvidenceMode.VERIFICATION_ENABLED,
    ),
    _configuration(
        "p9-c06",
        architecture=ArchitectureVariant.EXPLICIT_PLANNER,
        tool_budget=5,
        retrieval_depth=20,
        evidence_mode=EvidenceMode.PASSIVE_ONLY,
    ),
    _configuration(
        "p9-c07",
        architecture=ArchitectureVariant.EXPLICIT_PLANNER,
        tool_budget=15,
        retrieval_depth=5,
        evidence_mode=EvidenceMode.PASSIVE_ONLY,
    ),
    _configuration(
        "p9-c08",
        architecture=ArchitectureVariant.EXPLICIT_PLANNER,
        tool_budget=15,
        retrieval_depth=20,
        evidence_mode=EvidenceMode.VERIFICATION_ENABLED,
    ),
)


def pareto_configuration(config_id: str) -> ParetoConfiguration:
    for configuration in PARETO_CONFIGURATIONS:
        if configuration.id == config_id:
            return configuration.model_copy(deep=True)
    raise KeyError(f"unknown Phase 9 Pareto configuration: {config_id}")


def validate_pareto_catalog(catalog: BenchmarkCatalog) -> list[ScenarioSpec]:
    validation = [
        scenario for scenario in catalog.scenarios if scenario.split.value == "validation"
    ]
    observed_ids = sorted(scenario.scenario_id for scenario in validation)
    expected_ids = sorted(PARETO_VALIDATION_SCENARIO_IDS)
    if observed_ids != expected_ids:
        raise ValueError(
            "Phase 9 Pareto optimization requires the frozen validation cohort: "
            f"observed={observed_ids!r}, expected={expected_ids!r}"
        )
    by_id = {scenario.scenario_id: scenario for scenario in validation}
    selected = [by_id[scenario_id] for scenario_id in PARETO_VALIDATION_SCENARIO_IDS]
    if any(scenario.split.value != "validation" for scenario in selected):
        raise ValueError("Phase 9 Pareto optimization may not include hidden-test scenarios")
    return selected


class ParetoCampaignTrial(StrictModel):
    configuration: ParetoConfiguration
    scenario_id: str = Field(min_length=1, max_length=120)
    agent_run_id: UUID
    diagnostic_accuracy: float = Field(ge=0.0, le=1.0)
    exact_match: float = Field(ge=0.0, le=1.0)
    estimated_cost: float = Field(ge=0.0)
    total_tokens: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    retrieved_evidence: int = Field(ge=0)
    latency_seconds: float = Field(ge=0.0)
    time_to_diagnosis_ms: float | None = Field(default=None, ge=0.0)
    failure_categories: list[str] = Field(default_factory=list)
    no_fault_false_positive: bool | None = None


class ParetoConfigurationSummary(StrictModel):
    configuration: ParetoConfiguration
    trial_count: int = Field(ge=1)
    mean_diagnostic_accuracy: float = Field(ge=0.0, le=1.0)
    exact_match_rate: float = Field(ge=0.0, le=1.0)
    mean_estimated_cost: float = Field(ge=0.0)
    mean_total_tokens: float = Field(ge=0.0)
    mean_tool_calls: float = Field(ge=0.0)
    mean_retrieved_evidence: float = Field(ge=0.0)
    mean_latency_seconds: float = Field(ge=0.0)
    negative_control_count: int = Field(ge=0)
    false_positive_count: int = Field(ge=0)
    false_positive_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    failure_mode_counts: dict[str, int]


class ParetoCampaignReport(StrictModel):
    experiment: str = "phase9_pareto_optimization"
    interpretation: str = CAMPAIGN_INTERPRETATION
    selection_policy: str = SELECTION_POLICY_VERSION
    benchmark_version: str = Field(min_length=1, max_length=80)
    scenario_ids: list[str]
    configuration_ids: list[str]
    trial_count: int = Field(ge=1)
    model_dimension_status: str = MODEL_DIMENSION_STATUS
    configuration_summaries: list[ParetoConfigurationSummary]
    pareto: ParetoReport


def _summary(
    configuration: ParetoConfiguration,
    trials: list[ParetoCampaignTrial],
) -> ParetoConfigurationSummary:
    negative_controls = [
        trial for trial in trials if trial.no_fault_false_positive is not None
    ]
    false_positive_count = sum(
        1 for trial in negative_controls if trial.no_fault_false_positive is True
    )
    failures = Counter(
        category for trial in trials for category in trial.failure_categories
    )
    return ParetoConfigurationSummary(
        configuration=configuration,
        trial_count=len(trials),
        mean_diagnostic_accuracy=fmean(trial.diagnostic_accuracy for trial in trials),
        exact_match_rate=fmean(trial.exact_match for trial in trials),
        mean_estimated_cost=fmean(trial.estimated_cost for trial in trials),
        mean_total_tokens=fmean(trial.total_tokens for trial in trials),
        mean_tool_calls=fmean(trial.tool_calls for trial in trials),
        mean_retrieved_evidence=fmean(trial.retrieved_evidence for trial in trials),
        mean_latency_seconds=fmean(trial.latency_seconds for trial in trials),
        negative_control_count=len(negative_controls),
        false_positive_count=false_positive_count,
        false_positive_rate=(
            false_positive_count / len(negative_controls)
            if negative_controls
            else None
        ),
        failure_mode_counts=dict(sorted(failures.items())),
    )


def build_pareto_campaign_report(
    *,
    benchmark_version: str,
    trials: list[ParetoCampaignTrial],
) -> ParetoCampaignReport:
    expected_configurations = {
        configuration.id: configuration for configuration in PARETO_CONFIGURATIONS
    }
    expected_pairs = {
        (configuration.id, scenario_id)
        for configuration in PARETO_CONFIGURATIONS
        for scenario_id in PARETO_VALIDATION_SCENARIO_IDS
    }
    if len(trials) != len(expected_pairs):
        raise ValueError(
            f"Phase 9 Pareto campaign requires {len(expected_pairs)} trials; "
            f"found {len(trials)}"
        )

    observed_pairs: set[tuple[str, str]] = set()
    grouped: dict[str, list[ParetoCampaignTrial]] = defaultdict(list)
    observations: list[ParetoObservation] = []
    for trial in trials:
        expected_configuration = expected_configurations.get(trial.configuration.id)
        if expected_configuration is None:
            raise ValueError(
                f"unexpected Phase 9 Pareto configuration: {trial.configuration.id}"
            )
        if trial.configuration != expected_configuration:
            raise ValueError(
                f"configuration {trial.configuration.id} differs from the frozen grid"
            )
        if trial.scenario_id not in PARETO_VALIDATION_SCENARIO_IDS:
            raise ValueError(
                f"scenario {trial.scenario_id} is outside the frozen validation cohort"
            )
        pair = (trial.configuration.id, trial.scenario_id)
        if pair in observed_pairs:
            raise ValueError(f"duplicate Phase 9 Pareto trial pair: {pair!r}")
        observed_pairs.add(pair)

        if trial.scenario_id == NO_FAULT_SCENARIO_ID:
            if trial.no_fault_false_positive is None:
                raise ValueError("no-fault control trial must report false-positive status")
        elif trial.no_fault_false_positive is not None:
            raise ValueError(
                "false-positive status is only valid for the frozen no-fault control"
            )

        grouped[trial.configuration.id].append(trial)
        observations.append(
            ParetoObservation(
                configuration=trial.configuration,
                scenario_id=trial.scenario_id,
                diagnostic_accuracy=trial.diagnostic_accuracy,
                estimated_cost=trial.estimated_cost,
                total_tokens=trial.total_tokens,
                tool_calls=trial.tool_calls,
                retrieved_evidence=trial.retrieved_evidence,
            )
        )

    missing = sorted(expected_pairs - observed_pairs)
    extra = sorted(observed_pairs - expected_pairs)
    if missing or extra:
        raise ValueError(
            "Phase 9 Pareto campaign does not match the frozen grid/cohort: "
            f"missing={missing!r}, extra={extra!r}"
        )

    summaries = [
        _summary(configuration, grouped[configuration.id])
        for configuration in PARETO_CONFIGURATIONS
    ]
    return ParetoCampaignReport(
        benchmark_version=benchmark_version,
        scenario_ids=list(PARETO_VALIDATION_SCENARIO_IDS),
        configuration_ids=[item.id for item in PARETO_CONFIGURATIONS],
        trial_count=len(trials),
        configuration_summaries=summaries,
        pareto=build_pareto_report(observations),
    )


def render_pareto_svg(report: ParetoCampaignReport) -> str:
    width = 960.0
    height = 600.0
    left = 90.0
    right = 40.0
    top = 50.0
    bottom = 90.0
    plot_width = width - left - right
    plot_height = height - top - bottom

    points = report.pareto.points
    costs = [point.frontier_cost for point in points]
    min_cost = min(costs)
    max_cost = max(costs)
    cost_span = max(max_cost - min_cost, 1.0)
    frontier_ids = set(report.pareto.frontier_configuration_ids)

    def x_position(cost: float) -> float:
        return left + ((cost - min_cost) / cost_span) * plot_width

    def y_position(accuracy: float) -> float:
        return top + (1.0 - accuracy) * plot_height

    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="600" viewBox="0 0 960 600">',
        '<rect x="0" y="0" width="960" height="600" fill="white"/>',
        '<text x="480" y="28" text-anchor="middle" font-size="20">Phase 9 Pareto frontier</text>',
        f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="black"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="black"/>',
        f'<text x="{left + plot_width / 2}" y="575" text-anchor="middle" font-size="14">{escape(report.pareto.cost_basis.value)}</text>',
        '<text x="22" y="300" text-anchor="middle" font-size="14" transform="rotate(-90 22 300)">diagnostic accuracy</text>',
    ]

    frontier_points = sorted(
        (point for point in points if point.configuration.id in frontier_ids),
        key=lambda point: point.frontier_cost,
    )
    if len(frontier_points) > 1:
        coordinates = " ".join(
            f"{x_position(point.frontier_cost):.2f},{y_position(point.mean_diagnostic_accuracy):.2f}"
            for point in frontier_points
        )
        elements.append(
            f'<polyline points="{coordinates}" fill="none" stroke="black" stroke-width="2"/>'
        )

    for point in sorted(points, key=lambda item: item.configuration.id):
        x = x_position(point.frontier_cost)
        y = y_position(point.mean_diagnostic_accuracy)
        radius = 7 if point.configuration.id in frontier_ids else 5
        elements.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius}" fill="white" stroke="black" stroke-width="2"/>'
        )
        elements.append(
            f'<text x="{x + 9:.2f}" y="{y - 9:.2f}" font-size="12">{escape(point.configuration.id)}</text>'
        )

    elements.extend(
        [
            f'<text x="{left}" y="{top + plot_height + 26}" text-anchor="start" font-size="11">{min_cost:.4f}</text>',
            f'<text x="{left + plot_width}" y="{top + plot_height + 26}" text-anchor="end" font-size="11">{max_cost:.4f}</text>',
            f'<text x="{left - 12}" y="{top + plot_height}" text-anchor="end" font-size="11">0.0</text>',
            f'<text x="{left - 12}" y="{top + 4}" text-anchor="end" font-size="11">1.0</text>',
            "</svg>",
        ]
    )
    return "\n".join(elements) + "\n"
