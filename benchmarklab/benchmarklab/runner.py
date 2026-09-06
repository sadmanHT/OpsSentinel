from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx

from benchmarklab.models import (
    BenchmarkCatalog,
    BenchmarkRunArtifact,
    ScenarioLaunchRecord,
    ScenarioSpec,
    ServiceName,
)


@dataclass(frozen=True)
class BenchmarkEnvironment:
    backend_url: str = "http://127.0.0.1:8000"
    controller_url: str = "http://127.0.0.1:8100"
    service_urls: dict[ServiceName, str] = field(
        default_factory=lambda: {
            ServiceName.GATEWAY: "http://127.0.0.1:8080",
            ServiceName.CHECKOUT: "http://127.0.0.1:8101",
            ServiceName.INVENTORY: "http://127.0.0.1:8102",
            ServiceName.PAYMENT: "http://127.0.0.1:8103",
            ServiceName.WORKER: "http://127.0.0.1:8104",
        }
    )
    timeout_seconds: float = 60.0
    timeline_scale: float = 0.0


class BenchmarkRuntimeError(RuntimeError):
    pass


class BenchmarkRunner:
    """Launch benchmark incidents independently and keep hidden labels out of agent input."""

    def __init__(
        self,
        environment: BenchmarkEnvironment | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.environment = environment or BenchmarkEnvironment()
        self._client = client

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        if self._client is not None:
            return await self._client.request(method, url, json=json)
        async with httpx.AsyncClient(timeout=self.environment.timeout_seconds) as client:
            return await client.request(method, url, json=json)

    async def restore(self) -> None:
        response = await self._request(
            "POST",
            f"{self.environment.controller_url.rstrip('/')}/faults/restore-all",
            json={},
        )
        if response.status_code >= 400:
            raise BenchmarkRuntimeError(
                f"ChaosLab restore-all failed with HTTP {response.status_code}"
            )

    async def _active_faults(self) -> list[dict[str, Any]]:
        response = await self._request(
            "GET",
            f"{self.environment.controller_url.rstrip('/')}/faults",
        )
        if response.status_code >= 400:
            raise BenchmarkRuntimeError(
                f"ChaosLab fault listing failed with HTTP {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, list):
            raise BenchmarkRuntimeError("ChaosLab fault listing returned malformed JSON")
        return [item for item in payload if isinstance(item, dict)]

    async def _inject_fault(self, scenario: ScenarioSpec, index: int) -> None:
        fault = scenario.faults[index]
        response = await self._request(
            "POST",
            f"{self.environment.controller_url.rstrip('/')}/faults/inject",
            json={
                "fault": fault.fault.value,
                "service": fault.service.value,
                "severity": fault.severity.value,
                "seed": fault.seed,
                "configuration": fault.configuration,
            },
        )
        if response.status_code >= 400:
            raise BenchmarkRuntimeError(
                f"fault injection failed for {scenario.scenario_id}: "
                f"HTTP {response.status_code}"
            )
        active = await self._active_faults()
        expected = (fault.fault.value, fault.service.value)
        observed = {(item.get("fault"), item.get("service")) for item in active}
        if expected not in observed:
            raise BenchmarkRuntimeError(
                f"fault {expected} was not present after injection for {scenario.scenario_id}"
            )

    async def _sleep_to_offset(self, previous: float, current: float) -> None:
        scale = self.environment.timeline_scale
        if scale <= 0 or current <= previous:
            return
        await asyncio.sleep((current - previous) * scale)

    async def _run_stimulus(self, scenario: ScenarioSpec, index: int) -> int:
        stimulus = scenario.stimuli[index]
        base_url = self.environment.service_urls[stimulus.service].rstrip("/")
        last_status = 0
        for _ in range(stimulus.count):
            response = await self._request(
                stimulus.method,
                f"{base_url}{stimulus.path}",
            )
            last_status = response.status_code
        if stimulus.expected_status is not None and last_status != stimulus.expected_status:
            raise BenchmarkRuntimeError(
                f"stimulus for {scenario.scenario_id} expected final HTTP "
                f"{stimulus.expected_status}, got {last_status}"
            )
        return last_status

    async def launch(self, scenario: ScenarioSpec) -> ScenarioLaunchRecord:
        """Launch one scenario without starting the agent.

        Successful launches keep faults active so evaluators can inspect evidence. Any failed
        launch restores ChaosLab before re-raising the failure.
        """
        await self.restore()
        try:
            events: list[tuple[float, str, int]] = []
            events.extend(
                (fault.offset_seconds, "fault", index)
                for index, fault in enumerate(scenario.faults)
            )
            events.extend(
                (stimulus.offset_seconds, "stimulus", index)
                for index, stimulus in enumerate(scenario.stimuli)
            )
            events.sort(
                key=lambda item: (item[0], 0 if item[1] == "fault" else 1, item[2])
            )

            previous_offset = 0.0
            statuses: list[int] = []
            for offset, event_type, index in events:
                await self._sleep_to_offset(previous_offset, offset)
                if event_type == "fault":
                    await self._inject_fault(scenario, index)
                else:
                    statuses.append(await self._run_stimulus(scenario, index))
                previous_offset = offset

            return ScenarioLaunchRecord(
                scenario_id=scenario.scenario_id,
                injected_fault_count=len(scenario.faults),
                stimulus_count=len(scenario.stimuli),
                final_statuses=statuses,
            )
        except Exception:
            await self.restore()
            raise

    async def _start_agent(self, scenario: ScenarioSpec) -> dict[str, Any]:
        payload = {
            "incident": scenario.agent_payload(),
            "budget": {
                "max_steps": scenario.budget.max_steps,
                "max_tool_calls": scenario.budget.max_tool_calls,
                "time_limit_seconds": scenario.budget.time_limit_seconds,
            },
            "operational_mode": False,
        }
        response = await self._request(
            "POST",
            f"{self.environment.backend_url.rstrip('/')}/agent/runs",
            json=payload,
        )
        if response.status_code != 201:
            raise BenchmarkRuntimeError(
                f"agent launch for {scenario.scenario_id} failed with HTTP "
                f"{response.status_code}: {response.text[:500]}"
            )
        body = response.json()
        if not isinstance(body, dict):
            raise BenchmarkRuntimeError("agent API returned malformed run payload")
        return body

    async def run(
        self,
        scenario: ScenarioSpec,
        *,
        benchmark_version: str = "1.0.0",
    ) -> BenchmarkRunArtifact:
        try:
            await self.launch(scenario)
            agent_run = await self._start_agent(scenario)
            run_id = agent_run.get("run_id")
            return BenchmarkRunArtifact(
                benchmark_version=benchmark_version,
                scenario_id=scenario.scenario_id,
                scenario_version=scenario.scenario_version,
                split=scenario.split,
                difficulty=scenario.difficulty,
                seed=scenario.seed,
                agent_run_id=UUID(str(run_id)) if run_id else None,
                agent_status=str(agent_run.get("status", "unknown")),
                diagnosis_code=(
                    str(agent_run["diagnosis_code"])
                    if agent_run.get("diagnosis_code") is not None
                    else None
                ),
                confidence=(
                    float(agent_run["confidence"])
                    if agent_run.get("confidence") is not None
                    else None
                ),
                tool_call_count=len(agent_run.get("tool_history", [])),
                expected_primary_root_cause_code=(
                    scenario.ground_truth.primary_root_cause_code
                ),
                expected_secondary_root_cause_codes=(
                    scenario.ground_truth.secondary_root_cause_codes
                ),
                raw_agent_run=agent_run,
            )
        finally:
            await self.restore()

    async def run_catalog(
        self,
        catalog: BenchmarkCatalog,
        *,
        split: str | None = None,
        limit: int | None = None,
    ) -> list[BenchmarkRunArtifact]:
        selected = [
            scenario
            for scenario in catalog.scenarios
            if split is None or scenario.split.value == split
        ]
        if limit is not None:
            selected = selected[:limit]
        results: list[BenchmarkRunArtifact] = []
        for scenario in selected:
            results.append(
                await self.run(scenario, benchmark_version=catalog.benchmark_version)
            )
        return results
