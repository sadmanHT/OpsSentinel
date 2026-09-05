import json
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)

from chaoslab.runtime import RuntimeState

logger = logging.getLogger("chaoslab")
logging.basicConfig(level=logging.INFO, format="%(message)s")


class Telemetry:
    def __init__(self, service_name: str, runtime: RuntimeState) -> None:
        self.service_name = service_name
        self.runtime = runtime
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
        if request.url.path in {"/health", "/metrics"}:
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
            logger.info(
                json.dumps(
                    {
                        "event": "request_completed",
                        "service": self.service_name,
                        "method": request.method,
                        "path": request.url.path,
                        "status": status,
                        "latency_ms": round(elapsed_ms, 3),
                        "db_queries": self.runtime.db_query_count_last_request,
                    }
                )
            )

    def prometheus_response(self) -> Response:
        return Response(generate_latest(self.registry), media_type=CONTENT_TYPE_LATEST)
