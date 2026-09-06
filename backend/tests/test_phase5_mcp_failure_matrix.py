import asyncio
from typing import cast

import pytest

from app.mcp.errors import ServiceUnavailable
from app.mcp.models import (
    EvidenceEnvelope,
    PermissionSet,
    ToolCategory,
    ToolInvocation,
)
from app.mcp.registry import RegisteredTool, ToolRegistry
from app.mcp.registry_support import EmptyArgs
from app.mcp.retrying import RetryingToolRegistry
from app.models.domain import EvidenceType, RiskLevel, ToolCallStatus


MAJOR_TOOLS = [
    ("search_logs", RiskLevel.R0),
    ("query_metrics", RiskLevel.R0),
    ("execute_sql", RiskLevel.R0),
    ("list_deployments", RiskLevel.R0),
    ("inspect_deployment", RiskLevel.R0),
    ("inspect_commit", RiskLevel.R0),
    ("inspect_git_diff", RiskLevel.R0),
    ("search_code", RiskLevel.R0),
    ("search_documentation", RiskLevel.R0),
    ("run_diagnostic", RiskLevel.R1),
    ("run_tests", RiskLevel.R1),
    ("reproduce_request", RiskLevel.R1),
    ("rerun_load_test", RiskLevel.R1),
    ("explain_analyze", RiskLevel.R1),
    ("restart_sandbox_service", RiskLevel.R2),
    ("rollback_sandbox_deployment", RiskLevel.R2),
]


def registry_for(
    tool_name: str,
    risk_level: RiskLevel,
    handler,
    *,
    timeout_seconds: float = 0.1,
) -> RetryingToolRegistry:
    permissions = PermissionSet(
        principal="phase5-failure-matrix",
        allowed_tools={tool_name},
        allowed_services=set(),
    )
    inner = ToolRegistry(
        timeout_seconds=timeout_seconds,
        max_output_bytes=16_000,
        permissions=permissions,
    )
    inner.register(
        RegisteredTool(
            name=tool_name,
            description="Phase 5 failure-matrix tool.",
            category=ToolCategory.DIAGNOSTICS,
            risk_level=risk_level,
            args_model=EmptyArgs,
            handler=handler,
        )
    )
    return RetryingToolRegistry(inner, max_retries=1, backoff_seconds=0.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool_name", "risk_level"), MAJOR_TOOLS)
async def test_every_major_tool_recovers_from_retryable_unavailability(
    tool_name: str,
    risk_level: RiskLevel,
) -> None:
    attempts = 0

    async def transient(_args: EmptyArgs) -> EvidenceEnvelope:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ServiceUnavailable("injected transient 503/unavailable dependency")
        return EvidenceEnvelope(
            evidence_type=EvidenceType.DIAGNOSTIC,
            source=f"test.{tool_name}",
            payload={"recovered": True},
        )

    registry = registry_for(tool_name, risk_level, transient)
    registry.begin_capture()
    response = await registry.invoke(
        ToolInvocation(tool=tool_name, arguments={}),
        trusted_approval_id="phase5-approved-test" if risk_level == RiskLevel.R2 else None,
    )
    failures = registry.drain_failures()

    assert response.status == ToolCallStatus.SUCCEEDED
    assert attempts == 2
    assert len(failures) == 1
    assert failures[0].tool == tool_name
    assert failures[0].code == "service_unavailable"
    assert failures[0].retryable is True
    assert failures[0].attempt == 1


@pytest.mark.asyncio
async def test_timeout_is_recorded_retried_and_recovers() -> None:
    attempts = 0

    async def transient_timeout(_args: EmptyArgs) -> EvidenceEnvelope:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await asyncio.sleep(0.05)
        return EvidenceEnvelope(
            evidence_type=EvidenceType.DIAGNOSTIC,
            source="test.timeout",
            payload={"recovered": True},
        )

    registry = registry_for(
        "search_logs",
        RiskLevel.R0,
        transient_timeout,
        timeout_seconds=0.005,
    )
    registry.begin_capture()
    response = await registry.invoke(ToolInvocation(tool="search_logs", arguments={}))
    failures = registry.drain_failures()

    assert response.status == ToolCallStatus.SUCCEEDED
    assert attempts == 2
    assert len(failures) == 1
    assert failures[0].code == "timeout"
    assert failures[0].retryable is True


@pytest.mark.asyncio
async def test_malformed_result_becomes_failure_instead_of_escaping() -> None:
    async def malformed(_args: EmptyArgs) -> EvidenceEnvelope:
        return cast(EvidenceEnvelope, {"malformed": True})

    registry = registry_for("query_metrics", RiskLevel.R0, malformed)
    registry.begin_capture()
    response = await registry.invoke(ToolInvocation(tool="query_metrics", arguments={}))
    failures = registry.drain_failures()

    assert response.status == ToolCallStatus.FAILED
    assert response.error is not None
    assert response.error.code == "unexpected_tool_error"
    assert response.error.retryable is False
    assert len(failures) == 1
    assert failures[0].code == "unexpected_tool_error"


@pytest.mark.asyncio
async def test_unexpected_handler_exception_becomes_bounded_failure() -> None:
    async def broken(_args: EmptyArgs) -> EvidenceEnvelope:
        raise RuntimeError("injected malformed handler failure")

    registry = registry_for("search_documentation", RiskLevel.R0, broken)
    registry.begin_capture()
    response = await registry.invoke(
        ToolInvocation(tool="search_documentation", arguments={})
    )
    failures = registry.drain_failures()

    assert response.status == ToolCallStatus.FAILED
    assert response.error is not None
    assert response.error.code == "unexpected_tool_error"
    assert "injected malformed handler failure" not in response.error.message
    assert len(failures) == 1
    assert failures[0].retryable is False


@pytest.mark.asyncio
async def test_partial_metric_payload_is_preserved_without_crashing() -> None:
    async def partial(_args: EmptyArgs) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_type=EvidenceType.METRIC,
            source="test.partial_metrics",
            service="checkout",
            payload={"partial": True, "available": ["p95_latency"]},
        )

    registry = registry_for("query_metrics", RiskLevel.R0, partial)
    registry.begin_capture()
    response = await registry.invoke(ToolInvocation(tool="query_metrics", arguments={}))

    assert response.status == ToolCallStatus.SUCCEEDED
    assert response.data is not None
    assert response.data.payload == {"partial": True, "available": ["p95_latency"]}
    assert registry.drain_failures() == []
