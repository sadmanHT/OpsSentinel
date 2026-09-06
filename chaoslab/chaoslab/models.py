from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FaultType(StrEnum):
    N_PLUS_ONE = "n_plus_one"
    CONNECTION_LEAK = "connection_leak"
    DISK_EXHAUSTION = "disk_exhaustion"
    BROKEN_CONFIG = "broken_config"
    MEMORY_LEAK = "memory_leak"


class Severity(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class FaultSpec(StrictModel):
    fault: FaultType
    service: str = Field(min_length=1, max_length=80)
    severity: Severity = Severity.P2
    seed: int = 42
    configuration: dict[str, Any] = Field(default_factory=dict)


class FaultState(FaultSpec):
    active: bool = True
    generation: int = Field(default=1, ge=1)


class RestoreRequest(StrictModel):
    service: str = Field(min_length=1, max_length=80)
    fault: FaultType | None = None


class ServiceSnapshot(StrictModel):
    service: str
    request_count: int
    error_count: int
    last_latency_ms: float
    db_query_count_last_request: int
    simulated_db_connections: int
    simulated_disk_usage_ratio: float
    simulated_memory_leak_bytes: int
    simulated_restarts: int
