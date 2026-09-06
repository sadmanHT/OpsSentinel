from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx
import pytest

from benchmarklab import BenchmarkRunner, load_catalog
from benchmarklab.models import Difficulty


@pytest.mark.asyncio
async def test_launch_operates_without_agent_and_records_faults() -> None:
    scenario = next(
        item for item in load_catalog().scenarios if item.difficulty == Difficulty.EASY
    )
    active: list[dict[str, Any]] = []
    requests: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        if request.url.path == "/faults/restore-all":
            active.clear()
            return httpx.Response(200, json={"status": "restored", "removed": 0})
        if request.url.path == "/faults/inject":
            payload = json.loads(request.content)
            active.append(payload)
            return httpx.Response(200, json={**payload, "active": True})
        if request.url.path == "/faults":
            return httpx.Response(200, json=active)
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = BenchmarkRunner(client=client)
        launch = await runner.launch(scenario)

    assert launch.scenario_id == scenario.scenario_id
    assert launch.injected_fault_count == 1
    assert launch.stimulus_count >= 1
    assert not any(path.endswith("/agent/runs") for _, path in requests)


@pytest.mark.asyncio
async def test_launch_restores_after_stimulus_failure() -> None:
    scenario = next(
        item for item in load_catalog().scenarios if item.difficulty == Difficulty.EASY
    )
    active: list[dict[str, Any]] = []
    restore_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal restore_calls
        if request.url.path == "/faults/restore-all":
            restore_calls += 1
            active.clear()
            return httpx.Response(200, json={"status": "restored", "removed": 0})
        if request.url.path == "/faults/inject":
            payload = json.loads(request.content)
            active.append(payload)
            return httpx.Response(200, json={**payload, "active": True})
        if request.url.path == "/faults":
            return httpx.Response(200, json=active)
        return httpx.Response(500, json={"error": "injected stimulus failure"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = BenchmarkRunner(client=client)
        with pytest.raises(RuntimeError):
            await runner.launch(scenario)

    assert restore_calls == 2
    assert active == []


@pytest.mark.asyncio
async def test_agent_request_never_contains_hidden_benchmark_labels() -> None:
    scenario = next(
        item for item in load_catalog().scenarios if item.difficulty == Difficulty.MEDIUM
    )
    active: list[dict[str, Any]] = []
    agent_payloads: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/faults/restore-all":
            active.clear()
            return httpx.Response(200, json={"status": "restored", "removed": 0})
        if request.url.path == "/faults/inject":
            payload = json.loads(request.content)
            active.append(payload)
            return httpx.Response(200, json={**payload, "active": True})
        if request.url.path == "/faults":
            return httpx.Response(200, json=active)
        if request.url.path == "/agent/runs":
            payload = json.loads(request.content)
            agent_payloads.append(payload)
            return httpx.Response(
                201,
                json={
                    "run_id": str(uuid4()),
                    "status": "completed",
                    "diagnosis_code": "example",
                    "confidence": 0.5,
                    "tool_history": [],
                },
            )
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = BenchmarkRunner(client=client)
        await runner.run(scenario)

    assert len(agent_payloads) == 1
    payload = agent_payloads[0]
    serialized = json.dumps(payload).casefold()
    assert "ground_truth" not in serialized
    assert "expected_primary" not in serialized
    assert "difficulty" not in serialized
    assert "split" not in serialized
    assert scenario.ground_truth.primary_root_cause_code.casefold() not in serialized
    assert set(payload["incident"]) == {
        "title",
        "description",
        "severity",
        "service",
        "start_time",
        "scenario_id",
    }


@pytest.mark.asyncio
async def test_runner_restores_after_agent_failure() -> None:
    scenario = next(
        item for item in load_catalog().scenarios if item.difficulty == Difficulty.EASY
    )
    active: list[dict[str, Any]] = []
    restore_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal restore_calls
        if request.url.path == "/faults/restore-all":
            restore_calls += 1
            active.clear()
            return httpx.Response(200, json={"status": "restored", "removed": 0})
        if request.url.path == "/faults/inject":
            payload = json.loads(request.content)
            active.append(payload)
            return httpx.Response(200, json={**payload, "active": True})
        if request.url.path == "/faults":
            return httpx.Response(200, json=active)
        if request.url.path == "/agent/runs":
            return httpx.Response(500, text="injected agent failure")
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runner = BenchmarkRunner(client=client)
        with pytest.raises(RuntimeError):
            await runner.run(scenario)

    assert restore_calls == 2
    assert active == []
