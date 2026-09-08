from __future__ import annotations

from copy import deepcopy
from typing import Any, cast
from uuid import uuid4

import pytest
from benchmarklab.catalog import load_catalog

from researchlab.compound_handling import (
    COMPOUND_SCENARIO_IDS,
    EXPECTED_PLAN,
    STOPPING_STRATEGIES,
    build_compound_handling_report,
    compound_handling_plan,
    compound_handling_scenarios,
)
from researchlab.live_executor import (
    ARCHITECTURE_VERSION_BY_VARIANT,
    COMPOUND_EVIDENCE_PROVIDER_MARKER,
    UNRESOLVED_EVIDENCE_PROVIDER_MARKER,
    LiveTrialExecutor,
    TreatmentIsolationError,
)
from researchlab.models import (
    ArchitectureVariant,
    ExperimentSplit,
    StoppingStrategy,
    TrialRecord,
    TrialStatus,
    make_trial_identity,
)


class StaticHealthProbe:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    async def read(self) -> dict[str, object]:
        return self.payload


def _health(strategy: StoppingStrategy, *, compound_plan: bool = True) -> dict[str, object]:
    provider = f"deterministic+{COMPOUND_EVIDENCE_PROVIDER_MARKER}"
    if strategy == StoppingStrategy.UNRESOLVED_EVIDENCE:
        provider += f"+{UNRESOLVED_EVIDENCE_PROVIDER_MARKER}"
    return {
        "status": "ok",
        "architecture": ARCHITECTURE_VERSION_BY_VARIANT[
            ArchitectureVariant.EXPLICIT_PLANNER
        ],
        "provider": provider,
        "temporal_reasoning": "standard",
        "tool_order": "free",
        "tool_order_controlled": False,
        "evidence_mode": "passive_only",
        "stopping_strategy": strategy.value,
        "compound_evidence_plan": compound_plan,
        "legal_tool_count": 16,
    }


def test_h5_plan_is_hidden_and_varies_only_stopping_strategy() -> None:
    catalog = load_catalog()
    plan = compound_handling_plan(dataset_version=catalog.benchmark_version)

    assert plan.split == ExperimentSplit.HIDDEN_TEST
    assert tuple(cell.configuration.stopping_strategy for cell in plan.cells) == (
        STOPPING_STRATEGIES
    )
    baseline = plan.cells[0].configuration.model_dump(mode="json")
    for cell in plan.cells:
        payload = cell.configuration.model_dump(mode="json")
        for key, value in baseline.items():
            if key == "stopping_strategy":
                continue
            assert payload[key] == value


def test_h5_cohort_is_frozen_to_eight_hidden_compound_cases() -> None:
    catalog = load_catalog()
    scenarios = compound_handling_scenarios(catalog)

    assert [scenario.scenario_id for scenario in scenarios] == list(COMPOUND_SCENARIO_IDS)
    assert all(scenario.split == ExperimentSplit.HIDDEN_TEST for scenario in scenarios)
    assert all(scenario.difficulty.value == "compound" for scenario in scenarios)


@pytest.mark.asyncio
async def test_h5_runtime_accepts_matching_unresolved_evidence_health() -> None:
    catalog = load_catalog()
    plan = compound_handling_plan(dataset_version=catalog.benchmark_version)
    scenario = compound_handling_scenarios(catalog)[0]
    cell = next(
        item
        for item in plan.cells
        if item.configuration.stopping_strategy == StoppingStrategy.UNRESOLVED_EVIDENCE
    )
    identity = make_trial_identity(plan, cell, scenario, 0)
    executor = LiveTrialExecutor(
        catalog=catalog,
        benchmark_runner=cast(Any, object()),
        evaluation_store=cast(Any, object()),
        health_probe=StaticHealthProbe(_health(StoppingStrategy.UNRESOLVED_EVIDENCE)),
    )

    health = await executor._runtime_health(identity)

    assert health["compound_evidence_plan"] is True
    assert health["stopping_strategy"] == "unresolved_evidence"


@pytest.mark.asyncio
async def test_h5_runtime_rejects_missing_compound_plan_before_launch() -> None:
    catalog = load_catalog()
    plan = compound_handling_plan(dataset_version=catalog.benchmark_version)
    scenario = compound_handling_scenarios(catalog)[0]
    cell = plan.cells[0]
    identity = make_trial_identity(plan, cell, scenario, 0)
    executor = LiveTrialExecutor(
        catalog=catalog,
        benchmark_runner=cast(Any, object()),
        evaluation_store=cast(Any, object()),
        health_probe=StaticHealthProbe(
            _health(StoppingStrategy.CONFIDENCE_THRESHOLD, compound_plan=False)
        ),
    )

    with pytest.raises(TreatmentIsolationError, match="shared compound evidence plan"):
        await executor._runtime_health(identity)


