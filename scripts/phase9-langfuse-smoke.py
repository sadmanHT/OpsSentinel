from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from benchmarklab.models import Difficulty, ScenarioKind, ScenarioSpec

from benchmarklab import BenchmarkRunner, load_catalog
from evaluationlab import EvaluationEngine, adapt_benchmark_artifact

LANGFUSE = "http://127.0.0.1:3002"
PUBLIC_KEY = "pk-lf-opssentinel-phase9-ci"
SECRET_KEY = "sk-lf-opssentinel-phase9-ci"
OUTPUT = Path("phase9-langfuse-live.json")
TERMINAL_RESEARCH_STATUSES = {"completed", "budget_exhausted"}
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.langfuse.yml"]


def _authorization() -> str:
    encoded = base64.b64encode(f"{PUBLIC_KEY}:{SECRET_KEY}".encode()).decode("ascii")
    return f"Basic {encoded}"


def request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    authenticated: bool = True,
) -> tuple[int, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{LANGFUSE}{path}", data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if authenticated:
        req.add_header("Authorization", _authorization())
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            parsed: Any = json.loads(body) if body else None
        except json.JSONDecodeError:
            parsed = body
        return exc.code, parsed


def wait_for_langfuse() -> None:
    for _ in range(120):
        try:
            status, body = request("GET", "/api/public/health", authenticated=False)
            if status == 200 and body["status"] == "OK":
                return
        except (urllib.error.URLError, TimeoutError, ConnectionResetError):
            pass
        time.sleep(1)
    raise AssertionError("self-hosted Langfuse did not become healthy")


def _scenario(catalog_scenarios: list[ScenarioSpec]) -> ScenarioSpec:
    candidates = [
        scenario
        for scenario in catalog_scenarios
        if scenario.difficulty == Difficulty.EASY
        and scenario.kind != ScenarioKind.COUNTERFACTUAL
        and scenario.split.value == "dev"
    ]
    if not candidates:
        raise AssertionError("no eligible easy dev scenario for Langfuse smoke")
    return min(candidates, key=lambda scenario: scenario.scenario_id)


def _recent_observations(started_at: datetime) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "fields": "core,basic,metadata,model,usage,metrics,trace_context",
            "fromStartTime": (started_at - timedelta(seconds=30)).isoformat(),
            "toStartTime": (datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
            "limit": 1000,
        }
    )
    status, body = request("GET", f"/api/public/v2/observations?{params}")
    assert status == 200, body
    assert isinstance(body, dict) and isinstance(body.get("data"), list), body
    return body["data"]


def wait_for_trace(run_id: str, started_at: datetime) -> tuple[str, list[dict[str, Any]]]:
    for _ in range(90):
        observations = _recent_observations(started_at)
        roots = [
            item
            for item in observations
            if item.get("type") == "AGENT"
            and isinstance(item.get("metadata"), dict)
            and item["metadata"].get("runId") == run_id
        ]
        if len(roots) == 1:
            trace_id = str(roots[0]["traceId"])
            params = urllib.parse.urlencode(
                {
                    "fields": "core,basic,metadata,model,usage,metrics,trace_context",
                    "traceId": trace_id,
                    "limit": 1000,
                }
            )
            status, body = request("GET", f"/api/public/v2/observations?{params}")
            assert status == 200, body
            trace_rows = body["data"]
            types = {str(item["type"]) for item in trace_rows}
            if {"AGENT", "CHAIN", "TOOL", "GENERATION"}.issubset(types):
                return trace_id, trace_rows
        time.sleep(1)
    raise AssertionError(f"Langfuse trace for agent run {run_id} did not become queryable")


def publish_score(trace_id: str, exact_match: bool) -> str:
    score_id = str(uuid5(NAMESPACE_URL, f"opssentinel:phase9-langfuse:{trace_id}:rca-exact-match"))
    status, body = request(
        "POST",
        "/api/public/scores",
        {
            "id": score_id,
            "traceId": trace_id,
            "name": "opssentinel.rca_exact_match",
            "value": float(exact_match),
            "dataType": "NUMERIC",
            "comment": "Post-hoc EvaluationLab exact-match score.",
        },
    )
    assert status in {200, 201}, body
    return score_id


def wait_for_score(trace_id: str, score_id: str, expected: float) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {
            "id": score_id,
            "traceId": trace_id,
            "name": "opssentinel.rca_exact_match",
            "fields": "details,subject",
            "limit": 10,
        }
    )
    for _ in range(60):
        status, body = request("GET", f"/api/public/v3/scores?{params}")
        assert status == 200, body
        rows = body.get("data", [])
        if len(rows) == 1:
            score = rows[0]
            assert score["id"] == score_id, score
            assert float(score["value"]) == expected, score
            subject = score["subject"]
            assert subject["kind"] == "trace", subject
            assert subject["id"] == trace_id, subject
            return score
        time.sleep(1)
    raise AssertionError("Langfuse evaluation score did not become queryable")


