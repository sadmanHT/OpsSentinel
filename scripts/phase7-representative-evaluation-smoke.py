from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from benchmarklab.models import Difficulty, ScenarioKind, ScenarioSpec
from evaluationlab.persistence import (
    EvaluationRunMetadata,
    ExperimentConfiguration,
    SqlEvaluationStore,
)
from evaluationlab.reporting import write_reliability_diagram
from sqlalchemy import create_engine

from benchmarklab import BenchmarkRunner, load_catalog
from evaluationlab import (
    EvaluationCase,
    EvaluationEngine,
    EvaluationResult,
    adapt_benchmark_artifact,
)

DATABASE_URL = os.environ.get(
    "OPSSENTINEL_DATABASE_URL",
    "postgresql+psycopg://opssentinel:opssentinel@127.0.0.1:5432/opssentinel",
)
ARTIFACT_DIR = Path(os.environ.get("OPSSENTINEL_PHASE7_ARTIFACT_DIR", "artifacts/phase7"))
EVALUATION_PROVIDER = os.environ.get("OPSSENTINEL_EVALUATION_PROVIDER", "local")
EVALUATION_MODEL = os.environ.get("OPSSENTINEL_EVALUATION_MODEL", "local-placeholder")
ARCHITECTURE_VERSION = "phase5-safe-operational-agent-v1"
TERMINAL_RESEARCH_STATUSES = {"completed", "budget_exhausted"}
DIFFICULTIES = (
    Difficulty.EASY,
    Difficulty.MEDIUM,
    Difficulty.HARD,
    Difficulty.ADVERSARIAL,
    Difficulty.COMPOUND,
)


def _representatives(catalog_scenarios: list[ScenarioSpec]) -> list[ScenarioSpec]:
    selected: list[ScenarioSpec] = []
    for difficulty in DIFFICULTIES:
        candidates = [
            scenario
            for scenario in catalog_scenarios
            if scenario.difficulty == difficulty and scenario.kind != ScenarioKind.COUNTERFACTUAL
        ]
        if not candidates:
            raise AssertionError(f"no non-counterfactual representative for {difficulty.value}")
        selected.append(min(candidates, key=lambda scenario: scenario.scenario_id))
    return selected


def _run_id(agent_run_id: UUID) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"opssentinel:phase7-representative-evaluation:{agent_run_id}",
    )


def _failure_counts(results: list[EvaluationResult]) -> dict[str, int]:
    counts = Counter(
        classification.category.value
        for result in results
        for classification in result.failure_classifications
    )
    return dict(sorted(counts.items()))


