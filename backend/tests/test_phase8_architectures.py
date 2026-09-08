from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine

from app.agent.architectures import (
    ReactiveAgentRuntime,
    ReactivePhase5Runtime,
    ReactiveReasoningProvider,
)
from app.agent.models import AgentBudget
from app.agent.phase5_runtime import Phase5Runtime
from app.agent.providers import DeterministicReasoningProvider
from app.agent.runtime import AgentRuntime
from app.agent.service import AgentService
from app.agent.store import InMemoryAgentStore
from app.config import Settings
from app.mcp.models import EvidenceEnvelope, PermissionSet, ToolInvocation, ToolResponse
from app.mcp.registry import ToolRegistry
from app.models.domain import (
    AgentRunStatus,
    EvidenceType,
    Incident,
    IncidentSeverity,
    RiskLevel,
    ToolCallStatus,
    utc_now,
)


class ArchitectureRegistry(ToolRegistry):
    def __init__(self) -> None:
        super().__init__(
            timeout_seconds=1.0,
            max_output_bytes=64_000,
            permissions=PermissionSet(principal="phase8-architecture-test"),
        )

    async def invoke(
        self,
        invocation: ToolInvocation,
        *,
        trusted_approval_id: str | None = None,
    ) -> ToolResponse:
        now = utc_now()
        service = invocation.arguments.get("service")
        if invocation.tool == "query_metrics":
            metric = invocation.arguments["metric"]
            payload: object = {
                "value": {"p95_latency": 0.85, "db_query_count": 15}.get(metric, 0.0)
            }
            evidence_type = EvidenceType.METRIC
        elif invocation.tool == "search_logs":
            payload = [{"path": "/orders", "status": 200, "db_queries": 15}]
            evidence_type = EvidenceType.LOG
        else:
            raise AssertionError(f"unexpected architecture-test tool: {invocation.tool}")
        return ToolResponse(
            tool=invocation.tool,
            status=ToolCallStatus.SUCCEEDED,
            risk_level=RiskLevel.R0,
            started_at=now,
            completed_at=utc_now(),
            data=EvidenceEnvelope(
                evidence_type=evidence_type,
                source=f"architecture-test.{invocation.tool}",
                service=str(service) if service is not None else None,
                payload=payload,
            ),
        )


class CountingProvider(DeterministicReasoningProvider):
    def __init__(self) -> None:
        self.plan_calls = 0

    async def plan(self, state):  # type: ignore[no-untyped-def]
        self.plan_calls += 1
        return await super().plan(state)


def checkout_incident() -> Incident:
    return Incident(
        title="Checkout latency regression",
        description="Users report severe checkout latency.",
        severity=IncidentSeverity.P1,
        service="checkout",
        start_time=datetime.now(UTC),
        scenario_id="phase8-architecture-test",
    )


@pytest.mark.asyncio
async def test_reactive_runtime_replans_after_each_observation() -> None:
    explicit_provider = CountingProvider()
    explicit = AgentRuntime(
        registry=ArchitectureRegistry(),
        provider=explicit_provider,
        store=InMemoryAgentStore(),
    )
    explicit_state = await explicit.start(checkout_incident(), AgentBudget())

    reactive_base = CountingProvider()
    reactive_provider = ReactiveReasoningProvider(reactive_base)
    reactive = ReactiveAgentRuntime(
        registry=ArchitectureRegistry(),
        provider=reactive_provider,
        store=InMemoryAgentStore(),
    )
    reactive_state = await reactive.start(checkout_incident(), AgentBudget())

    assert explicit_state.status == AgentRunStatus.COMPLETED
    assert reactive_state.status == AgentRunStatus.COMPLETED
    assert explicit_state.diagnosis_code == "n_plus_one_query"
    assert reactive_state.diagnosis_code == "n_plus_one_query"
    assert explicit_provider.plan_calls == 1
    assert reactive_provider.plan_calls == 3
    assert [call.tool_name for call in explicit_state.tool_history] == [
        "query_metrics",
        "query_metrics",
        "search_logs",
    ]
    assert [call.tool_name for call in reactive_state.tool_history] == [
        "query_metrics",
        "query_metrics",
        "search_logs",
    ]
    assert reactive_state.final_diagnosis is not None
    assert reactive_state.final_diagnosis.evidence_ids


def test_agent_service_defaults_to_explicit_planner() -> None:
    service = AgentService(
        settings=Settings(agent_architecture="explicit_planner"),
        engine=create_engine("sqlite:///:memory:"),
        registry=ArchitectureRegistry(),
        provider=DeterministicReasoningProvider(),
    )

    assert service.runtime_type is Phase5Runtime
    assert type(service.runtime) is Phase5Runtime
    assert service.store.architecture_version == Phase5Runtime.architecture_version


def test_agent_service_selects_reactive_architecture() -> None:
    service = AgentService(
        settings=Settings(agent_architecture="reactive_react"),
        engine=create_engine("sqlite:///:memory:"),
        registry=ArchitectureRegistry(),
        provider=DeterministicReasoningProvider(),
    )

    assert service.runtime_type is ReactivePhase5Runtime
    assert isinstance(service.runtime, ReactivePhase5Runtime)
    assert service.store.architecture_version == ReactivePhase5Runtime.architecture_version
