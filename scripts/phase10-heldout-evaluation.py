from __future__ import annotations

import asyncio
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import httpx
from benchmarklab.catalog import load_catalog
from benchmarklab.final_report import (
    mean_or_none,
    nearest_rank_percentile,
    rate_or_none,
    sanitize_benchmark_artifact,
)
from benchmarklab.runner import BenchmarkRunner
from evaluationlab.adapter import adapt_benchmark_artifact
from evaluationlab.counterfactual import (
    CounterfactualObservation,
    adapt_counterfactual_observation,
    score_counterfactual_consistency,
)
from evaluationlab.engine import EvaluationEngine
from evaluationlab.models import FailureCategory

from benchmarklab.release import verify_release_freeze

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_URL = "http://127.0.0.1:8000"
CONTROLLER_URL = "http://127.0.0.1:8100"
OUTPUT_DIR = Path(os.environ.get("PHASE10_HELDOUT_OUTPUT_DIR", "phase10-heldout"))
REPORT_PATH = OUTPUT_DIR / "phase10-heldout-report.json"
TRAJECTORY_PATH = OUTPUT_DIR / "phase10-heldout-trajectories.json"
HIDDEN_SPLIT = "hidden_test"
DIFFICULTIES = ("easy", "medium", "hard", "adversarial", "compound")


def _dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{label} must be an object with string keys")
    return cast(dict[str, Any], value)


async def _json_get(path: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BACKEND_URL}{path}")
    response.raise_for_status()
    return _dict(response.json(), path)


async def _active_faults() -> list[object]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{CONTROLLER_URL}/faults")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise TypeError("ChaosLab fault listing is malformed")
    return payload


def _number(value: object, label: str) -> float:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    return float(value)


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _difficulty_summary(records: list[dict[str, Any]]) -> dict[str, float | None]:
    summary: dict[str, float | None] = {}
    for difficulty in DIFFICULTIES:
        values = [
            _number(item["primary_accuracy"], "primary_accuracy")
            for item in records
            if item["difficulty"] == difficulty
        ]
        summary[difficulty] = mean_or_none(values)
    return summary


def _counterfactual_summary(
    observations: dict[str, list[CounterfactualObservation]],
) -> dict[str, Any]:
    scored: list[dict[str, Any]] = []
    weighted_pairs = 0
    weighted_consistency = 0.0
    insufficient: list[dict[str, Any]] = []
    for family, values in sorted(observations.items()):
        if len(values) < 2:
            insufficient.append({"family": family, "variant_count": len(values)})
            continue
        metrics = score_counterfactual_consistency(values)
        dumped = metrics.model_dump(mode="json")
        scored.append(dumped)
        weighted_pairs += metrics.pair_count
        weighted_consistency += metrics.consistency * metrics.pair_count
    overall = weighted_consistency / weighted_pairs if weighted_pairs else None
    return {
        "available": bool(scored),
        "overall_consistency": overall,
        "scored_pair_count": weighted_pairs,
        "families": scored,
        "insufficient_families": insufficient,
    }


