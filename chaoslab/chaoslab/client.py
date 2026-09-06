from __future__ import annotations

from typing import Any

import httpx

from chaoslab.models import FaultSpec, FaultState, FaultType, Severity


class ChaosLabClient:
    """Small synchronous client for the ChaosLab controller API.

    This control interface is for scenario orchestration and test infrastructure.
    Future investigation agents must not receive access to it because it exposes
    fault-injection state that would leak benchmark ground truth.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8100", timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def inject(
        self,
        fault: FaultType | str,
        *,
        service: str,
        severity: Severity | str = Severity.P2,
        seed: int = 42,
        configuration: dict[str, Any] | None = None,
    ) -> FaultState:
        spec = FaultSpec(
            fault=FaultType(fault),
            service=service,
            severity=Severity(severity),
            seed=seed,
            configuration=configuration or {},
        )
        response = httpx.post(
            f"{self.base_url}/faults/inject",
            json=spec.model_dump(mode="json"),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return FaultState.model_validate(response.json())

    def status(self) -> list[FaultState]:
        response = httpx.get(f"{self.base_url}/faults", timeout=self.timeout)
        response.raise_for_status()
        return [FaultState.model_validate(item) for item in response.json()]

    def restore(self, service: str, fault: FaultType | str | None = None) -> int:
        payload: dict[str, Any] = {"service": service}
        if fault is not None:
            payload["fault"] = FaultType(fault).value
        response = httpx.post(
            f"{self.base_url}/faults/restore",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return int(response.json()["removed"])

    def restore_all(self) -> int:
        response = httpx.post(
            f"{self.base_url}/faults/restore-all",
            json={},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return int(response.json()["removed"])
