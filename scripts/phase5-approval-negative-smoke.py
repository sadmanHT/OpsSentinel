import json
import urllib.error
import urllib.request
from datetime import UTC, datetime

BACKEND = "http://127.0.0.1:8000"
CONTROLLER = "http://127.0.0.1:8100"
CHECKOUT = "http://127.0.0.1:8101"
UNKNOWN_RUN_ID = "00000000-0000-0000-0000-000000000001"


def request(method: str, url: str, payload=None):
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


def restore_all() -> None:
    status, body = request("POST", f"{CONTROLLER}/faults/restore-all", {})
    assert status == 200, body


def inject_n_plus_one() -> None:
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
    status, body = request("GET", f"{CHECKOUT}/orders")
    assert status == 200, body


def n_plus_one_is_present() -> bool:
    status, faults = request("GET", f"{CONTROLLER}/faults")
    assert status == 200, faults
    return any(
        item["fault"] == "n_plus_one" and item["service"] == "checkout"
        for item in faults
    )


def start_operational_run() -> dict:
    status, body = request(
        "POST",
        f"{BACKEND}/agent/runs",
        {
            "incident": {
                "title": "Checkout latency regression after deployment",
                "description": (
                    "Users report a severe checkout slowdown immediately after the "
                    "latest deployment."
                ),
                "severity": "P1",
                "service": "checkout",
                "start_time": datetime.now(UTC).isoformat(),
                "scenario_id": "phase5-negative-approval-api",
            },
            "operational_mode": True,
        },
    )
    assert status == 201, body
    assert body["status"] == "paused", body
    assert body["operation_stage"] == "wait_approval", body
    assert body["approval"]["decision"] == "pending", body
    assert body["proposed_action"]["risk_level"] == "R2", body
    assert body["proposed_action"]["tool"] == "rollback_sandbox_deployment", body
    return body


def assert_still_pending(run_id: str, approval_id: str) -> None:
    status, body = request("GET", f"{BACKEND}/agent/runs/{run_id}")
    assert status == 200, body
    assert body["status"] == "paused", body
    assert body["operation_stage"] == "wait_approval", body
    assert body["approval"]["id"] == approval_id, body
    assert body["approval"]["decision"] == "pending", body
    assert body["verification"]["status"] == "not_run", body
    assert not any(
        call["tool_name"] == "rollback_sandbox_deployment"
        for call in body["tool_history"]
    ), body
    assert n_plus_one_is_present(), body


def assert_invalid_requests_do_not_mutate(run_id: str, approval_id: str) -> None:
    status, body = request(
        "POST",
        f"{BACKEND}/agent/runs/{run_id}/approval",
        {"decision": "pending", "actor": "phase5-negative-smoke"},
    )
    assert status == 422, body
    assert_still_pending(run_id, approval_id)

    status, body = request(
        "POST",
        f"{BACKEND}/agent/runs/{run_id}/approval",
        {"decision": "approved", "actor": ""},
    )
    assert status == 422, body
    assert_still_pending(run_id, approval_id)

    status, body = request(
        "POST",
        f"{BACKEND}/agent/runs/{UNKNOWN_RUN_ID}/approval",
        {"decision": "approved", "actor": "phase5-negative-smoke"},
    )
    assert status == 404, body
    assert_still_pending(run_id, approval_id)


def reject_then_require_duplicate_conflict(run_id: str) -> None:
    status, body = request(
        "POST",
        f"{BACKEND}/agent/runs/{run_id}/approval",
        {"decision": "rejected", "actor": "phase5-negative-smoke"},
    )
    assert status == 200, body
    assert body["status"] == "completed", body
    assert body["operation_stage"] == "complete", body
    assert body["approval"]["decision"] == "rejected", body
    assert body["verification"]["status"] == "not_run", body
    assert not any(
        call["tool_name"] == "rollback_sandbox_deployment"
        for call in body["tool_history"]
    ), body
    assert n_plus_one_is_present(), body

    status, duplicate = request(
        "POST",
        f"{BACKEND}/agent/runs/{run_id}/approval",
        {"decision": "approved", "actor": "phase5-duplicate-attempt"},
    )
    assert status == 409, duplicate

    status, persisted = request("GET", f"{BACKEND}/agent/runs/{run_id}")
    assert status == 200, persisted
    assert persisted["approval"]["decision"] == "rejected", persisted
    assert persisted["approval"]["decided_by"] == "phase5-negative-smoke", persisted
    assert persisted["verification"]["status"] == "not_run", persisted
    assert not any(
        call["tool_name"] == "rollback_sandbox_deployment"
        for call in persisted["tool_history"]
    ), persisted
    assert n_plus_one_is_present(), persisted


if __name__ == "__main__":
    restore_all()
    inject_n_plus_one()
    assert n_plus_one_is_present()

    paused = start_operational_run()
    run_id = paused["run_id"]
    approval_id = paused["approval"]["id"]
    assert_invalid_requests_do_not_mutate(run_id, approval_id)
    reject_then_require_duplicate_conflict(run_id)

    restore_all()
    assert not n_plus_one_is_present()
    print(
        "Phase 5 approval negative smoke passed: invalid, unknown, and duplicate "
        "decisions were rejected without executing or mutating the pending R2 action"
    )
