import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.mcp.errors import (
    InvalidToolArguments,
    InvestigationToolError,
    ResultTooLarge,
    ToolTimeout,
)
from app.mcp.models import (
    EvidenceEnvelope,
    ExecuteSqlArgs,
    ExplainAnalyzeArgs,
    InspectCommitArgs,
    InspectDeploymentArgs,
    InspectGitDiffArgs,
    PermissionSet,
    QueryMetricsArgs,
    ReproduceRequestArgs,
    RerunLoadTestArgs,
    RunDiagnosticArgs,
    RunTestsArgs,
    SandboxServiceArgs,
    SearchCodeArgs,
    SearchDocumentationArgs,
    SearchLogsArgs,
    ToolCategory,
    ToolDefinition,
    ToolError,
    ToolInvocation,
    ToolResponse,
)
from app.mcp.phase5_tools import Phase5Tools
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
        "run_tests",
        "reproduce_request",
        "rerun_load_test",
        "explain_analyze",
        "restart_sandbox_service",
        "rollback_sandbox_deployment",
    }
    return PermissionSet(
        principal="phase5-agent",
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
    phase5_tools = Phase5Tools(
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
    registry.register(
        RegisteredTool(
            "run_tests",
            "Run an explicitly allowlisted deterministic backend test target.",
            ToolCategory.VERIFICATION,
            RiskLevel.R1,
            RunTestsArgs,
            phase5_tools.run_tests,
        )
    )
    registry.register(
        RegisteredTool(
            "reproduce_request",
            "Reproduce one allowlisted sandbox request and compare its observed status.",
            ToolCategory.VERIFICATION,
            RiskLevel.R1,
            ReproduceRequestArgs,
            phase5_tools.reproduce_request,
        )
    )
    registry.register(
        RegisteredTool(
            "rerun_load_test",
            "Rerun a bounded deterministic checkout load verification profile.",
            ToolCategory.VERIFICATION,
            RiskLevel.R1,
            RerunLoadTestArgs,
            phase5_tools.rerun_load_test,
        )
    )
    registry.register(
        RegisteredTool(
            "explain_analyze",
            "Run EXPLAIN ANALYZE against a validated read-only SELECT query.",
            ToolCategory.VERIFICATION,
            RiskLevel.R1,
            ExplainAnalyzeArgs,
            phase5_tools.explain_analyze,
        )
    )
    registry.register(
        RegisteredTool(
            "restart_sandbox_service",
            "Reset one allowlisted simulator service after explicit human approval.",
            ToolCategory.OPERATIONS,
            RiskLevel.R2,
            SandboxServiceArgs,
            phase5_tools.restart_sandbox_service,
        )
    )
    registry.register(
        RegisteredTool(
            "rollback_sandbox_deployment",
            "Restore one allowlisted simulator service to baseline after explicit human approval.",
            ToolCategory.OPERATIONS,
            RiskLevel.R2,
            SandboxServiceArgs,
            phase5_tools.rollback_sandbox_deployment,
        )
    )
    return registry
