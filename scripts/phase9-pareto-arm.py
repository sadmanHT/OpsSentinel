from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import httpx
from benchmarklab.catalog import load_catalog
from benchmarklab.runner import BenchmarkRunner
from evaluationlab.adapter import adapt_benchmark_artifact
from evaluationlab.engine import EvaluationEngine
from researchlab.live_executor import (
    ACTIVE_VERIFICATION_PROVIDER_MARKER,
    ARCHITECTURE_VERSION_BY_VARIANT,
)
from researchlab.models import EvidenceMode
from researchlab.pareto_campaign import (
    NO_FAULT_SCENARIO_ID,
    PARETO_VALIDATION_SCENARIO_IDS,
    ParetoCampaignTrial,
    pareto_configuration,
    validate_pareto_catalog,
)
from researchlab.pareto_live import ParetoArmArtifact, validate_pareto_arm

BACKEND_URL = "http://127.0.0.1:8000"
CONTROLLER_URL = "http://127.0.0.1:8100"
RETRIEVAL_PROVIDER_MARKER = "retrieval-depth-cap-v1"
BANNED_PROVIDER_MARKERS = (
    "tool-order-controlled-v1",
    "temporal-cause-effect-v1",
    "compound-evidence-plan-v1",
    "unresolved-evidence-stop-v1",
)
CONFIG_ID = os.environ["PHASE9_PARETO_CONFIG_ID"]
OUTPUT_PATH = Path(
    os.environ.get(
        "PHASE9_PARETO_ARM_OUTPUT",
        f"phase9-pareto-{CONFIG_ID}.json",
    )
)


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


def _assert_runtime_health(health: dict[str, Any]) -> None:
    configuration = pareto_configuration(CONFIG_ID)
    expected_architecture = ARCHITECTURE_VERSION_BY_VARIANT[configuration.architecture]
    assert health["architecture"] == expected_architecture
    assert health["llm_provider"] == configuration.provider == "local"
    assert health["llm_model"] == configuration.model == "local-placeholder"
    assert health["temporal_reasoning"] == "standard"
    assert health["tool_order"] == "free"
    assert health["tool_order_controlled"] is False
    assert health["evidence_mode"] == configuration.evidence_mode.value
    assert health["retrieval_depth"] == configuration.retrieval_depth
    assert health["retrieval_depth_controlled"] is True
    assert health["stopping_strategy"] == "confidence_threshold"
    assert health["compound_evidence_plan"] is False

    provider = health.get("provider")
    if not isinstance(provider, str):
        raise TypeError("agent health provider must be a string")
    assert RETRIEVAL_PROVIDER_MARKER in provider
    expects_verification = (
        configuration.evidence_mode == EvidenceMode.VERIFICATION_ENABLED
    )
    assert (ACTIVE_VERIFICATION_PROVIDER_MARKER in provider) is expects_verification
    for marker in BANNED_PROVIDER_MARKERS:
        assert marker not in provider


def _assert_no_ground_truth_leak(raw_run: dict[str, Any], expected_code: str) -> None:
    incident = json.dumps(raw_run.get("incident"), sort_keys=True).casefold()
    assert "ground_truth" not in incident
    assert "timeline" not in incident
    assert "offset_seconds" not in incident
    assert expected_code.casefold() not in incident


def _false_positive(scenario_id: str, predicted_code: str | None) -> bool | None:
    if scenario_id != NO_FAULT_SCENARIO_ID:
        return None
    return predicted_code is None or predicted_code.casefold() != "no_fault"


