from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from benchmarklab.models import ScenarioKind, ScenarioSpec
from evaluationlab.persistence import (
    EvaluationRunMetadata,
    ExperimentConfiguration,
    SqlEvaluationStore,
)
from sqlalchemy import create_engine

from benchmarklab import BenchmarkRunner, load_catalog
from evaluationlab import (
    CounterfactualObservation,
    EvaluationEngine,
    EvaluationResult,
    adapt_benchmark_artifact,
    adapt_counterfactual_observation,
    score_counterfactual_consistency,
)

DATABASE_URL = os.environ.get(
    "OPSSENTINEL_DATABASE_URL",
    "postgresql+psycopg://opssentinel:opssentinel@127.0.0.1:5432/opssentinel",
)
ARTIFACT_DIR = Path(os.environ.get("OPSSENTINEL_PHASE7_ARTIFACT_DIR", "artifacts/phase7"))
EVALUATION_PROVIDER = os.environ.get("OPSSENTINEL_EVALUATION_PROVIDER", "local")
EVALUATION_MODEL = os.environ.get("OPSSENTINEL_EVALUATION_MODEL", "local-placeholder")
ARCHITECTURE_VERSION = "phase5-safe-operational-agent-v1"
FAMILY = "deploy-cron-latency"
EXPECTED_VARIANTS = {
    "original",
    "gap_then_cron",
    "no_deploy_cron",
    "deploy_cron_disabled",
}
TERMINAL_RESEARCH_STATUSES = {"completed", "budget_exhausted"}


def _family_scenarios(catalog_scenarios: list[ScenarioSpec]) -> list[ScenarioSpec]:
    scenarios = [
        scenario
        for scenario in catalog_scenarios
        if scenario.kind == ScenarioKind.COUNTERFACTUAL
        and scenario.structure.counterfactual_family == FAMILY
    ]
    variants = {scenario.structure.counterfactual_variant for scenario in scenarios}
    if variants != EXPECTED_VARIANTS:
        raise AssertionError(
            f"unexpected {FAMILY} variants: {sorted(str(item) for item in variants)}"
        )
    if len(scenarios) != len(EXPECTED_VARIANTS):
        raise AssertionError(f"expected exactly four {FAMILY} scenarios")
    return sorted(
        scenarios,
        key=lambda scenario: str(scenario.structure.counterfactual_variant),
    )


def _variant_run_id(agent_run_id: UUID) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"opssentinel:phase7-counterfactual-variant:{agent_run_id}",
    )


def _family_run_id(agent_run_ids: list[UUID]) -> UUID:
    identity = ":".join(sorted(str(item) for item in agent_run_ids))
    return uuid5(
        NAMESPACE_URL,
        f"opssentinel:phase7-counterfactual-family:{FAMILY}:{identity}",
    )


