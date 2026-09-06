import json
import subprocess
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
        except Exception:
            pass
        time.sleep(1)
    raise AssertionError("Phase 5 agent API did not become healthy")


def restart_backend() -> None:
    subprocess.run(
        ["docker", "compose", "restart", "backend"],
        check=True,
        text=True,
    )
    wait_for_backend()


def psql_scalar(query: str) -> str:
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "opssentinel",
            "-d",
            "opssentinel",
            "-tAc",
            query,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def restore_all() -> None:
    status, body = request("POST", f"{CONTROLLER}/faults/restore-all", {})
    assert status == 200, body


def list_faults() -> list[dict]:
    status, body = request("GET", f"{CONTROLLER}/faults")
    assert status == 200, body
    assert isinstance(body, list), body
    return body


def fault_present(fault: str, service: str) -> bool:
    return any(
        item["fault"] == fault and item["service"] == service for item in list_faults()
    )


def inject(
    fault: str,
    service: str,
    configuration=None,
    severity: str = "P1",
) -> None:
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
    assert fault_present(fault, service), body


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


def start_operational_run(payload: dict) -> dict:
    status, body = request(
        "POST",
        f"{BACKEND}/agent/runs",
        {"incident": payload, "operational_mode": True},
    )
    assert status == 201, body
    return body


def assert_waiting_for_approval(body: dict, expected_code: str) -> None:
    assert body["status"] == "paused", body
    assert body["operational_mode"] is True, body
    assert body["operation_stage"] == "wait_approval", body
    assert body["diagnosis_code"] == expected_code, body
    assert body["final_diagnosis"] is not None, body
    assert body["final_diagnosis"]["evidence_ids"], body
    assert body["proposed_action"] is not None, body
    assert body["proposed_action"]["risk_level"] == "R2", body
    assert body["proposed_action"]["tool"] == "rollback_sandbox_deployment", body
    assert body["approval"] is not None, body
    assert body["approval"]["decision"] == "pending", body
    assert body["approval"]["evidence_ids"], body
    assert body["approval"]["expected_benefit"], body
    assert body["approval"]["possible_risk"], body
    assert body["approval"]["rollback_strategy"], body
    assert body["verification"]["status"] == "not_run", body
    assert not any(
        item["tool_name"] == "rollback_sandbox_deployment"
        for item in body["tool_history"]
    ), body
    assert all(item["risk_level"] in {"R0", "R1"} for item in body["tool_history"]), body

    status, persisted = request("GET", f"{BACKEND}/agent/runs/{body['run_id']}")
    assert status == 200, persisted
    assert persisted["approval"]["id"] == body["approval"]["id"], persisted
    assert persisted["approval"]["decision"] == "pending", persisted
    assert psql_scalar(
        f"SELECT decision FROM approvals WHERE run_id = '{body['run_id']}';"
    ) == "pending"


def decide(run_id: str, decision: str, actor: str) -> dict:
    status, body = request(
        "POST",
        f"{BACKEND}/agent/runs/{run_id}/approval",
        {"decision": decision, "actor": actor},
    )
    assert status == 200, body
    return body


def assert_approved(
    body: dict,
    *,
    fault: str,
    service: str,
    expected_code: str,
    actor: str,
) -> None:
    assert body["status"] == "completed", body
    assert body["operation_stage"] == "complete", body
    assert body["diagnosis_code"] == expected_code, body
    assert body["approval"]["decision"] == "approved", body
    assert body["approval"]["decided_by"] == actor, body
    assert body["approval"]["decided_at"] is not None, body
    assert body["verification"]["status"] == "passed", body
    assert body["verification"]["evidence_ids"], body
    assert body["final_diagnosis"]["verification_status"] == "passed", body
    assert body["report"]["verification"]["status"] == "passed", body

    action_calls = [
        item
        for item in body["tool_history"]
        if item["tool_name"] == "rollback_sandbox_deployment"
    ]
    assert len(action_calls) == 1, body
    assert action_calls[0]["risk_level"] == "R2", body
    assert all(item["risk_level"] != "R3" for item in body["tool_history"]), body
    assert not fault_present(fault, service), list_faults()
    assert psql_scalar(
        f"SELECT decision FROM approvals WHERE run_id = '{body['run_id']}';"
    ) == "approved"
    assert psql_scalar(
        "SELECT COUNT(*) FROM tool_calls "
        f"WHERE run_id = '{body['run_id']}' "
        "AND tool_name = 'rollback_sandbox_deployment';"
    ) == "1"


