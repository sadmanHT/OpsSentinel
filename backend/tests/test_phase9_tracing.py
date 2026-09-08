from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel

from app.agent.models import AgentBudget, AgentNode
from app.agent.providers import DeterministicReasoningProvider
from app.agent.runtime import AgentRuntime
from app.agent.store import InMemoryAgentStore
from app.config import Settings
from app.mcp.models import (
    EvidenceEnvelope,
    PermissionSet,
    ToolCategory,
    ToolInvocation,
)
from app.mcp.registry import RegisteredTool, ToolRegistry
from app.models.domain import (
    AgentRunStatus,
    EvidenceType,
    Incident,
    IncidentSeverity,
    RiskLevel,
    ToolCallStatus,
)
from app.observability.tracing import (
    _safe_async_httpx_request_hook,
    _safe_httpx_request_hook,
    _traces_endpoint,
    configure_backend_tracing,
)


class SecretArgs(BaseModel):
    secret: str


def _span_probe() -> tuple[TracerProvider, InMemorySpanExporter]:
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def _incident() -> Incident:
    return Incident(
        title="Trace propagation probe",
        description="Public incident text used only to exercise the tracing boundary.",
        severity=IncidentSeverity.P2,
        service="checkout",
        start_time=datetime.now(UTC),
        scenario_id="trace-probe-scenario",
    )


def test_otlp_http_trace_endpoint_is_normalized_once() -> None:
    assert _traces_endpoint("http://otel-collector:4318") == (
        "http://otel-collector:4318/v1/traces"
    )
    assert _traces_endpoint("http://otel-collector:4318/v1/traces") == (
        "http://otel-collector:4318/v1/traces"
    )


def test_backend_tracing_remains_disabled_by_default() -> None:
    app = FastAPI()
    settings = Settings(otel_enabled=False)

    assert configure_backend_tracing(app, settings) is None
    assert not getattr(app.state, "opssentinel_otel_instrumented", False)


@pytest.mark.asyncio
async def test_httpx_trace_hooks_redact_request_targets_before_export() -> None:
    provider, exporter = _span_probe()
    tracer = provider.get_tracer("test.httpx")
    secret = "must-not-enter-http-client-span"
    attributes = {
        "url.full": f"http://checkout:8080/metrics?secret={secret}",
        "url.query": f"secret={secret}",
        "http.url": f"http://checkout:8080/metrics?secret={secret}",
        "http.target": f"/metrics?secret={secret}",
    }

    with tracer.start_as_current_span("sync-client", attributes=attributes) as span:
        _safe_httpx_request_hook(span, object())
    with tracer.start_as_current_span("async-client", attributes=attributes) as span:
        await _safe_async_httpx_request_hook(span, object())

    spans = exporter.get_finished_spans()
    assert {span.name for span in spans} == {"sync-client", "async-client"}
    for span in spans:
        assert span.attributes["url.full"] == "[redacted]"
        assert span.attributes["url.query"] == "[redacted]"
        assert span.attributes["http.url"] == "[redacted]"
        assert span.attributes["http.target"] == "[redacted]"
        assert span.attributes["opssentinel.http.request_target_redacted"] is True
        assert secret not in repr(dict(span.attributes))


@pytest.mark.asyncio
async def test_agent_runtime_emits_run_and_node_spans_without_scenario_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, exporter = _span_probe()
    tracer = provider.get_tracer("test.agent")
    monkeypatch.setattr("app.agent.runtime.agent_tracer", lambda: tracer)

    runtime = AgentRuntime(
        registry=object(),  # type: ignore[arg-type]
        provider=DeterministicReasoningProvider(),
        store=InMemoryAgentStore(),
        interrupt_after=[AgentNode.TRIAGE],
    )
    state = await runtime.start(_incident(), AgentBudget())

    assert state.status == AgentRunStatus.PAUSED
    spans = exporter.get_finished_spans()
    names = {span.name for span in spans}
    assert "agent.investigation" in names
    assert "agent.node.triage" in names

    root = next(span for span in spans if span.name == "agent.investigation")
    triage = next(span for span in spans if span.name == "agent.node.triage")
    assert root.attributes["opssentinel.agent.run_id"] == str(state.run_id)
    assert root.attributes["opssentinel.agent.architecture"] == AgentRuntime.architecture_version
    assert root.attributes["opssentinel.agent.service"] == "checkout"
    assert triage.parent is not None
    assert triage.parent.span_id == root.context.span_id
    assert all(
        "scenario" not in key
        for span in spans
        for key in span.attributes
    )


@pytest.mark.asyncio
async def test_mcp_trace_records_outcome_without_serializing_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, exporter = _span_probe()
    tracer = provider.get_tracer("test.mcp")
    monkeypatch.setattr("app.mcp.registry.mcp_tracer", lambda: tracer)

    permissions = PermissionSet(
        principal="trace-test",
        allowed_tools={"trace_probe"},
        allowed_services=set(),
    )
    target = ToolRegistry(
        timeout_seconds=0.1,
        max_output_bytes=1_024,
        permissions=permissions,
    )

    async def handler(_args: SecretArgs) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_type=EvidenceType.DIAGNOSTIC,
            source="trace-test",
            payload={"ok": True},
        )

    target.register(
        RegisteredTool(
            "trace_probe",
            "Trace-only test tool.",
            ToolCategory.DIAGNOSTICS,
            RiskLevel.R1,
            SecretArgs,
            handler,
        )
    )
    secret = "must-not-enter-span-attributes"
    response = await target.invoke(
        ToolInvocation(tool="trace_probe", arguments={"secret": secret})
    )

    assert response.status == ToolCallStatus.SUCCEEDED
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "mcp.tool.trace_probe"
    assert span.attributes["opssentinel.mcp.tool"] == "trace_probe"
    assert span.attributes["opssentinel.mcp.principal"] == "trace-test"
    assert span.attributes["opssentinel.mcp.risk_level"] == RiskLevel.R1.value
    assert span.attributes["opssentinel.mcp.status"] == ToolCallStatus.SUCCEEDED.value
    serialized_attributes = repr(dict(span.attributes))
    assert secret not in serialized_attributes
    assert "arguments" not in serialized_attributes