async def main() -> None:
    catalog = load_catalog()
    scenarios = _family_scenarios(catalog.scenarios)
    runner = BenchmarkRunner()
    evaluator = EvaluationEngine()
    observations: list[CounterfactualObservation] = []
    results: list[EvaluationResult] = []
    records: list[dict[str, object]] = []
    agent_run_ids: list[UUID] = []

    db_engine = create_engine(DATABASE_URL)
    store = SqlEvaluationStore(db_engine)

    try:
        for scenario in scenarios:
            artifact = await runner.run(
                scenario,
                benchmark_version=catalog.benchmark_version,
            )
            variant = scenario.structure.counterfactual_variant
            if variant is None:
                raise AssertionError(f"{scenario.scenario_id}: counterfactual variant is missing")
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
            observation = adapt_counterfactual_observation(
                scenario.model_dump(mode="json"),
                artifact.model_dump(mode="json"),
            )

            # Safety and evaluator integrity are gates; causal performance is measured below.
            assert result.safety.unsafe_action_attempts == 0, scenario.scenario_id
            assert result.safety.incorrectly_classified_risk == 0, scenario.scenario_id
            assert observation.family == FAMILY
            assert observation.variant == variant

            agent_run_id = UUID(str(artifact.agent_run_id))
            evaluation_run_id = _variant_run_id(agent_run_id)
            run = EvaluationRunMetadata(
                id=evaluation_run_id,
                dataset_version=catalog.benchmark_version,
                architecture_version=ARCHITECTURE_VERSION,
                model=EVALUATION_MODEL,
                seed=scenario.seed,
                configuration={
                    "source": "phase7-counterfactual-live-compose",
                    "provider": EVALUATION_PROVIDER,
                    "scenario_id": scenario.scenario_id,
                    "scenario_version": scenario.scenario_version,
                    "counterfactual_family": FAMILY,
                    "counterfactual_variant": variant,
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
                "counterfactual_family": FAMILY,
                "counterfactual_variant": variant,
                "agent_run_id": str(agent_run_id),
                "agent_status": artifact.agent_status,
                "benchmark_artifact": artifact.model_dump(mode="json"),
                "evaluation_case": case.model_dump(mode="json"),
                "counterfactual_observation": observation.model_dump(mode="json"),
            }

            store.create_run(run, experiment)
            store.save_result(
                evaluation_run_id,
                result,
                agent_run_id=agent_run_id,
                trace=trace,
            )

            observations.append(observation)
            results.append(result)
            agent_run_ids.append(agent_run_id)
            records.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "scenario_version": scenario.scenario_version,
                    "seed": scenario.seed,
                    "tool_budget": scenario.budget.max_tool_calls,
                    "counterfactual_variant": variant,
                    "agent_run_id": str(agent_run_id),
                    "evaluation_run_id": str(evaluation_run_id),
                    "agent_status": artifact.agent_status,
                    "expected_root_cause_codes": observation.expected_root_cause_codes,
                    "predicted_root_cause_codes": observation.predicted_root_cause_codes,
                    "confidence": result.confidence,
                    "exact_match": result.root_cause.exact_match,
                    "critical_evidence_recall": result.evidence.critical_recall,
                    "failure_categories": [
                        item.category.value for item in result.failure_classifications
                    ],
                }
            )
    finally:
        await runner.restore()

    assert len(observations) == 4
    metrics = score_counterfactual_consistency(observations)
    assert metrics.family == FAMILY
    assert metrics.variant_count == 4
    assert metrics.pair_count == 6
    assert metrics.causal_sensitivity is not None
    assert metrics.causal_invariance is not None

    family_run_id = _family_run_id(agent_run_ids)
    family_trace = {
        "counterfactual_family": FAMILY,
        "variant_count": len(observations),
        "agent_run_ids": [str(item) for item in agent_run_ids],
        "scenario_ids": [str(record["scenario_id"]) for record in records],
        "variant_evaluation_run_ids": [
            str(record["evaluation_run_id"]) for record in records
        ],
    }
    store.create_run(
        EvaluationRunMetadata(
            id=family_run_id,
            dataset_version=catalog.benchmark_version,
            architecture_version=ARCHITECTURE_VERSION,
            model=EVALUATION_MODEL,
            seed=0,
            configuration={
                "source": "phase7-counterfactual-family-aggregate",
                "provider": EVALUATION_PROVIDER,
                "counterfactual_family": FAMILY,
                "aggregate_seed_scope": "not_applicable",
                "variant_seeds": {
                    str(record["counterfactual_variant"]): int(record["seed"])
                    for record in records
                },
                "variant_tool_budgets": {
                    str(record["counterfactual_variant"]): int(record["tool_budget"])
                    for record in records
                },
            },
        )
    )
    store.save_counterfactual_metrics(
        family_run_id,
        metrics,
        trace=family_trace,
    )

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
            assert loaded_run.configuration["counterfactual_variant"] == (
                scenario.structure.counterfactual_variant
            )
            assert loaded_experiment is not None
            assert loaded_experiment.tool_budget == scenario.budget.max_tool_calls
            assert loaded is not None
            assert loaded.agent_run_id == agent_run_id
            assert loaded.result.model_dump() == result.model_dump()
            assert loaded.trace["counterfactual_family"] == FAMILY

        loaded_family_run = restarted_store.load_run(family_run_id)
        loaded_metrics = restarted_store.load_counterfactual_metrics(family_run_id, FAMILY)
        assert loaded_family_run is not None
        assert loaded_family_run.seed == 0
        assert loaded_family_run.configuration["aggregate_seed_scope"] == "not_applicable"
        assert loaded_metrics is not None
        assert loaded_metrics.model_dump() == metrics.model_dump()
        assert restarted_store.counterfactual_metric_names(family_run_id, FAMILY) == [
            "counterfactual.causal_invariance",
            "counterfactual.causal_sensitivity",
            "counterfactual.consistency",
        ]
    finally:
        restarted_engine.dispose()

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = ARTIFACT_DIR / "counterfactual-evaluation-summary.json"
    summary = {
        "benchmark_version": catalog.benchmark_version,
        "architecture_version": ARCHITECTURE_VERSION,
        "provider": EVALUATION_PROVIDER,
        "model": EVALUATION_MODEL,
        "counterfactual_family": FAMILY,
        "performance_is_measurement_not_ci_threshold": True,
        "family_evaluation_run_id": str(family_run_id),
        "runs": records,
        "metrics": metrics.model_dump(mode="json"),
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert json.loads(summary_path.read_text(encoding="utf-8"))["metrics"] == summary[
        "metrics"
    ]

    print(
        "Phase 7 live counterfactual family passed integrity gates; "
        f"measured consistency={metrics.consistency:.3f}, "
        f"sensitivity={metrics.causal_sensitivity:.3f}, "
        f"invariance={metrics.causal_invariance:.3f}"
    )


if __name__ == "__main__":
    asyncio.run(main())
