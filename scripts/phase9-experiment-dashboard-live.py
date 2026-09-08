from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any
from uuid import UUID

import httpx
from app.persistence.models import (
    AgentRunRecord,
    EvaluationScoreRecord,
    IncidentRecord,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from evaluationlab.engine import EvaluationEngine
from evaluationlab.models import (
    EvidenceUtility,
    EvaluationCase,
    EvaluationResult,
    ToolCallAssessment,
    ToolCallOutcome,
)
from evaluationlab.persistence import (
    EvaluationRunMetadata,
    ExperimentConfiguration,
    SqlEvaluationStore,
)

DATABASE_URL = os.environ["OPSSENTINEL_DATABASE_URL"]
REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = REPO_ROOT / "phase9-experiment-dashboard-live.json"
BACKEND_LOG_PATH = Path("/tmp/opssentinel-phase9-experiment-dashboard-backend.log")
BACKEND_PORT = 8029
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"

POPULATED_EVALUATION_RUN_ID = UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc9")
EMPTY_EVALUATION_RUN_ID = UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd9")
INCIDENT_IDS = (
    UUID("11111111-1111-4111-8111-111111111119"),
    UUID("22222222-2222-4222-8222-222222222229"),
)
AGENT_RUN_IDS = (
    UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa9"),
    UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb9"),
)


def _tool_call(
    name: str,
    signature: str,
    utility: EvidenceUtility,
) -> ToolCallAssessment:
    return ToolCallAssessment(
        tool_name=name,
        signature=signature,
        outcome=ToolCallOutcome.SUCCEEDED,
        utility=utility,
    )


def _evaluation_cases() -> tuple[EvaluationCase, EvaluationCase]:
    incorrect = EvaluationCase(
        benchmark_version="phase9-dashboard-live-v1",
        scenario_id="phase9-dashboard-live-incorrect",
        expected_primary_root_cause_code="n_plus_one_query",
        predicted_primary_root_cause_code="memory_leak",
        confidence=0.9,
        selected_evidence_tags=[],
        relevant_evidence_tags=["metric:db_query_count"],
        critical_evidence_tags=["metric:db_query_count"],
        tool_calls=[
            _tool_call(
                "query_metrics",
                "query_metrics(service=checkout)",
                EvidenceUtility.IRRELEVANT,
            ),
            _tool_call(
                "query_logs",
                "query_logs(service=checkout)",
                EvidenceUtility.REPEATED,
            ),
        ],
    )
    correct = EvaluationCase(
        benchmark_version="phase9-dashboard-live-v1",
        scenario_id="phase9-dashboard-live-correct",
        expected_primary_root_cause_code="n_plus_one_query",
        predicted_primary_root_cause_code="N_PLUS_ONE",
        confidence=0.8,
        selected_evidence_tags=["metric:db_query_count"],
        relevant_evidence_tags=["metric:db_query_count"],
        critical_evidence_tags=["metric:db_query_count"],
        tool_calls=[
            _tool_call(
                "query_metrics",
                "query_metrics(service=checkout)",
                EvidenceUtility.DISCRIMINATIVE,
            )
        ],
    )
    return incorrect, correct


def _seed_agent_runs(engine: Any) -> None:
    start_time = datetime(2026, 9, 8, 16, 30, tzinfo=UTC)
    with Session(engine) as session:
        for index, (incident_id, agent_run_id) in enumerate(
            zip(INCIDENT_IDS, AGENT_RUN_IDS, strict=True)
        ):
            session.add(
                IncidentRecord(
                    id=str(incident_id),
                    title=f"Phase 9 dashboard live incident {index + 1}",
                    description="Synthetic persistence fixture for the dashboard live cross-check.",
                    severity="P2",
                    service="checkout",
                    start_time=start_time,
                    status="resolved",
                    scenario_id=f"phase9-dashboard-live-{index + 1}",
                )
            )
            session.flush()
            session.add(
                AgentRunRecord(
                    id=str(agent_run_id),
                    incident_id=str(incident_id),
                    architecture_version="phase9-dashboard-live-v1",
                    model="deterministic",
                    step_count=index + 2,
                    tool_call_count=index + 1,
                    token_usage=0,
                    estimated_cost=0.0,
                    status="completed",
                )
            )
        session.commit()


def _seed_evaluations(engine: Any) -> tuple[EvaluationResult, EvaluationResult]:
    evaluation_engine = EvaluationEngine()
    cases = _evaluation_cases()
    results = tuple(evaluation_engine.evaluate(case) for case in cases)

    populated_run = EvaluationRunMetadata(
        id=POPULATED_EVALUATION_RUN_ID,
        dataset_version="phase9-dashboard-live-v1",
        architecture_version="phase9-dashboard-live-v1",
        model="deterministic",
        seed=909,
        configuration={
            "planning_mode": "adaptive",
            "verification_enabled": True,
            "source": "phase9-dashboard-live",
        },
        created_at=datetime(2026, 9, 8, 16, 31, tzinfo=UTC),
    )
    experiment = ExperimentConfiguration(
        prompt_version="phase9-dashboard-live-v1",
        scenario_version="phase9-dashboard-live-v1",
        evaluation_version="phase9-dashboard-live-v1",
        retrieval_settings={"mode": "bounded", "max_depth": 3},
        tool_budget=15,
        recorded_at=datetime(2026, 9, 8, 16, 32, tzinfo=UTC),
    )
    empty_run = EvaluationRunMetadata(
        id=EMPTY_EVALUATION_RUN_ID,
        dataset_version="phase9-dashboard-empty-v1",
        architecture_version="phase9-dashboard-live-v1",
        model="deterministic",
        seed=910,
        configuration={"source": "phase9-dashboard-live-empty"},
        created_at=datetime(2026, 9, 8, 16, 33, tzinfo=UTC),
    )

    store = SqlEvaluationStore(engine)
    store.create_run(populated_run, experiment)
    for result, agent_run_id in zip(results, AGENT_RUN_IDS, strict=True):
        store.save_result(
            populated_run.id,
            result,
            agent_run_id=agent_run_id,
            trace={
                "source": "phase9-dashboard-live",
                "scenario_id": result.scenario_id,
            },
        )
    store.create_run(empty_run)
    return results


def _assert_close(actual: object, expected: float, label: str) -> None:
    if not isinstance(actual, (int, float)) or not math.isclose(
        float(actual),
        expected,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise AssertionError(f"{label}: expected {expected}, got {actual!r}")


def _expected_failure_counts(results: tuple[EvaluationResult, EvaluationResult]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for result in results:
        counter.update(item.category.value for item in result.failure_classifications)
    return dict(sorted(counter.items()))


def _verify_raw_postgres(
    engine: Any,
    results: tuple[EvaluationResult, EvaluationResult],
) -> None:
    expected_metrics = {
        "correctness": [result.correctness for result in results],
        "confidence": [result.confidence for result in results],
        "root_cause.primary_accuracy": [
            result.root_cause.primary_accuracy for result in results
        ],
        "evidence.precision": [result.evidence.precision for result in results],
        "evidence.recall": [result.evidence.recall for result in results],
        "efficiency.total_tool_calls": [
            float(result.efficiency.total_tool_calls) for result in results
        ],
        "safety.unsafe_action_attempts": [
            float(result.safety.unsafe_action_attempts) for result in results
        ],
    }

    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(EvaluationScoreRecord).where(
                    EvaluationScoreRecord.evaluation_run_id
                    == str(POPULATED_EVALUATION_RUN_ID)
                )
            ).all()
        )

    for metric_name, expected_values in expected_metrics.items():
        metric_rows = sorted(
            (row for row in rows if row.metric_name == metric_name),
            key=lambda row: row.scenario_id,
        )
        expected_by_scenario = sorted(
            zip((result.scenario_id for result in results), expected_values, strict=True)
        )
        actual_by_scenario = [(row.scenario_id, row.score) for row in metric_rows]
        if [item[0] for item in actual_by_scenario] != [
            item[0] for item in expected_by_scenario
        ]:
            raise AssertionError(f"raw Postgres scenario mismatch for {metric_name}")
        for (scenario_id, actual), (_, expected) in zip(
            actual_by_scenario,
            expected_by_scenario,
            strict=True,
        ):
            _assert_close(actual, expected, f"raw {metric_name} for {scenario_id}")

    correctness_rows = [row for row in rows if row.metric_name == "correctness"]
    actual_failure_counts: Counter[str] = Counter()
    for row in correctness_rows:
        actual_failure_counts.update(row.failure_categories)
    if dict(sorted(actual_failure_counts.items())) != _expected_failure_counts(results):
        raise AssertionError("raw Postgres failure categories do not match EvaluationLab")


def _verify_evaluation_restart(
    results: tuple[EvaluationResult, EvaluationResult],
) -> None:
    restarted_engine = create_engine(DATABASE_URL)
    restarted_store = SqlEvaluationStore(restarted_engine)
    try:
        run = restarted_store.load_run(POPULATED_EVALUATION_RUN_ID)
        experiment = restarted_store.load_experiment(POPULATED_EVALUATION_RUN_ID)
        if run is None or experiment is None:
            raise AssertionError("EvaluationLab restart readback lost run metadata")
        if experiment.tool_budget != 15:
            raise AssertionError("EvaluationLab restart readback changed tool budget")
        for result, agent_run_id in zip(results, AGENT_RUN_IDS, strict=True):
            loaded = restarted_store.load_result(
                POPULATED_EVALUATION_RUN_ID,
                result.scenario_id,
            )
            if loaded is None:
                raise AssertionError(f"missing restarted result for {result.scenario_id}")
            if loaded.result.model_dump() != result.model_dump():
                raise AssertionError(f"changed restarted result for {result.scenario_id}")
            if loaded.agent_run_id != agent_run_id:
                raise AssertionError(f"changed agent-run link for {result.scenario_id}")
    finally:
        restarted_engine.dispose()


def _start_backend() -> tuple[subprocess.Popen[bytes], Any]:
    log_handle = BACKEND_LOG_PATH.open("ab")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(BACKEND_PORT),
        ],
        cwd=REPO_ROOT / "backend",
        env=os.environ.copy(),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )

    deadline = time.monotonic() + 45
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                log_handle.flush()
                raise RuntimeError("backend exited before becoming healthy")
            try:
                response = httpx.get(f"{BACKEND_URL}/health", timeout=2.0)
                if response.status_code == 200:
                    return process, log_handle
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise TimeoutError("backend did not become healthy")
    except Exception:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log_handle.close()
        raise


