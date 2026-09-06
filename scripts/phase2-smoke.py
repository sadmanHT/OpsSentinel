import json
import time
import urllib.error
import urllib.request

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
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        return exc.code, json.loads(body) if body else None


def wait_healthy() -> None:
    for name, base in {"controller": CONTROLLER, **SERVICES}.items():
        for _ in range(45):
            try:
                status, _ = request("GET", f"{base}/health")
                if status == 200:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise AssertionError(f"{name} did not become healthy")


def restore_all() -> None:
    status, _ = request("POST", f"{CONTROLLER}/faults/restore-all", {})
    assert status == 200


def inject(
    fault: str,
    service: str,
    configuration=None,
    *,
    severity: str = "P1",
    seed: int = 42,
):
    status, body = request(
        "POST",
        f"{CONTROLLER}/faults/inject",
        {
            "fault": fault,
            "service": service,
            "severity": severity,
            "seed": seed,
            "configuration": configuration or {},
        },
    )
    assert status == 200, body
    return body


def telemetry(service: str):
    status, body = request("GET", f"{SERVICES[service]}/telemetry")
    assert status == 200
    return body


def active_faults():
    status, body = request("GET", f"{CONTROLLER}/faults")
    assert status == 200
    return body


def test_controller_validation_and_lifecycle() -> None:
    restore_all()

    status, _ = request(
        "POST",
        f"{CONTROLLER}/faults/inject",
        {"fault": "does_not_exist", "service": "checkout", "severity": "P1", "seed": 42},
    )
    assert status == 422

    status, _ = request(
        "POST",
        f"{CONTROLLER}/faults/inject",
        {"fault": "n_plus_one", "service": "unknown", "severity": "P1", "seed": 42},
    )
    assert status == 422

    status, _ = request(
        "POST",
        f"{CONTROLLER}/faults/inject",
        {"fault": "n_plus_one", "service": "payment", "severity": "P1", "seed": 42},
    )
    assert status == 422

    status, body = request("POST", f"{CONTROLLER}/faults/restore", {"service": "checkout"})
    assert status == 200 and body["removed"] == 0

    first = inject("n_plus_one", "checkout", {"delay_per_query_ms": 1})
    second = inject("n_plus_one", "checkout", {"delay_per_query_ms": 1})
    assert first["generation"] == 1
    assert second["generation"] == 2
    faults = active_faults()
    assert len(faults) == 1
    assert faults[0]["generation"] == 2
    restore_all()


def test_n_plus_one() -> None:
    restore_all()
    status, baseline = request("GET", f"{SERVICES['checkout']}/orders")
    assert status == 200 and baseline["query_count"] == 1
    baseline_telemetry = telemetry("checkout")

    inject("n_plus_one", "checkout", {"delay_per_query_ms": 3}, seed=123)
    status, degraded = request("GET", f"{SERVICES['checkout']}/orders")
    assert status == 200 and degraded["query_count"] > 10
    degraded_telemetry = telemetry("checkout")
    assert degraded_telemetry["db_query_count_last_request"] > 10
    assert degraded_telemetry["last_latency_ms"] > baseline_telemetry["last_latency_ms"]

    first_signature = degraded["query_count"]
    restore_all()
    inject("n_plus_one", "checkout", {"delay_per_query_ms": 3}, seed=123)
    status, repeated = request("GET", f"{SERVICES['checkout']}/orders")
    assert status == 200
    assert repeated["query_count"] == first_signature

    restore_all()
    status, restored = request("GET", f"{SERVICES['checkout']}/orders")
    assert status == 200 and restored["query_count"] == 1


def test_connection_leak() -> None:
    restore_all()
    inject("connection_leak", "inventory", {"capacity": 4}, severity="P3")
    statuses = [
        request("GET", f"{SERVICES['inventory']}/inventory/SKU-RED")[0]
        for _ in range(4)
    ]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 503
    assert telemetry("inventory")["simulated_db_connections"] == 4
    restore_all()
    assert telemetry("inventory")["simulated_db_connections"] == 0
    assert request("GET", f"{SERVICES['inventory']}/inventory/SKU-RED")[0] == 200


def test_disk_exhaustion() -> None:
    restore_all()
    inject("disk_exhaustion", "worker", {"max_files": 4}, severity="P3")

    first_status, _ = request("POST", f"{SERVICES['worker']}/work")
    first_snapshot = telemetry("worker")
    second_status, _ = request("POST", f"{SERVICES['worker']}/work")
    second_snapshot = telemetry("worker")
    assert first_status == 200 and second_status == 200
    assert 0 < first_snapshot["simulated_disk_usage_ratio"] < second_snapshot[
        "simulated_disk_usage_ratio"
    ]

    statuses = [request("POST", f"{SERVICES['worker']}/work")[0] for _ in range(2)]
    assert 507 in statuses
    assert telemetry("worker")["simulated_disk_usage_ratio"] == 1.0

    restore_all()
    assert telemetry("worker")["simulated_disk_usage_ratio"] == 0.0
    assert request("POST", f"{SERVICES['worker']}/work")[0] == 200


def test_broken_config() -> None:
    restore_all()
    assert request("POST", f"{SERVICES['payment']}/charge")[0] == 200
    assert request("GET", f"{SERVICES['inventory']}/inventory/SKU-RED")[0] == 200

    inject("broken_config", "payment")
    assert request("POST", f"{SERVICES['payment']}/charge")[0] == 401
    assert request("GET", f"{SERVICES['gateway']}/checkout")[0] == 502
    assert request("GET", f"{SERVICES['inventory']}/inventory/SKU-RED")[0] == 200

    restore_all()
    assert request("POST", f"{SERVICES['payment']}/charge")[0] == 200
    assert request("GET", f"{SERVICES['gateway']}/checkout")[0] == 200


def test_memory_leak() -> None:
    restore_all()
    inject(
        "memory_leak",
        "worker",
        {"chunk_bytes": 262_144, "max_bytes": 1_048_576},
        severity="P3",
    )

    assert request("POST", f"{SERVICES['worker']}/work")[0] == 200
    first_snapshot = telemetry("worker")
    assert request("POST", f"{SERVICES['worker']}/work")[0] == 200
    second_snapshot = telemetry("worker")
    assert 0 < first_snapshot["simulated_memory_leak_bytes"] < second_snapshot[
        "simulated_memory_leak_bytes"
    ]

    assert request("POST", f"{SERVICES['worker']}/work")[0] == 200
    assert request("POST", f"{SERVICES['worker']}/work")[0] == 503
    restarted = telemetry("worker")
    assert restarted["simulated_restarts"] >= 1
    assert restarted["simulated_memory_leak_bytes"] == 0

    restore_all()
    assert request("POST", f"{SERVICES['worker']}/work")[0] == 200


if __name__ == "__main__":
    wait_healthy()
    test_controller_validation_and_lifecycle()
    test_n_plus_one()
    test_connection_leak()
    test_disk_exhaustion()
    test_broken_config()
    test_memory_leak()
    restore_all()
    print("Phase 2 smoke validation passed")
