from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import Settings

_httpx_instrumented = False
_sqlalchemy_instrumented = False


def _traces_endpoint(endpoint: str) -> str:
    normalized = endpoint.rstrip("/")
    if normalized.endswith("/v1/traces"):
        return normalized
    return f"{normalized}/v1/traces"


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
    exporter = OTLPSpanExporter(endpoint=_traces_endpoint(settings.otel_exporter_otlp_endpoint))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def configure_backend_tracing(app: FastAPI, settings: Settings) -> TracerProvider | None:
    """Enable backend tracing only when the runtime explicitly opts in."""

    global _httpx_instrumented, _sqlalchemy_instrumented

    if not settings.otel_enabled:
        return None

    provider = _tracer_provider(settings)
    if not getattr(app.state, "opssentinel_otel_instrumented", False):
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
        app.state.opssentinel_otel_instrumented = True

    if not _httpx_instrumented:
        HTTPXClientInstrumentor().instrument(tracer_provider=provider)
        _httpx_instrumented = True

    if not _sqlalchemy_instrumented:
        SQLAlchemyInstrumentor().instrument(tracer_provider=provider)
        _sqlalchemy_instrumented = True

    return provider


def agent_tracer():
    return trace.get_tracer("opssentinel.agent")


def mcp_tracer():
    return trace.get_tracer("opssentinel.mcp")
