from fastapi import APIRouter

from app.mcp.models import ToolDefinition, ToolInvocation, ToolResponse
from app.mcp.registry import build_registry

router = APIRouter(prefix="/mcp", tags=["mcp"])
registry = build_registry()


@router.get("/health")
def mcp_health() -> dict[str, object]:
    return {
        "status": "ok",
        "boundary": "controlled-investigation",
        "tool_count": len(registry.definitions()),
    }


@router.get("/tools", response_model=list[ToolDefinition])
def list_tools() -> list[ToolDefinition]:
    return registry.definitions()


@router.post("/invoke", response_model=ToolResponse)
async def invoke_tool(invocation: ToolInvocation) -> ToolResponse:
    return await registry.invoke(invocation)
