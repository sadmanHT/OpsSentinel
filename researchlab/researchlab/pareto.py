from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
from statistics import fmean

from pydantic import Field

from researchlab.models import ArchitectureVariant, EvidenceMode, StrictModel

RESOURCE_PROXY_FORMULA = (
    "mean_tool_calls + mean_total_tokens / 1000 + mean_retrieved_evidence / 10"
)
REQUIRED_DIMENSIONS = (
    "model",
    "tool_budget",
    "planning_strategy",
    "retrieval_depth",
    "verification_strategy",
)


class ParetoCostBasis(StrEnum):
    MONETARY = "estimated_monetary_cost"
    RESOURCE_PROXY = "resource_cost_proxy"


class ParetoConfiguration(StrictModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    architecture: ArchitectureVariant
    tool_budget: int = Field(ge=1, le=200)
    retrieval_depth: int = Field(ge=1, le=1_000)
    evidence_mode: EvidenceMode

    @property
    def planning_strategy(self) -> str:
        return self.architecture.value

    @property
    def verification_strategy(self) -> str:
        return self.evidence_mode.value


class ParetoObservation(StrictModel):
    configuration: ParetoConfiguration
    scenario_id: str = Field(min_length=1, max_length=120)
    diagnostic_accuracy: float = Field(ge=0.0, le=1.0)
    estimated_cost: float = Field(default=0.0, ge=0.0)
    total_tokens: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    retrieved_evidence: int = Field(default=0, ge=0)


class ParetoPoint(StrictModel):
    configuration: ParetoConfiguration
    observation_count: int = Field(ge=1)
    mean_diagnostic_accuracy: float = Field(ge=0.0, le=1.0)
    mean_estimated_cost: float = Field(ge=0.0)
    mean_total_tokens: float = Field(ge=0.0)
    mean_tool_calls: float = Field(ge=0.0)
    mean_retrieved_evidence: float = Field(ge=0.0)
    resource_cost_proxy: float = Field(ge=0.0)
    frontier_cost: float = Field(ge=0.0)
    dominated: bool
    accuracy_per_cost: float | None = Field(default=None, ge=0.0)


class ParetoReport(StrictModel):
    cost_basis: ParetoCostBasis
    resource_proxy_formula: str
    points: list[ParetoPoint]
    frontier_configuration_ids: list[str]
    dominated_configuration_ids: list[str]
    best_accuracy_per_cost_configuration_id: str | None = None
    sampled_dimensions: list[str]
    unsampled_dimensions: list[str]


def _resource_proxy(
    *,
    mean_tool_calls: float,
    mean_total_tokens: float,
    mean_retrieved_evidence: float,
) -> float:
    return mean_tool_calls + mean_total_tokens / 1000.0 + mean_retrieved_evidence / 10.0


def _dimension_values(configurations: list[ParetoConfiguration]) -> dict[str, set[object]]:
    return {
        "model": {item.model for item in configurations},
        "tool_budget": {item.tool_budget for item in configurations},
        "planning_strategy": {item.architecture for item in configurations},
        "retrieval_depth": {item.retrieval_depth for item in configurations},
        "verification_strategy": {item.evidence_mode for item in configurations},
    }


def _is_dominated(candidate: ParetoPoint, points: list[ParetoPoint]) -> bool:
    for other in points:
        if other.configuration.id == candidate.configuration.id:
            continue
        no_more_costly = other.frontier_cost <= candidate.frontier_cost
        no_less_accurate = (
            other.mean_diagnostic_accuracy >= candidate.mean_diagnostic_accuracy
        )
        strictly_better = (
            other.frontier_cost < candidate.frontier_cost
            or other.mean_diagnostic_accuracy > candidate.mean_diagnostic_accuracy
        )
        if no_more_costly and no_less_accurate and strictly_better:
            return True
    return False


def build_pareto_report(observations: list[ParetoObservation]) -> ParetoReport:
    if not observations:
        raise ValueError("Pareto analysis requires at least one observation")

    grouped: dict[str, list[ParetoObservation]] = defaultdict(list)
    configurations: dict[str, ParetoConfiguration] = {}
    for observation in observations:
        config = observation.configuration
        existing = configurations.get(config.id)
        if existing is not None and existing != config:
            raise ValueError(
                f"configuration id {config.id!r} maps to multiple configurations"
            )
        configurations[config.id] = config.model_copy(deep=True)
        grouped[config.id].append(observation)

    aggregates: list[
        tuple[ParetoConfiguration, int, float, float, float, float, float, float]
    ] = []
    for config_id in sorted(grouped):
        rows = grouped[config_id]
        mean_accuracy = fmean(row.diagnostic_accuracy for row in rows)
        mean_estimated_cost = fmean(row.estimated_cost for row in rows)
        mean_total_tokens = fmean(row.total_tokens for row in rows)
        mean_tool_calls = fmean(row.tool_calls for row in rows)
        mean_retrieved_evidence = fmean(row.retrieved_evidence for row in rows)
        proxy = _resource_proxy(
            mean_tool_calls=mean_tool_calls,
            mean_total_tokens=mean_total_tokens,
            mean_retrieved_evidence=mean_retrieved_evidence,
        )
        aggregates.append(
            (
                configurations[config_id],
                len(rows),
                mean_accuracy,
                mean_estimated_cost,
                mean_total_tokens,
                mean_tool_calls,
                mean_retrieved_evidence,
                proxy,
            )
        )

    monetary_available = any(item[3] > 0.0 for item in aggregates)
    cost_basis = (
        ParetoCostBasis.MONETARY
        if monetary_available
        else ParetoCostBasis.RESOURCE_PROXY
    )

    points = [
        ParetoPoint(
            configuration=config,
            observation_count=count,
            mean_diagnostic_accuracy=mean_accuracy,
            mean_estimated_cost=mean_estimated_cost,
            mean_total_tokens=mean_total_tokens,
            mean_tool_calls=mean_tool_calls,
            mean_retrieved_evidence=mean_retrieved_evidence,
            resource_cost_proxy=proxy,
            frontier_cost=(
                mean_estimated_cost
                if cost_basis == ParetoCostBasis.MONETARY
                else proxy
            ),
            dominated=False,
            accuracy_per_cost=None,
        )
        for (
            config,
            count,
            mean_accuracy,
            mean_estimated_cost,
            mean_total_tokens,
            mean_tool_calls,
            mean_retrieved_evidence,
            proxy,
        ) in aggregates
    ]

    for point in points:
        point.dominated = _is_dominated(point, points)
        if point.frontier_cost > 0.0:
            point.accuracy_per_cost = (
                point.mean_diagnostic_accuracy / point.frontier_cost
            )

    frontier = [point for point in points if not point.dominated]
    zero_cost_frontier = [point for point in frontier if point.frontier_cost == 0.0]
    best: ParetoPoint | None
    if zero_cost_frontier:
        best = min(
            zero_cost_frontier,
            key=lambda point: (
                -point.mean_diagnostic_accuracy,
                point.resource_cost_proxy,
                point.configuration.id,
            ),
        )
    else:
        ratio_points = [point for point in frontier if point.accuracy_per_cost is not None]
        best = (
            min(
                ratio_points,
                key=lambda point: (
                    -(point.accuracy_per_cost or 0.0),
                    -point.mean_diagnostic_accuracy,
                    point.frontier_cost,
                    point.configuration.id,
                ),
            )
            if ratio_points
            else None
        )

    dimension_values = _dimension_values(list(configurations.values()))
    sampled = [name for name in REQUIRED_DIMENSIONS if len(dimension_values[name]) > 1]
    unsampled = [name for name in REQUIRED_DIMENSIONS if len(dimension_values[name]) <= 1]

    return ParetoReport(
        cost_basis=cost_basis,
        resource_proxy_formula=RESOURCE_PROXY_FORMULA,
        points=points,
        frontier_configuration_ids=[
            point.configuration.id
            for point in sorted(
                frontier,
                key=lambda point: (
                    point.frontier_cost,
                    -point.mean_diagnostic_accuracy,
                    point.configuration.id,
                ),
            )
        ],
        dominated_configuration_ids=sorted(
            point.configuration.id for point in points if point.dominated
        ),
        best_accuracy_per_cost_configuration_id=(
            best.configuration.id if best is not None else None
        ),
        sampled_dimensions=sampled,
        unsampled_dimensions=unsampled,
    )
