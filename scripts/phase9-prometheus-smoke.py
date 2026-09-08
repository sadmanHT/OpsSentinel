from __future__ import annotations

import base64
import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BACKEND = "http://127.0.0.1:8000"
PROMETHEUS = "http://127.0.0.1:9090"
GRAFANA = "http://127.0.0.1:3001"
GRAFANA_AUTH = base64.b64encode(b"opssentinel:opssentinel").decode("ascii")
LATENCY_SEED = Path("phase9-latency-live.json")
OUTPUT = Path("phase9-prometheus-live.json")


def request_json(url: str, *, grafana_auth: bool = False) -> tuple[int, Any]:
    request = urllib.request.Request(url, method="GET")
    if grafana_auth:
        request.add_header("Authorization", f"Basic {GRAFANA_AUTH}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        return exc.code, json.loads(body) if body else None


def request_text(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def wait_json(url: str, *, grafana_auth: bool = False) -> Any:
    for _ in range(90):
        try:
            status, body = request_json(url, grafana_auth=grafana_auth)
            if status == 200:
                return body
        except (urllib.error.URLError, TimeoutError, ConnectionResetError):
            pass
        time.sleep(1)
    raise AssertionError(f"service did not become ready: {url}")


def prometheus_query(expression: str) -> float:
    encoded = urllib.parse.urlencode({"query": expression})
    url = f"{PROMETHEUS}/api/v1/query?{encoded}"
    for _ in range(60):
        try:
            status, body = request_json(url)
            if status == 200 and body["status"] == "success":
                result = body["data"]["result"]
                if result:
                    return float(result[0]["value"][1])
        except (urllib.error.URLError, TimeoutError, ConnectionResetError, KeyError):
            pass
        time.sleep(1)
    raise AssertionError(f"Prometheus query produced no sample: {expression}")


def assert_target_up() -> None:
    latest_target: dict[str, Any] | None = None
    for _ in range(60):
        try:
            status, body = request_json(f"{PROMETHEUS}/api/v1/targets")
            if status == 200:
                active = body["data"]["activeTargets"]
                matching = [
                    target
                    for target in active
                    if target["labels"].get("job") == "opssentinel-backend"
                ]
                if len(matching) == 1:
                    latest_target = matching[0]
                    assert latest_target["scrapeUrl"].endswith(
                        "/observability/metrics"
                    ), latest_target
                    if latest_target["health"] == "up":
                        return
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionResetError,
            KeyError,
        ):
            pass
        time.sleep(1)
    raise AssertionError(f"Prometheus backend target did not recover: {latest_target}")


def assert_grafana_provisioned() -> None:
    health = wait_json(f"{GRAFANA}/api/health")
    assert health["database"] == "ok", health

    datasource = wait_json(
        f"{GRAFANA}/api/datasources/uid/opssentinel-prometheus",
        grafana_auth=True,
    )
    assert datasource["type"] == "prometheus", datasource
    assert datasource["url"] == "http://prometheus:9090", datasource
    assert datasource["isDefault"] is True, datasource

    dashboard = wait_json(
        f"{GRAFANA}/api/dashboards/uid/opssentinel-operational",
        grafana_auth=True,
    )
    assert dashboard["dashboard"]["title"] == "OpsSentinel Operational Metrics", dashboard
    assert dashboard["dashboard"]["uid"] == "opssentinel-operational", dashboard


def backend_metrics() -> str:
    for _ in range(60):
        try:
            status, body = request_text(f"{BACKEND}/observability/metrics")
            if status == 200 and "opssentinel_agent_runs" in body:
                return body
        except (urllib.error.URLError, TimeoutError, ConnectionResetError):
            pass
        time.sleep(1)
    raise AssertionError("backend Prometheus exposition did not become ready")


def latency_summary() -> dict[str, Any]:
    body = wait_json(f"{BACKEND}/observability/latency")
    assert isinstance(body, dict), body
    return body


def metric_snapshot() -> dict[str, float]:
    return {
        "run_count": prometheus_query("sum(opssentinel_agent_runs)"),
        "diagnosis_observations": prometheus_query(
            'opssentinel_run_latency_observations{stage="diagnosis"}'
        ),
        "verified_resolution_observations": prometheus_query(
            'opssentinel_run_latency_observations{stage="verified_resolution"}'
        ),
        "agent_tokens": prometheus_query("opssentinel_agent_token_usage"),
        "tool_calls": prometheus_query("sum(opssentinel_tool_calls)"),
    }


def restart_observability_stack() -> None:
    subprocess.run(
        ["docker", "compose", "restart", "backend", "prometheus", "grafana"],
        check=True,
    )


def main() -> None:
    seed = json.loads(LATENCY_SEED.read_text())
    run_ids = [seed["passed_run_id"], seed["rejected_run_id"]]

    metrics_before = backend_metrics()
    latency_before = latency_summary()
    assert latency_before == seed["aggregate_latency"], (latency_before, seed["aggregate_latency"])
    assert latency_before["run_count"] == 2, latency_before
    assert latency_before["time_to_diagnosis"]["count"] == 2, latency_before
    assert latency_before["time_to_verified_resolution"]["count"] == 1, latency_before

    for forbidden in (
        *run_ids,
        "phase9-latency-passed",
        "phase9-latency-rejected",
        "scenario_id",
        "raw_reference",
        "arguments",
    ):
        assert forbidden not in metrics_before, forbidden

    assert_target_up()
    assert_grafana_provisioned()
    snapshot_before = metric_snapshot()
    assert snapshot_before["run_count"] == 2.0, snapshot_before
    assert snapshot_before["diagnosis_observations"] == 2.0, snapshot_before
    assert snapshot_before["verified_resolution_observations"] == 1.0, snapshot_before
    assert snapshot_before["agent_tokens"] > 0.0, snapshot_before
    assert snapshot_before["tool_calls"] > 0.0, snapshot_before

    restart_observability_stack()

    metrics_after = backend_metrics()
    latency_after = latency_summary()
    assert latency_after == latency_before
    for forbidden in run_ids:
        assert forbidden not in metrics_after, forbidden
    assert_target_up()
    assert_grafana_provisioned()
    snapshot_after = metric_snapshot()
    assert snapshot_after == snapshot_before, (snapshot_before, snapshot_after)

    payload = {
        "passed": True,
        "run_count": int(snapshot_before["run_count"]),
        "diagnosis_observations": int(snapshot_before["diagnosis_observations"]),
        "verified_resolution_observations": int(
            snapshot_before["verified_resolution_observations"]
        ),
        "agent_tokens": int(snapshot_before["agent_tokens"]),
        "tool_calls": int(snapshot_before["tool_calls"]),
        "grafana_dashboard_uid": "opssentinel-operational",
        "prometheus_target_health": "up",
        "restart_persistence_verified": True,
        "privacy_checks": {
            "run_ids_absent": True,
            "scenario_ids_absent": True,
            "tool_arguments_absent": True,
            "raw_evidence_absent": True,
        },
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
