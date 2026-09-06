from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
from benchmarklab.models import Difficulty, ScenarioSpec
from benchmarklab.validation import (
    validate_agent_payload_is_public_only,
    validate_release_catalog,
)

from benchmarklab import BenchmarkRunner, load_catalog, scenario_by_id

CONTROLLER = "http://127.0.0.1:8100"
SERVICES = {
    "gateway": "http://127.0.0.1:8080",
    "checkout": "http://127.0.0.1:8101",
    "inventory": "http://127.0.0.1:8102",
    "payment": "http://127.0.0.1:8103",
    "worker": "http://127.0.0.1:8104",
}


def get_json(url: str) -> dict[str, Any] | list[dict[str, Any]]:
    response = httpx.get(url, timeout=20.0)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, (dict, list)):
        raise TypeError(f"expected JSON object/list from {url}, got {type(payload)!r}")
    return payload


def post_json(url: str, payload: dict[str, Any] | None = None) -> httpx.Response:
    return httpx.post(url, json=payload or {}, timeout=20.0)


async def async_status(url: str) -> int:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url)
    return response.status_code


def active_fault_pairs() -> set[tuple[str, str]]:
    payload = get_json(f"{CONTROLLER}/faults")
    assert isinstance(payload, list)
    return {
        (str(item.get("fault")), str(item.get("service")))
        for item in payload
        if isinstance(item, dict)
    }


def telemetry(service: str) -> dict[str, Any]:
    payload = get_json(f"{SERVICES[service]}/telemetry")
    assert isinstance(payload, dict)
    return payload


def assert_timeline_contract(scenario: ScenarioSpec) -> None:
    effects = [
        event.offset_seconds for event in scenario.timeline if event.role.value == "effect"
    ]
    causes = [
        event.offset_seconds for event in scenario.timeline if event.role.value == "cause"
    ]
    assert effects, scenario.scenario_id
    if causes:
        assert min(causes) <= min(effects), scenario.scenario_id
    if scenario.difficulty in {Difficulty.MEDIUM, Difficulty.ADVERSARIAL}:
        assert scenario.distractor_tags, scenario.scenario_id
    if scenario.difficulty == Difficulty.ADVERSARIAL:
        assert any(
            event.role.value == "distractor" and event.offset_seconds < min(effects)
            for event in scenario.timeline
        ), scenario.scenario_id


def assert_public_boundary(scenario: ScenarioSpec) -> None:
    validate_agent_payload_is_public_only(scenario)
    payload = scenario.agent_payload()
    assert set(payload) == {
        "title",
        "description",
        "severity",
        "service",
        "start_time",
        "scenario_id",
    }
    serialized = json.dumps(payload, sort_keys=True).casefold()
    assert "ground_truth" not in serialized
    assert "difficulty" not in serialized
    assert "split" not in serialized
    assert scenario.ground_truth.primary_root_cause_code.casefold() not in serialized


def expected_fault_pairs(scenario: ScenarioSpec) -> set[tuple[str, str]]:
    return {(fault.fault.value, fault.service.value) for fault in scenario.faults}


def assert_restored() -> None:
    assert active_fault_pairs() == set()
    assert httpx.get(f"{SERVICES['checkout']}/orders", timeout=20.0).status_code == 200
    assert httpx.get(
        f"{SERVICES['inventory']}/inventory/SKU-RED", timeout=20.0
    ).status_code == 200
    assert post_json(f"{SERVICES['payment']}/charge").status_code == 200
    assert post_json(f"{SERVICES['worker']}/work").status_code == 200


def evidence_n_plus_one() -> tuple[int, float]:
    snapshot = telemetry("checkout")
    query_count = int(snapshot["db_query_count_last_request"])
    latency = float(snapshot["last_latency_ms"])
    assert query_count > 10
    assert latency > 0
    return query_count, latency


def evidence_connection_leak() -> int:
    snapshot = telemetry("inventory")
    connections = int(snapshot["simulated_db_connections"])
    assert connections >= 4
    return connections


def evidence_disk_exhaustion() -> float:
    snapshot = telemetry("worker")
    ratio = float(snapshot["simulated_disk_usage_ratio"])
    assert ratio == 1.0
    return ratio


def evidence_memory_leak() -> int:
    snapshot = telemetry("worker")
    restarts = int(snapshot["simulated_restarts"])
    assert restarts >= 1
    return restarts


async def launch_and_validate(
    runner: BenchmarkRunner,
    scenario: ScenarioSpec,
    evidence_check: Callable[[], object],
) -> object:
    assert_timeline_contract(scenario)
    assert_public_boundary(scenario)
    launch = await runner.launch(scenario)
    assert launch.injected_fault_count == len(scenario.faults)
    assert launch.stimulus_count == len(scenario.stimuli)
    assert active_fault_pairs() == expected_fault_pairs(scenario)
    evidence = evidence_check()
    await runner.restore()
    assert_restored()
    return evidence


