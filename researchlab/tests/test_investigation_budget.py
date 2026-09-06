from __future__ import annotations

import pytest
from benchmarklab.catalog import load_catalog

from researchlab.investigation_budget import (
    BUDGETS,
    build_investigation_budget_report,
    investigation_budget_plan,
    validation_scenarios,
)
from researchlab.models import ArchitectureVariant, TrialRecord, TrialStatus, make_trial_identity

EXPECTED_VALIDATION_IDS = [
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
]


def test_h2_uses_complete_validation_split_and_registered_budgets() -> None:
    catalog = load_catalog()
    scenarios = validation_scenarios(catalog)
    plan = investigation_budget_plan(dataset_version=catalog.benchmark_version)

    assert [scenario.scenario_id for scenario in scenarios] == EXPECTED_VALIDATION_IDS
    assert [cell.configuration.tool_budget for cell in plan.cells] == list(BUDGETS)
    assert all(
        cell.configuration.architecture == ArchitectureVariant.EXPLICIT_PLANNER
        for cell in plan.cells
    )


def _records() -> tuple[list[object], list[TrialRecord]]:
    catalog = load_catalog()
    scenarios = validation_scenarios(catalog)
    plan = investigation_budget_plan(dataset_version=catalog.benchmark_version)
    records: list[TrialRecord] = []
    for cell in plan.cells:
        budget = cell.configuration.tool_budget
        for scenario in scenarios:
            no_fault = scenario.scenario_id == "ops-v1-040"
            false_positive = no_fault and budget == 5
            expected_root_cause = "NO_FAULT" if no_fault else "N_PLUS_ONE"
            if false_positive:
                predicted_root_cause = "N_PLUS_ONE"
            elif no_fault:
                predicted_root_cause = "NO_FAULT"
            else:
                predicted_root_cause = "N_PLUS_ONE"
            budget_exhausted = budget == 5 and scenario.scenario_id == "ops-v1-021"
            identity = make_trial_identity(plan, cell, scenario, 0)
            records.append(
                TrialRecord(
                    identity=identity,
                    status=TrialStatus.COMPLETED,
                    raw_trajectory={
                        "evaluation_case": {
                            "expected_primary_root_cause_code": expected_root_cause,
                            "predicted_primary_root_cause_code": predicted_root_cause,
                            "budget_exhausted": budget_exhausted,
                        },
                        "evaluation_result": {
                            "evidence": {"distractor_selection_rate": budget / 100.0},
                            "failure_classifications": (
                                [{"category": "OVER_INVESTIGATION"}] if budget == 20 else []
                            ),
                        },
                    },
                    scores={
                        "root_cause_accuracy": 1.0,
                        "exact_match": 1.0,
                        "confidence": 0.5 + budget / 100.0,
                        "tool_calls": 3.0,
                        "latency_seconds": budget / 10.0,
                        "estimated_cost": budget / 1000.0,
                    },
                )
            )
    return scenarios, records


def test_h2_report_tracks_false_positive_distractors_and_exhaustion() -> None:
    catalog = load_catalog()
    scenarios, records = _records()

    report = build_investigation_budget_report(
        benchmark_version=catalog.benchmark_version,
        scenarios=scenarios,
        records=records,
    )

    assert report.interpretation == "descriptive_only"
    assert len(report.observations) == 40
    assert len(report.aggregates) == 4
    assert report.budgets == list(BUDGETS)
    assert report.scenario_ids == EXPECTED_VALIDATION_IDS

    by_budget = {item.tool_budget: item for item in report.aggregates}
    assert by_budget[5].negative_control_n == 1
    assert by_budget[5].false_positive_count == 1
    assert by_budget[5].false_positive_rate == 1.0
    assert by_budget[5].budget_exhaustion_count == 1
    assert by_budget[10].false_positive_rate == 0.0
    assert by_budget[20].failure_mode_counts == {"OVER_INVESTIGATION": 10}
    assert by_budget[20].mean_distractor_selection_rate == pytest.approx(0.2)
    assert by_budget[20].mean_budget_utilization == pytest.approx(0.15)


def test_h2_report_rejects_incomplete_budget_coverage() -> None:
    catalog = load_catalog()
    scenarios, records = _records()

    with pytest.raises(ValueError, match="requires 40 observations"):
        build_investigation_budget_report(
            benchmark_version=catalog.benchmark_version,
            scenarios=scenarios,
            records=records[:-1],
        )
