from __future__ import annotations

import json
from base64 import b64decode
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.agent.models import AgentBudget, AgentState
from app.agent.providers import DeterministicReasoningProvider
from app.config import Settings
from app.models.domain import Incident, IncidentSeverity
from app.observability.provider import MeteredReasoningProvider
from app.observability.store import InMemoryObservabilityStore
from app.observability.tracing import (
    LangfuseSemanticSpanProcessor,
    _langfuse_headers,
    _langfuse_traces_endpoint,
    _safe_trace_metadata,
)


def _incident() -> Incident:
    return Incident(
        title="Langfuse trace probe",
        description="Public incident text used only for observability testing.",
        severity=IncidentSeverity.P2,
        service="checkout",
        start_time=datetime.now(UTC),
    )


def _span_probe(
    settings: Settings | None = None,
) -> tuple[TracerProvider, InMemorySpanExporter]:
    provider = TracerProvider()
    if settings is not None:
        provider.add_span_processor(LangfuseSemanticSpanProcessor(settings))
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def test_langfuse_trace_endpoint_is_normalized() -> None:
    expected = "http://langfuse-web:3000/api/public/otel/v1/traces"
    assert _langfuse_traces_endpoint("http://langfuse-web:3000") == expected
    assert (
        _langfuse_traces_endpoint("http://langfuse-web:3000/api/public/otel")
        == expected
    )
    assert _langfuse_traces_endpoint(expected) == expected


def test_langfuse_headers_use_basic_auth_and_v4_ingestion() -> None:
    settings = Settings(
        langfuse_enabled=True,
        langfuse_public_key="pk-test",
        langfuse_secret_key="sk-test",
    )

    headers = _langfuse_headers(settings)

    scheme, encoded = headers["Authorization"].split(" ", maxsplit=1)
    assert scheme == "Basic"
    assert b64decode(encoded).decode("utf-8") == "pk-test:sk-test"
    assert headers["x-langfuse-ingestion-version"] == "4"


def test_langfuse_enabled_without_project_keys_fails_closed() -> None:
    settings = Settings(langfuse_enabled=True)

    with pytest.raises(ValueError, match="LANGFUSE_PUBLIC_KEY"):
        _langfuse_headers(settings)


def test_safe_trace_metadata_contains_configuration_not_benchmark_truth() -> None:
    settings = Settings(
        agent_architecture="reactive_react",
        temporal_reasoning="explicit_cause_effect",
        tool_order="adaptive",
        tool_order_controlled=True,
        evidence_mode="verification_enabled",
        retrieval_depth=7,
        retrieval_depth_controlled=True,
        stopping_strategy="unresolved_evidence",
        compound_evidence_plan=True,
        max_steps=11,
        max_tool_calls=9,
        llm_provider="deterministic",
        llm_model="local-placeholder",
    )

    metadata = _safe_trace_metadata(settings)
    serialized = json.dumps(metadata, sort_keys=True).lower()

    assert metadata["agentArchitecture"] == "reactive_react"
    assert metadata["toolOrder"] == "adaptive"
    assert metadata["retrievalDepth"] == 7
    for forbidden in (
        "scenario",
        "ground_truth",
        "expected_root",
        "fault_state",
        "causal_timeline",
    ):
        assert forbidden not in serialized


def test_semantic_processor_maps_existing_agent_chain_and_tool_spans() -> None:
    settings = Settings(agent_architecture="explicit_planner", max_tool_calls=5)
    provider, exporter = _span_probe(settings)
    tracer = provider.get_tracer("test.langfuse.semantic")

    with tracer.start_as_current_span("agent.investigation"):
        with tracer.start_as_current_span("agent.node.plan"):
            pass
        with tracer.start_as_current_span("mcp.tool.query_metrics"):
            pass

    spans = {span.name: span for span in exporter.get_finished_spans()}
    root = spans["agent.investigation"]
    node = spans["agent.node.plan"]
    tool = spans["mcp.tool.query_metrics"]

    assert root.attributes["langfuse.observation.type"] == "agent"
    assert root.attributes["langfuse.trace.name"] == "OpsSentinel incident investigation"
    assert (
        root.attributes["langfuse.trace.metadata.agentArchitecture"]
        == "explicit_planner"
    )
    assert root.attributes["langfuse.trace.metadata.maxToolCalls"] == 5
    assert node.attributes["langfuse.observation.type"] == "chain"
    assert node.attributes["langfuse.observation.metadata.agentNode"] == "plan"
    assert tool.attributes["langfuse.observation.type"] == "tool"
    assert (
        tool.attributes["langfuse.observation.metadata.toolName"]
        == "query_metrics"
    )


@pytest.mark.asyncio
async def test_metered_provider_emits_generation_usage_without_prompt_or_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, exporter = _span_probe()
    tracer = provider.get_tracer("test.langfuse.generation")
    monkeypatch.setattr("app.observability.provider.model_tracer", lambda: tracer)

    state = AgentState(
        run_id=uuid4(),
        incident=_incident(),
        budget=AgentBudget(),
    )
    sink = InMemoryObservabilityStore()
    metered = MeteredReasoningProvider(DeterministicReasoningProvider(), sink)

    _plan, usage = await metered.plan(state)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "model.plan"
    assert span.attributes["langfuse.observation.type"] == "generation"
    assert span.attributes["langfuse.observation.model.name"] == metered.name
    assert span.attributes["langfuse.observation.metadata.runId"] == str(state.run_id)
    assert json.loads(span.attributes["langfuse.observation.usage_details"]) == {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "total": usage.total_tokens,
    }
    assert json.loads(span.attributes["langfuse.observation.cost_details"]) == {
        "total": usage.estimated_cost
    }
    serialized = repr(dict(span.attributes)).lower()
    assert "public incident text" not in serialized
    assert "raw_reference" not in serialized
    assert "evidence" not in serialized
    assert sink.events[0].run_id == state.run_id
