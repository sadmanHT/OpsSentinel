from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from benchmarklab import BenchmarkEnvironment, BenchmarkRunner, load_catalog
from benchmarklab.models import BenchmarkRunArtifact, Difficulty, ScenarioSpec
from evaluationlab import (
    EvaluationCase,
    EvaluationEngine,
    EvaluationResult,
    adapt_benchmark_artifact,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "frontend"
ARTIFACT_PATH = REPO_ROOT / "phase9-representative-frontend.json"
FRONTEND_URL = os.environ.get("OPSSENTINEL_FRONTEND_URL", "http://127.0.0.1:5173/")
BACKEND_URL = os.environ.get("OPSSENTINEL_BACKEND_URL", "http://127.0.0.1:8000")
CONTROLLER_URL = os.environ.get("OPSSENTINEL_CONTROLLER_URL", "http://127.0.0.1:8100")
TERMINAL_RESEARCH_STATUSES = {"completed", "budget_exhausted"}
REPRESENTATIVES = {
    Difficulty.EASY: "ops-v1-001",
    Difficulty.HARD: "ops-v1-033",
    Difficulty.ADVERSARIAL: "ops-v1-035",
    Difficulty.COMPOUND: "ops-v1-043",
}


def _scenario_by_id(scenarios: list[ScenarioSpec], scenario_id: str) -> ScenarioSpec:
    for scenario in scenarios:
        if scenario.scenario_id == scenario_id:
            return scenario
    raise AssertionError(f"missing preregistered scenario {scenario_id}")


def _browser_input(scenario: ScenarioSpec) -> dict[str, str]:
    public = scenario.public_incident
    payload = {
        "title": public.title,
        "description": public.description,
        "severity": public.severity.value,
        "service": public.service.value,
    }
    serialized = json.dumps(payload, sort_keys=True).casefold()
    if scenario.scenario_id.casefold() in serialized:
        raise AssertionError(f"{scenario.scenario_id}: scenario ID leaked into browser input")
    forbidden = {
        scenario.ground_truth.primary_root_cause_code.casefold(),
        *(item.casefold() for item in scenario.ground_truth.secondary_root_cause_codes),
    }
    leaked = sorted(item for item in forbidden if item and item in serialized)
    if leaked:
        raise AssertionError(
            f"{scenario.scenario_id}: hidden RCA leaked into browser input: {leaked}"
        )
    return payload


def _run_browser(scenario: ScenarioSpec) -> dict[str, Any]:
    input_path = REPO_ROOT / f".phase9-frontend-{scenario.scenario_id}-input.json"
    output_path = REPO_ROOT / f".phase9-frontend-{scenario.scenario_id}-output.json"
    input_path.write_text(json.dumps(_browser_input(scenario)), encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "OPSSENTINEL_FRONTEND_URL": FRONTEND_URL,
            "OPSSENTINEL_FRONTEND_SCENARIO_INPUT": str(input_path),
            "OPSSENTINEL_FRONTEND_SCENARIO_OUTPUT": str(output_path),
        }
    )
    try:
        subprocess.run(
            ["node", "scripts/phase9-representative-frontend-proof.mjs"],
            cwd=FRONTEND_DIR,
            env=env,
            check=True,
            timeout=240,
        )
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("browser proof output must be a JSON object")
        return payload
    finally:
        input_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)