async def main() -> None:
    configuration = pareto_configuration(CONFIG_ID)
    catalog = load_catalog()
    scenarios = validate_pareto_catalog(catalog)
    assert [scenario.scenario_id for scenario in scenarios] == list(
        PARETO_VALIDATION_SCENARIO_IDS
    )

    health = await _json_get("/agent/health")
    _assert_runtime_health(health)
    benchmark = BenchmarkRunner()
    evaluation = EvaluationEngine()
    trials: list[ParetoCampaignTrial] = []
    raw_records: list[dict[str, Any]] = []

    for scenario in scenarios:
        trial_scenario = scenario.model_copy(deep=True)
        trial_scenario.budget = trial_scenario.budget.model_copy(
            update={"max_tool_calls": configuration.tool_budget}
        )

        started = perf_counter()
        artifact = await benchmark.run(
            trial_scenario,
            benchmark_version=catalog.benchmark_version,
        )
        latency_seconds = perf_counter() - started
        if artifact.agent_run_id is None:
            raise RuntimeError(
                f"Pareto trial {configuration.id}/{scenario.scenario_id} has no agent run id"
            )

        raw_run = _dict(artifact.raw_agent_run, "benchmark raw agent run")
        raw_budget = _dict(raw_run.get("budget"), "agent run budget")
        assert raw_budget.get("max_tool_calls") == configuration.tool_budget
        _assert_no_ground_truth_leak(
            raw_run,
            scenario.ground_truth.primary_root_cause_code,
        )

        case = adapt_benchmark_artifact(
            scenario.model_dump(mode="json"),
            artifact.model_dump(mode="json"),
        )
        result = evaluation.evaluate(case)
        cost = await _json_get(f"/observability/runs/{artifact.agent_run_id}/cost")
        assert cost["run_id"] == str(artifact.agent_run_id)
        assert cost["tool_call_count"] == len(raw_run.get("tool_history", []))

        total_tokens = cost.get("total_tokens")
        tool_calls = cost.get("tool_call_count")
        retrieved_evidence = cost.get("retrieval_depth")
        estimated_cost = cost.get("total_estimated_cost")
        diagnosis_ms = cost.get("time_to_diagnosis_ms")
        if not isinstance(total_tokens, int):
            raise TypeError("cost summary total_tokens must be an integer")
        if not isinstance(tool_calls, int):
            raise TypeError("cost summary tool_call_count must be an integer")
        if not isinstance(retrieved_evidence, int):
            raise TypeError("cost summary retrieval_depth must be an integer")
        if not isinstance(estimated_cost, (int, float)):
            raise TypeError("cost summary total_estimated_cost must be numeric")
        if diagnosis_ms is not None and not isinstance(diagnosis_ms, (int, float)):
            raise TypeError("cost summary time_to_diagnosis_ms must be numeric or null")

        failure_categories = sorted(
            {item.category.value for item in result.failure_classifications}
        )
        trial = ParetoCampaignTrial(
            configuration=configuration.model_copy(deep=True),
            scenario_id=scenario.scenario_id,
            agent_run_id=artifact.agent_run_id,
            diagnostic_accuracy=result.root_cause.primary_accuracy,
            exact_match=float(result.root_cause.exact_match),
            estimated_cost=float(estimated_cost),
            total_tokens=total_tokens,
            tool_calls=tool_calls,
            retrieved_evidence=retrieved_evidence,
            latency_seconds=latency_seconds,
            time_to_diagnosis_ms=(
                float(diagnosis_ms) if diagnosis_ms is not None else None
            ),
            failure_categories=failure_categories,
            no_fault_false_positive=_false_positive(
                scenario.scenario_id,
                case.predicted_primary_root_cause_code,
            ),
        )
        trials.append(trial)
        raw_records.append(
            {
                "configuration_id": configuration.id,
                "scenario_id": scenario.scenario_id,
                "runtime_health": health,
                "benchmark_artifact": artifact.model_dump(mode="json"),
                "evaluation_case": case.model_dump(mode="json"),
                "evaluation_result": result.model_dump(mode="json"),
                "cost_summary": cost,
                "latency_seconds": latency_seconds,
            }
        )

    assert len(trials) == 10
    assert len({trial.agent_run_id for trial in trials}) == 10
    assert await _active_faults() == []

    artifact = validate_pareto_arm(
        ParetoArmArtifact(
            benchmark_version=catalog.benchmark_version,
            configuration=configuration,
            scenario_ids=list(PARETO_VALIDATION_SCENARIO_IDS),
            runtime_health=health,
            trials=trials,
            raw_records=raw_records,
        )
    )
    OUTPUT_PATH.write_text(artifact.model_dump_json(indent=2) + "\n")
    print(
        "Phase 9 Pareto arm complete:",
        configuration.id,
        "trials=",
        len(trials),
    )


if __name__ == "__main__":
    asyncio.run(main())
