from datetime import UTC, datetime

import pytest

from app.agent.models import AgentBudget, AgentState, ProviderUsage
from app.agent.providers import DeterministicReasoningProvider
from app.agent.resilience import DiminishingReturnsReasoningProvider
from app.mcp.errors import ServiceUnavailable, UnsafeOperation
from app.mcp.models import EvidenceEnvelope, PermissionSet, ToolCategory, ToolInvocation
from app.mcp.registry import RegisteredTool, ToolRegistry
from app.mcp.registry_support import EmptyArgs
from app.mcp.retrying import RetryingToolRegistry
from app.models.domain import (
    EvidenceType,
    Incident,
    IncidentSeverity,
    RiskLevel,
    ToolCall,
    ToolCallStatus,
    utc_now,
)


class NeverEnoughProvider(DeterministicReasoningProvider):
    async def enough_evidence(self, state: AgentState) -> tuple[bool, ProviderUsage]:
        return False, ProviderUsage()


def incident() -> Incident:
    return Incident(
        title="Retry resilience incident",
        description="Exercise Phase 5 retry and diminishing-return behavior.",
        severity=IncidentSeverity.P2,
        service="checkout",
        start_time=datetime.now(UTC),
        scenario_id="phase5-resilience",
    )


def registry_for(handler, *, tool_name: str = "flaky") -> ToolRegistry:
    permissions = PermissionSet(
        principal="phase5-resilience-test",
        allowed_tools={tool_name},
        allowed_services=set(),
    )
    registry = ToolRegistry(
        timeout_seconds=1.0,
        max_output_bytes=16_000,
        permissions=permissions,
    )
    registry.register(
        RegisteredTool(
            name=tool_name,
            description="Phase 5 resilience test tool.",
            category=ToolCategory.DIAGNOSTICS,
            risk_level=RiskLevel.R0,
            args_model=EmptyArgs,
            handler=handler,
        )
    )
    return registry


@pytest.mark.asyncio
async def test_retrying_registry_retries_only_retryable_failures() -> None:
    attempts = 0

    async def flaky(_args: EmptyArgs) -> EvidenceEnvelope:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ServiceUnavailable("temporary dependency failure")
        return EvidenceEnvelope(
            evidence_type=EvidenceType.DIAGNOSTIC,
            source="test.flaky",
            payload={"attempt": attempts},
        )

    registry = RetryingToolRegistry(
        registry_for(flaky),
        max_retries=2,
        backoff_seconds=0.0,
    )
    response = await registry.invoke(ToolInvocation(tool="flaky", arguments={}))
    failures = registry.drain_failures()

    assert response.status == ToolCallStatus.SUCCEEDED
    assert attempts == 3
    assert [event.attempt for event in failures] == [1, 2]
    assert all(event.retryable for event in failures)


@pytest.mark.asyncio
async def test_retrying_registry_does_not_retry_blocked_unsafe_operation() -> None:
    attempts = 0

    async def blocked(_args: EmptyArgs) -> EvidenceEnvelope:
        nonlocal attempts
        attempts += 1
        raise UnsafeOperation("blocked by policy")

    registry = RetryingToolRegistry(
        registry_for(blocked),
        max_retries=5,
        backoff_seconds=0.0,
    )
    response = await registry.invoke(ToolInvocation(tool="flaky", arguments={}))
    failures = registry.drain_failures()

    assert response.status == ToolCallStatus.BLOCKED
    assert attempts == 1
    assert len(failures) == 1
    assert failures[0].retryable is False


@pytest.mark.asyncio
async def test_diminishing_returns_stops_after_repeated_non_progress() -> None:
    provider = DiminishingReturnsReasoningProvider(
        NeverEnoughProvider(),
        max_non_progress_steps=2,
    )
    state = AgentState(
        run_id=incident().id,
        incident=incident(),
        budget=AgentBudget(),
    )

    for _ in range(2):
        now = utc_now()
        state.tool_history.append(
            ToolCall(
                tool_name="query_metrics",
                arguments={"service": "checkout", "metric": "p95_latency"},
                started_at=now,
                completed_at=now,
                status=ToolCallStatus.FAILED,
                risk_level=RiskLevel.R0,
            )
        )
        enough, _usage = await provider.enough_evidence(state)

    assert enough is True
    assert state.non_progress_count == 2