def _read_agent_run(run_id: UUID) -> dict[str, Any]:
    response = httpx.get(f"{BACKEND_URL.rstrip('/')}/agent/runs/{run_id}", timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError("agent readback must be a JSON object")
    return payload


def _benchmark_artifact(scenario: ScenarioSpec, run: dict[str, Any]) -> BenchmarkRunArtifact:
    run_id = UUID(str(run["run_id"]))
    return BenchmarkRunArtifact(
        benchmark_version=load_catalog().benchmark_version,
        scenario_id=scenario.scenario_id,
        scenario_version=scenario.scenario_version,
        split=scenario.split,
        difficulty=scenario.difficulty,
        seed=scenario.seed,
        agent_run_id=run_id,
        agent_status=str(run.get("status", "unknown")),
        diagnosis_code=(str(run["diagnosis_code"]) if run.get("diagnosis_code") else None),
        confidence=(float(run["confidence"]) if run.get("confidence") is not None else None),
        tool_call_count=len(run.get("tool_history", [])),
        expected_primary_root_cause_code=scenario.ground_truth.primary_root_cause_code,
        expected_secondary_root_cause_codes=scenario.ground_truth.secondary_root_cause_codes,
        raw_agent_run=run,
    )


def _evaluate(
    evaluator: EvaluationEngine,
    scenario: ScenarioSpec,
    run: dict[str, Any],
) -> tuple[EvaluationCase, EvaluationResult]:
    artifact = _benchmark_artifact(scenario, run)
    case = adapt_benchmark_artifact(
        scenario.model_dump(mode="json"),
        artifact.model_dump(mode="json"),
    )
    return case, evaluator.evaluate(case)


async def _assert_faults_clear() -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{CONTROLLER_URL.rstrip('/')}/faults")
        response.raise_for_status()
        if response.json() != []:
            raise AssertionError(f"ChaosLab faults were not restored: {response.text[:500]}")


async def main() -> None:
    catalog = load_catalog()
    scenarios = [
        _scenario_by_id(catalog.scenarios, REPRESENTATIVES[difficulty])
        for difficulty in REPRESENTATIVES
    ]
    if [scenario.difficulty for scenario in scenarios] != list(REPRESENTATIVES):
        raise AssertionError("representative scenario difficulty mapping changed")

    runner = BenchmarkRunner(
        BenchmarkEnvironment(
            backend_url=BACKEND_URL,
            controller_url=CONTROLLER_URL,
            timeout_seconds=180,
        )
    )
    evaluator = EvaluationEngine()
    cases: list[EvaluationCase] = []
    results: list[EvaluationResult] = []
    records: list[dict[str, Any]] = []

    try:
        for scenario in scenarios:
            try:
                launch = await runner.launch(scenario)
                browser = _run_browser(scenario)
                run_id = UUID(str(browser["run_id"]))
                run = _read_agent_run(run_id)
                if run.get("incident", {}).get("scenario_id") is not None:
                    raise AssertionError(
                        f"{scenario.scenario_id}: frontend-created incident retained "
                        "scenario metadata"
                    )
                status = str(run.get("status", "unknown"))
                if status not in TERMINAL_RESEARCH_STATUSES:
                    raise AssertionError(
                        f"{scenario.scenario_id}: invalid terminal frontend status {status!r}"
                    )
                if browser.get("request_shape_safe") is not True:
                    raise AssertionError(f"{scenario.scenario_id}: unsafe browser request shape")
                if browser.get("terminal_state_rendered") is not True:
                    raise AssertionError(f"{scenario.scenario_id}: terminal state was not rendered")

                case, result = _evaluate(evaluator, scenario, run)
                if result.safety.unsafe_action_attempts != 0:
                    raise AssertionError(f"{scenario.scenario_id}: unsafe action attempt")
                if result.safety.incorrectly_classified_risk != 0:
                    raise AssertionError(f"{scenario.scenario_id}: risk classification failure")

                cases.append(case)
                results.append(result)
                records.append(
                    {
                        "difficulty": scenario.difficulty.value,
                        "scenario_id": scenario.scenario_id,
                        "run_id": str(run_id),
                        "agent_status": status,
                        "injected_fault_count": launch.injected_fault_count,
                        "stimulus_count": launch.stimulus_count,
                        "frontend_request_safe": True,
                        "scenario_id_absent_from_agent_incident": True,
                        "terminal_state_rendered": True,
                        "timeline_rendered": browser["timeline_rendered"],
                        "evidence_panel_rendered": browser["evidence_panel_rendered"],
                        "hypotheses_panel_rendered": browser["hypotheses_panel_rendered"],
                        "primary_accuracy": result.root_cause.primary_accuracy,
                        "exact_match": result.root_cause.exact_match,
                        "critical_evidence_recall": result.evidence.critical_recall,
                        "tool_call_count": result.efficiency.total_tool_calls,
                        "failure_categories": [
                            item.category.value for item in result.failure_classifications
                        ],
                        "unsafe_action_attempts": result.safety.unsafe_action_attempts,
                    }
                )
            finally:
                await runner.restore()
                await _assert_faults_clear()
    finally:
        await runner.restore()

    aggregate = evaluator.evaluate_many(cases)
    if aggregate.run_count != 4:
        raise AssertionError(
            f"expected four representative frontend runs, got {aggregate.run_count}"
        )
    if aggregate.unsafe_action_attempts != 0 or aggregate.incorrectly_classified_risk != 0:
        raise AssertionError("representative frontend aggregate violated safety gates")

    proof = {
        "head_sha": os.environ.get("OPSSENTINEL_EXPECTED_HEAD_SHA", "local"),
        "selection_policy": "preregistered first representative per required difficulty tier",
        "performance_is_measurement_not_ci_threshold": True,
        "frontend_is_only_agent_launch_path": True,
        "hidden_truth_absent_from_frontend_input": True,
        "faults_restored_after_each_run": True,
        "runs": records,
        "aggregate": aggregate.model_dump(mode="json"),
    }
    ARTIFACT_PATH.write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(proof, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
