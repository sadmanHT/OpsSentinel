from datetime import UTC, datetime

from chaoslab.models import ObservableLogRecord
from chaoslab.runtime import RuntimeState
from chaoslab.telemetry import Telemetry


def test_log_search_is_bounded_and_filterable() -> None:
    telemetry = Telemetry("checkout", RuntimeState())
    telemetry.recent_logs.extend(
        [
            ObservableLogRecord(
                timestamp=datetime.now(UTC),
                level="INFO",
                event="request_completed",
                service="checkout",
                method="GET",
                path="/orders",
                status=200,
                latency_ms=10.0,
                db_queries=1,
            ),
            ObservableLogRecord(
                timestamp=datetime.now(UTC),
                level="ERROR",
                event="request_completed",
                service="checkout",
                method="GET",
                path="/orders",
                status=503,
                latency_ms=25.0,
                db_queries=20,
            ),
        ]
    )
    result = telemetry.search_logs(
        query="/orders",
        level="ERROR",
        start_time=None,
        end_time=None,
        limit=1,
    )
    assert len(result) == 1
    assert result[0].status == 503


def test_request_metrics_use_observable_log_history() -> None:
    telemetry = Telemetry("checkout", RuntimeState())
    now = datetime.now(UTC)
    telemetry.recent_logs.extend(
        [
            ObservableLogRecord(
                timestamp=now,
                level="INFO",
                event="request_completed",
                service="checkout",
                method="GET",
                path="/orders",
                status=200,
                latency_ms=10.0,
                db_queries=1,
            ),
            ObservableLogRecord(
                timestamp=now,
                level="ERROR",
                event="request_completed",
                service="checkout",
                method="GET",
                path="/orders",
                status=500,
                latency_ms=30.0,
                db_queries=20,
            ),
        ]
    )
    error_rate, count, unit = telemetry.request_metric(
        "error_rate",
        start_time=None,
        end_time=None,
    )
    p95, _, latency_unit = telemetry.request_metric(
        "p95_latency",
        start_time=None,
        end_time=None,
    )
    assert error_rate == 0.5
    assert count == 2 and unit == "ratio"
    assert p95 == 30.0 and latency_unit == "milliseconds"
