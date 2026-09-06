from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from researchlab.models import (
    Difficulty,
    ExperimentCell,
    ExperimentSplit,
    ScenarioRef,
    TrialIdentity,
    TrialOutcome,
    TrialStatus,
)
from researchlab.plans import build_phase8_plans
from researchlab.runner import ExperimentInterrupted, ExperimentRunner, InMemoryTrialStore


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[UUID] = []
        self.interrupt_once = False

    async def execute(
        self,
        identity: TrialIdentity,
        scenario: ScenarioRef,
        cell: ExperimentCell,
    ) -> TrialOutcome:
        self.calls.append(identity.trial_id)
        if self.interrupt_once:
            self.interrupt_once = False
            raise ExperimentInterrupted("simulated worker interruption")
        return TrialOutcome(
            evaluation_run_id=uuid4(),
            agent_run_id=uuid4(),
            raw_trajectory={"scenario_id": scenario.scenario_id, "cell": cell.id},
            scores={"root_cause_accuracy": 1.0},
        )


@pytest.fixture
def easy_scenario() -> ScenarioRef:
    return ScenarioRef(
        scenario_id="ops-v1-001",
        split=ExperimentSplit.VALIDATION,
        difficulty=Difficulty.EASY,
    )


@pytest.mark.asyncio
async def test_completed_trials_are_skipped_on_resume(easy_scenario: ScenarioRef) -> None:
    plan = build_phase8_plans()[0]
    executor = RecordingExecutor()
    store = InMemoryTrialStore()
    runner = ExperimentRunner()

    first = await runner.run(plan, [easy_scenario], executor, store)
    second = await runner.run(plan, [easy_scenario], executor, store)

    assert len(first) == 2
    assert len(second) == 2
    assert len(executor.calls) == 2
    assert all(record.status == TrialStatus.COMPLETED for record in second)
    assert all(record.raw_trajectory for record in second)
    assert all(record.scores for record in second)


@pytest.mark.asyncio
async def test_interrupted_trial_is_persisted_and_retried_safely(
    easy_scenario: ScenarioRef,
) -> None:
    plan = build_phase8_plans()[0]
    executor = RecordingExecutor()
    executor.interrupt_once = True
    store = InMemoryTrialStore()
    runner = ExperimentRunner()

    with pytest.raises(ExperimentInterrupted, match="simulated worker interruption"):
        await runner.run(plan, [easy_scenario], executor, store)

    interrupted = list(store.records.values())
    assert len(interrupted) == 1
    assert interrupted[0].status == TrialStatus.INTERRUPTED

    resumed = await runner.run(plan, [easy_scenario], executor, store)

    assert len(resumed) == 2
    assert all(record.status == TrialStatus.COMPLETED for record in resumed)
    assert len(executor.calls) == 3


@pytest.mark.asyncio
async def test_split_mismatch_fails_before_any_trial_executes() -> None:
    plan = build_phase8_plans()[0]
    scenario = ScenarioRef(
        scenario_id="ops-v1-dev",
        split=ExperimentSplit.DEV,
        difficulty=Difficulty.EASY,
    )
    executor = RecordingExecutor()
    store = InMemoryTrialStore()

    with pytest.raises(ValueError, match="does not match plan split"):
        await ExperimentRunner().run(plan, [scenario], executor, store)

    assert executor.calls == []
    assert store.records == {}
