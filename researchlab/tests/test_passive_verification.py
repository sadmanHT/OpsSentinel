from __future__ import annotations

from copy import deepcopy
from typing import Any, cast
from uuid import uuid4

import pytest
from benchmarklab.catalog import load_catalog

from researchlab.live_executor import (
    ACTIVE_VERIFICATION_PROVIDER_MARKER,
    ARCHITECTURE_VERSION_BY_VARIANT,
    LiveTrialExecutor,
    TreatmentIsolationError,
)
from researchlab.models import (
    ArchitectureVariant,
    EvidenceMode,
    TrialRecord,
    TrialStatus,
    make_trial_identity,
)
from researchlab.passive_verification import (
    EVIDENCE_MODES,
    PASSIVE_VERIFICATION_NEGATIVE_CONTROL,
    PASSIVE_VERIFICATION_SCENARIO_IDS,
    build_passive_verification_report,
    passive_verification_plan,
    passive_verification_scenarios,
)


class StaticHealthProbe:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    async def read(self) -> dict[str, object]:
        return self.payload


def _health(mode: EvidenceMode, *, marker: bool | None = None) -> dict[str, object]:
    provider = "deterministic"
    include_marker = mode == EvidenceMode.VERIFICATION_ENABLED if marker is None else marker
    if include_marker:
        provider += f"+{ACTIVE_VERIFICATION_PROVIDER_MARKER}"
    return {
        "status": "ok",
        "architecture": ARCHITECTURE_VERSION_BY_VARIANT[
            ArchitectureVariant.EXPLICIT_PLANNER
        ],
        "provider": provider,
        "temporal_reasoning": "standard",
        "tool_order": "free",
        "tool_order_controlled": False,
        "evidence_mode": mode.value,
        "legal_tool_count": 16,
    }


def test_h4_plan_holds_non_evidence_dimensions_fixed() -> None:
    catalog = load_catalog()
    plan = passive_verification_plan(dataset_version=catalog.benchmark_version)

    assert tuple(cell.configuration.evidence_mode for cell in plan.cells) == EVIDENCE_MODES
    baseline = plan.cells[0].configuration.model_dump(mode="json")
    for cell in plan.cells:
        payload = cell.configuration.model_dump(mode="json")
        for key, value in baseline.items():
            if key == "evidence_mode":
                continue
            assert payload[key] == value


def test_h4_cohort_is_frozen_with_six_adversarial_cases_and_control() -> None:
    catalog = load_catalog()
    scenarios = passive_verification_scenarios(catalog)

    assert [scenario.scenario_id for scenario in scenarios] == list(
        PASSIVE_VERIFICATION_SCENARIO_IDS
    )
    assert sum(scenario.difficulty.value == "adversarial" for scenario in scenarios) == 6
    assert scenarios[-1].scenario_id == PASSIVE_VERIFICATION_NEGATIVE_CONTROL


@pytest.mark.asyncio
async def test_h4_runtime_accepts_matching_active_verification_health() -> None:
    catalog = load_catalog()
    plan = passive_verification_plan(dataset_version=catalog.benchmark_version)
    scenario = passive_verification_scenarios(catalog)[0]
    cell = next(
        item
        for item in plan.cells
        if item.configuration.evidence_mode == EvidenceMode.VERIFICATION_ENABLED
    )
    identity = make_trial_identity(plan, cell, scenario, 0)
    executor = LiveTrialExecutor(
        catalog=catalog,
        benchmark_runner=cast(Any, object()),
        evaluation_store=cast(Any, object()),
        health_probe=StaticHealthProbe(_health(EvidenceMode.VERIFICATION_ENABLED)),
    )

    health = await executor._runtime_health(identity)

    assert health["evidence_mode"] == "verification_enabled"


@pytest.mark.asyncio
async def test_h4_runtime_rejects_evidence_mode_mismatch_before_launch() -> None:
    catalog = load_catalog()
    plan = passive_verification_plan(dataset_version=catalog.benchmark_version)
    scenario = passive_verification_scenarios(catalog)[0]
    cell = next(
        item
        for item in plan.cells
        if item.configuration.evidence_mode == EvidenceMode.VERIFICATION_ENABLED
    )
    identity = make_trial_identity(plan, cell, scenario, 0)
    executor = LiveTrialExecutor(
        catalog=catalog,
        benchmark_runner=cast(Any, object()),
        evaluation_store=cast(Any, object()),
        health_probe=StaticHealthProbe(_health(EvidenceMode.PASSIVE_ONLY)),
    )

    with pytest.raises(TreatmentIsolationError, match="active evidence mode"):
        await executor._runtime_health(identity)