def assert_trace_integrity(
    observations: list[dict[str, Any]],
    *,
    run_id: str,
) -> dict[str, Any]:
    types = [str(item["type"]) for item in observations]
    type_counts = {kind: types.count(kind) for kind in sorted(set(types))}
    assert type_counts.get("AGENT", 0) == 1, type_counts
    assert type_counts.get("CHAIN", 0) > 0, type_counts
    assert type_counts.get("TOOL", 0) > 0, type_counts
    assert type_counts.get("GENERATION", 0) > 0, type_counts

    generations = [item for item in observations if item["type"] == "GENERATION"]
    assert all(item.get("model") for item in generations), generations
    assert all(item.get("latency") is not None for item in generations), generations

    total_input_tokens = sum(int(item.get("inputUsage") or 0) for item in generations)
    total_output_tokens = sum(int(item.get("outputUsage") or 0) for item in generations)
    total_cost = sum(float(item.get("totalCost") or 0.0) for item in generations)

    roots = [item for item in observations if item["type"] == "AGENT"]
    root_metadata = roots[0]["metadata"]
    assert root_metadata["runId"] == run_id
    assert root_metadata["agentArchitecture"] == "explicit_planner"
    assert root_metadata["evidenceMode"] == "passive_only"
    assert root_metadata["toolOrder"] == "free"

    serialized_metadata = json.dumps(
        [item.get("metadata") for item in observations],
        sort_keys=True,
    ).lower()
    for forbidden in (
        "ground_truth",
        "expected_primary_root_cause",
        "expected_root",
        "fault_state",
        "causal_timeline",
    ):
        assert forbidden not in serialized_metadata, forbidden

    return {
        "observation_type_counts": type_counts,
        "generation_count": len(generations),
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "estimated_cost": total_cost,
        "runtime_metadata": {
            "agentArchitecture": root_metadata["agentArchitecture"],
            "evidenceMode": root_metadata["evidenceMode"],
            "toolOrder": root_metadata["toolOrder"],
            "temporalReasoning": root_metadata["temporalReasoning"],
        },
    }


def restart_langfuse() -> None:
    subprocess.run(
        [*COMPOSE, "restart", "langfuse-worker", "langfuse-web"],
        check=True,
    )
    wait_for_langfuse()


async def main() -> None:
    wait_for_langfuse()
    started_at = datetime.now(UTC)
    catalog = load_catalog()
    scenario = _scenario(catalog.scenarios)
    runner = BenchmarkRunner()
    try:
        artifact = await runner.run(
            scenario,
            benchmark_version=catalog.benchmark_version,
        )
    finally:
        await runner.restore()

    assert artifact.agent_run_id is not None
    assert artifact.agent_status in TERMINAL_RESEARCH_STATUSES, artifact.agent_status
    case = adapt_benchmark_artifact(
        scenario.model_dump(mode="json"),
        artifact.model_dump(mode="json"),
    )
    result = EvaluationEngine().evaluate(case)
    assert result.safety.unsafe_action_attempts == 0
    assert result.safety.incorrectly_classified_risk == 0

    run_id = str(artifact.agent_run_id)
    trace_id, observations = wait_for_trace(run_id, started_at)
    trace_summary = assert_trace_integrity(observations, run_id=run_id)

    score_value = float(result.root_cause.exact_match)
    score_id = publish_score(trace_id, result.root_cause.exact_match)
    score_before = wait_for_score(trace_id, score_id, score_value)

    restart_langfuse()
    trace_id_after, observations_after = wait_for_trace(run_id, started_at)
    assert trace_id_after == trace_id
    assert_trace_integrity(observations_after, run_id=run_id)
    score_after = wait_for_score(trace_id, score_id, score_value)
    assert score_after["id"] == score_before["id"]

    payload = {
        "trace_id": trace_id,
        "agent_run_id": run_id,
        "trace": trace_summary,
        "evaluation_score": {
            "name": "opssentinel.rca_exact_match",
            "value": score_value,
            "score_id": score_id,
            "source": "post-hoc EvaluationLab",
        },
        "restart_persistence_verified": True,
        "privacy_checks": {
            "hidden_ground_truth_absent_from_runtime_metadata": True,
            "fault_state_absent_from_runtime_metadata": True,
        },
        "performance_is_measurement_not_ci_threshold": True,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
