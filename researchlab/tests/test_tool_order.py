from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from benchmarklab.catalog import load_catalog

from researchlab.models import ToolOrderVariant, TrialRecord, TrialStatus, make_trial_identity
from researchlab.tool_order import (
    ORDERING_VARIANTS,
    TOOL_ORDER_NEGATIVE_CONTROL,
    TOOL_ORDER_SCENARIO_IDS,
    build_tool_order_report,
    tool_order_plan,
    tool_order_scenarios,
)


def test_tool_order_plan_holds_non_order_dimensions_fixed() -> None:
    catalog = load_catalog()
    plan = tool_order_plan(dataset_version=catalog.benchmark_version)

    assert tuple(cell.configuration.tool_order for cell in plan.cells) == ORDERING_VARIANTS
    baseline = plan.cells[0].configuration.model_dump(mode="json")
    for cell in plan.cells:
        payload = cell.configuration.model_dump(mode="json")
        for key, value in baseline.items():
            if key == "tool_order":
                continue
            assert payload[key] == value


def test_tool_order_cohort_is_frozen_with_six_adversarial_cases_and_control() -> None:
    catalog = load_catalog()
    scenarios = tool_order_scenarios(catalog)

    assert [scenario.scenario_id for scenario in scenarios] == list(TOOL_ORDER_SCENARIO_IDS)
    assert sum(scenario.difficulty.value == "adversarial" for scenario in scenarios) == 6
    control = scenarios[-1]
    assert control.scenario_id == TOOL_ORDER_NEGATIVE_CONTROL


def _records() -> list[TrialRecord]:
    catalog = load_catalog()
    scenarios = tool_order_scenarios(catalog)
    plan = tool_order_plan(dataset_version=catalog.benchmark_version)
    records: list[TrialRecord] = []
    for cell in plan.cells:
        for scenario in scenarios:
            identity = make_trial_identity(plan, cell, scenario, 0)
            order = cell.configuration.tool_order
            planned_tools = [
                "query_metrics",
                "search_logs",
                "inspect_deployment",
                "inspect_git_diff",
            ]
            if order == ToolOrderVariant.DEPLOYMENT_FIRST:
                planned_tools = [
                    "inspect_deployment",
                    "query_metrics",
                    "search_logs",
                    "inspect_git_diff",
                ]
            steps = []
            for tool in planned_tools:
                if tool == "query_metrics":
                    arguments = {"service": "inventory", "metric": "error_rate"}
                elif tool == "search_logs":
                    arguments = {"service": "inventory", "level": "ERROR", "limit": 20}
                elif tool == "inspect_deployment":
                    arguments = {"service": "inventory"}
                else:
                    arguments = {"base": "HEAD~1", "head": "HEAD"}
                steps.append({"tool": tool, "arguments": arguments})
            expected = "no_fault" if scenario.scenario_id == TOOL_ORDER_NEGATIVE_CONTROL else "x"
            records.append(
                TrialRecord(
                    identity=identity,
                    status=TrialStatus.COMPLETED,
                    agent_run_id=uuid4(),
                    raw_trajectory={
                        "evaluation_case": {
                            "expected_primary_root_cause_code": expected,
                            "predicted_primary_root_cause_code": expected,
                        },
                        "evaluation_result": {"failure_classifications": []},
                        "benchmark_artifact": {
                            "raw_agent_run": {
                                "plan": {"steps": steps},
                                "tool_history": [{"tool_name": planned_tools[0]}],
                            }
                        },
                    },
                    scores={
                        "root_cause_accuracy": 1.0,
                        "exact_match": 1.0,
                        "confidence": 0.9,
                        "tool_calls": 4.0,
                        "latency_seconds": 1.0,
                        "estimated_cost": 0.0,
                    },
                )
            )
    return records


def test_tool_order_report_builds_four_arm_descriptive_comparison() -> None:
    catalog = load_catalog()
    report = build_tool_order_report(
        benchmark_version=catalog.benchmark_version,
        records=_records(),
    )

    assert len(report.observations) == 40
    assert len(report.aggregates) == 4
    assert len(report.paired_deltas) == 30
    assert all(aggregate.n == 10 for aggregate in report.aggregates)
    assert all(aggregate.adversarial_n == 6 for aggregate in report.aggregates)


def test_tool_order_report_rejects_changed_planned_invocation_set() -> None:
    catalog = load_catalog()
    records = _records()
    mutated = deepcopy(records)
    target = next(
        record
        for record in mutated
        if record.identity.scenario_id == TOOL_ORDER_SCENARIO_IDS[0]
        and record.identity.configuration.tool_order == ToolOrderVariant.ADAPTIVE
    )
    target.raw_trajectory["benchmark_artifact"]["raw_agent_run"]["plan"]["steps"].append(
        {"tool": "search_docs", "arguments": {"query": "inventory"}}
    )

    with pytest.raises(ValueError, match="changed the legal planned invocation set"):
        build_tool_order_report(
            benchmark_version=catalog.benchmark_version,
            records=mutated,
        )
