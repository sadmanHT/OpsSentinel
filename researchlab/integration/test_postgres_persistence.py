from __future__ import annotations

import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine

from researchlab.models import (
    Difficulty,
    ExperimentCell,
    ExperimentSplit,
    ScenarioRef,
    TrialIdentity,
    TrialOutcome,
    TrialRecord,
    TrialStatus,
)
from researchlab.persistence import SqlTrialStore
from researchlab.plans import build_phase8_plans
from researchlab.runner import ExperimentRunner


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[UUID] = []

    async def execute(
        self,
        identity: TrialIdentity,
        scenario: ScenarioRef,
        cell: ExperimentCell,
    ) -> TrialOutcome:
        self.calls.append(identity.trial_id)
        return TrialOutcome(
            raw_trajectory={"scenario_id": scenario.scenario_id, "cell_id": cell.id},
            scores={"root_cause.primary_accuracy": 1.0},
        )


@pytest.mark.asyncio
async def test_postgres_trial_journal_survives_restart_and_resumes_safely() -> None:
    database_url = os.environ["OPSSENTINEL_DATABASE_URL"]
    plan = build_phase8_plans()[0]
    scenario = ScenarioRef(
        scenario_id="ops-v1-001",
        split=ExperimentSplit.VALIDATION,
        difficulty=Difficulty.EASY,
    )
    runner = ExperimentRunner()
    trials = runner.enumerate_trials(plan, [scenario])
    assert len(trials) == 2

    engine = create_engine(database_url)
    store = SqlTrialStore(engine)
    first_identity, _, _ = trials[0]
    second_identity, _, _ = trials[1]
    store.save(
        TrialRecord(
            identity=first_identity,
            status=TrialStatus.COMPLETED,
            raw_trajectory={"persisted_before_restart": True},
            scores={"root_cause.primary_accuracy": 1.0},
        )
    )
    store.save(
        TrialRecord(
            identity=second_identity,
            status=TrialStatus.INTERRUPTED,
            error="simulated process termination",
        )
    )
    engine.dispose()

    restarted_engine = create_engine(database_url)
    restarted_store = SqlTrialStore(restarted_engine)
    first_loaded = restarted_store.load(first_identity.trial_id)
    second_loaded = restarted_store.load(second_identity.trial_id)

    assert first_loaded is not None
    assert first_loaded.status == TrialStatus.COMPLETED
    assert first_loaded.raw_trajectory == {"persisted_before_restart": True}
    assert first_loaded.identity.configuration_hash == first_identity.configuration_hash
    assert second_loaded is not None
    assert second_loaded.status == TrialStatus.INTERRUPTED
    assert second_loaded.error == "simulated process termination"

    executor = RecordingExecutor()
    resumed = await runner.run(plan, [scenario], executor, restarted_store)

    assert len(resumed) == 2
    assert executor.calls == [second_identity.trial_id]
    assert all(record.status == TrialStatus.COMPLETED for record in resumed)
    final_second = restarted_store.load(second_identity.trial_id)
    assert final_second is not None
    assert final_second.status == TrialStatus.COMPLETED
    assert final_second.error is None
    assert final_second.raw_trajectory["cell_id"] == plan.cells[1].id
    restarted_engine.dispose()
