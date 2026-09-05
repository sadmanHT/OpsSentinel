import asyncio

import httpx
from fastapi import FastAPI, HTTPException

from chaoslab.config import ChaosConfig
from chaoslab.models import FaultSpec, FaultState, RestoreRequest
from chaoslab.state import FaultStore

config = ChaosConfig()
store = FaultStore(config.redis_url)
app = FastAPI(title="ChaosLab Controller")

SERVICE_URLS = {
    "gateway": "http://gateway:8080",
    "checkout": "http://checkout:8080",
    "inventory": "http://inventory:8080",
    "payment": "http://payment:8080",
    "worker": "http://worker:8080",
}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "chaoslab-controller"}


@app.post("/faults/inject", response_model=FaultState)
def inject_fault(spec: FaultSpec) -> FaultState:
    if spec.service not in SERVICE_URLS:
        raise HTTPException(status_code=422, detail="unknown service")
    return store.inject(spec)


@app.get("/faults", response_model=list[FaultState])
def list_faults() -> list[FaultState]:
    return store.list_all()


async def reset_service(service: str) -> None:
    url = SERVICE_URLS.get(service)
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            await client.post(f"{url}/internal/reset")
    except httpx.HTTPError:
        return


@app.post("/faults/restore")
async def restore_fault(request: RestoreRequest) -> dict[str, int | str]:
    if request.service not in SERVICE_URLS:
        raise HTTPException(status_code=422, detail="unknown service")
    removed = store.restore(request.service, request.fault)
    await reset_service(request.service)
    return {"status": "restored", "removed": removed}


@app.post("/faults/restore-all")
async def restore_all() -> dict[str, int | str]:
    removed = store.restore_all()
    await asyncio.gather(*(reset_service(service) for service in SERVICE_URLS))
    return {"status": "restored", "removed": removed}
