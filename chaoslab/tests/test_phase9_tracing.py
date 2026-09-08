import pytest
from fastapi import FastAPI
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from chaoslab.config import ChaosConfig, _env_flag
from chaoslab.tracing import (
    _safe_async_httpx_request_hook,
    _safe_httpx_request_hook,
    _traces_endpoint,
    configure_chaoslab_tracing,
)


def test_trace_endpoint_is_normalized_once() -> None:
    assert _traces_endpoint("http://otel-collector:4318") == (
        "http://otel-collector:4318/v1/traces"
    )
    assert _traces_endpoint("http://otel-collector:4318/v1/traces") == (
        "http://otel-collector:4318/v1/traces"
    )


def test_chaoslab_tracing_is_disabled_by_default() -> None:
    app = FastAPI()
    config = ChaosConfig()

    assert config.otel_enabled is False
    assert configure_chaoslab_tracing(app, config) is None
    assert not getattr(app.state, "opssentinel_otel_instrumented", False)


def test_chaoslab_trace_service_name_is_isolated_per_service() -> None:
    assert ChaosConfig(service_name="gateway").otel_service_name == "chaoslab-gateway"
    assert ChaosConfig(service_name="checkout").otel_service_name == "chaoslab-checkout"


def test_environment_flag_parser_is_strict(monkeypatch) -> None:
    monkeypatch.setenv("CHAOSLAB_TEST_FLAG", "true")
    assert _env_flag("CHAOSLAB_TEST_FLAG") is True
    monkeypatch.setenv("CHAOSLAB_TEST_FLAG", "0")
    assert _env_flag("CHAOSLAB_TEST_FLAG", default=True) is False


@pytest.mark.asyncio
async def test_httpx_trace_hooks_redact_request_targets_before_export() -> None:
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test.chaoslab.httpx")
    secret = "must-not-enter-chaoslab-client-span"
    attributes = {
        "url.full": f"http://checkout:8080/internal/reset?secret={secret}",
        "url.query": f"secret={secret}",
        "http.url": f"http://checkout:8080/internal/reset?secret={secret}",
        "http.target": f"/internal/reset?secret={secret}",
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
