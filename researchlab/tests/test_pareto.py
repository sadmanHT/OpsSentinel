from __future__ import annotations

import pytest

from researchlab.models import ArchitectureVariant, EvidenceMode
from researchlab.pareto import (
    ParetoConfiguration,
    ParetoCostBasis,
    ParetoObservation,
    build_pareto_report,
)


def configuration(
    config_id: str,
    *,
    model: str = "deterministic-evidence-v1",
    architecture: ArchitectureVariant = ArchitectureVariant.EXPLICIT_PLANNER,
    tool_budget: int = 10,
    retrieval_depth: int = 20,
    evidence_mode: EvidenceMode = EvidenceMode.PASSIVE_ONLY,
) -> ParetoConfiguration:
    return ParetoConfiguration(
        id=config_id,
        provider="local",
        model=model,
        architecture=architecture,
        tool_budget=tool_budget,
        retrieval_depth=retrieval_depth,
        evidence_mode=evidence_mode,
    )


def observation(
    config: ParetoConfiguration,
    *,
    scenario_id: str,
    accuracy: float,
    estimated_cost: float = 0.0,
    tokens: int = 0,
    tool_calls: int = 0,
    evidence: int = 0,
) -> ParetoObservation:
    return ParetoObservation(
        configuration=config,
        scenario_id=scenario_id,
        diagnostic_accuracy=accuracy,
        estimated_cost=estimated_cost,
        total_tokens=tokens,
        tool_calls=tool_calls,
        retrieved_evidence=evidence,
    )


def test_zero_monetary_cost_uses_resource_proxy_and_marks_dominated() -> None:
    efficient = configuration("efficient", tool_budget=5, retrieval_depth=5)
    expensive = configuration(
        "expensive",
        architecture=ArchitectureVariant.REACTIVE_REACT,
        tool_budget=20,
        retrieval_depth=20,
        evidence_mode=EvidenceMode.VERIFICATION_ENABLED,
    )

    report = build_pareto_report(
        [
            observation(
                efficient,
                scenario_id="s1",
                accuracy=0.8,
                tool_calls=3,
                evidence=4,
            ),
            observation(
                efficient,
                scenario_id="s2",
                accuracy=0.8,
                tool_calls=3,
                evidence=4,
            ),
            observation(
                expensive,
                scenario_id="s1",
                accuracy=0.8,
                tool_calls=7,
                evidence=12,
            ),
            observation(
                expensive,
                scenario_id="s2",
                accuracy=0.8,
                tool_calls=7,
                evidence=12,
            ),
        ]
    )

    assert report.cost_basis == ParetoCostBasis.RESOURCE_PROXY
    assert report.frontier_configuration_ids == ["efficient"]
    assert report.dominated_configuration_ids == ["expensive"]
    assert report.best_accuracy_per_cost_configuration_id == "efficient"
    assert "model" in report.unsampled_dimensions
    assert set(report.sampled_dimensions) == {
        "tool_budget",
        "planning_strategy",
        "retrieval_depth",
        "verification_strategy",
    }


def test_any_nonzero_monetary_cost_selects_monetary_basis() -> None:
    cheap = configuration("cheap", tool_budget=5)
    costly = configuration("costly", tool_budget=20)

    report = build_pareto_report(
        [
            observation(
                cheap,
                scenario_id="s1",
                accuracy=0.7,
                estimated_cost=0.01,
                tool_calls=4,
            ),
            observation(
                costly,
                scenario_id="s1",
                accuracy=0.9,
                estimated_cost=0.05,
                tool_calls=8,
            ),
        ]
    )

    assert report.cost_basis == ParetoCostBasis.MONETARY
    points = {point.configuration.id: point for point in report.points}
    assert points["cheap"].frontier_cost == pytest.approx(0.01)
    assert points["costly"].frontier_cost == pytest.approx(0.05)
    assert set(report.frontier_configuration_ids) == {"cheap", "costly"}


def test_duplicate_configuration_id_with_different_settings_is_rejected() -> None:
    first = configuration("same", tool_budget=5)
    second = configuration("same", tool_budget=10)

    with pytest.raises(ValueError, match="maps to multiple configurations"):
        build_pareto_report(
            [
                observation(first, scenario_id="s1", accuracy=1.0),
                observation(second, scenario_id="s2", accuracy=1.0),
            ]
        )


def test_model_dimension_is_reported_as_sampled_only_when_models_differ() -> None:
    deterministic = configuration("deterministic", model="deterministic-evidence-v1")
    local_model = configuration("local-model", model="qwen2.5:7b")

    report = build_pareto_report(
        [
            observation(deterministic, scenario_id="s1", accuracy=0.8, tool_calls=4),
            observation(local_model, scenario_id="s1", accuracy=0.8, tool_calls=4),
        ]
    )

    assert "model" in report.sampled_dimensions
    assert "model" not in report.unsampled_dimensions


def test_empty_observation_set_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one observation"):
        build_pareto_report([])
