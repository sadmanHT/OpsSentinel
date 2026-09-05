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


def inject(fault: str, service: str, configuration=None) -> None:
    status, body = request(
        "POST",
        f"{CONTROLLER}/faults/inject",
        {
            "fault": fault,
            "service": service,
            "severity": "P1",
            "seed": 42,
            "configuration": configuration or {},
        },
    )
    assert status == 200, body


def telemetry(service: str):
    status, body = request("GET", f"{SERVICES[service]}/telemetry")
    assert status == 200
    return body


def test_n_plus_one() -> None:
    restore_all()
    status, baseline = request("GET", f"{SERVICES['checkout']}/orders")
    assert status == 200 and baseline["query_count"] == 1
    inject("n_plus_one", "checkout", {"delay_per_query_ms": 2})
    status, degraded = request("GET", f"{SERVICES['checkout']}/orders")
    assert status == 200 and degraded["query_count"] > 10
    assert telemetry("checkout")["db_query_count_last_request"] > 10
    restore_all()
    status, restored = request("GET", f"{SERVICES['checkout']}/orders")
    assert status == 200 and restored["query_count"] == 1


def test_connection_leak() -> None:
    restore_all()
    inject("connection_leak", "inventory", {"capacity": 3})
    statuses = [request("GET", f"{SERVICES['inventory']}/inventory/SKU-RED")[0] for _ in range(4)]
    assert 503 in statuses
    assert telemetry("inventory")["simulated_db_connections"] >= 3
    restore_all()
    assert request("GET", f"{SERVICES['inventory']}/inventory/SKU-RED")[0] == 200


def test_disk_exhaustion() -> None:
    restore_all()
    inject("disk_exhaustion", "worker", {"max_files": 4})
    statuses = [request("POST", f"{SERVICES['worker']}/work")[0] for _ in range(4)]
    assert any(code == 507 for code in statuses)
    assert telemetry("worker")["simulated_disk_usage_ratio"] > 0
    restore_all()
    assert request("POST", f"{SERVICES['worker']}/work")[0] == 200


def test_broken_config() -> None:
    restore_all()
    assert request("POST", f"{SERVICES['payment']}/charge")[0] == 200
    inject("broken_config", "payment")
    assert request("POST", f"{SERVICES['payment']}/charge")[0] == 401
    restore_all()
    assert request("POST", f"{SERVICES['payment']}/charge")[0] == 200


def test_memory_leak() -> None:
    restore_all()
    inject("memory_leak", "worker", {"chunk_bytes": 262144, "max_bytes": 1048576})
    statuses = [request("POST", f"{SERVICES['worker']}/work")[0] for _ in range(6)]
    assert 503 in statuses
    assert telemetry("worker")["simulated_restarts"] >= 1
    restore_all()
    assert request("POST", f"{SERVICES['worker']}/work")[0] == 200


def test_controller_validation() -> None:
    restore_all()
    status, _ = request(
        "POST",
        f"{CONTROLLER}/faults/inject",
        {"fault": "n_plus_one", "service": "unknown", "severity": "P1", "seed": 42},
    )
    assert status == 422
    status, body = request("POST", f"{CONTROLLER}/faults/restore", {"service": "checkout"})
    assert status == 200 and body["removed"] == 0


if __name__ == "__main__":
    wait_healthy()
    test_controller_validation()
    test_n_plus_one()
    test_connection_leak()
    test_disk_exhaustion()
    test_broken_config()
    test_memory_leak()
    restore_all()
    print("Phase 2 smoke validation passed")
