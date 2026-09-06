from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol, cast
from uuid import UUID

import httpx

from benchmarklab.catalog import scenario_by_id
from benchmarklab.models import BenchmarkCatalog, ScenarioSpec
from benchmarklab.runner import BenchmarkRunner
from evaluationlab.adapter import adapt_benchmark_artifact
from evaluationlab.engine import EvaluationEngine
from evaluationlab.models import EvaluationResult
from evaluationlab.persistence import (
    EvaluationRunMetadata,
    ExperimentConfiguration,
    PersistedEvaluation,
)
from researchlab.models import (
    ArchitectureVariant,
    EvidenceMode,
    ExperimentCell,
    ResearchConfiguration,
    ScenarioRef,
    StoppingStrategy,
    TemporalReasoningVariant,
    ToolOrderVariant,
    TrialIdentity,
    TrialOutcome,
)

EVALUATION_VERSION = "0.1.0"

ARCHITECTURE_VERSION_BY_VARIANT: dict[ArchitectureVariant, str] = {
    ArchitectureVariant.EXPLICIT_PLANNER: "phase5-safe-operational-agent-v1",
    ArchitectureVariant.REACTIVE_REACT: "phase5-safe-operational-agent-v1-reactive-react-v1",
}


class TreatmentIsolationError(RuntimeError):
    """Raised when a declared research treatment is not actually active."""


class UnsupportedTreatmentError(RuntimeError):
    """Raised before launch when a Phase 8 treatment has no executable implementation yet."""


class EvaluationStore(Protocol):
    def load_run(self, evaluation_run_id: UUID) -> EvaluationRunMetadata | None: ...

    def load_experiment(
        self, evaluation_run_id: UUID
    ) -> ExperimentConfiguration | None: ...

    def load_result(
        self,
        evaluation_run_id: UUID,
        scenario_id: str,
    ) -> PersistedEvaluation | None: ...

    def create_run(
        self,
        run: EvaluationRunMetadata,
        experiment: ExperimentConfiguration | None = None,
    ) -> None: ...

    def save_result(
        self,
        evaluation_run_id: UUID,
        result: EvaluationResult,
        *,
        agent_run_id: UUID | None = None,
        trace: dict[str, Any] | None = None,
    ) -> None: ...


class RuntimeHealthProbe(Protocol):
    async def read(self) -> dict[str, object]: ...


@dataclass(frozen=True)
class HttpRuntimeHealthProbe:
    backend_url: str
    timeout_seconds: float = 15.0

    async def read(self) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(f"{self.backend_url.rstrip('/')}/agent/health")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
            raise TreatmentIsolationError("agent health returned malformed JSON")
        return cast(dict[str, object], payload)


def _validate_supported_configuration(configuration: ResearchConfiguration) -> None:
    unsupported: list[str] = []
    if configuration.tool_order != ToolOrderVariant.FREE:
        unsupported.append(f"tool_order={configuration.tool_order.value}")
    if configuration.evidence_mode != EvidenceMode.PASSIVE_ONLY:
        unsupported.append(f"evidence_mode={configuration.evidence_mode.value}")
    if configuration.temporal_reasoning != TemporalReasoningVariant.STANDARD:
        unsupported.append(
            f"temporal_reasoning={configuration.temporal_reasoning.value}"
        )
    if configuration.stopping_strategy != StoppingStrategy.CONFIDENCE_THRESHOLD:
        unsupported.append(
            f"stopping_strategy={configuration.stopping_strategy.value}"
        )
    if unsupported:
        raise UnsupportedTreatmentError(
            "Phase 8 treatment is declared but not executable yet: " + ", ".join(unsupported)
        )


def _score_payload(
    result: EvaluationResult,
    *,
    latency_seconds: float,
    cost_used: float,
) -> dict[str, float]:
    return {
        "root_cause_accuracy": result.root_cause.primary_accuracy,
        "exact_match": float(result.root_cause.exact_match),
        "evidence_precision": result.evidence.precision,
        "evidence_recall": result.evidence.recall,
        "critical_evidence_recall": result.evidence.critical_recall,
        "useful_evidence_per_tool_call": result.efficiency.useful_evidence_per_tool_call,
        "confidence": result.confidence,
        "correctness": result.correctness,
        "brier_component": result.brier_component,
        "tool_calls": float(result.efficiency.total_tool_calls),
        "latency_seconds": latency_seconds,
        "estimated_cost": cost_used,
    }


