from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from OPSSENTINEL_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="OPSSENTINEL_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://opssentinel:opssentinel@localhost:5432/opssentinel"
    redis_url: str = "redis://localhost:6379/0"
    llm_provider: str = "local"
    llm_model: str = "local-placeholder"
    llm_timeout_seconds: float = Field(default=30.0, ge=0.1, le=300.0)
    local_model_base_url: str = "http://localhost:11434"
    max_steps: int = Field(default=20, ge=1, le=200)
    max_tool_calls: int = Field(default=15, ge=1, le=200)
    max_repeated_identical_calls: int = Field(default=2, ge=1, le=20)
    agent_time_limit_seconds: float = Field(default=120.0, ge=1.0, le=3600.0)
    agent_token_budget: int = Field(default=32_000, ge=0, le=10_000_000)
    agent_cost_budget: float = Field(default=0.0, ge=0.0, le=10_000.0)
    max_tool_retries: int = Field(default=2, ge=0, le=10)
    tool_retry_backoff_seconds: float = Field(default=0.05, ge=0.0, le=10.0)
    max_non_progress_steps: int = Field(default=3, ge=1, le=20)
    random_seed: int = 42
    langfuse_enabled: bool = False
    langfuse_host: str = "http://localhost:3000"
    otel_enabled: bool = False

    mcp_database_url: str = (
        "postgresql://opssentinel_reader:opssentinel_readonly@localhost:5432/opssentinel"
    )
    mcp_repo_root: Path = Path("/workspace")
    mcp_docs_root: Path = Path("/workspace/docs")
    mcp_tool_timeout_seconds: float = Field(default=3.0, ge=0.1, le=30.0)
    mcp_diagnostic_timeout_seconds: float = Field(default=10.0, ge=0.1, le=60.0)
    mcp_max_output_bytes: int = Field(default=64_000, ge=1_024, le=1_000_000)
    mcp_backend_url: str = "http://localhost:8000"
    mcp_gateway_url: str = "http://localhost:8080"
    mcp_checkout_url: str = "http://localhost:8101"
    mcp_inventory_url: str = "http://localhost:8102"
    mcp_payment_url: str = "http://localhost:8103"
    mcp_worker_url: str = "http://localhost:8104"
    sandbox_actuator_url: str = "http://chaoslab-controller:8080"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
