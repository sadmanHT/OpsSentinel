from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
from benchmarklab.catalog import load_catalog, scenario_by_id
from benchmarklab.runner import BenchmarkRunner
from evaluationlab.persistence import SqlEvaluationStore
from researchlab.investigation_budget import (
    BUDGETS,
    DATASET_POLICY_VERSION,
    build_investigation_budget_report,
    investigation_budget_plan,
    validation_scenarios,
)
from researchlab.live_executor import ARCHITECTURE_VERSION_BY_VARIANT, LiveTrialExecutor
from researchlab.models import ArchitectureVariant, TrialRecord, TrialStatus
from researchlab.persistence import SqlTrialStore
from researchlab.runner import ExperimentRunner
from sqlalchemy import Engine, create_engine, text

DATABASE_URL = os.environ.get(
    "OPSSENTINEL_DATABASE_URL",
    "postgresql+psycopg://opssentinel:opssentinel@127.0.0.1:5432/opssentinel",
)
OUTPUT_PATH = Path(os.environ.get("PHASE8_H2_OUTPUT", "phase8-h2-investigation-budget.json"))


def _agent_run_count(engine: Engine) -> int:
    with engine.connect() as connection:
        value = connection.execute(text("SELECT COUNT(*) FROM agent_runs")).scalar_one()
    return int(value)


async def _active_faults() -> list[object]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get("http://127.0.0.1:8100/faults")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise TypeError("ChaosLab fault listing is malformed")
    return payload


def _assert_no_ground_truth_leak(record: TrialRecord, expected_root_cause: str) -> None:
    artifact = record.raw_trajectory["benchmark_artifact"]
    raw_run = artifact["raw_agent_run"]
    incident = json.dumps(raw_run["incident"], sort_keys=True).casefold()
    assert "ground_truth" not in incident
    assert expected_root_cause.casefold() not in incident


def _assert_applied_budget(record: TrialRecord) -> None:
    artifact = record.raw_trajectory["benchmark_artifact"]
    raw_run = artifact["raw_agent_run"]
    applied = int(raw_run["budget"]["max_tool_calls"])
    expected = record.identity.configuration.tool_budget
    assert applied == expected
    assert record.scores["tool_calls"] <= expected


async def main() -> None:
    architecture = ArchitectureVariant.EXPLICIT_PLANNER
    expected_architecture = ARCHITECTURE_VERSION_BY_VARIANT[architecture]
    catalog = load_catalog()
    scenarios = validation_scenarios(catalog)
    plan = investigation_budget_plan(
        dataset_version=catalog.benchmark_version,
        provider="local",
        model="local-placeholder",
        prompt_version="phase8-v1",
    )

    engine = create_engine(DATABASE_URL)
    evaluation_store = SqlEvaluationStore(engine)
    trial_store = SqlTrialStore(engine)
    executor = LiveTrialExecutor(
        catalog=catalog,
        benchmark_runner=BenchmarkRunner(),
        evaluation_store=evaluation_store,
    )
    runner = ExperimentRunner()

    records = await runner.run(plan, scenarios, executor, trial_store)
    assert len(records) == len(BUDGETS) * len(scenarios) == 40
    assert all(record.status == TrialStatus.COMPLETED for record in records)
    assert len({record.identity.trial_id for record in records}) == 40
    assert len({record.agent_run_id for record in records}) == 40
    assert {record.identity.configuration.tool_budget for record in records} == set(BUDGETS)
    assert all(
        record.identity.configuration.architecture == architecture for record in records
    )

    persisted_trials = trial_store.list_plan(plan.id)
    assert len(persisted_trials) == 40
    assert all(record.status == TrialStatus.COMPLETED for record in persisted_trials)

    for record in records:
        scenario = scenario_by_id(catalog, record.identity.scenario_id)
        assert record.evaluation_run_id == record.identity.trial_id
        assert record.agent_run_id is not None
        assert record.raw_trajectory["runtime_health"]["architecture"] == expected_architecture
        assert record.raw_trajectory["configuration"]["architecture"] == architecture.value
        _assert_applied_budget(record)
        _assert_no_ground_truth_leak(
            record,
            scenario.ground_truth.primary_root_cause_code,
        )

        persisted_run = evaluation_store.load_run(record.identity.trial_id)
        assert persisted_run is not None
        assert persisted_run.architecture_version == expected_architecture
        assert persisted_run.seed == record.identity.seed
        persisted_experiment = evaluation_store.load_experiment(record.identity.trial_id)
        assert persisted_experiment is not None
        assert persisted_experiment.tool_budget == record.identity.configuration.tool_budget
        persisted_result = evaluation_store.load_result(
            record.identity.trial_id,
            record.identity.scenario_id,
        )
        assert persisted_result is not None

    assert await _active_faults() == []

    agent_runs_before_resume = _agent_run_count(engine)
    resumed = await runner.run(plan, scenarios, executor, trial_store)
    agent_runs_after_resume = _agent_run_count(engine)
    assert agent_runs_before_resume == agent_runs_after_resume
    assert [record.agent_run_id for record in resumed] == [record.agent_run_id for record in records]
    assert await _active_faults() == []

    report = build_investigation_budget_report(
        benchmark_version=catalog.benchmark_version,
        scenarios=scenarios,
        records=records,
    )
    payload = {
        "experiment": "investigation_budget",
        "hypothesis_id": "H2",
        "interpretation": "descriptive_only",
        "dataset_policy": DATASET_POLICY_VERSION,
        "benchmark_version": catalog.benchmark_version,
        "architecture": architecture.value,
        "budgets": list(BUDGETS),
        "scenario_ids": [scenario.scenario_id for scenario in scenarios],
        "records": [record.model_dump(mode="json") for record in records],
        "report": report.model_dump(mode="json"),
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    print("Phase 8 investigation-budget descriptive report:")
    for aggregate in report.aggregates:
        print(
            "budget=",
            aggregate.tool_budget,
            "n=",
            aggregate.n,
            "accuracy=",
            aggregate.mean_root_cause_accuracy,
            "exact_match=",
            aggregate.exact_match_rate,
            "false_positive_rate=",
            aggregate.false_positive_rate,
            "distractor_selection_rate=",
            aggregate.mean_distractor_selection_rate,
            "confidence=",
            aggregate.mean_confidence,
            "tool_calls=",
            aggregate.mean_tool_calls,
            "budget_utilization=",
            aggregate.mean_budget_utilization,
            "budget_exhaustion_count=",
            aggregate.budget_exhaustion_count,
            "latency_seconds=",
            aggregate.mean_latency_seconds,
            "estimated_cost=",
            aggregate.mean_estimated_cost,
            "failures=",
            aggregate.failure_mode_counts,
        )
    print("Phase 8 investigation-budget per-difficulty observations:")
    for aggregate in report.by_difficulty:
        print(aggregate.model_dump(mode="json"))


if __name__ == "__main__":
    asyncio.run(main())
