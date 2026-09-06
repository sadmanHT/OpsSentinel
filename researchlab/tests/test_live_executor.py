from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from benchmarklab.catalog import load_catalog
from benchmarklab.models import BenchmarkRunArtifact, ScenarioSpec
from evaluationlab.models import EvaluationResult
from evaluationlab.persistence import (
    EvaluationRunMetadata,
    ExperimentConfiguration,
    PersistedEvaluation,
)

from researchlab.benchmark_adapter import scenario_ref_from_benchmark
from researchlab.live_executor import (
    ARCHITECTURE_VERSION_BY_VARIANT,
    LiveTrialExecutor,
    TreatmentIsolationError,
    UnsupportedTreatmentError,
)
from researchlab.models import (
    ArchitectureVariant,
    Difficulty,
    EvidenceMode,
    ExperimentCell,
    ExperimentKind,
    ExperimentPlan,
    ExperimentSplit,
    ResearchConfiguration,
    TrialIdentity,
    make_trial_identity,
)


class FakeHealthProbe:
    def __init__(self, architecture: str) -> None:
        self.architecture = architecture
        self.calls = 0

    async def read(self) -> dict[str, object]:
        self.calls += 1
        return {
            "status": "ok",
            "architecture": self.architecture,
            "provider": "deterministic",
            "legal_tool_count": 16,
        }


class FakeBenchmarkRunner:
    def __init__(self, expected_code: str) -> None:
        self.expected_code = expected_code
        self.calls = 0
        self.seen_budgets: list[int] = []

    async def run(
        self,
        scenario: ScenarioSpec,
        *,
        benchmark_version: str = "1.0.0",
    ) -> BenchmarkRunArtifact:
        self.calls += 1
        self.seen_budgets.append(scenario.budget.max_tool_calls)
        run_id = uuid4()
        return BenchmarkRunArtifact(
            benchmark_version=benchmark_version,
            scenario_id=scenario.scenario_id,
            scenario_version=scenario.scenario_version,
            split=scenario.split,
            difficulty=scenario.difficulty,
            seed=scenario.seed,
            agent_run_id=run_id,
            agent_status="completed",
            diagnosis_code=self.expected_code,
            confidence=0.9,
            tool_call_count=0,
            expected_primary_root_cause_code=self.expected_code,
            expected_secondary_root_cause_codes=[],
            raw_agent_run={
                "run_id": str(run_id),
                "status": "completed",
                "confidence": 0.9,
                "diagnosis_code": self.expected_code,
                "budget": {
                    "max_tool_calls": scenario.budget.max_tool_calls,
                    "tool_calls_used": 0,
                    "cost_used": 0.0,
                    "exhausted_reason": None,
                },
                "tool_history": [],
                "evidence": [],
                "hypotheses": [],
                "approval": None,
                "final_diagnosis": None,
            },
        )


class FakeEvaluationStore:
    def __init__(self) -> None:
        self.runs: dict[UUID, EvaluationRunMetadata] = {}
        self.experiments: dict[UUID, ExperimentConfiguration] = {}
        self.results: dict[tuple[UUID, str], PersistedEvaluation] = {}

    def load_run(self, evaluation_run_id: UUID) -> EvaluationRunMetadata | None:
        return self.runs.get(evaluation_run_id)

    def load_experiment(
        self, evaluation_run_id: UUID
    ) -> ExperimentConfiguration | None:
        return self.experiments.get(evaluation_run_id)

    def load_result(
        self,
        evaluation_run_id: UUID,
        scenario_id: str,
    ) -> PersistedEvaluation | None:
        return self.results.get((evaluation_run_id, scenario_id))

    def create_run(
        self,
        run: EvaluationRunMetadata,
        experiment: ExperimentConfiguration | None = None,
    ) -> None:
        if run.id in self.runs:
            raise ValueError("duplicate evaluation run")
        self.runs[run.id] = run
        if experiment is not None:
            self.experiments[run.id] = experiment

    def save_result(
        self,
        evaluation_run_id: UUID,
        result: EvaluationResult,
        *,
        agent_run_id: UUID | None = None,
        trace: dict[str, Any] | None = None,
    ) -> None:
        self.results[(evaluation_run_id, result.scenario_id)] = PersistedEvaluation(
            evaluation_run_id=evaluation_run_id,
            agent_run_id=agent_run_id,
            result=result,
            trace=trace or {},
            failure_categories=[
                item.category for item in result.failure_classifications
            ],
        )


