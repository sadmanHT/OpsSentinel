import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

BACKEND = "http://127.0.0.1:8000"
CONTROLLER = "http://127.0.0.1:8100"
SERVICES = {
    "gateway": "http://127.0.0.1:8080",
    "checkout": "http://127.0.0.1:8101",
    "inventory": "http://127.0.0.1:8102",
    "payment": "http://127.0.0.1:8103",
    "worker": "http://127.0.0.1:8104",
}


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


def inject(fault: str, service: str, configuration=None, severity: str = "P1") -> None:
    status, body = request(
        "POST",
        f"{CONTROLLER}/faults/inject",
        {
            "fault": fault,
            "service": service,
            "severity": severity,
            "seed": 42,
            "configuration": configuration or {},
        },
    )
    assert status == 200, body


def restore_all() -> None:
    status, body = request("POST", f"{CONTROLLER}/faults/restore-all", {})
    assert status == 200, body


def hit(method: str, service: str, path: str) -> int:
    return request(method, f"{SERVICES[service]}{path}")[0]


def incident(service: str, title: str, description: str, scenario_id: str) -> dict:
    return {
        "title": title,
        "description": description,
        "severity": "P1",
        "service": service,
        "start_time": datetime.now(UTC).isoformat(),
        "scenario_id": scenario_id,
    }


def assert_grounded_run(body: dict, expected_code: str) -> None:
    assert body["status"] == "completed", body
    assert body["next_node"] == "end", body
    assert body["diagnosis_code"] == expected_code, body
    diagnosis = body["final_diagnosis"]
    assert diagnosis is not None, body
    assert diagnosis["confidence"] >= 0.9, body
    assert diagnosis["evidence_ids"], body

    report = body["report"]
    assert report is not None, body
    assert report["status"] == "completed", body
    assert report["root_cause_code"] == expected_code, body
    assert report["claims"], body
    diagnosis_ids = set(diagnosis["evidence_ids"])
    for claim in report["claims"]:
        assert claim["evidence_ids"], claim
        assert set(claim["evidence_ids"]) <= diagnosis_ids, claim

    proposed = report["proposed_action"]
    assert proposed is not None, body
    assert proposed["risk_level"] == "R2", proposed
    assert set(proposed["evidence_ids"]) <= diagnosis_ids, proposed
    assert report["verification"]["status"] == "not_run", report

    history = body["tool_history"]
    assert history, body
    assert body["budget"]["tool_calls_used"] == len(history), body
    assert body["budget"]["tool_calls_used"] <= body["budget"]["max_tool_calls"], body
    assert all("fault" not in item["tool_name"] for item in history), history
    assert all(item["risk_level"] in {"R0", "R1"} for item in history), history

    status, persisted = request("GET", f"{BACKEND}/agent/runs/{body['run_id']}")
    assert status == 200, persisted
    assert persisted["diagnosis_code"] == expected_code, persisted
    assert persisted["final_diagnosis"]["evidence_ids"] == diagnosis["evidence_ids"], persisted


def start_run(payload: dict, *, pause_after: str | None = None) -> dict:
    request_payload = {"incident": payload}
    if pause_after is not None:
        request_payload["pause_after"] = pause_after
    status, body = request("POST", f"{BACKEND}/agent/runs", request_payload)
    assert status == 201, body
    return body


def test_n_plus_one_agent_with_pause_resume() -> None:
    restore_all()
    assert hit("GET", "checkout", "/orders") == 200
    inject("n_plus_one", "checkout", {"delay_per_query_ms": 3})
    assert hit("GET", "checkout", "/orders") == 200

    started = start_run(
        incident(
            "checkout",
            "Checkout latency regression after deployment",
            "Users report a severe checkout slowdown immediately after the latest deployment.",
            "phase4-n-plus-one",
        ),
        pause_after="plan",
    )
    assert started["status"] == "paused", started
    assert started["next_node"] == "select_tool", started
    assert started["plan"] is not None, started
    assert not started["tool_history"], started

    status, resumed = request("POST", f"{BACKEND}/agent/runs/{started['run_id']}/resume", {})
    assert status == 200, resumed
    assert_grounded_run(resumed, "n_plus_one_query")
    assert [item["tool_name"] for item in resumed["tool_history"]] == [
        "query_metrics",
        "inspect_deployment",
        "inspect_git_diff",
        "query_metrics",
        "search_logs",
    ], resumed


def test_connection_leak_agent() -> None:
    restore_all()
    inject("connection_leak", "inventory", {"capacity": 4}, severity="P3")
    statuses = [hit("GET", "inventory", "/inventory/SKU-RED") for _ in range(4)]
    assert statuses[-1] == 503, statuses

    body = start_run(
        incident(
            "inventory",
            "Inventory requests are failing",
            "Inventory becomes unavailable under ordinary request traffic.",
            "phase4-connection-leak",
        )
    )
    assert_grounded_run(body, "database_connection_leak")


def test_disk_exhaustion_agent() -> None:
    restore_all()
    inject("disk_exhaustion", "worker", {"max_files": 4}, severity="P3")
    statuses = [hit("POST", "worker", "/work") for _ in range(4)]
    assert 507 in statuses, statuses

    body = start_run(
        incident(
            "worker",
            "Worker jobs fail with storage errors",
            "Worker processing fails after sustained output generation.",
            "phase4-disk-exhaustion",
        )
    )
    assert_grounded_run(body, "disk_exhaustion")


def test_broken_payment_configuration_agent() -> None:
    restore_all()
    inject("broken_config", "payment")
    assert hit("POST", "payment", "/charge") == 401
    assert hit("GET", "gateway", "/checkout") == 502

    body = start_run(
        incident(
            "payment",
            "Payment authentication failures",
            "Checkout fails because the payment dependency rejects requests.",
            "phase4-broken-payment-config",
        )
    )
    assert_grounded_run(body, "broken_payment_configuration")


def test_memory_leak_agent() -> None:
    restore_all()
    inject(
        "memory_leak",
        "worker",
        {"chunk_bytes": 262_144, "max_bytes": 1_048_576},
        severity="P3",
    )
    assert hit("POST", "worker", "/work") == 200
    assert hit("POST", "worker", "/work") == 200
    assert hit("POST", "worker", "/work") == 200
    assert hit("POST", "worker", "/work") == 503

    body = start_run(
        incident(
            "worker",
            "Worker restarts after memory growth",
            "Repeated worker jobs show resource growth followed by a service failure.",
            "phase4-memory-leak",
        )
    )
    assert_grounded_run(body, "memory_leak")


if __name__ == "__main__":
    for _ in range(45):
        try:
            if request("GET", f"{BACKEND}/agent/health")[0] == 200:
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        raise AssertionError("Phase 4 agent API did not become healthy")

    test_n_plus_one_agent_with_pause_resume()
    test_connection_leak_agent()
    test_disk_exhaustion_agent()
    test_broken_payment_configuration_agent()
    test_memory_leak_agent()
    restore_all()
    print("Phase 4 autonomous agent smoke validation passed for all five incidents")
