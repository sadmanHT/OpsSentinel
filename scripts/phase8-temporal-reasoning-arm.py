from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
from benchmarklab.catalog import load_catalog, scenario_by_id
from evaluationlab.persistence import SqlEvaluationStore
from researchlab.live_executor import ARCHITECTURE_VERSION_BY_VARIANT, LiveTrialExecutor
from researchlab.models import ArchitectureVariant, TemporalReasoningVariant, TrialRecord, TrialStatus
from researchlab.persistence import SqlTrialStore
from researchlab.runner import ExperimentRunner
from researchlab.temporal_reasoning import (
    H3_SCENARIO_IDS,
    RuntimeOnsetBenchmarkRunner,
    temporal_reasoning_plan,
    temporal_scenarios,
)
from sqlalchemy import Engine, create_engine, text

DATABASE_URL = os.environ.get(
    "OPSSENTINEL_DATABASE_URL",
    "postgresql+psycopg://opssentinel:opssentinel@127.0.0.1:5432/opssentinel",
)
TEMPORAL_MODE = TemporalReasoningVariant(
    os.environ.get("PHASE8_H3_TEMPORAL", TemporalReasoningVariant.STANDARD.value)
)
OUTPUT_PATH = Path(
    os.environ.get(
        "PHASE8_H3_ARM_OUTPUT",
        f"phase8-h3-{TEMPORAL_MODE.value}.json",
    )
)


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
    assert "timeline" not in incident
    assert "offset_seconds" not in incident


def _cell_id() -> str:
    if TEMPORAL_MODE == TemporalReasoningVariant.STANDARD:
        return "standard"
    return "explicit-cause-effect"


async def main() -> None:
    catalog = load_catalog()
    scenarios = temporal_scenarios(catalog)
    assert [scenario.scenario_id for scenario in scenarios] == list(H3_SCENARIO_IDS)
    plan = temporal_reasoning_plan(
        dataset_version=catalog.benchmark_version,
        provider="local",
        model="local-placeholder",
        prompt_version="phase8-v1",
    )
    cell = next(item for item in plan.cells if item.id == _cell_id())
    assert cell.configuration.temporal_reasoning == TEMPORAL_MODE
    assert cell.configuration.architecture == ArchitectureVariant.EXPLICIT_PLANNER

    engine = create_engine(DATABASE_URL)
    evaluation_store = SqlEvaluationStore(engine)
    trial_store = SqlTrialStore(engine)
    executor = LiveTrialExecutor(
        catalog=catalog,
        benchmark_runner=RuntimeOnsetBenchmarkRunner(),
        evaluation_store=evaluation_store,
    )
    runner = ExperimentRunner()

    records = await runner.run(
        plan,
        scenarios,
        executor,
        trial_store,
        cell_ids=[cell.id],
    )
    assert len(records) == len(H3_SCENARIO_IDS) == 5
    assert all(record.status == TrialStatus.COMPLETED for record in records)
    assert len({record.identity.trial_id for record in records}) == 5
    assert len({record.agent_run_id for record in records}) == 5

    expected_architecture = ARCHITECTURE_VERSION_BY_VARIANT[ArchitectureVariant.EXPLICIT_PLANNER]
    for record in records:
        scenario = scenario_by_id(catalog, record.identity.scenario_id)
        health = record.raw_trajectory["runtime_health"]
        assert health["architecture"] == expected_architecture
        assert health["temporal_reasoning"] == TEMPORAL_MODE.value
        provider = str(health["provider"])
        has_marker = "temporal-cause-effect-v1" in provider
        assert has_marker == (TEMPORAL_MODE == TemporalReasoningVariant.EXPLICIT_CAUSE_EFFECT)
        _assert_no_ground_truth_leak(
            record,
            scenario.ground_truth.primary_root_cause_code,
        )
        raw_run = record.raw_trajectory["benchmark_artifact"]["raw_agent_run"]
        incident_start = raw_run["incident"]["start_time"]
        assert isinstance(incident_start, str)
        assert incident_start.startswith("2026-")
        persisted = evaluation_store.load_result(
            record.identity.trial_id,
            record.identity.scenario_id,
        )
        assert persisted is not None

    assert await _active_faults() == []

    agent_runs_before_resume = _agent_run_count(engine)
    resumed = await runner.run(
        plan,
        scenarios,
        executor,
        trial_store,
        cell_ids=[cell.id],
    )
    agent_runs_after_resume = _agent_run_count(engine)
    assert agent_runs_before_resume == agent_runs_after_resume
    assert [record.agent_run_id for record in resumed] == [record.agent_run_id for record in records]
    assert await _active_faults() == []

    payload = {
        "experiment": "temporal_reasoning",
        "hypothesis_id": "H3",
        "interpretation": "descriptive_only",
        "benchmark_version": catalog.benchmark_version,
        "temporal_reasoning": TEMPORAL_MODE.value,
        "scenario_ids": list(H3_SCENARIO_IDS),
        "records": [record.model_dump(mode="json") for record in records],
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        "Phase 8 H3 arm complete:",
        TEMPORAL_MODE.value,
        "trials=",
        len(records),
    )


if __name__ == "__main__":
    asyncio.run(main())