def _stop_backend(process: subprocess.Popen[bytes], log_handle: Any) -> None:
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    finally:
        log_handle.close()


def _read_dashboard() -> dict[str, Any]:
    response = httpx.get(f"{BACKEND_URL}/observability/experiments?limit=10", timeout=10.0)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("dashboard response must be a JSON object")
    return payload


def _run_by_id(payload: dict[str, Any], evaluation_run_id: UUID) -> dict[str, Any]:
    runs = payload.get("runs")
    if not isinstance(runs, list):
        raise AssertionError("dashboard runs must be a list")
    for item in runs:
        if isinstance(item, dict) and item.get("evaluation_run_id") == str(evaluation_run_id):
            return item
    raise AssertionError(f"dashboard did not return evaluation run {evaluation_run_id}")


def _verify_dashboard_payload(
    payload: dict[str, Any],
    results: tuple[EvaluationResult, EvaluationResult],
) -> None:
    if payload.get("run_count") != 2:
        raise AssertionError(f"expected two dashboard runs, got {payload.get('run_count')!r}")

    populated = _run_by_id(payload, POPULATED_EVALUATION_RUN_ID)
    empty = _run_by_id(payload, EMPTY_EVALUATION_RUN_ID)

    if populated.get("scenario_count") != 2:
        raise AssertionError("populated run scenario count is not two")
    if populated.get("linked_agent_run_count") != 2:
        raise AssertionError("populated run agent-run link count is not two")
    if populated.get("configuration") != {
        "planning_mode": "adaptive",
        "verification_enabled": True,
        "source": "phase9-dashboard-live",
    }:
        raise AssertionError("dashboard changed persisted experiment configuration")
    if populated.get("retrieval_settings") != {"mode": "bounded", "max_depth": 3}:
        raise AssertionError("dashboard changed persisted retrieval settings")
    if populated.get("tool_budget") != 15:
        raise AssertionError("dashboard changed persisted tool budget")

    metrics = populated.get("metrics")
    if not isinstance(metrics, dict):
        raise AssertionError("populated dashboard metrics must be an object")
    expected = {
        "correctness_mean": fmean(result.correctness for result in results),
        "confidence_mean": fmean(result.confidence for result in results),
        "primary_root_cause_accuracy_mean": fmean(
            result.root_cause.primary_accuracy for result in results
        ),
        "evidence_precision_mean": fmean(result.evidence.precision for result in results),
        "evidence_recall_mean": fmean(result.evidence.recall for result in results),
        "total_tool_calls_mean": fmean(
            float(result.efficiency.total_tool_calls) for result in results
        ),
        "unsafe_action_attempts_total": sum(
            float(result.safety.unsafe_action_attempts) for result in results
        ),
    }
    for metric_name, expected_value in expected.items():
        _assert_close(metrics.get(metric_name), expected_value, metric_name)

    if metrics.get("unsafe_action_attempts_total") is None:
        raise AssertionError("a measured zero safety total was incorrectly rendered as missing")
    if metrics.get("unsafe_action_attempts_total") != 0.0:
        raise AssertionError("expected a truthful zero unsafe-action total")

    if populated.get("failure_categories") != _expected_failure_counts(results):
        raise AssertionError("dashboard failure counts do not match EvaluationLab")

    empty_metrics = empty.get("metrics")
    if not isinstance(empty_metrics, dict):
        raise AssertionError("empty dashboard metrics must be an object")
    if any(value is not None for value in empty_metrics.values()):
        raise AssertionError("missing evaluation metrics were silently replaced with values")
    if empty.get("prompt_version") is not None:
        raise AssertionError("missing experiment metadata was silently fabricated")
    if empty.get("tool_budget") is not None:
        raise AssertionError("missing tool budget was silently fabricated")
    if empty.get("retrieval_settings") != {}:
        raise AssertionError("missing retrieval settings must remain an empty object")


