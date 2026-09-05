from functools import lru_cache
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
    max_steps: int = Field(default=20, ge=1, le=200)
    max_tool_calls: int = Field(default=15, ge=1, le=200)
    random_seed: int = 42
    langfuse_enabled: bool = False
    langfuse_host: str = "http://localhost:3000"
    otel_enabled: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