def assert_non_approved(
    body: dict,
    *,
    decision: str,
    fault: str,
    service: str,
    actor: str,
) -> None:
    assert body["status"] == "completed", body
    assert body["operation_stage"] == "complete", body
    assert body["approval"]["decision"] == decision, body
    assert body["approval"]["decided_by"] == actor, body
    assert body["verification"]["status"] == "not_run", body
    assert not any(
        item["tool_name"] == "rollback_sandbox_deployment"
        for item in body["tool_history"]
    ), body
    assert fault_present(fault, service), list_faults()
    assert psql_scalar(
        f"SELECT decision FROM approvals WHERE run_id = '{body['run_id']}';"
    ) == decision


def prepare_n_plus_one() -> tuple[dict, str, str, str]:
    restore_all()
    inject("n_plus_one", "checkout", {"delay_per_query_ms": 3})
    assert hit("GET", "checkout", "/orders") == 200
    return (
        incident(
            "checkout",
            "Checkout latency regression after deployment",
            "Users report a severe checkout slowdown immediately after the latest deployment.",
            "phase5-approved-n-plus-one",
        ),
        "n_plus_one_query",
        "n_plus_one",
        "checkout",
    )


def prepare_connection_leak() -> tuple[dict, str, str, str]:
    restore_all()
    inject("connection_leak", "inventory", {"capacity": 4}, severity="P3")
    statuses = [hit("GET", "inventory", "/inventory/SKU-RED") for _ in range(4)]
    assert statuses[-1] == 503, statuses
    return (
        incident(
            "inventory",
            "Inventory requests are failing",
            "Inventory becomes unavailable under ordinary request traffic.",
            "phase5-approved-connection-leak",
        ),
        "database_connection_leak",
        "connection_leak",
        "inventory",
    )


def prepare_disk_exhaustion() -> tuple[dict, str, str, str]:
    restore_all()
    inject("disk_exhaustion", "worker", {"max_files": 4}, severity="P3")
    statuses = [hit("POST", "worker", "/work") for _ in range(4)]
    assert 507 in statuses, statuses
    return (
        incident(
            "worker",
            "Worker jobs fail with storage errors",
            "Worker processing fails after sustained output generation.",
            "phase5-approved-disk-exhaustion",
        ),
        "disk_exhaustion",
        "disk_exhaustion",
        "worker",
    )


def prepare_broken_config() -> tuple[dict, str, str, str]:
    restore_all()
    inject("broken_config", "payment")
    assert hit("POST", "payment", "/charge") == 401
    assert hit("GET", "gateway", "/checkout") == 502
    return (
        incident(
            "payment",
            "Payment authentication failures",
            "Checkout fails because the payment dependency rejects requests.",
            "phase5-approved-broken-payment-config",
        ),
        "broken_payment_configuration",
        "broken_config",
        "payment",
    )


def prepare_memory_leak() -> tuple[dict, str, str, str]:
    restore_all()
    inject(
        "memory_leak",
        "worker",
        {"chunk_bytes": 262_144, "max_bytes": 1_048_576},
        severity="P3",
    )
    statuses = [hit("POST", "worker", "/work") for _ in range(4)]
    assert statuses[-1] == 503, statuses
    return (
        incident(
            "worker",
            "Worker restarts after memory growth",
            "Repeated worker jobs show resource growth followed by a service failure.",
            "phase5-approved-memory-leak",
        ),
        "memory_leak",
        "memory_leak",
        "worker",
    )


