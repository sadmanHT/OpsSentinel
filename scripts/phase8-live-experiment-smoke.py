from __future__ import annotations

import asyncio
import json
import os

import httpx
from sqlalchemy import Engine, create_engine, text

from benchmarklab.catalog import load_catalog
from benchmarklab.runner import BenchmarkRunner
from evaluationlab.persistence import SqlEvaluationStore
from researchlab.benchmark_adapter import scenario_ref_from_benchmark
from researchlab.live_executor import (
    ARCHITECTURE_VERSION_BY_VARIANT,
    LiveTrialExecutor,
)
from researchlab.models import (
    ArchitectureVariant,
    Difficulty,
    ExperimentCell,
    ExperimentKind,
    ExperimentPlan,
    ExperimentSplit,
    ResearchConfiguration,
    TrialStatus,
)
from researchlab.persistence import SqlTrialStore
from researchlab.runner import ExperimentRunner

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


def _plan(architecture: ArchitectureVariant) -> ExperimentPlan:
    baseline = ResearchConfiguration(
        architecture=architecture,
        provider="local",
        model="local-placeholder",
        prompt_version="phase8-v1",
    )
    return ExperimentPlan(
        id=f"phase8-tiny-budget-{architecture.value.replace('_', '-')}",
        experiment=ExperimentKind.INVESTIGATION_BUDGET,
        hypothesis_id="H2",
        dataset_version="ops-v1",
        split=ExperimentSplit.DEV,
        repeat_count=1,
        seed_base=8800,
        cells=[
            ExperimentCell(
                id="budget-5",
                label="5 tool calls",
                configuration=baseline.model_copy(update={"tool_budget": 5}),
                difficulties=[Difficulty.EASY],
            ),
            ExperimentCell(
                id="budget-15",
                label="15 tool calls",
                configuration=baseline.model_copy(update={"tool_budget": 15}),
                difficulties=[Difficulty.EASY],
            ),
        ],
    )


async def _active_faults() -> list[object]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get("http://127.0.0.1:8100/faults")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise AssertionError("ChaosLab fault listing is malformed")
    return payload


def _agent_run_count(engine: Engine) -> int:
    with engine.connect() as connection:
        value = connection.execute(text("SELECT COUNT(*) FROM agent_runs")).scalar_one()
    return int(value)


async def main() -> None:
    architecture = _architecture()
    expected_architecture = ARCHITECTURE_VERSION_BY_VARIANT[architecture]
    catalog = load_catalog()
    scenario = next(
        item
        for item in catalog.scenarios
        if item.split.value == "dev" and item.difficulty.value == "easy"
    )
    scenario_ref = scenario_ref_from_benchmark(scenario)
    plan = _plan(architecture)

    engine = create_engine(DATABASE_URL)
    evaluation_store = SqlEvaluationStore(engine)
    trial_store = SqlTrialStore(engine)
    benchmark_runner = BenchmarkRunner()
    executor = LiveTrialExecutor(
        catalog=catalog,
        benchmark_runner=benchmark_runner,
        evaluation_store=evaluation_store,
    )
    runner = ExperimentRunner()

    first = await runner.run(plan, [scenario_ref], executor, trial_store)
    assert len(first) == 2
    assert all(record.status == TrialStatus.COMPLETED for record in first)
    assert [record.identity.configuration.tool_budget for record in first] == [5, 15]
    assert all(record.agent_run_id is not None for record in first)
    assert len({record.agent_run_id for record in first}) == 2

    for record in first:
        assert record.evaluation_run_id == record.identity.trial_id
        assert record.scores["root_cause_accuracy"] == 1.0
        assert record.scores["correctness"] == 1.0
        assert record.scores["latency_seconds"] >= 0.0
        assert record.scores["estimated_cost"] >= 0.0
        trace = record.raw_trajectory
        assert trace["runtime_health"]["architecture"] == expected_architecture
        assert trace["configuration"]["tool_budget"] == (
            record.identity.configuration.tool_budget
        )
        artifact = trace["benchmark_artifact"]
        raw_run = artifact["raw_agent_run"]
        assert raw_run["budget"]["max_tool_calls"] == (
            record.identity.configuration.tool_budget
        )
        visible_incident = json.dumps(raw_run["incident"], sort_keys=True).casefold()
        assert "ground_truth" not in visible_incident
        assert scenario.ground_truth.primary_root_cause_code.casefold() not in visible_incident

        persisted_run = evaluation_store.load_run(record.identity.trial_id)
        assert persisted_run is not None
        assert persisted_run.architecture_version == expected_architecture
        assert persisted_run.seed == record.identity.seed
        persisted_experiment = evaluation_store.load_experiment(record.identity.trial_id)
        assert persisted_experiment is not None
        assert persisted_experiment.tool_budget == record.identity.configuration.tool_budget
        persisted_result = evaluation_store.load_result(
            record.identity.trial_id,
            scenario.scenario_id,
        )
        assert persisted_result is not None
        assert persisted_result.result.root_cause.exact_match

    persisted_trials = trial_store.list_plan(plan.id)
    assert len(persisted_trials) == 2
    assert all(record.status == TrialStatus.COMPLETED for record in persisted_trials)

    agent_runs_before_resume = _agent_run_count(engine)
    second = await runner.run(plan, [scenario_ref], executor, trial_store)
    agent_runs_after_resume = _agent_run_count(engine)
    assert agent_runs_before_resume == agent_runs_after_resume
    assert [record.agent_run_id for record in second] == [
        record.agent_run_id for record in first
    ]
    assert await _active_faults() == []

    print(
        "Phase 8 tiny live experiment passed:",
        architecture.value,
        scenario.scenario_id,
        [
            (record.identity.configuration.tool_budget, record.scores["correctness"])
            for record in first
        ],
    )


if __name__ == "__main__":
    asyncio.run(main())