def main() -> None:
    engine = create_engine(DATABASE_URL)
    _seed_agent_runs(engine)
    results = _seed_evaluations(engine)
    _verify_raw_postgres(engine, results)
    engine.dispose()

    _verify_evaluation_restart(results)

    first_process, first_log = _start_backend()
    try:
        first_payload = _read_dashboard()
        _verify_dashboard_payload(first_payload, results)
    finally:
        _stop_backend(first_process, first_log)

    second_process, second_log = _start_backend()
    try:
        second_payload = _read_dashboard()
        _verify_dashboard_payload(second_payload, results)
    finally:
        _stop_backend(second_process, second_log)

    if first_payload != second_payload:
        raise AssertionError("dashboard response changed after backend restart")

    artifact = {
        "head_sha": os.environ.get("GITHUB_SHA", "local"),
        "evaluation_run_id": str(POPULATED_EVALUATION_RUN_ID),
        "empty_run_id": str(EMPTY_EVALUATION_RUN_ID),
        "scenario_count": 2,
        "linked_agent_run_count": 2,
        "raw_postgres_matches_evaluationlab": True,
        "evaluation_restart_readback": True,
        "dashboard_matches_persisted_evaluation": True,
        "missing_metrics_remain_null": True,
        "measured_zero_remains_zero": True,
        "failure_categories_match": True,
        "backend_restart_readback": True,
    }
    ARTIFACT_PATH.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(artifact, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        if BACKEND_LOG_PATH.exists():
            print("\n--- backend diagnostics ---", file=sys.stderr)
            print(BACKEND_LOG_PATH.read_text(encoding="utf-8"), file=sys.stderr)
        raise
