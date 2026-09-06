from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from researchlab.models import (
    ExperimentCell,
    ExperimentPlan,
    ScenarioRef,
    TrialIdentity,
    TrialOutcome,
    TrialRecord,
    TrialStatus,
    make_trial_identity,
)


class ExperimentInterrupted(RuntimeError):
    pass


class TrialExecutor(Protocol):
    async def execute(
        self,
        identity: TrialIdentity,
        scenario: ScenarioRef,
        cell: ExperimentCell,
    ) -> TrialOutcome: ...


class TrialStore(Protocol):
    def load(self, trial_id: UUID) -> TrialRecord | None: ...

    def save(self, record: TrialRecord) -> None: ...


class InMemoryTrialStore:
    def __init__(self) -> None:
        self.records: dict[UUID, TrialRecord] = {}

    def load(self, trial_id: UUID) -> TrialRecord | None:
        record = self.records.get(trial_id)
        return record.model_copy(deep=True) if record is not None else None

    def save(self, record: TrialRecord) -> None:
        self.records[record.identity.trial_id] = record.model_copy(deep=True)


def _now() -> datetime:
    return datetime.now(UTC)


class ExperimentRunner:
    def enumerate_trials(
        self,
        plan: ExperimentPlan,
        scenarios: Sequence[ScenarioRef],
    ) -> list[tuple[TrialIdentity, ScenarioRef, ExperimentCell]]:
        ordered_scenarios = sorted(scenarios, key=lambda item: item.scenario_id)
        trials: list[tuple[TrialIdentity, ScenarioRef, ExperimentCell]] = []
        for cell in plan.cells:
            for scenario in ordered_scenarios:
                if scenario.difficulty not in cell.difficulties:
                    continue
                if scenario.split != plan.split:
                    raise ValueError(
                        f"scenario {scenario.scenario_id} split {scenario.split.value} "
                        f"does not match plan split {plan.split.value}"
                    )
                for repeat_index in range(plan.repeat_count):
                    identity = make_trial_identity(plan, cell, scenario, repeat_index)
                    trials.append((identity, scenario, cell))
        return trials

    async def run(
        self,
        plan: ExperimentPlan,
        scenarios: Sequence[ScenarioRef],
        executor: TrialExecutor,
        store: TrialStore,
    ) -> list[TrialRecord]:
        results: list[TrialRecord] = []
        for identity, scenario, cell in self.enumerate_trials(plan, scenarios):
            existing = store.load(identity.trial_id)
            if existing is not None and existing.status == TrialStatus.COMPLETED:
                results.append(existing)
                continue

            running = TrialRecord(
                identity=identity,
                status=TrialStatus.RUNNING,
                updated_at=_now(),
            )
            store.save(running)
            try:
                outcome = await executor.execute(identity, scenario, cell)
            except ExperimentInterrupted as exc:
                interrupted = running.model_copy(
                    update={
                        "status": TrialStatus.INTERRUPTED,
                        "error": str(exc),
                        "updated_at": _now(),
                    }
                )
                store.save(interrupted)
                raise
            except Exception as exc:
                failed = running.model_copy(
                    update={
                        "status": TrialStatus.FAILED,
                        "error": f"{type(exc).__name__}: {exc}",
                        "updated_at": _now(),
                    }
                )
                store.save(failed)
                raise

            completed = TrialRecord(
                identity=identity,
                status=TrialStatus.COMPLETED,
                evaluation_run_id=outcome.evaluation_run_id,
                agent_run_id=outcome.agent_run_id,
                raw_trajectory=outcome.raw_trajectory,
                scores=outcome.scores,
                updated_at=_now(),
            )
            store.save(completed)
            results.append(completed)
        return results
