from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
from benchmarklab.catalog import load_catalog, scenario_by_id
from benchmarklab.runner import BenchmarkRunner
from evaluationlab.persistence import SqlEvaluationStore
from researchlab.compound_handling import (
    COMPOUND_SCENARIO_IDS,
    compound_handling_plan,
    compound_handling_scenarios,
    observation_from_record,
)
from researchlab.live_executor import (
    ARCHITECTURE_VERSION_BY_VARIANT,
    COMPOUND_EVIDENCE_PROVIDER_MARKER,
    UNRESOLVED_EVIDENCE_PROVIDER_MARKER,
    LiveTrialExecutor,
)
from researchlab.models import (
    ArchitectureVariant,
    StoppingStrategy,
    TrialRecord,
    TrialStatus,
)
from researchlab.persistence import SqlTrialStore
from researchlab.runner import ExperimentRunner
from sqlalchemy import Engine, create_engine, text

DATABASE_URL = os.environ.get(
    "OPSSENTINEL_DATABASE_URL",
    "postgresql+psycopg://opssentinel:opssentinel@127.0.0.1:5432/opssentinel",
)
STOPPING_STRATEGY = StoppingStrategy(
    os.environ.get(
        "PHASE8_STOPPING_STRATEGY",
        StoppingStrategy.CONFIDENCE_THRESHOLD.value,
    )
)
OUTPUT_PATH = Path(
    os.environ.get(
        "PHASE8_COMPOUND_ARM_OUTPUT",
        f"phase8-compound-{STOPPING_STRATEGY.value}.json",
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


def _assert_no_ground_truth_leak(record: TrialRecord) -> None:
    artifact = record.raw_trajectory["benchmark_artifact"]
    raw_run = artifact["raw_agent_run"]
    incident = json.dumps(raw_run["incident"], sort_keys=True).casefold()
    case = record.raw_trajectory["evaluation_case"]
    expected_codes: list[str] = []
    primary = case.get("expected_primary_root_cause_code")
    if isinstance(primary, str):
        expected_codes.append(primary)
    secondary = case.get("expected_secondary_root_cause_codes", [])
    if isinstance(secondary, list):
        expected_codes.extend(item for item in secondary if isinstance(item, str))
    assert "ground_truth" not in incident
    assert "timeline" not in incident
    assert "offset_seconds" not in incident
    assert all(code.casefold() not in incident for code in expected_codes)


async def main() -> None:
    catalog = load_catalog()
    scenarios = compound_handling_scenarios(catalog)
    assert [scenario.scenario_id for scenario in scenarios] == list(COMPOUND_SCENARIO_IDS)
    plan = compound_handling_plan(
        dataset_version=catalog.benchmark_version,
        provider="local",
        model="local-placeholder",
        prompt_version="phase8-v1",
    )
    cell = next(
        item
        for item in plan.cells
        if item.configuration.stopping_strategy == STOPPING_STRATEGY
    )
    configuration = cell.configuration
    assert configuration.architecture == ArchitectureVariant.EXPLICIT_PLANNER
    assert configuration.tool_budget == 15
    assert configuration.evidence_mode.value == "passive_only"
    assert configuration.tool_order.value == "free"
    assert configuration.temporal_reasoning.value == "standard"

    engine = create_engine(DATABASE_URL)
    evaluation_store = SqlEvaluationStore(engine)
    trial_store = SqlTrialStore(engine)
    executor = LiveTrialExecutor(
        catalog=catalog,
        benchmark_runner=BenchmarkRunner(),
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
    assert len(records) == len(COMPOUND_SCENARIO_IDS) == 8
    assert all(record.status == TrialStatus.COMPLETED for record in records)
    assert len({record.identity.trial_id for record in records}) == 8
    assert len({record.agent_run_id for record in records}) == 8

    expected_architecture = ARCHITECTURE_VERSION_BY_VARIANT[
        ArchitectureVariant.EXPLICIT_PLANNER
    ]
    expects_unresolved = STOPPING_STRATEGY == StoppingStrategy.UNRESOLVED_EVIDENCE
    for record in records:
        scenario = scenario_by_id(catalog, record.identity.scenario_id)
        health = record.raw_trajectory["runtime_health"]
        assert health["architecture"] == expected_architecture
        assert health["temporal_reasoning"] == "standard"
        assert health["tool_order"] == "free"
        assert health["tool_order_controlled"] is False
        assert health["evidence_mode"] == "passive_only"
        assert health["stopping_strategy"] == STOPPING_STRATEGY.value
        assert health["compound_evidence_plan"] is True
        provider = str(health["provider"])
        assert COMPOUND_EVIDENCE_PROVIDER_MARKER in provider
        assert (UNRESOLVED_EVIDENCE_PROVIDER_MARKER in provider) is expects_unresolved
        assert "active-verification-v1" not in provider
        assert "tool-order-controlled-v1" not in provider
        assert "temporal-cause-effect-v1" not in provider
        _assert_no_ground_truth_leak(record)
        observation = observation_from_record(record)
        assert observation.scenario_id == scenario.scenario_id
        assert observation.stopping_strategy == STOPPING_STRATEGY
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
    assert [record.agent_run_id for record in resumed] == [
        record.agent_run_id for record in records
    ]
    assert await _active_faults() == []

    payload = {
        "experiment": "compound_handling",
        "interpretation": "descriptive_only",
        "benchmark_version": catalog.benchmark_version,
        "stopping_strategy": STOPPING_STRATEGY.value,
        "scenario_ids": list(COMPOUND_SCENARIO_IDS),
        "records": [record.model_dump(mode="json") for record in records],
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        "Phase 8 H5 arm complete:",
        STOPPING_STRATEGY.value,
        "trials=",
        len(records),
    )


if __name__ == "__main__":
    asyncio.run(main())
