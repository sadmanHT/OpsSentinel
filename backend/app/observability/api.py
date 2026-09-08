from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.observability.models import RunCostSummary, RunLatencySummary
from app.observability.store import SqlObservabilityStore
from app.persistence.session import create_database_engine

router = APIRouter(prefix="/observability", tags=["observability"])
settings = get_settings()
store = SqlObservabilityStore(create_database_engine(settings))


@router.get("/runs/{run_id}/cost", response_model=RunCostSummary)
def get_run_cost_summary(run_id: UUID) -> RunCostSummary:
    summary = store.summarize(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="agent run not found")
    return summary


@router.get("/latency", response_model=RunLatencySummary)
def get_latency_summary() -> RunLatencySummary:
    return store.summarize_latency()
