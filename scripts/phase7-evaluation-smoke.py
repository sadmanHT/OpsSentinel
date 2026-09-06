from __future__ import annotations

import asyncio
import os
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import create_engine

from benchmarklab import BenchmarkRunner, load_catalog, scenario_by_id
from evaluationlab import EvaluationEngine, adapt_benchmark_artifact
from evaluationlab.persistence import (
    EvaluationRunMetadata,
    ExperimentConfiguration,
    SqlEvaluationStore,
)

DATABASE_URL = os.environ.get(
    "OPSSENTINEL_DATABASE_URL",
    "postgresql+psycopg://opssentinel:opssentinel@127.0.0.1:5432/opssentinel",
)
EVALUATION_PROVIDER = os.environ.get("OPSSENTINEL_EVALUATION_PROVIDER", "local")
EVALUATION_MODEL = os.environ.get("OPSSENTINEL_EVALUATION_MODEL", "local-placeholder")
ARCHITECTURE_VERSION = "phase5-safe-operational-agent-v1"


async def main() -> None:
    catalog = load_catalog()
    scenario = scenario_by_id(catalog, "ops-v1-001")
    runner = BenchmarkRunner()

    artifact = await runner.run(scenario, benchmark_version=catalog.benchmark_version)
    assert artifact.agent_run_id is not None
    assert artifact.agent_status == "completed"

    case = adapt_benchmark_artifact(
        scenario.model_dump(mode="json"),
        artifact.model_dump(mode="json"),
    )
    result = EvaluationEngine().evaluate(case)

    assert result.root_cause.primary_accuracy == 1.0
    assert result.root_cause.exact_match is True
    assert result.correctness == 1.0
    assert result.confidence >= 0.9
    assert result.efficiency.total_tool_calls > 0
    assert result.safety.unsafe_action_attempts == 0
    assert result.safety.incorrectly_classified_risk == 0

    agent_run_id = UUID(str(artifact.agent_run_id))
    evaluation_run_id = uuid5(
        NAMESPACE_URL,
        f"opssentinel:phase7-live-evaluation:{artifact.agent_run_id}",
    )
    raw_budget = artifact.raw_agent_run.get("budget", {})
    tool_budget = 0
    if isinstance(raw_budget, dict):
        max_tool_calls = raw_budget.get("max_tool_calls")
        if isinstance(max_tool_calls, int):
            tool_budget = max_tool_calls

    run = EvaluationRunMetadata(
        id=evaluation_run_id,
        dataset_version=catalog.benchmark_version,
        architecture_version=ARCHITECTURE_VERSION,
        model=EVALUATION_MODEL,
        seed=scenario.seed,
        configuration={
            "source": "phase7-live-compose",
            "scenario_id": scenario.scenario_id,
            "difficulty": scenario.difficulty.value,
            "provider": EVALUATION_PROVIDER,
        },
    )
    experiment = ExperimentConfiguration(
        prompt_version=ARCHITECTURE_VERSION,
        scenario_version=scenario.scenario_version,
        evaluation_version="0.1.0",
        retrieval_settings={"source": "saved-benchmark-trajectory"},
        tool_budget=tool_budget,
    )
    trace = {
        "scenario_id": scenario.scenario_id,
        "agent_run_id": str(agent_run_id),
        "benchmark_artifact": artifact.model_dump(mode="json"),
        "evaluation_case": case.model_dump(mode="json"),
    }

    engine = create_engine(DATABASE_URL)
    store = SqlEvaluationStore(engine)
    store.create_run(run, experiment)
    store.save_result(
        evaluation_run_id,
        result,
        agent_run_id=agent_run_id,
        trace=trace,
    )
    engine.dispose()

    restarted_engine = create_engine(DATABASE_URL)
    restarted_store = SqlEvaluationStore(restarted_engine)
    loaded_run = restarted_store.load_run(evaluation_run_id)
    loaded_experiment = restarted_store.load_experiment(evaluation_run_id)
    loaded = restarted_store.load_result(evaluation_run_id, scenario.scenario_id)

    assert loaded_run is not None
    assert loaded_run.dataset_version == catalog.benchmark_version
    assert loaded_run.architecture_version == ARCHITECTURE_VERSION
    assert loaded_run.model == EVALUATION_MODEL
    assert loaded_run.seed == scenario.seed
    assert loaded_run.configuration["provider"] == EVALUATION_PROVIDER
    assert loaded_run.configuration["scenario_id"] == scenario.scenario_id
    assert loaded_experiment is not None
    assert loaded_experiment.scenario_version == scenario.scenario_version
    assert loaded_experiment.evaluation_version == "0.1.0"
    assert loaded is not None
    assert loaded.agent_run_id == agent_run_id
    assert loaded.result.model_dump() == result.model_dump()
    assert loaded.trace == trace

    metric_names = restarted_store.metric_names(evaluation_run_id, scenario.scenario_id)
    assert "correctness" in metric_names
    assert "root_cause.primary_accuracy" in metric_names
    assert "safety.incorrectly_classified_risk" in metric_names

    restarted_engine.dispose()
    await runner.restore()

    print(
        "Phase 7 live evaluation smoke passed: benchmark -> agent -> evaluator -> "
        "Postgres -> restart/readback"
    )


if __name__ == "__main__":
    asyncio.run(main())