@pytest.mark.asyncio
async def test_h4_passive_runtime_rejects_active_verification_marker() -> None:
    catalog = load_catalog()
    plan = passive_verification_plan(dataset_version=catalog.benchmark_version)
    scenario = passive_verification_scenarios(catalog)[0]
    cell = next(
        item
        for item in plan.cells
        if item.configuration.evidence_mode == EvidenceMode.PASSIVE_ONLY
    )
    identity = make_trial_identity(plan, cell, scenario, 0)
    executor = LiveTrialExecutor(
        catalog=catalog,
        benchmark_runner=cast(Any, object()),
        evaluation_store=cast(Any, object()),
        health_probe=StaticHealthProbe(
            _health(EvidenceMode.PASSIVE_ONLY, marker=True)
        ),
    )

    with pytest.raises(TreatmentIsolationError, match="verification provider marker"):
        await executor._runtime_health(identity)


def _records() -> list[TrialRecord]:
    catalog = load_catalog()
    scenarios = passive_verification_scenarios(catalog)
    plan = passive_verification_plan(dataset_version=catalog.benchmark_version)
    records: list[TrialRecord] = []
    for cell in plan.cells:
        for scenario in scenarios:
            identity = make_trial_identity(plan, cell, scenario, 0)
            active = cell.configuration.evidence_mode == EvidenceMode.VERIFICATION_ENABLED
            steps = [
                {
                    "tool": "query_metrics",
                    "arguments": {"service": "inventory", "metric": "error_rate"},
                },
                {
                    "tool": "search_logs",
                    "arguments": {
                        "service": "inventory",
                        "level": "ERROR",
                        "limit": 20,
                    },
                },
            ]
            history = [{"tool_name": "query_metrics"}, {"tool_name": "search_logs"}]
            if active:
                steps.insert(
                    1,
                    {
                        "tool": "reproduce_request",
                        "arguments": {
                            "service": "inventory",
                            "method": "GET",
                            "path": "/inventory/SKU-RED",
                            "expected_status": 200,
                        },
                    },
                )
                history.insert(1, {"tool_name": "reproduce_request"})
            expected = (
                "no_fault"
                if scenario.scenario_id == PASSIVE_VERIFICATION_NEGATIVE_CONTROL
                else "x"
            )
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
                                "tool_history": history,
                            }
                        },
                    },
                    scores={
                        "root_cause_accuracy": 1.0,
                        "exact_match": 1.0,
                        "evidence_precision": 1.0,
                        "evidence_recall": 1.0,
                        "critical_evidence_recall": 1.0,
                        "confidence": 0.9,
                        "tool_calls": 3.0 if active else 2.0,
                        "latency_seconds": 1.0,
                        "estimated_cost": 0.0,
                    },
                )
            )
    return records


def test_h4_report_builds_two_arm_descriptive_comparison() -> None:
    catalog = load_catalog()
    report = build_passive_verification_report(
        benchmark_version=catalog.benchmark_version,
        records=_records(),
    )

    assert len(report.observations) == 20
    assert len(report.aggregates) == 2
    assert len(report.paired_deltas) == 10
    assert all(aggregate.n == 10 for aggregate in report.aggregates)
    active = next(
        aggregate
        for aggregate in report.aggregates
        if aggregate.evidence_mode == EvidenceMode.VERIFICATION_ENABLED
    )
    assert active.mean_executed_verification_count == 1.0


def test_h4_report_rejects_changed_passive_invocation_sequence() -> None:
    catalog = load_catalog()
    mutated = deepcopy(_records())
    target = next(
        record
        for record in mutated
        if record.identity.scenario_id == PASSIVE_VERIFICATION_SCENARIO_IDS[0]
        and record.identity.configuration.evidence_mode
        == EvidenceMode.VERIFICATION_ENABLED
    )
    target.raw_trajectory["benchmark_artifact"]["raw_agent_run"]["plan"]["steps"].append(
        {"tool": "search_documentation", "arguments": {"query": "inventory"}}
    )

    with pytest.raises(ValueError, match="changed the passive planned invocation sequence"):
        build_passive_verification_report(
            benchmark_version=catalog.benchmark_version,
            records=mutated,
        )


def test_h4_report_rejects_missing_executed_verification_probe() -> None:
    catalog = load_catalog()
    mutated = deepcopy(_records())
    target = next(
        record
        for record in mutated
        if record.identity.scenario_id == PASSIVE_VERIFICATION_SCENARIO_IDS[0]
        and record.identity.configuration.evidence_mode
        == EvidenceMode.VERIFICATION_ENABLED
    )
    target.raw_trajectory["benchmark_artifact"]["raw_agent_run"]["tool_history"] = [
        {"tool_name": "query_metrics"},
        {"tool_name": "search_logs"},
    ]

    with pytest.raises(ValueError, match="execute exactly one verification probe"):
        build_passive_verification_report(
            benchmark_version=catalog.benchmark_version,
            records=mutated,
        )