def _budget_cost(raw_agent_run: dict[str, Any]) -> float:
    budget = raw_agent_run.get("budget")
    if not isinstance(budget, dict):
        return 0.0
    value = budget.get("cost_used", 0.0)
    return float(value) if isinstance(value, (int, float)) else 0.0


class LiveTrialExecutor:
    """Execute one controlled Phase 8 trial through BenchmarkLab and EvaluationLab."""

    def __init__(
        self,
        *,
        catalog: BenchmarkCatalog,
        benchmark_runner: BenchmarkRunner,
        evaluation_store: EvaluationStore,
        evaluation_engine: EvaluationEngine | None = None,
        health_probe: RuntimeHealthProbe | None = None,
    ) -> None:
        self.catalog = catalog
        self.benchmark_runner = benchmark_runner
        self.evaluation_store = evaluation_store
        self.evaluation_engine = evaluation_engine or EvaluationEngine()
        self.health_probe = health_probe or HttpRuntimeHealthProbe(
            benchmark_runner.environment.backend_url
        )

    def _scenario(self, reference: ScenarioRef) -> ScenarioSpec:
        scenario = scenario_by_id(self.catalog, reference.scenario_id)
        if scenario.scenario_version != reference.scenario_version:
            raise TreatmentIsolationError(
                f"scenario version mismatch for {reference.scenario_id}: "
                f"{scenario.scenario_version} != {reference.scenario_version}"
            )
        if scenario.split.value != reference.split.value:
            raise TreatmentIsolationError(
                f"scenario split mismatch for {reference.scenario_id}: "
                f"{scenario.split.value} != {reference.split.value}"
            )
        if scenario.difficulty.value != reference.difficulty.value:
            raise TreatmentIsolationError(
                f"scenario difficulty mismatch for {reference.scenario_id}: "
                f"{scenario.difficulty.value} != {reference.difficulty.value}"
            )
        return scenario

    async def _runtime_health(
        self,
        configuration: ResearchConfiguration,
    ) -> dict[str, object]:
        health = await self.health_probe.read()
        expected = ARCHITECTURE_VERSION_BY_VARIANT[configuration.architecture]
        observed = health.get("architecture")
        if observed != expected:
            raise TreatmentIsolationError(
                "active agent architecture does not match the research cell: "
                f"{observed!r} != {expected!r}"
            )
        return health

    def _validate_existing_run(
        self,
        identity: TrialIdentity,
        scenario: ScenarioSpec,
        architecture_version: str,
    ) -> None:
        run = self.evaluation_store.load_run(identity.trial_id)
        if run is None:
            return
        expected_configuration = identity.configuration.model_dump(mode="json")
        mismatches: list[str] = []
        if run.dataset_version != identity.dataset_version:
            mismatches.append("dataset_version")
        if run.architecture_version != architecture_version:
            mismatches.append("architecture_version")
        if run.model != identity.configuration.model:
            mismatches.append("model")
        if run.seed != identity.seed:
            mismatches.append("seed")
        if run.configuration != expected_configuration:
            mismatches.append("configuration")
        experiment = self.evaluation_store.load_experiment(identity.trial_id)
        if experiment is None:
            mismatches.append("experiment_metadata")
        else:
            if experiment.prompt_version != identity.configuration.prompt_version:
                mismatches.append("prompt_version")
            if experiment.scenario_version != scenario.scenario_version:
                mismatches.append("scenario_version")
            if experiment.evaluation_version != EVALUATION_VERSION:
                mismatches.append("evaluation_version")
            if experiment.tool_budget != identity.configuration.tool_budget:
                mismatches.append("tool_budget")
        if mismatches:
            raise TreatmentIsolationError(
                "persisted evaluation metadata does not match the resumed trial: "
                + ", ".join(mismatches)
            )

    def _ensure_evaluation_run(
        self,
        identity: TrialIdentity,
        scenario: ScenarioSpec,
        architecture_version: str,
    ) -> None:
        if self.evaluation_store.load_run(identity.trial_id) is not None:
            self._validate_existing_run(identity, scenario, architecture_version)
            return
        configuration = identity.configuration
        self.evaluation_store.create_run(
            EvaluationRunMetadata(
                id=identity.trial_id,
                dataset_version=identity.dataset_version,
                architecture_version=architecture_version,
                model=configuration.model,
                seed=identity.seed,
                configuration=configuration.model_dump(mode="json"),
            ),
            ExperimentConfiguration(
                prompt_version=configuration.prompt_version,
                scenario_version=scenario.scenario_version,
                evaluation_version=EVALUATION_VERSION,
                retrieval_settings={},
                tool_budget=configuration.tool_budget,
            ),
        )

    def _recover_persisted(
        self,
        identity: TrialIdentity,
        scenario: ScenarioSpec,
    ) -> TrialOutcome | None:
        persisted = self.evaluation_store.load_result(identity.trial_id, scenario.scenario_id)
        if persisted is None:
            return None
        latency_value = persisted.trace.get("latency_seconds", 0.0)
        cost_value = persisted.trace.get("estimated_cost", 0.0)
        latency = float(latency_value) if isinstance(latency_value, (int, float)) else 0.0
        cost = float(cost_value) if isinstance(cost_value, (int, float)) else 0.0
        return TrialOutcome(
            evaluation_run_id=identity.trial_id,
            agent_run_id=persisted.agent_run_id,
            raw_trajectory=persisted.trace,
            scores=_score_payload(
                persisted.result,
                latency_seconds=latency,
                cost_used=cost,
            ),
        )

    async def execute(
        self,
        identity: TrialIdentity,
        scenario: ScenarioRef,
        cell: ExperimentCell,
    ) -> TrialOutcome:
        if identity.cell_id != cell.id:
            raise TreatmentIsolationError("trial identity and experiment cell id differ")
        if identity.scenario_id != scenario.scenario_id:
            raise TreatmentIsolationError("trial identity and scenario reference id differ")
        if identity.configuration != cell.configuration:
            raise TreatmentIsolationError("trial identity and experiment cell configuration differ")
        _validate_supported_configuration(identity.configuration)
        benchmark_scenario = self._scenario(scenario)
        health = await self._runtime_health(identity.configuration)
        architecture_version = ARCHITECTURE_VERSION_BY_VARIANT[
            identity.configuration.architecture
        ]
        self._ensure_evaluation_run(identity, benchmark_scenario, architecture_version)

        recovered = self._recover_persisted(identity, benchmark_scenario)
        if recovered is not None:
            return recovered

        trial_scenario = benchmark_scenario.model_copy(deep=True)
        trial_scenario.budget = trial_scenario.budget.model_copy(
            update={"max_tool_calls": identity.configuration.tool_budget}
        )

        started = perf_counter()
        artifact = await self.benchmark_runner.run(
            trial_scenario,
            benchmark_version=self.catalog.benchmark_version,
        )
        latency_seconds = perf_counter() - started
        if artifact.agent_run_id is None:
            raise TreatmentIsolationError("benchmark run completed without an agent_run_id")

        raw_budget = artifact.raw_agent_run.get("budget")
        if not isinstance(raw_budget, dict):
            raise TreatmentIsolationError("agent run did not return a budget payload")
        applied_budget = raw_budget.get("max_tool_calls")
        if applied_budget != identity.configuration.tool_budget:
            raise TreatmentIsolationError(
                "agent tool budget does not match the research cell: "
                f"{applied_budget!r} != {identity.configuration.tool_budget!r}"
            )

        case = adapt_benchmark_artifact(
            benchmark_scenario.model_dump(mode="json"),
            artifact.model_dump(mode="json"),
        )
        result = self.evaluation_engine.evaluate(case)
        cost_used = _budget_cost(artifact.raw_agent_run)
        trace: dict[str, Any] = {
            "trial_id": str(identity.trial_id),
            "plan_id": identity.plan_id,
            "cell_id": identity.cell_id,
            "configuration": identity.configuration.model_dump(mode="json"),
            "runtime_health": health,
            "benchmark_artifact": artifact.model_dump(mode="json"),
            "evaluation_case": case.model_dump(mode="json"),
            "evaluation_result": result.model_dump(mode="json"),
            "latency_seconds": latency_seconds,
            "estimated_cost": cost_used,
        }
        self.evaluation_store.save_result(
            identity.trial_id,
            result,
            agent_run_id=artifact.agent_run_id,
            trace=trace,
        )
        return TrialOutcome(
            evaluation_run_id=identity.trial_id,
            agent_run_id=artifact.agent_run_id,
            raw_trajectory=trace,
            scores=_score_payload(
                result,
                latency_seconds=latency_seconds,
                cost_used=cost_used,
            ),
        )
