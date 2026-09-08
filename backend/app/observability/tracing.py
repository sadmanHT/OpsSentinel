from __future__ import annotations

from base64 import b64encode
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, ReadWriteSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Tracer

from app.config import Settings

_httpx_instrumented = False
_sqlalchemy_instrumented = False


def _traces_endpoint(endpoint: str) -> str:
    normalized = endpoint.rstrip("/")
    if normalized.endswith("/v1/traces"):
        return normalized
    return f"{normalized}/v1/traces"


def _langfuse_traces_endpoint(host: str) -> str:
    normalized = host.rstrip("/")
    if normalized.endswith("/api/public/otel/v1/traces"):
        return normalized
    if normalized.endswith("/api/public/otel"):
        return f"{normalized}/v1/traces"
    return f"{normalized}/api/public/otel/v1/traces"


def _langfuse_headers(settings: Settings) -> dict[str, str]:
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        raise ValueError(
            "Langfuse tracing requires OPSSENTINEL_LANGFUSE_PUBLIC_KEY and "
            "OPSSENTINEL_LANGFUSE_SECRET_KEY"
        )
    credentials = f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}"
    authorization = b64encode(credentials.encode("utf-8")).decode("ascii")
    return {
        "Authorization": f"Basic {authorization}",
        "x-langfuse-ingestion-version": "4",
    }


def _safe_trace_metadata(settings: Settings) -> dict[str, str | int | bool]:
    """Return runtime configuration only; never benchmark truth or hidden causal state."""

    return {
        "environment": settings.environment,
        "agentArchitecture": settings.agent_architecture,
        "temporalReasoning": settings.temporal_reasoning,
        "toolOrder": settings.tool_order,
        "toolOrderControlled": settings.tool_order_controlled,
        "evidenceMode": settings.evidence_mode,
        "retrievalDepth": settings.retrieval_depth,
        "retrievalDepthControlled": settings.retrieval_depth_controlled,
        "stoppingStrategy": settings.stopping_strategy,
        "compoundEvidencePlan": settings.compound_evidence_plan,
        "maxSteps": settings.max_steps,
        "maxToolCalls": settings.max_tool_calls,
        "llmProvider": settings.llm_provider,
        "llmModel": settings.llm_model,
    }


class LangfuseSemanticSpanProcessor(SpanProcessor):
    """Annotate existing OpsSentinel spans with Langfuse v4 observation semantics."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def on_start(
        self,
        span: ReadWriteSpan,
        parent_context: Context | None = None,
    ) -> None:
        del parent_context
        name = span.name
        if name == "agent.investigation":
            span.set_attribute("langfuse.observation.type", "agent")
            span.set_attribute("langfuse.trace.name", "OpsSentinel incident investigation")
            run_id = span.attributes.get("opssentinel.agent.run_id")
            if isinstance(run_id, str):
                span.set_attribute("langfuse.trace.metadata.runId", run_id)
                span.set_attribute("langfuse.observation.metadata.runId", run_id)
            for key, value in _safe_trace_metadata(self.settings).items():
                span.set_attribute(f"langfuse.trace.metadata.{key}", value)
                span.set_attribute(f"langfuse.observation.metadata.{key}", value)
            return
        if name.startswith("agent.node."):
            span.set_attribute("langfuse.observation.type", "chain")
            span.set_attribute(
                "langfuse.observation.metadata.agentNode",
                name.removeprefix("agent.node."),
            )
            return
        if name.startswith("mcp.tool."):
            span.set_attribute("langfuse.observation.type", "tool")
            span.set_attribute(
                "langfuse.observation.metadata.toolName",
                name.removeprefix("mcp.tool."),
            )

    def on_end(self, span: ReadableSpan) -> None:
        del span

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        del timeout_millis
        return True


def _redact_http_request_target(span: Span) -> None:
    """Remove request-target details that can encode MCP arguments or secrets."""

    for attribute in ("url.full", "url.query", "http.url", "http.target"):
        span.set_attribute(attribute, "[redacted]")
    span.set_attribute("opssentinel.http.request_target_redacted", True)


def _safe_server_request_hook(span: Span, _scope: dict[str, Any]) -> None:
    _redact_http_request_target(span)


def _safe_httpx_request_hook(span: Span, _request: Any) -> None:
    _redact_http_request_target(span)


async def _safe_async_httpx_request_hook(span: Span, _request: Any) -> None:
    _redact_http_request_target(span)


def _tracer_provider(settings: Settings) -> TracerProvider:
    existing = trace.get_tracer_provider()
    if isinstance(existing, TracerProvider):
        return existing

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.otel_service_name,
                "deployment.environment.name": settings.environment,
            }
        )
    )
    if settings.langfuse_enabled:
        provider.add_span_processor(LangfuseSemanticSpanProcessor(settings))
    if settings.otel_enabled:
        exporter = OTLPSpanExporter(
            endpoint=_traces_endpoint(settings.otel_exporter_otlp_endpoint)
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
    if settings.langfuse_enabled:
        langfuse_exporter = OTLPSpanExporter(
            endpoint=_langfuse_traces_endpoint(settings.langfuse_host),
            headers=_langfuse_headers(settings),
        )
        provider.add_span_processor(BatchSpanProcessor(langfuse_exporter))
    trace.set_tracer_provider(provider)
    return provider


def configure_backend_tracing(app: FastAPI, settings: Settings) -> TracerProvider | None:
    """Enable backend tracing only when OpenTelemetry or Langfuse explicitly opts in."""

    global _httpx_instrumented, _sqlalchemy_instrumented

    if not settings.otel_enabled and not settings.langfuse_enabled:
        return None

    provider = _tracer_provider(settings)
    if not getattr(app.state, "opssentinel_otel_instrumented", False):
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=provider,
            server_request_hook=_safe_server_request_hook,
        )
        app.state.opssentinel_otel_instrumented = True

    if not _httpx_instrumented:
        HTTPXClientInstrumentor().instrument(
            tracer_provider=provider,
            request_hook=_safe_httpx_request_hook,
            async_request_hook=_safe_async_httpx_request_hook,
        )
        _httpx_instrumented = True

    if not _sqlalchemy_instrumented:
        SQLAlchemyInstrumentor().instrument(tracer_provider=provider)
        _sqlalchemy_instrumented = True

    return provider


def agent_tracer() -> Tracer:
    return trace.get_tracer("opssentinel.agent")


def mcp_tracer() -> Tracer:
    return trace.get_tracer("opssentinel.mcp")


def model_tracer() -> Tracer:
    return trace.get_tracer("opssentinel.model")
