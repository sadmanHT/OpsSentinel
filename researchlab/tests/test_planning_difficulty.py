from __future__ import annotations

from benchmarklab.catalog import load_catalog

from researchlab.models import (
    ArchitectureVariant,
    Difficulty,
    TrialRecord,
    TrialStatus,
    make_trial_identity,
)
from researchlab.planning_difficulty import (
    SPLIT_BY_DIFFICULTY,
    build_planning_difficulty_report,
    build_planning_difficulty_tier_plans,
    select_planning_difficulty_scenarios,
)

EXPECTED_IDS: dict[Difficulty, list[str]] = {
    Difficulty.EASY: ["ops-v1-001", "ops-v1-002"],
    Difficulty.MEDIUM: ["ops-v1-021", "ops-v1-022"],
    Difficulty.HARD: ["ops-v1-033", "ops-v1-034"],
    Difficulty.ADVERSARIAL: ["ops-v1-035", "ops-v1-036"],
    Difficulty.COMPOUND: ["ops-v1-043", "ops-v1-044"],
}


def test_planning_difficulty_selection_is_preregistered_and_split_safe() -> None:
    selected = select_planning_difficulty_scenarios(load_catalog())

    assert {
        difficulty: [scenario.scenario_id for scenario in scenarios]
        for difficulty, scenarios in selected.items()
    } == EXPECTED_IDS
    for difficulty, scenarios in selected.items():
        assert all(scenario.difficulty == difficulty for scenario in scenarios)
        assert all(scenario.split == SPLIT_BY_DIFFICULTY[difficulty] for scenario in scenarios)


def test_planning_difficulty_tier_plans_vary_only_architecture() -> None:
    plans = build_planning_difficulty_tier_plans()

    assert set(plans) == set(Difficulty)
    for difficulty, plan in plans.items():
        assert plan.split == SPLIT_BY_DIFFICULTY[difficulty]
        assert plan.repeat_count == 1
        assert [cell.id for cell in plan.cells] == ["reactive", "planner"]
        assert [cell.configuration.architecture for cell in plan.cells] == [
            ArchitectureVariant.REACTIVE_REACT,
            ArchitectureVariant.EXPLICIT_PLANNER,
        ]
        assert all(cell.configuration.tool_budget == 15 for cell in plan.cells)
        assert all(cell.difficulties == [difficulty] for cell in plan.cells)


def _completed_records() -> tuple[dict[Difficulty, list[object]], list[TrialRecord]]:
    catalog = load_catalog()
    selected = select_planning_difficulty_scenarios(catalog)
    plans = build_planning_difficulty_tier_plans(dataset_version=catalog.benchmark_version)
    records: list[TrialRecord] = []

    for difficulty in Difficulty:
        plan = plans[difficulty]
        for cell in plan.cells:
            for scenario in selected[difficulty]:
                identity = make_trial_identity(plan, cell, scenario, 0)
                is_planner = cell.configuration.architecture == ArchitectureVariant.EXPLICIT_PLANNER
                records.append(
                    TrialRecord(
                        identity=identity,
                        status=TrialStatus.COMPLETED,
                        raw_trajectory={
                            "evaluation_result": {
                                "failure_classifications": (
                                    [{"category": "over_investigation"}] if is_planner else []
                                )
                            }
                        },
                        scores={
                            "root_cause_accuracy": 1.0 if is_planner else 0.5,
                            "exact_match": 1.0 if is_planner else 0.0,
                            "tool_calls": 8.0 if is_planner else 5.0,
                            "latency_seconds": 2.0 if is_planner else 1.0,
                            "estimated_cost": 0.08 if is_planner else 0.05,
                            "confidence": 0.9 if is_planner else 0.6,
                        },
                    )
                )
    return selected, records


def test_planning_difficulty_report_is_descriptive_and_complete() -> None:
    catalog = load_catalog()
    selected, records = _completed_records()

    report = build_planning_difficulty_report(
        benchmark_version=catalog.benchmark_version,
        selected=selected,
        records=records,
    )

    assert report.interpretation == "descriptive_only"
    assert len(report.observations) == 20
    assert len(report.aggregates) == 10
    assert len(report.deltas) == 5
    assert report.selected_scenarios == {
        difficulty.value: ids for difficulty, ids in EXPECTED_IDS.items()
    }
    for delta in report.deltas:
        assert delta.planner_minus_reactive_accuracy == 0.5
        assert delta.planner_minus_reactive_exact_match == 1.0
        assert delta.planner_minus_reactive_tool_calls == 3.0
        assert delta.planner_minus_reactive_latency_seconds == 1.0
        assert delta.planner_minus_reactive_estimated_cost == 0.03
    planner_aggregates = [
        item
        for item in report.aggregates
        if item.architecture == ArchitectureVariant.EXPLICIT_PLANNER
    ]
    assert all(item.failure_mode_counts == {"over_investigation": 2} for item in planner_aggregates)


def test_planning_difficulty_report_rejects_incomplete_campaign() -> None:
    catalog = load_catalog()
    selected, records = _completed_records()

    try:
        build_planning_difficulty_report(
            benchmark_version=catalog.benchmark_version,
            selected=selected,
            records=records[:-1],
        )
    except ValueError as exc:
        assert "requires 20 observations" in str(exc)
    else:
        raise AssertionError("incomplete planning/difficulty campaign was accepted")
