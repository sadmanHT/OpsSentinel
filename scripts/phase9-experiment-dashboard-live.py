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
from typing import Any, BinaryIO
from uuid import UUID

import httpx
from app.persistence.models import AgentRunRecord, EvaluationScoreRecord, IncidentRecord
from evaluationlab.engine import EvaluationEngine
from evaluationlab.models import (
    EvaluationCase,
    EvaluationResult,
    EvidenceUtility,
    ToolCallAssessment,
    ToolCallOutcome,
)
from evaluationlab.persistence import (
    EvaluationRunMetadata,
    ExperimentConfiguration,
    SqlEvaluationStore,
)
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

DATABASE_URL = os.environ["OPSSENTINEL_DATABASE_URL"]
REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = REPO_ROOT / "phase9-experiment-dashboard-live.json"
BACKEND_LOG_PATH = Path("/tmp/opssentinel-phase9-experiment-dashboard-backend.log")
BACKEND_PORT = 8029
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"

POPULATED_RUN_ID = UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc9")
EMPTY_RUN_ID = UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd9")
INCIDENT_IDS = (
    UUID("11111111-1111-4111-8111-111111111119"),
    UUID("22222222-2222-4222-8222-222222222229"),
)
AGENT_RUN_IDS = (
    UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa9"),
    UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb9"),
)


def _tool(name: str, utility: EvidenceUtility) -> ToolCallAssessment:
    return ToolCallAssessment(
        tool_name=name,
        signature=f"{name}(service=checkout)",
        outcome=ToolCallOutcome.SUCCEEDED,
        utility=utility,
    )


def _cases() -> tuple[EvaluationCase, EvaluationCase]:
    common = {
        "benchmark_version": "phase9-dashboard-live-v1",
        "expected_primary_root_cause_code": "n_plus_one_query",
        "relevant_evidence_tags": ["metric:db_query_count"],
        "critical_evidence_tags": ["metric:db_query_count"],
    }
    return (
        EvaluationCase(
            **common,
            scenario_id="phase9-dashboard-live-incorrect",
            predicted_primary_root_cause_code="memory_leak",
            confidence=0.9,
            selected_evidence_tags=[],
            tool_calls=[
                _tool("query_metrics", EvidenceUtility.IRRELEVANT),
                _tool("query_logs", EvidenceUtility.REPEATED),
            ],
        ),
        EvaluationCase(
            **common,
            scenario_id="phase9-dashboard-live-correct",
            predicted_primary_root_cause_code="N_PLUS_ONE",
            confidence=0.8,
            selected_evidence_tags=["metric:db_query_count"],
            tool_calls=[_tool("query_metrics", EvidenceUtility.DISCRIMINATIVE)],
        ),
    )