def _easy_dev_scenario() -> ScenarioSpec:
    catalog = load_catalog()
    return next(
        scenario
        for scenario in catalog.scenarios
        if scenario.split.value == "dev" and scenario.difficulty.value == "easy"
    )


def _trial(
    scenario: ScenarioSpec,
    configuration: ResearchConfiguration,
) -> tuple[TrialIdentity, ExperimentCell]:
    cell = ExperimentCell(
        id="test-cell",
        label="Test cell",
        configuration=configuration,
        difficulties=[Difficulty.EASY],
    )
    plan = ExperimentPlan(
        id="phase8-live-executor-test",
        experiment=ExperimentKind.INVESTIGATION_BUDGET,
        hypothesis_id="H2",
        dataset_version="ops-v1",
        split=ExperimentSplit.DEV,
        cells=[
            cell,
            ExperimentCell(
                id="comparison",
                label="Comparison",
                configuration=configuration.model_copy(
                    update={"tool_budget": configuration.tool_budget + 1}
                ),
                difficulties=[Difficulty.EASY],
            ),
        ],
    )
    reference = scenario_ref_from_benchmark(scenario)
    return make_trial_identity(plan, cell, reference, 0), cell


@pytest.mark.asyncio
async def test_live_executor_applies_budget_scores_and_persists_trace() -> None:
    catalog = load_catalog()
    scenario = _easy_dev_scenario()
    configuration = ResearchConfiguration(tool_budget=5)
    identity, cell = _trial(scenario, configuration)
    benchmark = FakeBenchmarkRunner(scenario.ground_truth.primary_root_cause_code)
    store = FakeEvaluationStore()
    health = FakeHealthProbe(
        ARCHITECTURE_VERSION_BY_VARIANT[ArchitectureVariant.EXPLICIT_PLANNER]
    )
    executor = LiveTrialExecutor(
        catalog=catalog,
        benchmark_runner=benchmark,  # type: ignore[arg-type]
        evaluation_store=store,
        health_probe=health,
    )

    outcome = await executor.execute(
        identity,
        scenario_ref_from_benchmark(scenario),
        cell,
    )

    assert benchmark.seen_budgets == [5]
    assert outcome.evaluation_run_id == identity.trial_id
    assert outcome.agent_run_id is not None
    assert outcome.scores["root_cause_accuracy"] == 1.0
    assert outcome.scores["correctness"] == 1.0
    assert outcome.raw_trajectory["configuration"]["tool_budget"] == 5
    assert outcome.raw_trajectory["runtime_health"]["architecture"] == (
        ARCHITECTURE_VERSION_BY_VARIANT[ArchitectureVariant.EXPLICIT_PLANNER]
    )
    assert store.load_run(identity.trial_id) is not None
    assert store.load_result(identity.trial_id, scenario.scenario_id) is not None


@pytest.mark.asyncio
async def test_live_executor_recovers_saved_evaluation_without_rerunning_agent() -> None:
    catalog = load_catalog()
    scenario = _easy_dev_scenario()
    configuration = ResearchConfiguration(tool_budget=5)
    identity, cell = _trial(scenario, configuration)
    benchmark = FakeBenchmarkRunner(scenario.ground_truth.primary_root_cause_code)
    store = FakeEvaluationStore()
    health = FakeHealthProbe(
        ARCHITECTURE_VERSION_BY_VARIANT[ArchitectureVariant.EXPLICIT_PLANNER]
    )
    executor = LiveTrialExecutor(
        catalog=catalog,
        benchmark_runner=benchmark,  # type: ignore[arg-type]
        evaluation_store=store,
        health_probe=health,
    )

    first = await executor.execute(identity, scenario_ref_from_benchmark(scenario), cell)
    second = await executor.execute(identity, scenario_ref_from_benchmark(scenario), cell)

    assert benchmark.calls == 1
    assert second.evaluation_run_id == first.evaluation_run_id
    assert second.agent_run_id == first.agent_run_id
    assert second.scores["correctness"] == first.scores["correctness"]


