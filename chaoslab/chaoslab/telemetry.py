import json
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from math import ceil

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)

from chaoslab.models import ObservableLogRecord
from chaoslab.runtime import RuntimeState

logger = logging.getLogger("chaoslab")
logging.basicConfig(level=logging.INFO, format="%(message)s")


class Telemetry:
    def __init__(self, service_name: str, runtime: RuntimeState) -> None:
        self.service_name = service_name
        self.runtime = runtime
        self.started_monotonic = time.monotonic()
        self.recent_logs: deque[ObservableLogRecord] = deque(maxlen=1_000)
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "chaoslab_requests_total",
            "Total simulator requests",
            ["service", "path", "status"],
            registry=self.registry,
        )
        self.latency = Gauge(
            "chaoslab_last_request_latency_ms",
            "Latency of the most recent request",
            ["service"],
            registry=self.registry,
        )
        self.db_queries = Gauge(
            "chaoslab_db_queries_last_request",
            "Database queries performed by the most recent request",
            ["service"],
            registry=self.registry,
        )
        self.db_connections = Gauge(
            "chaoslab_simulated_db_connections",
            "Simulated active DB connections under connection-leak faults",
            ["service"],
            registry=self.registry,
        )
        self.memory_bytes = Gauge(
            "chaoslab_simulated_memory_leak_bytes",
            "Bounded bytes retained for the memory-leak simulation",
            ["service"],
            registry=self.registry,
        )
        self.restarts = Gauge(
            "chaoslab_simulated_restarts",
            "Controlled restart events triggered by fault simulation",
            ["service"],
            registry=self.registry,
        )

    async def middleware(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in {
            "/health",
            "/metrics",
            "/telemetry",
            "/observability/logs",
            "/observability/metrics",
        }:
            return await call_next(request)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.runtime.request_count += 1
            self.runtime.last_latency_ms = elapsed_ms
            if status >= 500:
                self.runtime.error_count += 1
            self.requests.labels(self.service_name, request.url.path, str(status)).inc()
            self.latency.labels(self.service_name).set(elapsed_ms)
            self.db_queries.labels(self.service_name).set(self.runtime.db_query_count_last_request)
            self.db_connections.labels(self.service_name).set(self.runtime.simulated_db_connections)
            self.memory_bytes.labels(self.service_name).set(
                self.runtime.simulated_memory_leak_bytes
            )
            self.restarts.labels(self.service_name).set(self.runtime.simulated_restarts)
            level = "ERROR" if status >= 500 else "WARNING" if status >= 400 else "INFO"
            record = ObservableLogRecord(
                timestamp=datetime.now(UTC),
                level=level,
                event="request_completed",
                service=self.service_name,
                method=request.method,
                path=request.url.path,
                status=status,
                latency_ms=round(elapsed_ms, 3),
                db_queries=self.runtime.db_query_count_last_request,
            )
            self.recent_logs.append(record)
            logger.info(json.dumps(record.model_dump(mode="json")))

    def prometheus_response(self) -> Response:
        return Response(generate_latest(self.registry), media_type=CONTENT_TYPE_LATEST)

    def search_logs(
        self,
        *,
        query: str | None,
        level: str | None,
        start_time: datetime | None,
        end_time: datetime | None,
        limit: int,
    ) -> list[ObservableLogRecord]:
        needle = query.casefold() if query else None
        results: list[ObservableLogRecord] = []
        for record in reversed(self.recent_logs):
            if level and record.level != level:
                continue
            if start_time and record.timestamp < start_time:
                continue
            if end_time and record.timestamp > end_time:
                continue
            if needle and needle not in json.dumps(record.model_dump(mode="json")).casefold():
                continue
            results.append(record)
            if len(results) >= limit:
                break
        return list(reversed(results))

    def request_metric(
        self,
        metric: str,
        *,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> tuple[float, int, str]:
        samples = [
            record
            for record in self.recent_logs
            if (start_time is None or record.timestamp >= start_time)
            and (end_time is None or record.timestamp <= end_time)
        ]
        if metric == "request_rate":
            if not samples:
                return 0.0, 0, "requests_per_second"
            if start_time and end_time:
                seconds = max((end_time - start_time).total_seconds(), 1.0)
            elif len(samples) > 1:
                seconds = max(
                    (samples[-1].timestamp - samples[0].timestamp).total_seconds(),
                    1.0,
                )
            else:
                seconds = 1.0
            return len(samples) / seconds, len(samples), "requests_per_second"
        if metric == "error_rate":
            if not samples:
                return 0.0, 0, "ratio"
            errors = sum(1 for record in samples if record.status >= 500)
            return errors / len(samples), len(samples), "ratio"
        if metric in {"p50_latency", "p95_latency"}:
            if not samples:
                return 0.0, 0, "milliseconds"
            values = sorted(record.latency_ms for record in samples)
            quantile = 0.5 if metric == "p50_latency" else 0.95
            index = max(0, min(len(values) - 1, ceil(quantile * len(values)) - 1))
            return values[index], len(values), "milliseconds"
        raise ValueError(f"unsupported request metric {metric}")
