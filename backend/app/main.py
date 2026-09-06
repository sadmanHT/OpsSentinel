from fastapi import FastAPI

from app.config import get_settings
from app.mcp.api import router as mcp_router

settings = get_settings()

app = FastAPI(
    title="OpsSentinel API",
    version="0.2.0",
    description="Research platform for autonomous incident-response agents.",
)
app.include_router(mcp_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "opssentinel-backend",
        "environment": settings.environment,
        "version": app.version,
    }