def _seed_agent_runs(engine: Engine) -> None:
    with Session(engine) as session:
        for index, (incident_id, agent_run_id) in enumerate(
            zip(INCIDENT_IDS, AGENT_RUN_IDS, strict=True)
        ):
            session.add(
                IncidentRecord(
                    id=str(incident_id),
                    title=f"Phase 9 dashboard live incident {index + 1}",
                    description="Synthetic fixture for the dashboard persistence cross-check.",
                    severity="P2",
                    service="checkout",
                    start_time=datetime(2026, 9, 8, 16, 30, tzinfo=UTC),
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


def _seed_evaluations(engine: Engine) -> tuple[EvaluationResult, EvaluationResult]:
    evaluator = EvaluationEngine()
    results = tuple(evaluator.evaluate(case) for case in _cases())
    store = SqlEvaluationStore(engine)
    store.create_run(
        EvaluationRunMetadata(
            id=POPULATED_RUN_ID,
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
        ),
        ExperimentConfiguration(
            prompt_version="phase9-dashboard-live-v1",
            scenario_version="phase9-dashboard-live-v1",
            evaluation_version="phase9-dashboard-live-v1",
            retrieval_settings={"mode": "bounded", "max_depth": 3},
            tool_budget=15,
            recorded_at=datetime(2026, 9, 8, 16, 32, tzinfo=UTC),
        ),
    )
    for result, agent_run_id in zip(results, AGENT_RUN_IDS, strict=True):
        store.save_result(
            POPULATED_RUN_ID,
            result,
            agent_run_id=agent_run_id,
            trace={"source": "phase9-dashboard-live", "scenario_id": result.scenario_id},
        )
    store.create_run(
        EvaluationRunMetadata(
            id=EMPTY_RUN_ID,
            dataset_version="phase9-dashboard-empty-v1",
            architecture_version="phase9-dashboard-live-v1",
            model="deterministic",
            seed=910,
            configuration={"source": "phase9-dashboard-live-empty"},
            created_at=datetime(2026, 9, 8, 16, 33, tzinfo=UTC),
        )
    )
    return results


def _close(actual: object, expected: float, label: str) -> None:
    if not isinstance(actual, (int, float)):
        raise TypeError(f"{label} must be numeric, got {type(actual).__name__}")
    if not math.isclose(float(actual), expected, rel_tol=1e-12, abs_tol=1e-12):
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def _failure_counts(results: tuple[EvaluationResult, EvaluationResult]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for result in results:
        counts.update(item.category.value for item in result.failure_classifications)
    return dict(sorted(counts.items()))


def _verify_postgres(
    engine: Engine,
    results: tuple[EvaluationResult, EvaluationResult],
) -> None:
    expected = {
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
                    EvaluationScoreRecord.evaluation_run_id == str(POPULATED_RUN_ID)
                )
            ).all()
        )

    for metric_name, values in expected.items():
        actual = sorted(
            (row.scenario_id, row.score)
            for row in rows
            if row.metric_name == metric_name
        )
        wanted = sorted(
            zip((result.scenario_id for result in results), values, strict=True)
        )
        if [scenario for scenario, _ in actual] != [scenario for scenario, _ in wanted]:
            raise AssertionError(f"raw Postgres scenario mismatch for {metric_name}")
        for (scenario, score), (_, wanted_score) in zip(actual, wanted, strict=True):
            _close(score, wanted_score, f"raw {metric_name} for {scenario}")

    correctness = [row for row in rows if row.metric_name == "correctness"]
    counts: Counter[str] = Counter()
    for row in correctness:
        counts.update(row.failure_categories)
    if dict(sorted(counts.items())) != _failure_counts(results):
        raise AssertionError("raw Postgres failure categories differ from EvaluationLab")


def _verify_evaluator_restart(results: tuple[EvaluationResult, EvaluationResult]) -> None:
    engine = create_engine(DATABASE_URL)
    store = SqlEvaluationStore(engine)
    try:
        run = store.load_run(POPULATED_RUN_ID)
        experiment = store.load_experiment(POPULATED_RUN_ID)
        if run is None or experiment is None:
            raise AssertionError("EvaluationLab restart readback lost run metadata")
        if experiment.tool_budget != 15:
            raise AssertionError("EvaluationLab restart readback changed tool budget")
        for result, agent_run_id in zip(results, AGENT_RUN_IDS, strict=True):
            loaded = store.load_result(POPULATED_RUN_ID, result.scenario_id)
            if loaded is None:
                raise AssertionError(f"missing restarted result for {result.scenario_id}")
            if loaded.result.model_dump() != result.model_dump():
                raise AssertionError(f"changed restarted result for {result.scenario_id}")
            if loaded.agent_run_id != agent_run_id:
                raise AssertionError(f"changed agent-run link for {result.scenario_id}")
    finally:
        engine.dispose()


def _stop_backend(process: subprocess.Popen[bytes], log: BinaryIO) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    log.close()


def _start_backend() -> tuple[subprocess.Popen[bytes], BinaryIO]:
    log = BACKEND_LOG_PATH.open("ab")
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
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("backend exited before becoming healthy")
            try:
                if httpx.get(f"{BACKEND_URL}/health", timeout=2).status_code == 200:
                    return process, log
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise TimeoutError("backend did not become healthy")
    except Exception:
        _stop_backend(process, log)
        raise


def _read_dashboard() -> dict[str, Any]:
    response = httpx.get(f"{BACKEND_URL}/observability/experiments?limit=10", timeout=10)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError("dashboard response must be a JSON object")
    return payload


def _run(payload: dict[str, Any], run_id: UUID) -> dict[str, Any]:
    runs = payload.get("runs")
    if not isinstance(runs, list):
        raise TypeError("dashboard runs must be a list")
    for item in runs:
        if isinstance(item, dict) and item.get("evaluation_run_id") == str(run_id):
            return item
    raise AssertionError(f"dashboard did not return evaluation run {run_id}")


def _verify_dashboard(
    payload: dict[str, Any],
    results: tuple[EvaluationResult, EvaluationResult],
) -> None:
    if payload.get("run_count") != 2:
        raise AssertionError(f"expected two dashboard runs, got {payload.get('run_count')!r}")
    populated = _run(payload, POPULATED_RUN_ID)
    empty = _run(payload, EMPTY_RUN_ID)

    if populated.get("scenario_count") != 2 or populated.get("linked_agent_run_count") != 2:
        raise AssertionError("dashboard changed persisted scenario or agent-run counts")
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
    if populated.get("failure_categories") != _failure_counts(results):
        raise AssertionError("dashboard failure counts differ from EvaluationLab")

    metrics = populated.get("metrics")
    if not isinstance(metrics, dict):
        raise TypeError("populated dashboard metrics must be an object")
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
        "unsafe_action_attempts_total": 0.0,
    }
    for name, value in expected.items():
        _close(metrics.get(name), value, name)
    if metrics.get("unsafe_action_attempts_total") != 0.0:
        raise AssertionError("measured zero unsafe-action total was not preserved")

    empty_metrics = empty.get("metrics")
    if not isinstance(empty_metrics, dict):
        raise TypeError("empty dashboard metrics must be an object")
    if any(value is not None for value in empty_metrics.values()):
        raise AssertionError("missing evaluation metrics were replaced with values")
    if empty.get("prompt_version") is not None or empty.get("tool_budget") is not None:
        raise AssertionError("missing experiment metadata was fabricated")
    if empty.get("retrieval_settings") != {}:
        raise AssertionError("missing retrieval settings must remain empty")


def _backend_read(results: tuple[EvaluationResult, EvaluationResult]) -> dict[str, Any]:
    process, log = _start_backend()
    try:
        payload = _read_dashboard()
        _verify_dashboard(payload, results)
        return payload
    finally:
        _stop_backend(process, log)


def main() -> None:
    engine = create_engine(DATABASE_URL)
    try:
        _seed_agent_runs(engine)
        results = _seed_evaluations(engine)
        _verify_postgres(engine, results)
    finally:
        engine.dispose()

    _verify_evaluator_restart(results)
    first = _backend_read(results)
    second = _backend_read(results)
    if first != second:
        raise AssertionError("dashboard response changed after backend restart")

    proof = {
        "head_sha": os.environ.get("GITHUB_SHA", "local"),
        "evaluation_run_id": str(POPULATED_RUN_ID),
        "empty_run_id": str(EMPTY_RUN_ID),
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
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(proof, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        if BACKEND_LOG_PATH.exists():
            print("\n--- backend diagnostics ---", file=sys.stderr)
            print(BACKEND_LOG_PATH.read_text(encoding="utf-8"), file=sys.stderr)
        raise
