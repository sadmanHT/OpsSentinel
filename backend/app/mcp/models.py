from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from app.models.domain import EvidenceType, RiskLevel, StrictModel, ToolCallStatus, utc_now


class ToolCategory(StrEnum):
    LOGS = "logs"
    METRICS = "metrics"
    DATABASE = "database"
    GIT = "git"
    DEPLOYMENTS = "deployments"
    DOCUMENTATION = "documentation"
    DIAGNOSTICS = "diagnostics"


class MetricName(StrEnum):
    REQUEST_RATE = "request_rate"
    ERROR_RATE = "error_rate"
    P50_LATENCY = "p50_latency"
    P95_LATENCY = "p95_latency"
    CPU_USAGE = "cpu_usage"
    MEMORY_USAGE = "memory_usage"
    DISK_USAGE = "disk_usage"
    DB_CONNECTIONS = "db_connections"
    DB_QUERY_COUNT = "db_query_count"
    CONTAINER_RESTARTS = "container_restarts"


class MetricAggregation(StrEnum):
    LATEST = "latest"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    SUM = "sum"


class DiagnosticCommand(StrEnum):
    DF = "df"
    FREE = "free"
    PS = "ps"
    CURL = "curl"
    PYTEST = "pytest"


class ToolInvocation(StrictModel):
    tool: str = Field(min_length=1, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolError(StrictModel):
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False


class EvidenceEnvelope(StrictModel):
    evidence_type: EvidenceType
    source: str = Field(min_length=1, max_length=120)
    service: str | None = Field(default=None, max_length=120)
    captured_at: datetime = Field(default_factory=utc_now)
    payload: Any
    truncated: bool = False


class ToolResponse(StrictModel):
    tool: str
    status: ToolCallStatus
    risk_level: RiskLevel
    started_at: datetime
    completed_at: datetime
    data: EvidenceEnvelope | None = None
    error: ToolError | None = None


class ToolDefinition(StrictModel):
    name: str
    description: str
    category: ToolCategory
    risk_level: RiskLevel
    input_schema: dict[str, Any]


class PermissionSet(StrictModel):
    principal: str = Field(min_length=1, max_length=120)
    allowed_tools: set[str] = Field(default_factory=set)
    allowed_services: set[str] = Field(default_factory=set)


class SearchLogsArgs(StrictModel):
    query: str | None = Field(default=None, max_length=200)
    service: str = Field(min_length=1, max_length=80)
    level: str | None = Field(default=None, pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    start_time: datetime | None = None
    end_time: datetime | None = None
    limit: int = Field(default=50, ge=1, le=100)


class QueryMetricsArgs(StrictModel):
    metric: MetricName
    service: str = Field(min_length=1, max_length=80)
    start_time: datetime | None = None
    end_time: datetime | None = None
    aggregation: MetricAggregation = MetricAggregation.LATEST


class ExecuteSqlArgs(StrictModel):
    query: str = Field(min_length=1, max_length=20_000)
    max_rows: int = Field(default=50, ge=1, le=100)


class InspectDeploymentArgs(StrictModel):
    service: str = Field(min_length=1, max_length=80)


class InspectCommitArgs(StrictModel):
    revision: str = Field(default="HEAD", min_length=1, max_length=80)


class InspectGitDiffArgs(StrictModel):
    base: str = Field(default="HEAD~1", min_length=1, max_length=80)
    head: str = Field(default="HEAD", min_length=1, max_length=80)


class SearchCodeArgs(StrictModel):
    query: str = Field(min_length=1, max_length=120)
    path: str | None = Field(default=None, max_length=240)
    limit: int = Field(default=50, ge=1, le=100)


class SearchDocumentationArgs(StrictModel):
    query: str = Field(min_length=1, max_length=120)
    path: str | None = Field(default=None, max_length=240)
    limit: int = Field(default=50, ge=1, le=100)


class RunDiagnosticArgs(StrictModel):
    command: DiagnosticCommand
    service: str | None = Field(default=None, max_length=80)
    path: str | None = Field(default=None, max_length=240)
    test: str | None = Field(default=None, max_length=240)
