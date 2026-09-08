from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND = "http://127.0.0.1:8000"
CONTROLLER = "http://127.0.0.1:8100"
CHECKOUT = "http://127.0.0.1:8101"
OUTPUT = Path("phase9-latency-live.json")


def request(method: str, url: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        return exc.code, json.loads(body) if body else None


def wait_for_backend() -> None:
    for _ in range(60):
        try:
            status, body = request("GET", f"{BACKEND}/agent/health")
            if (
                status == 200
                and body["architecture"] == "phase5-safe-operational-agent-v1"
                and body["legal_tool_count"] == 16
            ):
                return
        except (urllib.error.URLError, TimeoutError, ConnectionResetError):
            time.sleep(1)
            continue
        time.sleep(1)
    raise AssertionError("Phase 9 latency backend did not become healthy")


def restore_all() -> None:
    status, body = request("POST", f"{CONTROLLER}/faults/restore-all", {})
    assert status == 200, body


def faults() -> list[dict[str, Any]]:
    status, body = request("GET", f"{CONTROLLER}/faults")
    assert status == 200, body
    assert isinstance(body, list), body
    return body


def prepare_n_plus_one() -> None:
    restore_all()
    status, body = request(
        "POST",
        f"{CONTROLLER}/faults/inject",
        {
            "fault": "n_plus_one",
            "service": "checkout",
            "severity": "P1",
            "seed": 42,
            "configuration": {"delay_per_query_ms": 3},
        },
    )
    assert status == 200, body
    assert any(
        item["fault"] == "n_plus_one" and item["service"] == "checkout"
        for item in faults()
    )
    status, body = request("GET", f"{CHECKOUT}/orders")
    assert status == 200, body


def incident(label: str) -> dict[str, Any]:
    return {
        "title": "Checkout latency regression after deployment",
        "description": (
            "Users report a severe checkout slowdown immediately after the latest deployment."
        ),
        "severity": "P1",
        "service": "checkout",
        "start_time": datetime.now(UTC).isoformat(),
        "scenario_id": f"phase9-latency-{label}",
    }


def run_decision(label: str, decision: str) -> dict[str, Any]:
    prepare_n_plus_one()
    status, paused = request(
        "POST",
        f"{BACKEND}/agent/runs",
        {"incident": incident(label), "operational_mode": True},
    )
    assert status == 201, paused
    assert paused["status"] == "paused", paused
    assert paused["operation_stage"] == "wait_approval", paused
    assert paused["diagnosis_code"] == "n_plus_one_query", paused
    assert paused["approval"]["decision"] == "pending", paused
    assert paused["verification"]["status"] == "not_run", paused

    status, completed = request(
        "POST",
        f"{BACKEND}/agent/runs/{paused['run_id']}/approval",
        {"decision": decision, "actor": "phase9-latency-ci"},
    )
    assert status == 200, completed
    assert completed["status"] == "completed", completed
    assert completed["operation_stage"] == "complete", completed
    assert completed["approval"]["decision"] == decision, completed
    expected_verification = "passed" if decision == "approved" else "not_run"
    assert completed["verification"]["status"] == expected_verification, completed
    return completed


def cost_summary(run_id: str) -> dict[str, Any]:
    status, body = request("GET", f"{BACKEND}/observability/runs/{run_id}/cost")
    assert status == 200, body
    assert isinstance(body, dict), body
    return body


def latency_summary() -> dict[str, Any]:
    status, body = request("GET", f"{BACKEND}/observability/latency")
    assert status == 200, body
    assert isinstance(body, dict), body
    return body


def restart_backend() -> None:
    subprocess.run(["docker", "compose", "restart", "backend"], check=True)
    wait_for_backend()


def main() -> None:
    wait_for_backend()
    restore_all()

    passed = run_decision("passed", "approved")
    assert faults() == []
    passed_cost_before = cost_summary(passed["run_id"])
    assert passed_cost_before["time_to_diagnosis_ms"] is not None
    assert passed_cost_before["time_to_verified_resolution_ms"] is not None
    assert (
        passed_cost_before["time_to_verified_resolution_ms"]
        >= passed_cost_before["time_to_diagnosis_ms"]
    )

    rejected = run_decision("rejected", "rejected")
    rejected_cost_before = cost_summary(rejected["run_id"])
    assert rejected_cost_before["time_to_diagnosis_ms"] is not None
    assert rejected_cost_before["time_to_verified_resolution_ms"] is None
    restore_all()
    assert faults() == []

    aggregate_before = latency_summary()
    assert aggregate_before["run_count"] == 2, aggregate_before
    assert aggregate_before["time_to_first_investigation_step"]["count"] == 2
    assert aggregate_before["time_to_diagnosis"]["count"] == 2
    assert aggregate_before["time_to_verified_resolution"]["count"] == 1
    assert aggregate_before["time_to_verified_resolution"]["p50_ms"] is not None
    assert aggregate_before["time_to_verified_resolution"]["p95_ms"] is not None

    restart_backend()
    passed_cost_after = cost_summary(passed["run_id"])
    rejected_cost_after = cost_summary(rejected["run_id"])
    aggregate_after = latency_summary()

    assert passed_cost_after == passed_cost_before
    assert rejected_cost_after == rejected_cost_before
    assert aggregate_after == aggregate_before
    assert faults() == []

    payload = {
        "passed_run_id": passed["run_id"],
        "rejected_run_id": rejected["run_id"],
        "passed_cost": passed_cost_before,
        "rejected_cost": rejected_cost_before,
        "aggregate_latency": aggregate_before,
        "restart_persistence_verified": True,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