@pytest.mark.asyncio
async def test_live_executor_rejects_architecture_mismatch_before_launch() -> None:
    catalog = load_catalog()
    scenario = _easy_dev_scenario()
    configuration = ResearchConfiguration(
        architecture=ArchitectureVariant.REACTIVE_REACT,
        tool_budget=5,
    )
    identity, cell = _trial(scenario, configuration)
    benchmark = FakeBenchmarkRunner(scenario.ground_truth.primary_root_cause_code)
    executor = LiveTrialExecutor(
        catalog=catalog,
        benchmark_runner=benchmark,  # type: ignore[arg-type]
        evaluation_store=FakeEvaluationStore(),
        health_probe=FakeHealthProbe(
            ARCHITECTURE_VERSION_BY_VARIANT[ArchitectureVariant.EXPLICIT_PLANNER]
        ),
    )

    with pytest.raises(TreatmentIsolationError, match="active agent architecture"):
        await executor.execute(identity, scenario_ref_from_benchmark(scenario), cell)

    assert benchmark.calls == 0


@pytest.mark.asyncio
async def test_live_executor_rejects_unimplemented_treatment_before_launch() -> None:
    catalog = load_catalog()
    scenario = _easy_dev_scenario()
    configuration = ResearchConfiguration(
        tool_budget=5,
        evidence_mode=EvidenceMode.VERIFICATION_ENABLED,
    )
    identity, cell = _trial(scenario, configuration)
    benchmark = FakeBenchmarkRunner(scenario.ground_truth.primary_root_cause_code)
    health = FakeHealthProbe(
        ARCHITECTURE_VERSION_BY_VARIANT[ArchitectureVariant.EXPLICIT_PLANNER]
    )
    executor = LiveTrialExecutor(
        catalog=catalog,
        benchmark_runner=benchmark,  # type: ignore[arg-type]
        evaluation_store=FakeEvaluationStore(),
        health_probe=health,
    )

    with pytest.raises(UnsupportedTreatmentError, match="not executable yet"):
        await executor.execute(identity, scenario_ref_from_benchmark(scenario), cell)

    assert health.calls == 0
    assert benchmark.calls == 0


@pytest.mark.asyncio
async def test_live_executor_rejects_budget_not_applied_by_agent() -> None:
    catalog = load_catalog()
    scenario = _easy_dev_scenario()
    configuration = ResearchConfiguration(tool_budget=5)
    identity, cell = _trial(scenario, configuration)

    class WrongBudgetBenchmark(FakeBenchmarkRunner):
        async def run(
            self,
            scenario: ScenarioSpec,
            *,
            benchmark_version: str = "1.0.0",
        ) -> BenchmarkRunArtifact:
            artifact = await super().run(scenario, benchmark_version=benchmark_version)
            artifact.raw_agent_run["budget"]["max_tool_calls"] = 15
            return artifact

    benchmark = WrongBudgetBenchmark(scenario.ground_truth.primary_root_cause_code)
    executor = LiveTrialExecutor(
        catalog=catalog,
        benchmark_runner=benchmark,  # type: ignore[arg-type]
        evaluation_store=FakeEvaluationStore(),
        health_probe=FakeHealthProbe(
            ARCHITECTURE_VERSION_BY_VARIANT[ArchitectureVariant.EXPLICIT_PLANNER]
        ),
    )

    with pytest.raises(TreatmentIsolationError, match="tool budget"):
        await executor.execute(identity, scenario_ref_from_benchmark(scenario), cell)