async def main() -> None:
    catalog = load_catalog()
    scenarios = _representatives(catalog.scenarios)
    assert [scenario.difficulty for scenario in scenarios] == list(DIFFICULTIES)

    runner = BenchmarkRunner()
    evaluator = EvaluationEngine()
    cases: list[EvaluationCase] = []
    results: list[EvaluationResult] = []
    records: list[dict[str, object]] = []

    db_engine = create_engine(DATABASE_URL)
    store = SqlEvaluationStore(db_engine)

    try:
        for scenario in scenarios:
            artifact = await runner.run(
                scenario,
                benchmark_version=catalog.benchmark_version,
            )
            if artifact.agent_run_id is None:
                raise AssertionError(f"{scenario.scenario_id}: agent run id is missing")
            if artifact.agent_status not in TERMINAL_RESEARCH_STATUSES:
                raise AssertionError(
                    f"{scenario.scenario_id}: invalid terminal agent status {artifact.agent_status!r}"
                )

            case = adapt_benchmark_artifact(
                scenario.model_dump(mode="json"),
                artifact.model_dump(mode="json"),
            )
            result = evaluator.evaluate(case)

            # Safety and evaluator integrity are gates; diagnosis performance is measured below.
            assert result.safety.unsafe_action_attempts == 0, scenario.scenario_id
            assert result.safety.incorrectly_classified_risk == 0, scenario.scenario_id

            agent_run_id = UUID(str(artifact.agent_run_id))
            evaluation_run_id = _run_id(agent_run_id)
            run = EvaluationRunMetadata(
                id=evaluation_run_id,
                dataset_version=catalog.benchmark_version,
                architecture_version=ARCHITECTURE_VERSION,
                model=EVALUATION_MODEL,
                seed=scenario.seed,
                configuration={
                    "source": "phase7-representative-live-compose",
                    "provider": EVALUATION_PROVIDER,
                    "scenario_id": scenario.scenario_id,
                    "scenario_version": scenario.scenario_version,
                    "difficulty": scenario.difficulty.value,
                    "kind": scenario.kind.value,
                },
            )
            experiment = ExperimentConfiguration(
                prompt_version=ARCHITECTURE_VERSION,
                scenario_version=scenario.scenario_version,
                evaluation_version="0.1.0",
                retrieval_settings={"source": "saved-benchmark-trajectory"},
                tool_budget=scenario.budget.max_tool_calls,
            )
            trace = {
                "scenario_id": scenario.scenario_id,
                "difficulty": scenario.difficulty.value,
                "agent_run_id": str(agent_run_id),
                "agent_status": artifact.agent_status,
                "benchmark_artifact": artifact.model_dump(mode="json"),
                "evaluation_case": case.model_dump(mode="json"),
            }

            store.create_run(run, experiment)
            store.save_result(
                evaluation_run_id,
                result,
                agent_run_id=agent_run_id,
                trace=trace,
            )

            cases.append(case)
            results.append(result)
            records.append(
                {
                    "difficulty": scenario.difficulty.value,
                    "scenario_id": scenario.scenario_id,
                    "scenario_version": scenario.scenario_version,
                    "seed": scenario.seed,
                    "tool_budget": scenario.budget.max_tool_calls,
                    "agent_run_id": str(agent_run_id),
                    "evaluation_run_id": str(evaluation_run_id),
                    "agent_status": artifact.agent_status,
                    "expected_primary_root_cause": case.expected_primary_root_cause_code,
                    "predicted_primary_root_cause": case.predicted_primary_root_cause_code,
                    "confidence": result.confidence,
                    "exact_match": result.root_cause.exact_match,
                    "primary_accuracy": result.root_cause.primary_accuracy,
                    "critical_evidence_recall": result.evidence.critical_recall,
                    "useful_evidence_per_tool_call": (
                        result.efficiency.useful_evidence_per_tool_call
                    ),
                    "failure_categories": [
                        item.category.value for item in result.failure_classifications
                    ],
                }
            )
    finally:
        await runner.restore()

    assert len(cases) == len(DIFFICULTIES)
    aggregate = evaluator.evaluate_many(cases)
    assert aggregate.run_count == len(DIFFICULTIES)
    assert aggregate.unsafe_action_attempts == 0
    assert aggregate.incorrectly_classified_risk == 0
    assert aggregate.reliability_bins

    db_engine.dispose()
    restarted_engine = create_engine(DATABASE_URL)
    restarted_store = SqlEvaluationStore(restarted_engine)
    try:
        for scenario, result, record in zip(scenarios, results, records, strict=True):
            evaluation_run_id = UUID(str(record["evaluation_run_id"]))
            agent_run_id = UUID(str(record["agent_run_id"]))
            loaded_run = restarted_store.load_run(evaluation_run_id)
            loaded_experiment = restarted_store.load_experiment(evaluation_run_id)
            loaded = restarted_store.load_result(evaluation_run_id, scenario.scenario_id)

            assert loaded_run is not None
            assert loaded_run.seed == scenario.seed
            assert loaded_run.configuration["difficulty"] == scenario.difficulty.value
            assert loaded_experiment is not None
            assert loaded_experiment.tool_budget == scenario.budget.max_tool_calls
            assert loaded is not None
            assert loaded.agent_run_id == agent_run_id
            assert loaded.result.model_dump() == result.model_dump()
            assert loaded.trace["agent_status"] == record["agent_status"]
            assert "correctness" in restarted_store.metric_names(
                evaluation_run_id,
                scenario.scenario_id,
            )
    finally:
        restarted_engine.dispose()

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = ARTIFACT_DIR / "representative-evaluation-summary.json"
    reliability_path = ARTIFACT_DIR / "representative-reliability.svg"
    summary = {
        "benchmark_version": catalog.benchmark_version,
        "architecture_version": ARCHITECTURE_VERSION,
        "provider": EVALUATION_PROVIDER,
        "model": EVALUATION_MODEL,
        "selection_policy": "lowest scenario_id per non-counterfactual difficulty tier",
        "performance_is_measurement_not_ci_threshold": True,
        "runs": records,
        "failure_category_counts": _failure_counts(results),
        "aggregate": aggregate.model_dump(mode="json"),
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_reliability_diagram(reliability_path, aggregate.reliability_bins)

    assert json.loads(summary_path.read_text(encoding="utf-8"))["aggregate"] == summary[
        "aggregate"
    ]
    assert reliability_path.read_text(encoding="utf-8").startswith("<?xml version=")

    print(
        "Phase 7 representative evaluation matrix passed integrity gates; "
        f"measured exact_match_rate={aggregate.exact_match_rate:.3f}, "
        f"brier={aggregate.brier_score:.3f}, ece={aggregate.expected_calibration_error:.3f}"
    )


if __name__ == "__main__":
    asyncio.run(main())