async def validate_live_agent_run(
    runner: BenchmarkRunner,
    scenario: ScenarioSpec,
    benchmark_version: str,
) -> None:
    assert_public_boundary(scenario)
    artifact = await runner.run(scenario, benchmark_version=benchmark_version)

    assert artifact.scenario_id == scenario.scenario_id
    assert artifact.agent_run_id is not None
    assert artifact.agent_status == "completed"
    assert artifact.diagnosis_code == "n_plus_one_query"
    assert artifact.confidence is not None and artifact.confidence >= 0.9
    assert artifact.tool_call_count > 0
    assert artifact.expected_primary_root_cause_code == "n_plus_one_query"
    assert artifact.expected_secondary_root_cause_codes == []

    agent_run = artifact.raw_agent_run
    assert agent_run["status"] == "completed", agent_run
    assert agent_run["next_node"] == "end", agent_run
    assert agent_run["diagnosis_code"] == "n_plus_one_query", agent_run
    final_diagnosis = agent_run["final_diagnosis"]
    assert final_diagnosis is not None, agent_run
    assert float(final_diagnosis["confidence"]) >= 0.9, final_diagnosis
    assert final_diagnosis["evidence_ids"], final_diagnosis
    report = agent_run["report"]
    assert report is not None, agent_run
    assert report["root_cause_code"] == "n_plus_one_query", report
    assert report["claims"], report

    assert_restored()


async def main() -> None:
    catalog = load_catalog()
    validate_release_catalog(catalog)

    runner = BenchmarkRunner()

    # Easy: single N+1 with strong query/latency signal.
    easy = scenario_by_id(catalog, "ops-v1-001")
    assert easy.difficulty == Difficulty.EASY
    first_signature = await launch_and_validate(runner, easy, evidence_n_plus_one)

    # Identical seed must replay the same deterministic query-count signature.
    second_signature = await launch_and_validate(runner, easy, evidence_n_plus_one)
    assert isinstance(first_signature, tuple)
    assert isinstance(second_signature, tuple)
    assert first_signature[0] == second_signature[0]

    # The benchmark runner must also drive the real autonomous agent without label leakage.
    await validate_live_agent_run(runner, easy, catalog.benchmark_version)

    # Medium: connection leak with realistic distractor metadata.
    medium = scenario_by_id(catalog, "ops-v1-012")
    assert medium.difficulty == Difficulty.MEDIUM
    await launch_and_validate(runner, medium, evidence_connection_leak)

    # Hard: delayed disk-exhaustion effect and worker evidence.
    hard = scenario_by_id(catalog, "ops-v1-025")
    assert hard.difficulty == Difficulty.HARD
    await launch_and_validate(runner, hard, evidence_disk_exhaustion)

    # Adversarial: misleading-change metadata while memory evidence identifies the issue.
    adversarial = scenario_by_id(catalog, "ops-v1-042")
    assert adversarial.difficulty == Difficulty.ADVERSARIAL
    await launch_and_validate(runner, adversarial, evidence_memory_leak)

    # Counterfactual control: deployment metadata but no fault and no degradation.
    counterfactual = scenario_by_id(catalog, "ops-v1-040")
    assert counterfactual.ground_truth.primary_root_cause_code == "no_fault"
    assert_timeline_contract(counterfactual)
    assert_public_boundary(counterfactual)
    launch = await runner.launch(counterfactual)
    assert launch.injected_fault_count == 0
    assert launch.stimulus_count == 0
    assert active_fault_pairs() == set()
    assert (
        await async_status(f"{SERVICES['inventory']}/inventory/SKU-RED")
        == 200
    )
    await runner.restore()
    assert_restored()

    # Compound: pre-existing memory leak plus later acute N+1. Both faults must coexist,
    # both evidence families must be observable, and labels must separate primary/secondary.
    compound = scenario_by_id(catalog, "ops-v1-043")
    assert compound.difficulty == Difficulty.COMPOUND
    assert compound.ground_truth.primary_root_cause_code == "n_plus_one_query"
    assert compound.ground_truth.secondary_root_cause_codes == ["memory_leak"]
    assert_timeline_contract(compound)
    assert_public_boundary(compound)
    launch = await runner.launch(compound)
    assert launch.injected_fault_count == 2
    assert active_fault_pairs() == expected_fault_pairs(compound)
    evidence_n_plus_one()
    evidence_memory_leak()
    await runner.restore()
    assert_restored()

    print(
        "Phase 6 live BenchmarkLab smoke passed: easy, live-agent, medium, hard, "
        "adversarial, counterfactual, compound, reproducibility, restoration"
    )


if __name__ == "__main__":
    asyncio.run(main())
