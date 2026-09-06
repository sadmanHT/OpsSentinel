import asyncio

import pytest
from fastapi import HTTPException

from chaoslab.effects import apply_pre_request_faults
from chaoslab.models import FaultState, FaultType, Severity
from chaoslab.runtime import RuntimeState


def run_fault_until_failure(fault: FaultState, runtime: RuntimeState, tmp_path) -> int:
    for request_number in range(1, 20):
        try:
            asyncio.run(apply_pre_request_faults([fault], runtime, str(tmp_path)))
        except HTTPException:
            return request_number
    raise AssertionError("fault never reached its failure condition")


def test_higher_disk_severity_fails_earlier(tmp_path) -> None:
    failures: dict[Severity, int] = {}
    for severity in Severity:
        runtime = RuntimeState()
        fault = FaultState(
            fault=FaultType.DISK_EXHAUSTION,
            service="worker",
            severity=severity,
            configuration={"max_files": 10},
        )
        failures[severity] = run_fault_until_failure(fault, runtime, tmp_path / severity.value)

    assert failures[Severity.P1] < failures[Severity.P2] < failures[Severity.P3]


def test_higher_memory_severity_fails_earlier_and_memory_is_bounded(tmp_path) -> None:
    failures: dict[Severity, int] = {}
    max_bytes = 1_048_576
    for severity in Severity:
        runtime = RuntimeState()
        fault = FaultState(
            fault=FaultType.MEMORY_LEAK,
            service="worker",
            severity=severity,
            configuration={"chunk_bytes": 131_072, "max_bytes": max_bytes},
        )
        failures[severity] = run_fault_until_failure(fault, runtime, tmp_path)
        assert runtime.simulated_memory_leak_bytes <= max_bytes
        assert runtime.simulated_restarts == 1

    assert failures[Severity.P1] < failures[Severity.P2] < failures[Severity.P3]


def test_connection_leak_eventually_exhausts_pool(tmp_path) -> None:
    runtime = RuntimeState()
    fault = FaultState(
        fault=FaultType.CONNECTION_LEAK,
        service="inventory",
        severity=Severity.P3,
        configuration={"capacity": 4},
    )

    with pytest.raises(HTTPException) as exc_info:
        for _ in range(4):
            asyncio.run(apply_pre_request_faults([fault], runtime, str(tmp_path)))

    assert exc_info.value.status_code == 503
    assert runtime.simulated_db_connections == 4
