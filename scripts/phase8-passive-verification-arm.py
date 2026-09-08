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
    ACTIVE_VERIFICATION_PROVIDER_MARKER,
    ARCHITECTURE_VERSION_BY_VARIANT,
    LiveTrialExecutor,
)
from researchlab.models import (
    ArchitectureVariant,
    EvidenceMode,
    TrialRecord,
    TrialStatus,
)
from researchlab.passive_verification import (
    PASSIVE_VERIFICATION_SCENARIO_IDS,
    VERIFICATION_TOOLS,
    passive_verification_plan,
    passive_verification_scenarios,
)
from researchlab.persistence import SqlTrialStore
from researchlab.runner import ExperimentRunner
from sqlalchemy import Engine, create_engine, text

DATABASE_URL = os.environ.get(
    "OPSSENTINEL_DATABASE_URL",
    "postgresql+psycopg://opssentinel:opssentinel@127.0.0.1:5432/opssentinel",
)
EVIDENCE_MODE = EvidenceMode(
    os.environ.get("PHASE8_EVIDENCE_MODE", EvidenceMode.PASSIVE_ONLY.value)
)
OUTPUT_PATH = Path(
    os.environ.get(
        "PHASE8_PASSIVE_VERIFICATION_ARM_OUTPUT",
        f"phase8-passive-verification-{EVIDENCE_MODE.value}.json",
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


def _executed_verification_count(record: TrialRecord) -> int:
    artifact = record.raw_trajectory["benchmark_artifact"]
    raw_run = artifact["raw_agent_run"]
    history = raw_run.get("tool_history", [])
    if not isinstance(history, list):
        raise TypeError("raw tool history is malformed")
    count = 0
    for item in history:
        if not isinstance(item, dict):
            continue
        tool = item.get("tool_name")
        if isinstance(tool, str) and tool in VERIFICATION_TOOLS:
            count += 1
    return count


async def main() -> None:
    catalog = load_catalog()
    scenarios = passive_verification_scenarios(catalog)
    assert [scenario.scenario_id for scenario in scenarios] == list(
        PASSIVE_VERIFICATION_SCENARIO_IDS
    )
    plan = passive_verification_plan(
        dataset_version=catalog.benchmark_version,
        provider="local",
        model="local-placeholder",
        prompt_version="phase8-v1",
    )
    cell = next(
        item
        for item in plan.cells
        if item.configuration.evidence_mode == EVIDENCE_MODE
    )
    assert cell.configuration.architecture == ArchitectureVariant.EXPLICIT_PLANNER
    assert cell.configuration.tool_budget == 15
    assert cell.configuration.evidence_mode == EVIDENCE_MODE
    assert cell.configuration.tool_order.value == "free"
    assert cell.configuration.temporal_reasoning.value == "standard"

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
    assert len(records) == len(PASSIVE_VERIFICATION_SCENARIO_IDS) == 10
    assert all(record.status == TrialStatus.COMPLETED for record in records)
    assert len({record.identity.trial_id for record in records}) == 10
    assert len({record.agent_run_id for record in records}) == 10

    expected_architecture = ARCHITECTURE_VERSION_BY_VARIANT[
        ArchitectureVariant.EXPLICIT_PLANNER
    ]
    expects_active = EVIDENCE_MODE == EvidenceMode.VERIFICATION_ENABLED
    for record in records:
        scenario = scenario_by_id(catalog, record.identity.scenario_id)
        health = record.raw_trajectory["runtime_health"]
        assert health["architecture"] == expected_architecture
        assert health["temporal_reasoning"] == "standard"
        assert health["tool_order"] == "free"
        assert health["tool_order_controlled"] is False
        assert health["evidence_mode"] == EVIDENCE_MODE.value
        provider = str(health["provider"])
        assert (ACTIVE_VERIFICATION_PROVIDER_MARKER in provider) is expects_active
        assert "tool-order-controlled-v1" not in provider
        assert "temporal-cause-effect-v1" not in provider
        expected_count = 1 if expects_active else 0
        assert _executed_verification_count(record) == expected_count
        _assert_no_ground_truth_leak(
            record,
            scenario.ground_truth.primary_root_cause_code,
        )
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
        "experiment": "passive_vs_verification",
        "interpretation": "descriptive_only",
        "benchmark_version": catalog.benchmark_version,
        "evidence_mode": EVIDENCE_MODE.value,
        "scenario_ids": list(PASSIVE_VERIFICATION_SCENARIO_IDS),
        "records": [record.model_dump(mode="json") for record in records],
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        "Phase 8 H4 arm complete:",
        EVIDENCE_MODE.value,
        "trials=",
        len(records),
    )


if __name__ == "__main__":
    asyncio.run(main())
