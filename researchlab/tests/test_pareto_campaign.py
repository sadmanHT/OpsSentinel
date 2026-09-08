from __future__ import annotations

from collections import Counter
from itertools import combinations
from uuid import UUID

import pytest
from benchmarklab.catalog import load_catalog

from researchlab.models import ArchitectureVariant, EvidenceMode
from researchlab.pareto import ParetoCostBasis
from researchlab.pareto_campaign import (
    MODEL_DIMENSION_STATUS,
    NO_FAULT_SCENARIO_ID,
    PARETO_CONFIGURATIONS,
    PARETO_VALIDATION_SCENARIO_IDS,
    ParetoCampaignTrial,
    build_pareto_campaign_report,
    pareto_configuration,
    render_pareto_svg,
    validate_pareto_catalog,
)


def _complete_trials() -> list[ParetoCampaignTrial]:
    trials: list[ParetoCampaignTrial] = []
    counter = 1
    for config_index, configuration in enumerate(PARETO_CONFIGURATIONS):
        for scenario_index, scenario_id in enumerate(PARETO_VALIDATION_SCENARIO_IDS):
            correct = (config_index + scenario_index) % 5 != 0
            trials.append(
                ParetoCampaignTrial(
                    configuration=configuration.model_copy(deep=True),
                    scenario_id=scenario_id,
                    agent_run_id=UUID(int=counter),
                    diagnostic_accuracy=float(correct),
                    exact_match=float(correct),
                    estimated_cost=0.0,
                    total_tokens=100 + config_index * 10,
                    tool_calls=2 + (config_index % 3),
                    retrieved_evidence=4 + config_index,
                    latency_seconds=0.1 + config_index * 0.01,
                    time_to_diagnosis_ms=50.0 + config_index,
                    failure_categories=[] if correct else ["MISSED_EVIDENCE"],
                    no_fault_false_positive=(
                        not correct if scenario_id == NO_FAULT_SCENARIO_ID else None
                    ),
                )
            )
            counter += 1
    return trials


def _factor_tuple(configuration: object) -> tuple[object, ...]:
    item = configuration
    assert hasattr(item, "architecture")
    assert hasattr(item, "tool_budget")
    assert hasattr(item, "retrieval_depth")
    assert hasattr(item, "evidence_mode")
    return (
        item.architecture,
        item.tool_budget,
        item.retrieval_depth,
        item.evidence_mode,
    )


def test_frozen_grid_is_balanced_and_model_is_fixed() -> None:
    assert [item.id for item in PARETO_CONFIGURATIONS] == [
        "p9-c01",
        "p9-c02",
        "p9-c03",
        "p9-c04",
        "p9-c05",
        "p9-c06",
        "p9-c07",
        "p9-c08",
    ]
    assert {item.provider for item in PARETO_CONFIGURATIONS} == {"local"}
    assert {item.model for item in PARETO_CONFIGURATIONS} == {"local-placeholder"}

    factors = [_factor_tuple(item) for item in PARETO_CONFIGURATIONS]
    for factor_index in range(4):
        counts = Counter(row[factor_index] for row in factors)
        assert sorted(counts.values()) == [4, 4]

    for first, second in combinations(range(4), 2):
        pair_counts = Counter((row[first], row[second]) for row in factors)
        assert len(pair_counts) == 4
        assert set(pair_counts.values()) == {2}

    assert {item.architecture for item in PARETO_CONFIGURATIONS} == {
        ArchitectureVariant.REACTIVE_REACT,
        ArchitectureVariant.EXPLICIT_PLANNER,
    }
    assert {item.evidence_mode for item in PARETO_CONFIGURATIONS} == {
        EvidenceMode.PASSIVE_ONLY,
        EvidenceMode.VERIFICATION_ENABLED,
    }


def test_catalog_selection_is_exact_validation_only_cohort() -> None:
    selected = validate_pareto_catalog(load_catalog())
    assert [item.scenario_id for item in selected] == list(PARETO_VALIDATION_SCENARIO_IDS)
    assert len(selected) == 10
    assert all(item.split.value == "validation" for item in selected)
    assert not any(item.split.value == "hidden_test" for item in selected)


def test_configuration_lookup_is_frozen_and_defensive() -> None:
    configuration = pareto_configuration("p9-c05")
    assert configuration == PARETO_CONFIGURATIONS[4]
    configuration.tool_budget = 99
    assert PARETO_CONFIGURATIONS[4].tool_budget == 5
    with pytest.raises(KeyError, match="unknown Phase 9 Pareto configuration"):
        pareto_configuration("p9-unknown")


def test_complete_campaign_builds_resource_proxy_frontier() -> None:
    report = build_pareto_campaign_report(
        benchmark_version="ops-v1",
        trials=_complete_trials(),
    )
    assert report.trial_count == 80
    assert report.model_dimension_status == MODEL_DIMENSION_STATUS
    assert report.pareto.cost_basis == ParetoCostBasis.RESOURCE_PROXY
    assert "model" in report.pareto.unsampled_dimensions
    assert set(report.pareto.sampled_dimensions) == {
        "tool_budget",
        "planning_strategy",
        "retrieval_depth",
        "verification_strategy",
    }
    assert len(report.configuration_summaries) == 8
    assert all(item.trial_count == 10 for item in report.configuration_summaries)
    assert all(item.negative_control_count == 1 for item in report.configuration_summaries)
    assert report.pareto.frontier_configuration_ids

    svg = render_pareto_svg(report)
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert "Phase 9 Pareto frontier" in svg
    for configuration in PARETO_CONFIGURATIONS:
        assert configuration.id in svg


def test_campaign_rejects_missing_trial() -> None:
    with pytest.raises(ValueError, match="requires 80 trials"):
        build_pareto_campaign_report(
            benchmark_version="ops-v1",
            trials=_complete_trials()[:-1],
        )


def test_campaign_rejects_duplicate_pair() -> None:
    trials = _complete_trials()
    trials[-1] = trials[0].model_copy(deep=True)
    with pytest.raises(ValueError, match="duplicate Phase 9 Pareto trial pair"):
        build_pareto_campaign_report(benchmark_version="ops-v1", trials=trials)


def test_campaign_rejects_configuration_drift() -> None:
    trials = _complete_trials()
    altered = trials[0].model_copy(deep=True)
    altered.configuration.model = "unregistered-model"
    trials[0] = altered
    with pytest.raises(ValueError, match="differs from the frozen grid"):
        build_pareto_campaign_report(benchmark_version="ops-v1", trials=trials)


def test_campaign_rejects_scenario_outside_validation_cohort() -> None:
    trials = _complete_trials()
    altered = trials[0].model_copy(deep=True)
    altered.scenario_id = "ops-v1-001"
    trials[0] = altered
    with pytest.raises(ValueError, match="outside the frozen validation cohort"):
        build_pareto_campaign_report(benchmark_version="ops-v1", trials=trials)


def test_campaign_rejects_missing_no_fault_false_positive_status() -> None:
    trials = _complete_trials()
    index = next(
        index
        for index, trial in enumerate(trials)
        if trial.scenario_id == NO_FAULT_SCENARIO_ID
    )
    altered = trials[index].model_copy(deep=True)
    altered.no_fault_false_positive = None
    trials[index] = altered
    with pytest.raises(ValueError, match="must report false-positive status"):
        build_pareto_campaign_report(benchmark_version="ops-v1", trials=trials)
