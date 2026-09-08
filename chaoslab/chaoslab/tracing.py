from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from chaoslab.config import ChaosConfig

_httpx_instrumented = False


def _traces_endpoint(endpoint: str) -> str:
    normalized = endpoint.rstrip("/")
    if normalized.endswith("/v1/traces"):
        return normalized
    return f"{normalized}/v1/traces"


def _tracer_provider(config: ChaosConfig) -> TracerProvider:
    existing = trace.get_tracer_provider()
    if isinstance(existing, TracerProvider):
        return existing

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": config.otel_service_name,
                "service.namespace": "opssentinel-chaoslab",
            }
        )
    )
    exporter = OTLPSpanExporter(
        endpoint=_traces_endpoint(config.otel_exporter_otlp_endpoint)
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def configure_chaoslab_tracing(
    app: FastAPI,
    config: ChaosConfig,
) -> TracerProvider | None:
    """Enable simulator tracing only when explicitly requested by the runtime."""

    global _httpx_instrumented

    if not config.otel_enabled:
        return None

    provider = _tracer_provider(config)
    if not getattr(app.state, "opssentinel_otel_instrumented", False):
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
        app.state.opssentinel_otel_instrumented = True

    if not _httpx_instrumented:
        HTTPXClientInstrumentor().instrument(tracer_provider=provider)
        _httpx_instrumented = True

    return provider
