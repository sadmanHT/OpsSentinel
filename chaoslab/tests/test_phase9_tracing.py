from fastapi import FastAPI

from chaoslab.config import ChaosConfig, _env_flag
from chaoslab.tracing import _traces_endpoint, configure_chaoslab_tracing


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
