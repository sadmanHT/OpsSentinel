from fastapi import FastAPI

from app.agent.api import router as agent_router
from app.config import get_settings
from app.mcp.api import router as mcp_router

settings = get_settings()

app = FastAPI(
    title="OpsSentinel API",
    version="0.3.0",
    description="Research platform for autonomous incident-response agents.",
)
app.include_router(mcp_router)
app.include_router(agent_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "opssentinel-backend",
        "environment": settings.environment,
        "version": app.version,
    }
