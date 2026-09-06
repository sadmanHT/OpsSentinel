from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.agent.models import AgentRunView, StartInvestigationRequest
from app.agent.service import AgentService, build_agent_service

router = APIRouter(prefix="/agent", tags=["agent"])
service: AgentService = build_agent_service()


@router.get("/health")
def agent_health() -> dict[str, object]:
    return {
        "status": "ok",
        "architecture": service.runtime.architecture_version,
        "provider": service.provider.name,
        "legal_tool_count": len(service.runtime.registry.definitions()),
    }


@router.post(
    "/runs",
    response_model=AgentRunView,
    status_code=status.HTTP_201_CREATED,
)
async def start_investigation(request: StartInvestigationRequest) -> AgentRunView:
    return await service.start(request)


@router.get("/runs/{run_id}", response_model=AgentRunView)
def get_investigation(run_id: UUID) -> AgentRunView:
    view = service.get(run_id)
    if view is None:
        raise HTTPException(status_code=404, detail="agent run not found")
    return view


@router.post("/runs/{run_id}/resume", response_model=AgentRunView)
async def resume_investigation(run_id: UUID) -> AgentRunView:
    try:
        return await service.resume(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent run not found") from exc
