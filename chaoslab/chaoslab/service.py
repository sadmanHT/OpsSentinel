import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

import httpx
from fastapi import FastAPI, HTTPException, Query

from chaoslab.config import ChaosConfig
from chaoslab.database import SimulatorDatabase
from chaoslab.effects import apply_pre_request_faults, disk_usage_ratio
from chaoslab.models import (
    FaultState,
    FaultType,
    ObservableLogRecord,
    ObservableMetric,
    ServiceSnapshot,
)
from chaoslab.runtime import RuntimeState
from chaoslab.state import FaultStore
from chaoslab.telemetry import Telemetry

config = ChaosConfig()
runtime = RuntimeState()
store = FaultStore(config.redis_url)
database = SimulatorDatabase(config.database_url)
telemetry = Telemetry(config.service_name, runtime)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if config.service_name in {"checkout", "inventory"}:
        for attempt in range(30):
            try:
                database.ensure_schema()
                break
            except Exception:
                if attempt == 29:
                    raise
                await asyncio.sleep(1)
    yield


app = FastAPI(title=f"ChaosLab {config.service_name}", lifespan=lifespan)
app.middleware("http")(telemetry.middleware)


def active_faults() -> list[FaultState]:
    return store.active_for(config.service_name)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": config.service_name}


@app.get("/metrics")
def metrics():
    return telemetry.prometheus_response()


@app.get("/telemetry", response_model=ServiceSnapshot)
def observable_snapshot() -> ServiceSnapshot:
    faults = active_faults()
    return ServiceSnapshot(
        service=config.service_name,
        request_count=runtime.request_count,
        error_count=runtime.error_count,
        last_latency_ms=runtime.last_latency_ms,
        db_query_count_last_request=runtime.db_query_count_last_request,
        simulated_db_connections=runtime.simulated_db_connections,
        simulated_disk_usage_ratio=disk_usage_ratio(faults, runtime),
        simulated_memory_leak_bytes=runtime.simulated_memory_leak_bytes,
        simulated_restarts=runtime.simulated_restarts,
    )


@app.get("/observability/logs", response_model=list[ObservableLogRecord])
def observable_logs(
    query: Annotated[str | None, Query(max_length=200)] = None,
    level: Annotated[
        str | None,
        Query(pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$"),
    ] = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ObservableLogRecord]:
    return telemetry.search_logs(
        query=query,
        level=level,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )


@app.get("/observability/metrics", response_model=ObservableMetric)
def observable_metric(
    metric: str,
    aggregation: Annotated[
        str,
        Query(pattern=r"^(latest|avg|min|max|sum)$"),
    ] = "latest",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> ObservableMetric:
    request_metrics = {"request_rate", "error_rate", "p50_latency", "p95_latency"}
    if metric in request_metrics:
        value, sample_count, unit = telemetry.request_metric(
            metric,
            start_time=start_time,
            end_time=end_time,
        )
    elif metric == "cpu_usage":
        elapsed = max(time.monotonic() - telemetry.started_monotonic, 0.001)
        value = (time.process_time() / elapsed) * 100.0
        sample_count = 1
        unit = "percent"
    elif metric == "memory_usage":
        value = float(runtime.simulated_memory_leak_bytes)
        sample_count = 1
        unit = "bytes"
    elif metric == "disk_usage":
        value = float(disk_usage_ratio(active_faults(), runtime))
        sample_count = 1
        unit = "ratio"
    elif metric == "db_connections":
        value = float(runtime.simulated_db_connections)
        sample_count = 1
        unit = "connections"
    elif metric == "db_query_count":
        value = float(runtime.db_query_count_last_request)
        sample_count = 1
        unit = "queries"
    elif metric == "container_restarts":
        value = float(runtime.simulated_restarts)
        sample_count = 1
        unit = "restarts"
    else:
        raise HTTPException(status_code=422, detail="unsupported metric")

    return ObservableMetric(
        metric=metric,
        service=config.service_name,
        value=value,
        unit=unit,
        aggregation=aggregation,
        sample_count=sample_count,
        start_time=start_time,
        end_time=end_time,
    )


@app.post("/internal/reset")
def reset_runtime() -> dict[str, str]:
    runtime.reset_fault_artifacts()
    runtime.db_query_count_last_request = 0
    return {"status": "reset", "service": config.service_name}


@app.get("/orders")
async def orders():
    if config.service_name != "checkout":
        raise HTTPException(status_code=404, detail="route unavailable")
    faults = active_faults()
    await apply_pre_request_faults(faults, runtime, config.disk_dir)
    n_plus_one = next((f for f in faults if f.fault == FaultType.N_PLUS_ONE), None)
    if n_plus_one:
        result, count = database.fetch_orders_n_plus_one()
        delay_ms = int(n_plus_one.configuration.get("delay_per_query_ms", 8))
        await asyncio.sleep((count * delay_ms) / 1000)
    else:
        result, count = database.fetch_orders_batch()
    runtime.db_query_count_last_request = count
    return {"orders": result, "query_count": count}


@app.get("/inventory/{sku}")
async def inventory(sku: str):
    if config.service_name != "inventory":
        raise HTTPException(status_code=404, detail="route unavailable")
    faults = active_faults()
    await apply_pre_request_faults(faults, runtime, config.disk_dir)
    runtime.db_query_count_last_request = 1
    with database.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT sku, name FROM sim_products WHERE sku = %s", (sku,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="sku not found")
    return {"sku": row[0], "name": row[1], "available": 25}


@app.post("/charge")
async def charge():
    if config.service_name != "payment":
        raise HTTPException(status_code=404, detail="route unavailable")
    await apply_pre_request_faults(active_faults(), runtime, config.disk_dir)
    return {"status": "authorized", "provider": "sandbox-payments"}


@app.post("/work")
async def work():
    if config.service_name != "worker":
        raise HTTPException(status_code=404, detail="route unavailable")
    await apply_pre_request_faults(active_faults(), runtime, config.disk_dir)
    return {"status": "processed"}


@app.get("/checkout")
async def gateway_checkout():
    if config.service_name != "gateway":
        raise HTTPException(status_code=404, detail="route unavailable")
    await apply_pre_request_faults(active_faults(), runtime, config.disk_dir)
    async with httpx.AsyncClient(timeout=10) as client:
        orders_response = await client.get(f"{config.checkout_url}/orders")
        if orders_response.status_code >= 500:
            raise HTTPException(status_code=502, detail="checkout dependency unavailable")
        if orders_response.status_code >= 400:
            raise HTTPException(
                status_code=orders_response.status_code,
                detail=orders_response.text,
            )
        payment_response = await client.post(f"{config.payment_url}/charge")
        if payment_response.status_code >= 400:
            raise HTTPException(status_code=502, detail="payment dependency failure")
    return {"orders": orders_response.json(), "payment": payment_response.json()}