def _raw_steps(*, completed: int) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    for index, (step_id, tool, arguments) in enumerate(EXPECTED_PLAN):
        steps.append(
            {
                "id": step_id,
                "objective": step_id,
                "tool": tool,
                "arguments": arguments,
                "rationale": step_id,
                "required": True,
                "completed": index < completed,
            }
        )
    return steps


def _records() -> list[TrialRecord]:
    catalog = load_catalog()
    scenarios = compound_handling_scenarios(catalog)
    plan = compound_handling_plan(dataset_version=catalog.benchmark_version)
    records: list[TrialRecord] = []
    for cell in plan.cells:
        unresolved = (
            cell.configuration.stopping_strategy == StoppingStrategy.UNRESOLVED_EVIDENCE
        )
        completed = len(EXPECTED_PLAN) if unresolved else 4
        for scenario in scenarios:
            identity = make_trial_identity(plan, cell, scenario, 0)
            provider = f"deterministic+{COMPOUND_EVIDENCE_PROVIDER_MARKER}"
            if unresolved:
                provider += f"+{UNRESOLVED_EVIDENCE_PROVIDER_MARKER}"
            records.append(
                TrialRecord(
                    identity=identity,
                    status=TrialStatus.COMPLETED,
                    agent_run_id=uuid4(),
                    raw_trajectory={
                        "runtime_health": {
                            "provider": provider,
                            "compound_evidence_plan": True,
                            "stopping_strategy": cell.configuration.stopping_strategy.value,
                        },
                        "evaluation_case": {
                            "expected_primary_root_cause_code": "primary_truth",
                            "expected_secondary_root_cause_codes": ["secondary_truth"],
                        },
                        "benchmark_artifact": {
                            "raw_agent_run": {
                                "incident": {
                                    "title": "Acute service incident overlaps older degradation",
                                    "description": "Two genuine problems coexist.",
                                },
                                "plan": {"steps": _raw_steps(completed=completed)},
                                "tool_history": [
                                    {"tool_name": EXPECTED_PLAN[index][1]}
                                    for index in range(completed)
                                ],
                            }
                        },
                    },
                    scores={
                        "root_cause_accuracy": 1.0,
                        "exact_match": 1.0,
                        "secondary_recall": 0.0,
                        "multi_root_cause_precision": 1.0,
                        "multi_root_cause_recall": 0.5,
                        "evidence_precision": 1.0,
                        "evidence_recall": 0.5,
                        "critical_evidence_recall": 0.5,
                        "confidence": 0.9,
                        "tool_calls": float(completed),
                        "latency_seconds": float(completed) / 10.0,
                        "estimated_cost": 0.0,
                    },
                )
            )
    return records


def test_h5_report_builds_descriptive_two_arm_comparison() -> None:
    catalog = load_catalog()
    report = build_compound_handling_report(
        benchmark_version=catalog.benchmark_version,
        records=_records(),
    )

    assert len(report.observations) == 16
    assert len(report.aggregates) == 2
    assert len(report.paired_deltas) == 8
    unresolved = next(
        aggregate
        for aggregate in report.aggregates
        if aggregate.stopping_strategy == StoppingStrategy.UNRESOLVED_EVIDENCE
    )
    assert unresolved.full_plan_completion_rate == 1.0
    assert unresolved.mean_completed_required_steps == float(len(EXPECTED_PLAN))


def test_h5_report_rejects_unresolved_arm_with_incomplete_required_evidence() -> None:
    catalog = load_catalog()
    mutated = deepcopy(_records())
    target = next(
        record
        for record in mutated
        if record.identity.configuration.stopping_strategy
        == StoppingStrategy.UNRESOLVED_EVIDENCE
    )
    steps = target.raw_trajectory["benchmark_artifact"]["raw_agent_run"]["plan"]["steps"]
    steps[-1]["completed"] = False

    with pytest.raises(ValueError, match="stopped with required evidence unresolved"):
        build_compound_handling_report(
            benchmark_version=catalog.benchmark_version,
            records=mutated,
        )


def test_h5_report_rejects_shared_plan_tampering() -> None:
    catalog = load_catalog()
    mutated = deepcopy(_records())
    target = mutated[0]
    steps = target.raw_trajectory["benchmark_artifact"]["raw_agent_run"]["plan"]["steps"]
    steps[0]["arguments"] = {"service": "checkout", "metric": "error_rate"}

    with pytest.raises(ValueError, match="shared investigation plan invocation changed"):
        build_compound_handling_report(
            benchmark_version=catalog.benchmark_version,
            records=mutated,
        )