async def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    freeze_proof = verify_release_freeze(REPO_ROOT)
    catalog = load_catalog()
    scenarios = [item for item in catalog.scenarios if item.split.value == HIDDEN_SPLIT]
    if len(scenarios) != 10:
        raise RuntimeError(f"frozen hidden split must contain 10 scenarios, got {len(scenarios)}")

    runtime_health = await _json_get("/agent/health")
    benchmark = BenchmarkRunner()
    evaluator = EvaluationEngine()
    cases = []
    results = []
    per_run: list[dict[str, Any]] = []
    safe_trajectories: list[dict[str, Any]] = []
    counterfactual_observations: dict[str, list[CounterfactualObservation]] = defaultdict(list)
    run_ids: set[str] = set()

    for scenario in scenarios:
        started = perf_counter()
        artifact = await benchmark.run(
            scenario,
            benchmark_version=catalog.benchmark_version,
        )
        wall_clock_seconds = perf_counter() - started
        if artifact.agent_run_id is None:
            raise RuntimeError(f"hidden run {scenario.scenario_id} has no agent_run_id")
        run_id = str(artifact.agent_run_id)
        if run_id in run_ids:
            raise RuntimeError(f"duplicate agent_run_id in hidden evaluation: {run_id}")
        run_ids.add(run_id)

        raw_run = _dict(artifact.raw_agent_run, "benchmark raw agent run")
        case = adapt_benchmark_artifact(
            scenario.model_dump(mode="json"),
            artifact.model_dump(mode="json"),
        )
        result = evaluator.evaluate(case)
        cost = await _json_get(f"/observability/runs/{run_id}/cost")
        if cost.get("run_id") != run_id:
            raise RuntimeError(f"cost summary run mismatch for {scenario.scenario_id}")
        observed_tool_calls = len(raw_run.get("tool_history", []))
        if _integer(cost.get("tool_call_count"), "cost.tool_call_count") != observed_tool_calls:
            raise RuntimeError(f"tool-count mismatch for {scenario.scenario_id}")

        if scenario.kind.value == "counterfactual":
            observation = adapt_counterfactual_observation(
                scenario.model_dump(mode="json"),
                artifact.model_dump(mode="json"),
            )
            counterfactual_observations[observation.family].append(observation)

        failure_categories = sorted(
            {item.category.value for item in result.failure_classifications}
        )
        diagnosis_ms_value = cost.get("time_to_diagnosis_ms")
        diagnosis_ms = (
            None
            if diagnosis_ms_value is None
            else _number(diagnosis_ms_value, "cost.time_to_diagnosis_ms")
        )
        estimated_cost = _number(
            cost.get("total_estimated_cost"),
            "cost.total_estimated_cost",
        )
        total_tokens = _integer(cost.get("total_tokens"), "cost.total_tokens")

        per_run.append(
            {
                "scenario_id": scenario.scenario_id,
                "difficulty": scenario.difficulty.value,
                "kind": scenario.kind.value,
                "agent_run_id": run_id,
                "agent_status": artifact.agent_status,
                "predicted_root_cause": case.predicted_primary_root_cause_code,
                "confidence": case.confidence,
                "primary_accuracy": result.root_cause.primary_accuracy,
                "exact_match": result.root_cause.exact_match,
                "secondary_recall": result.root_cause.secondary_recall,
                "evidence_precision": result.evidence.precision,
                "evidence_recall": result.evidence.recall,
                "critical_evidence_recall": result.evidence.critical_recall,
                "useful_evidence_per_tool_call": (
                    result.efficiency.useful_evidence_per_tool_call
                ),
                "total_tool_calls": result.efficiency.total_tool_calls,
                "duplicate_tool_calls": result.efficiency.duplicate_tool_calls,
                "irrelevant_tool_calls": result.efficiency.irrelevant_tool_calls,
                "misleading_tool_calls": result.efficiency.misleading_tool_calls,
                "failed_tool_calls": result.efficiency.failed_tool_calls,
                "steps_to_correct_hypothesis": result.efficiency.steps_to_correct_hypothesis,
                "failure_categories": failure_categories,
                "total_tokens": total_tokens,
                "estimated_cost": estimated_cost,
                "time_to_diagnosis_ms": diagnosis_ms,
                "wall_clock_seconds": wall_clock_seconds,
                "unsafe_action_attempts": result.safety.unsafe_action_attempts,
            }
        )
        safe_trajectories.append(
            {
                "scenario_id": scenario.scenario_id,
                "difficulty": scenario.difficulty.value,
                "benchmark_artifact": sanitize_benchmark_artifact(
                    artifact.model_dump(mode="json")
                ),
                "evaluation_result": result.model_dump(mode="json"),
                "cost_summary": cost,
                "wall_clock_seconds": wall_clock_seconds,
            }
        )
        cases.append(case)
        results.append(result)

    if await _active_faults() != []:
        raise RuntimeError("ChaosLab faults remain active after final hidden evaluation")

    aggregate = evaluator.evaluate_many(cases)
    failure_counts = Counter(
        category
        for item in per_run
        for category in cast(list[str], item["failure_categories"])
    )
    unsupported_count = failure_counts.get(FailureCategory.UNSUPPORTED_ASSERTION.value, 0)
    tool_failure_records = [item for item in per_run if item["failed_tool_calls"] > 0]
    recovered_tool_failure_records = [
        item for item in tool_failure_records if item["agent_status"] == "completed"
    ]
    compound_records = [item for item in per_run if item["difficulty"] == "compound"]
    diagnosis_latencies = [
        cast(float, item["time_to_diagnosis_ms"])
        for item in per_run
        if item["time_to_diagnosis_ms"] is not None
    ]
    tool_calls = [float(cast(int, item["total_tool_calls"])) for item in per_run]
    token_counts = [float(cast(int, item["total_tokens"])) for item in per_run]
    costs = [cast(float, item["estimated_cost"]) for item in per_run]
    status_counts = Counter(str(item["agent_status"]) for item in per_run)
    budget_exhausted = status_counts.get("budget_exhausted", 0)

    report = {
        "report_version": "phase10-heldout-v1",
        "benchmark_release": freeze_proof,
        "split": HIDDEN_SPLIT,
        "run_count": len(per_run),
        "runtime_health": runtime_health,
        "metric_protocol": {
            "preregistration": "docs/phase-10-heldout-preregistration.md",
            "calibration_correctness": "frozen exact-match correctness",
            "unsupported_claim": "frozen UNSUPPORTED_ASSERTION failure classification",
            "latency_percentile": "nearest-rank over non-null time_to_diagnosis_ms",
            "missing_values": "null; no imputation",
        },
        "aggregate": {
            "overall_rca_accuracy": aggregate.root_cause_accuracy,
            "exact_match_rate": aggregate.exact_match_rate,
            "difficulty_primary_accuracy": _difficulty_summary(per_run),
            "compound_primary_accuracy": mean_or_none(
                [cast(float, item["primary_accuracy"]) for item in compound_records]
            ),
            "compound_secondary_recall": mean_or_none(
                [cast(float, item["secondary_recall"]) for item in compound_records]
            ),
            "evidence_precision": aggregate.evidence_precision,
            "evidence_recall": aggregate.evidence_recall,
            "critical_evidence_recall": aggregate.critical_evidence_recall,
            "tool_efficiency": {
                "useful_evidence_per_tool_call": aggregate.useful_evidence_per_tool_call,
                "mean_tool_calls": mean_or_none(tool_calls),
                "total_tool_calls": int(sum(tool_calls)),
                "duplicate_tool_calls": sum(
                    cast(int, item["duplicate_tool_calls"]) for item in per_run
                ),
                "irrelevant_tool_calls": sum(
                    cast(int, item["irrelevant_tool_calls"]) for item in per_run
                ),
                "misleading_tool_calls": sum(
                    cast(int, item["misleading_tool_calls"]) for item in per_run
                ),
                "failed_tool_calls": sum(
                    cast(int, item["failed_tool_calls"]) for item in per_run
                ),
            },
            "unsupported_claim_rate": rate_or_none(unsupported_count, len(per_run)),
            "calibration": {
                "brier_score": aggregate.brier_score,
                "expected_calibration_error": aggregate.expected_calibration_error,
                "reliability_bins": [
                    item.model_dump(mode="json") for item in aggregate.reliability_bins
                ],
            },
            "latency_ms": {
                "measured_run_count": len(diagnosis_latencies),
                "p50_time_to_diagnosis": nearest_rank_percentile(
                    diagnosis_latencies, 50.0
                ),
                "p95_time_to_diagnosis": nearest_rank_percentile(
                    diagnosis_latencies, 95.0
                ),
            },
            "tokens": {
                "total": int(sum(token_counts)),
                "mean": mean_or_none(token_counts),
            },
            "cost": {
                "total_estimated": sum(costs),
                "mean_estimated": mean_or_none(costs),
            },
            "safety": {
                "unsafe_action_attempts": aggregate.unsafe_action_attempts,
                "blocked_destructive_requests": aggregate.blocked_destructive_requests,
                "unnecessary_approval_requests": aggregate.unnecessary_approval_requests,
                "incorrectly_classified_risk": aggregate.incorrectly_classified_risk,
            },
            "tool_failure_recovery": {
                "affected_runs": len(tool_failure_records),
                "recovered_runs": len(recovered_tool_failure_records),
                "rate": rate_or_none(
                    len(recovered_tool_failure_records),
                    len(tool_failure_records),
                ),
            },
            "run_status_counts": dict(sorted(status_counts.items())),
            "budget_exhausted_runs": budget_exhausted,
            "counterfactual_consistency": _counterfactual_summary(
                counterfactual_observations
            ),
        },
        "failure_category_counts": dict(sorted(failure_counts.items())),
        "per_run": per_run,
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    TRAJECTORY_PATH.write_text(
        json.dumps(
            {
                "report_version": "phase10-heldout-v1",
                "split": HIDDEN_SPLIT,
                "trajectories": safe_trajectories,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(
        "Phase 10 held-out evaluation complete:",
        f"runs={len(per_run)}",
        f"primary_accuracy={aggregate.root_cause_accuracy:.3f}",
        f"exact_match={aggregate.exact_match_rate:.3f}",
    )


if __name__ == "__main__":
    asyncio.run(main())
