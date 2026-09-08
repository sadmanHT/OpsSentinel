from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from prometheus_client import CONTENT_TYPE_LATEST

from app.config import get_settings
from app.observability.experiments import ExperimentDashboard, SqlExperimentDashboardStore
from app.observability.models import RunCostSummary, RunLatencySummary
from app.observability.prometheus import SqlPrometheusExporter
from app.observability.store import SqlObservabilityStore
from app.persistence.session import create_database_engine

router = APIRouter(prefix="/observability", tags=["observability"])
settings = get_settings()
engine = create_database_engine(settings)
store = SqlObservabilityStore(engine)
experiment_store = SqlExperimentDashboardStore(engine)
prometheus_exporter = SqlPrometheusExporter(engine)


@router.get("/runs/{run_id}/cost", response_model=RunCostSummary)
def get_run_cost_summary(run_id: UUID) -> RunCostSummary:
    summary = store.summarize(run_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="agent run not found")
    return summary


@router.get("/latency", response_model=RunLatencySummary)
def get_latency_summary() -> RunLatencySummary:
    return store.summarize_latency()


@router.get("/experiments", response_model=ExperimentDashboard)
def get_experiment_dashboard(
    limit: int = Query(default=20, ge=1, le=100),
) -> ExperimentDashboard:
    return experiment_store.list_runs(limit=limit)


@router.get("/metrics", response_class=Response)
def get_prometheus_metrics() -> Response:
    return Response(
        content=prometheus_exporter.render(),
        media_type=CONTENT_TYPE_LATEST,
    )
