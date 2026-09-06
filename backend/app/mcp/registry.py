import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.mcp.errors import (
    InvestigationToolError,
    InvalidToolArguments,
    ResultTooLarge,
    ToolTimeout,
)
from app.mcp.models import (
    EvidenceEnvelope,
    ExecuteSqlArgs,
    InspectCommitArgs,
    InspectDeploymentArgs,
    InspectGitDiffArgs,
    PermissionSet,
    QueryMetricsArgs,
    RunDiagnosticArgs,
    SearchCodeArgs,
    SearchDocumentationArgs,
    SearchLogsArgs,
    ToolCategory,
    ToolDefinition,
    ToolError,
    ToolInvocation,
    ToolResponse,
)
from app.mcp.policy import RiskPolicy, authorize_tool
from app.mcp.registry_support import EmptyArgs
from app.mcp.services import ServiceClient
from app.mcp.tools import InvestigationTools
from app.models.domain import RiskLevel, ToolCallStatus, utc_now

Handler = Callable[[Any], Awaitable[EvidenceEnvelope]]


@dataclass
class RegisteredTool:
    name: str
    description: str
    category: ToolCategory
    risk_level: RiskLevel
    args_model: type[BaseModel]
    handler: Handler

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            category=self.category,
            risk_level=self.risk_level,
            input_schema=self.args_model.model_json_schema(),
        )


class ToolRegistry:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_output_bytes: int,
        permissions: PermissionSet,
        policy: RiskPolicy | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.permissions = permissions
        self.policy = policy or RiskPolicy()
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def definitions(self) -> list[ToolDefinition]:
        return [self._tools[name].definition() for name in sorted(self._tools)]

    async def invoke(
        self,
        invocation: ToolInvocation,
        *,
        trusted_approval_id: str | None = None,
    ) -> ToolResponse:
        started = utc_now()
        risk = RiskLevel.R0
        try:
            tool = self._tools.get(invocation.tool)
            if tool is None:
                raise InvalidToolArguments(f"unknown tool {invocation.tool!r}")
            risk = tool.risk_level
            authorize_tool(self.permissions, tool.name)
            self.policy.authorize(risk, trusted_approval_id)
            try:
                args = tool.args_model.model_validate(invocation.arguments)
            except ValidationError as exc:
                raise InvalidToolArguments("arguments do not match the tool schema") from exc

            try:
                async with asyncio.timeout(self.timeout_seconds):
                    evidence = await tool.handler(args)
            except TimeoutError as exc:
                raise ToolTimeout("tool execution timed out") from exc

            encoded = json.dumps(
                evidence.model_dump(mode="json"),
                separators=(",", ":"),
                default=str,
            ).encode()
            if len(encoded) > self.max_output_bytes:
                raise ResultTooLarge(
                    f"tool result exceeded {self.max_output_bytes} byte output limit"
                )
            return ToolResponse(
                tool=invocation.tool,
                status=ToolCallStatus.SUCCEEDED,
                risk_level=risk,
                started_at=started,
                completed_at=utc_now(),
                data=evidence,
            )
        except InvestigationToolError as exc:
            status = ToolCallStatus.BLOCKED if exc.blocked else ToolCallStatus.FAILED
            return ToolResponse(
                tool=invocation.tool,
                status=status,
                risk_level=risk,
                started_at=started,
                completed_at=utc_now(),
                error=ToolError(code=exc.code, message=exc.message, retryable=exc.retryable),
            )


def default_permissions() -> PermissionSet:
    tools = {
        "search_logs",
        "query_metrics",
        "execute_sql",
        "list_deployments",
        "inspect_deployment",
        "inspect_commit",
        "inspect_git_diff",
        "search_code",
        "search_documentation",
        "run_diagnostic",
    }
    return PermissionSet(
        principal="phase4-agent",
        allowed_tools=tools,
        allowed_services={"backend", "gateway", "checkout", "inventory", "payment", "worker"},
    )


def build_registry(
    settings: Settings | None = None,
    *,
    permissions: PermissionSet | None = None,
    service_client: ServiceClient | None = None,
) -> ToolRegistry:
    resolved_settings = settings or get_settings()
    resolved_permissions = permissions or default_permissions()
    tools = InvestigationTools(
        resolved_settings,
        resolved_permissions,
        service_client=service_client,
    )
    registry = ToolRegistry(
        timeout_seconds=resolved_settings.mcp_tool_timeout_seconds,
        max_output_bytes=resolved_settings.mcp_max_output_bytes,
        permissions=resolved_permissions,
    )
    registry.register(
        RegisteredTool(
            "search_logs",
            "Search structured service logs with bounded filters and result count.",
            ToolCategory.LOGS,
            RiskLevel.R0,
            SearchLogsArgs,
            tools.search_logs,
        )
    )
    registry.register(
        RegisteredTool(
            "query_metrics",
            "Query an allowlisted service metric over an optional time window.",
            ToolCategory.METRICS,
            RiskLevel.R0,
            QueryMetricsArgs,
            tools.query_metrics,
        )
    )
    registry.register(
        RegisteredTool(
            "execute_sql",
            "Run bounded read-only SELECT, SHOW, EXPLAIN, or EXPLAIN ANALYZE SQL.",
            ToolCategory.DATABASE,
            RiskLevel.R0,
            ExecuteSqlArgs,
            tools.execute_sql,
        )
    )
    registry.register(
        RegisteredTool(
            "list_deployments",
            "List legal observable deployments and their health.",
            ToolCategory.DEPLOYMENTS,
            RiskLevel.R0,
            EmptyArgs,
            tools.list_deployments,
        )
    )
    registry.register(
        RegisteredTool(
            "inspect_deployment",
            "Inspect one allowlisted deployment without hidden fault state.",
            ToolCategory.DEPLOYMENTS,
            RiskLevel.R0,
            InspectDeploymentArgs,
            tools.inspect_deployment,
        )
    )
    registry.register(
        RegisteredTool(
            "inspect_commit",
            "Inspect a bounded Git commit from the read-only repository snapshot.",
            ToolCategory.GIT,
            RiskLevel.R0,
            InspectCommitArgs,
            tools.inspect_commit,
        )
    )
    registry.register(
        RegisteredTool(
            "inspect_git_diff",
            "Inspect a bounded Git diff between validated revisions.",
            ToolCategory.GIT,
            RiskLevel.R0,
            InspectGitDiffArgs,
            tools.inspect_git_diff,
        )
    )
    registry.register(
        RegisteredTool(
            "search_code",
            "Search repository text under the read-only repository root.",
            ToolCategory.GIT,
            RiskLevel.R0,
            SearchCodeArgs,
            tools.search_code,
        )
    )
    registry.register(
        RegisteredTool(
            "search_documentation",
            "Search documentation under the approved documentation root.",
            ToolCategory.DOCUMENTATION,
            RiskLevel.R0,
            SearchDocumentationArgs,
            tools.search_documentation,
        )
    )
    registry.register(
        RegisteredTool(
            "run_diagnostic",
            "Run one explicitly allowlisted diagnostic command with no shell.",
            ToolCategory.DIAGNOSTICS,
            RiskLevel.R1,
            RunDiagnosticArgs,
            tools.run_diagnostic,
        )
    )
    return registry
