import json
import time
import urllib.error
import urllib.request

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
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        return exc.code, json.loads(body) if body else None


def invoke(tool: str, arguments=None, *, expected: str = "succeeded"):
    status, body = request(
        "POST",
        f"{BACKEND}/mcp/invoke",
        {"tool": tool, "arguments": arguments or {}},
    )
    assert status == 200, body
    assert body["status"] == expected, body
    return body


def evidence(tool: str, arguments=None):
    body = invoke(tool, arguments)
    return body["data"]["payload"]


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


def metric(service: str, name: str) -> float:
    payload = evidence("query_metrics", {"service": service, "metric": name})
    return float(payload["value"])


def test_registry_and_security_boundary() -> None:
    status, tools = request("GET", f"{BACKEND}/mcp/tools")
    assert status == 200
    names = {item["name"] for item in tools}
    assert "execute_sql" in names and "run_diagnostic" in names
    assert all("fault" not in name for name in names)

    assert invoke(
        "execute_sql",
        {"query": "UPDATE incidents SET title = 'unsafe'"},
        expected="blocked",
    )["error"]["code"] == "unsafe_operation"
    assert invoke(
        "search_logs",
        {"service": "controller"},
        expected="blocked",
    )["error"]["code"] == "permission_denied"
    assert invoke(
        "run_diagnostic",
        {"command": "curl", "service": "worker", "path": "/;id"},
        expected="blocked",
    )["error"]["code"] == "unsafe_operation"
    assert invoke(
        "search_documentation",
        {"query": "phase", "path": "../"},
        expected="blocked",
    )["error"]["code"] == "unsafe_operation"

    sql = evidence("execute_sql", {"query": "SELECT current_user"})
    assert sql["rows"][0][0] == "opssentinel_reader"
    docs = evidence("search_documentation", {"query": "ChaosLab", "limit": 5})
    assert docs
    code = evidence("search_code", {"query": "class RiskPolicy", "limit": 5})
    assert code
    commit = evidence("inspect_commit", {"revision": "HEAD"})
    assert "commit" in commit["output"]
    diff = evidence("inspect_git_diff", {"base": "HEAD", "head": "HEAD"})
    assert diff["base"] == "HEAD" and diff["head"] == "HEAD"
    deployments = evidence("list_deployments")
    checkout_deployment = evidence("inspect_deployment", {"service": "checkout"})
    assert checkout_deployment["health"]["status"] == "ok"
    assert {item["service"] for item in deployments} >= {
        "gateway",
        "checkout",
        "inventory",
        "payment",
        "worker",
    }
    diagnostic = evidence("run_diagnostic", {"command": "df"})
    assert "Filesystem" in diagnostic["output"]


def test_n_plus_one_only_mcp_evidence() -> None:
    restore_all()
    assert hit("GET", "checkout", "/orders") == 200
    baseline = metric("checkout", "db_query_count")
    inject("n_plus_one", "checkout", {"delay_per_query_ms": 3})
    assert hit("GET", "checkout", "/orders") == 200
    degraded = metric("checkout", "db_query_count")
    logs = evidence("search_logs", {"service": "checkout", "query": "/orders", "limit": 5})
    assert degraded > baseline and degraded > 10
    assert logs and logs[-1]["db_queries"] > 10


def test_connection_leak_only_mcp_evidence() -> None:
    restore_all()
    inject("connection_leak", "inventory", {"capacity": 4}, severity="P3")
    statuses = [hit("GET", "inventory", "/inventory/SKU-RED") for _ in range(4)]
    assert statuses[-1] == 503
    assert metric("inventory", "db_connections") == 4
    logs = evidence("search_logs", {"service": "inventory", "level": "ERROR", "limit": 10})
    assert any(item["status"] == 503 for item in logs)


def test_disk_exhaustion_only_mcp_evidence() -> None:
    restore_all()
    inject("disk_exhaustion", "worker", {"max_files": 4}, severity="P3")
    statuses = [hit("POST", "worker", "/work") for _ in range(4)]
    assert 507 in statuses
    assert metric("worker", "disk_usage") == 1.0
    logs = evidence("search_logs", {"service": "worker", "level": "ERROR", "limit": 10})
    assert any(item["status"] == 507 for item in logs)


def test_broken_config_only_mcp_evidence() -> None:
    restore_all()
    inject("broken_config", "payment")
    assert hit("POST", "payment", "/charge") == 401
    assert hit("GET", "gateway", "/checkout") == 502
    payment_logs = evidence(
        "search_logs",
        {"service": "payment", "level": "WARNING", "limit": 10},
    )
    gateway_logs = evidence(
        "search_logs",
        {"service": "gateway", "level": "ERROR", "limit": 10},
    )
    assert any(item["status"] == 401 for item in payment_logs)
    assert any(item["status"] == 502 for item in gateway_logs)


def test_memory_leak_only_mcp_evidence() -> None:
    restore_all()
    inject(
        "memory_leak",
        "worker",
        {"chunk_bytes": 262_144, "max_bytes": 1_048_576},
        severity="P3",
    )
    assert hit("POST", "worker", "/work") == 200
    first = metric("worker", "memory_usage")
    assert hit("POST", "worker", "/work") == 200
    second = metric("worker", "memory_usage")
    assert second > first > 0
    assert hit("POST", "worker", "/work") == 200
    assert hit("POST", "worker", "/work") == 503
    assert metric("worker", "container_restarts") >= 1
    logs = evidence("search_logs", {"service": "worker", "level": "ERROR", "limit": 10})
    assert any(item["status"] == 503 for item in logs)


if __name__ == "__main__":
    for _ in range(45):
        try:
            if request("GET", f"{BACKEND}/mcp/health")[0] == 200:
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        raise AssertionError("MCP boundary did not become healthy")

    test_registry_and_security_boundary()
    test_n_plus_one_only_mcp_evidence()
    test_connection_leak_only_mcp_evidence()
    test_disk_exhaustion_only_mcp_evidence()
    test_broken_config_only_mcp_evidence()
    test_memory_leak_only_mcp_evidence()
    restore_all()
    print("Phase 3 MCP and safety-boundary smoke validation passed")
