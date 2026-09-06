from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
from benchmarklab.catalog import load_catalog, scenario_by_id
from benchmarklab.runner import BenchmarkRunner
from evaluationlab.persistence import SqlEvaluationStore
from researchlab.live_executor import (
    ARCHITECTURE_VERSION_BY_VARIANT,
    LiveTrialExecutor,
)
from researchlab.models import ArchitectureVariant, Difficulty, TrialRecord, TrialStatus
from researchlab.persistence import SqlTrialStore
from researchlab.planning_difficulty import (
    CELL_BY_ARCHITECTURE,
    SELECTION_POLICY_VERSION,
    build_planning_difficulty_tier_plans,
    select_planning_difficulty_scenarios,
)
from researchlab.runner import ExperimentRunner
from sqlalchemy import Engine, create_engine, text

DATABASE_URL = os.environ.get(
    "OPSSENTINEL_DATABASE_URL",
    "postgresql+psycopg://opssentinel:opssentinel@127.0.0.1:5432/opssentinel",
)


def _architecture() -> ArchitectureVariant:
    value = os.environ.get(
        "PHASE8_EXPECTED_ARCHITECTURE",
        os.environ.get("OPSSENTINEL_AGENT_ARCHITECTURE", "explicit_planner"),
    )
    return ArchitectureVariant(value)


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


def _output_path(architecture: ArchitectureVariant) -> Path:
    configured = os.environ.get("PHASE8_H1_ARM_OUTPUT")
    if configured:
        return Path(configured)
    return Path(f"phase8-h1-{architecture.value}.json")


def _assert_no_ground_truth_leak(record: TrialRecord, expected_root_cause: str) -> None:
    trace = record.raw_trajectory
    artifact = trace["benchmark_artifact"]
    raw_run = artifact["raw_agent_run"]
    incident = json.dumps(raw_run["incident"], sort_keys=True).casefold()
    assert "ground_truth" not in incident
    assert expected_root_cause.casefold() not in incident


async def main() -> None:
    architecture = _architecture()
    expected_architecture = ARCHITECTURE_VERSION_BY_VARIANT[architecture]
    cell_id = CELL_BY_ARCHITECTURE[architecture]
    catalog = load_catalog()
    selected = select_planning_difficulty_scenarios(catalog, per_tier=2)
    plans = build_planning_difficulty_tier_plans(
        dataset_version=catalog.benchmark_version,
        provider="local",
        model="local-placeholder",
        prompt_version="phase8-v1",
        tool_budget=15,
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
    records: list[TrialRecord] = []

    for difficulty in Difficulty:
        plan = plans[difficulty]
        scenarios = selected[difficulty]
        tier_records = await runner.run(
            plan,
            scenarios,
            executor,
            trial_store,
            cell_ids=[cell_id],
        )
        assert len(tier_records) == 2
        assert all(record.status == TrialStatus.COMPLETED for record in tier_records)
        assert all(record.identity.difficulty == difficulty for record in tier_records)
        assert all(record.identity.split == plan.split for record in tier_records)
        assert all(record.identity.configuration.architecture == architecture for record in tier_records)

        persisted_trials = trial_store.list_plan(plan.id)
        assert len(persisted_trials) == 2
        assert all(record.status == TrialStatus.COMPLETED for record in persisted_trials)

        for record in tier_records:
            scenario = scenario_by_id(catalog, record.identity.scenario_id)
            assert record.evaluation_run_id == record.identity.trial_id
            assert record.agent_run_id is not None
            assert record.scores["root_cause_accuracy"] >= 0.0
            assert record.scores["root_cause_accuracy"] <= 1.0
            assert record.scores["exact_match"] in {0.0, 1.0}
            assert record.scores["tool_calls"] >= 0.0
            assert record.scores["latency_seconds"] >= 0.0
            assert record.scores["estimated_cost"] >= 0.0
            assert record.scores["confidence"] >= 0.0
            assert record.scores["confidence"] <= 1.0
            assert record.raw_trajectory["runtime_health"]["architecture"] == expected_architecture
            assert record.raw_trajectory["configuration"]["architecture"] == architecture.value
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
            assert persisted_experiment.tool_budget == 15
            persisted_result = evaluation_store.load_result(
                record.identity.trial_id,
                record.identity.scenario_id,
            )
            assert persisted_result is not None

        records.extend(tier_records)
        assert await _active_faults() == []

    assert len(records) == 10
    assert len({record.identity.trial_id for record in records}) == 10
    assert len({record.agent_run_id for record in records}) == 10

    agent_runs_before_resume = _agent_run_count(engine)
    resumed_records: list[TrialRecord] = []
    for difficulty in Difficulty:
        resumed_records.extend(
            await runner.run(
                plans[difficulty],
                selected[difficulty],
                executor,
                trial_store,
                cell_ids=[cell_id],
            )
        )
    agent_runs_after_resume = _agent_run_count(engine)
    assert agent_runs_before_resume == agent_runs_after_resume
    assert [record.agent_run_id for record in resumed_records] == [
        record.agent_run_id for record in records
    ]
    assert await _active_faults() == []

    payload = {
        "experiment": "planning_difficulty",
        "hypothesis_id": "H1",
        "interpretation": "descriptive_only",
        "selection_policy": SELECTION_POLICY_VERSION,
        "benchmark_version": catalog.benchmark_version,
        "per_tier": 2,
        "architecture": architecture.value,
        "selected_scenarios": {
            difficulty.value: [scenario.scenario_id for scenario in selected[difficulty]]
            for difficulty in Difficulty
        },
        "records": [record.model_dump(mode="json") for record in records],
    }
    output_path = _output_path(architecture)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    print(
        "Phase 8 planning/difficulty arm complete:",
        architecture.value,
        [
            (
                record.identity.difficulty.value,
                record.identity.scenario_id,
                record.scores["root_cause_accuracy"],
                record.scores["tool_calls"],
            )
            for record in records
        ],
    )


if __name__ == "__main__":
    asyncio.run(main())