def run_approved_scenario(
    prepared: tuple[dict, str, str, str],
    *,
    restart_before_decision: bool = False,
    restart_after_decision: bool = False,
) -> None:
    payload, expected_code, fault, service = prepared
    paused = start_operational_run(payload)
    assert_waiting_for_approval(paused, expected_code)
    assert fault_present(fault, service), list_faults()

    if restart_before_decision:
        run_id = paused["run_id"]
        approval_id = paused["approval"]["id"]
        restart_backend()
        status, persisted = request("GET", f"{BACKEND}/agent/runs/{run_id}")
        assert status == 200, persisted
        assert persisted["status"] == "paused", persisted
        assert persisted["operation_stage"] == "wait_approval", persisted
        assert persisted["approval"]["id"] == approval_id, persisted
        assert persisted["approval"]["decision"] == "pending", persisted
        paused = persisted

    actor = "phase5-ci-incident-commander"
    completed = decide(paused["run_id"], "approved", actor)
    assert_approved(
        completed,
        fault=fault,
        service=service,
        expected_code=expected_code,
        actor=actor,
    )

    if restart_after_decision:
        restart_backend()
        status, persisted = request("GET", f"{BACKEND}/agent/runs/{completed['run_id']}")
        assert status == 200, persisted
        assert persisted["approval"]["decision"] == "approved", persisted
        assert persisted["approval"]["decided_by"] == actor, persisted
        assert persisted["verification"]["status"] == "passed", persisted
        assert persisted["final_diagnosis"]["verification_status"] == "passed", persisted


def run_rejected_scenario() -> None:
    payload, expected_code, fault, service = prepare_connection_leak()
    payload["scenario_id"] = "phase5-rejected-connection-leak"
    paused = start_operational_run(payload)
    assert_waiting_for_approval(paused, expected_code)
    actor = "phase5-ci-rejector"
    completed = decide(paused["run_id"], "rejected", actor)
    assert_non_approved(
        completed,
        decision="rejected",
        fault=fault,
        service=service,
        actor=actor,
    )
    restore_all()


def run_abandoned_scenario() -> None:
    payload, expected_code, fault, service = prepare_disk_exhaustion()
    payload["scenario_id"] = "phase5-abandoned-disk-exhaustion"
    paused = start_operational_run(payload)
    assert_waiting_for_approval(paused, expected_code)
    actor = "phase5-ci-abandoner"
    completed = decide(paused["run_id"], "abandoned", actor)
    assert_non_approved(
        completed,
        decision="abandoned",
        fault=fault,
        service=service,
        actor=actor,
    )
    restore_all()


def assert_global_safety_invariants() -> None:
    assert psql_scalar("SELECT COUNT(*) FROM tool_calls WHERE risk_level = 'R3';") == "0"
    assert psql_scalar("SELECT COUNT(*) FROM approvals WHERE risk_level <> 'R2';") == "0"
    status, tools = request("GET", f"{BACKEND}/mcp/tools")
    assert status == 200, tools
    names = {item["name"] for item in tools}
    assert "run_shell" not in names, names
    assert all("fault" not in name for name in names), names


if __name__ == "__main__":
    wait_for_backend()

    run_approved_scenario(
        prepare_n_plus_one(),
        restart_before_decision=True,
        restart_after_decision=True,
    )
    run_approved_scenario(prepare_connection_leak())
    run_approved_scenario(prepare_disk_exhaustion())
    run_approved_scenario(prepare_broken_config())
    run_approved_scenario(prepare_memory_leak())
    run_rejected_scenario()
    run_abandoned_scenario()

    restore_all()
    assert list_faults() == []
    assert_global_safety_invariants()
    print(
        "Phase 5 operational smoke passed: five approved incident remediations, "
        "reject/abandon no-op safety, durable approval restart, verification, and R3 invariants"
    )
