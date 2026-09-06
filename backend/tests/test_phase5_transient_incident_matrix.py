from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from app.agent.models import AgentBudget, ApprovalDecision, OperationStage
from app.agent.phase5_runtime import Phase5Runtime
from app.agent.providers import DeterministicReasoningProvider
from app.agent.store import InMemoryAgentStore
from app.mcp.errors import ServiceUnavailable
from app.mcp.models import (
    EvidenceEnvelope,
    InspectDeploymentArgs,
    InspectGitDiffArgs,
    MetricName,
    PermissionSet,
    QueryMetricsArgs,
    ReproduceRequestArgs,
    RerunLoadTestArgs,
    SandboxServiceArgs,
    SearchLogsArgs,
    ToolCategory,
)
from app.mcp.registry import RegisteredTool, ToolRegistry
from app.mcp.retrying import RetryingToolRegistry
from app.models.domain import (
    AgentRunStatus,
    EvidenceType,
    Incident,
    IncidentSeverity,
    RiskLevel,
    VerificationStatus,
)


@dataclass(frozen=True)
class IncidentCase:
    name: str
    service: str
    title: str
    description: str
    expected_code: str
    transient_tool: str


CASES = [
    IncidentCase(
        name="n-plus-one",
        service="checkout",
        title="Checkout latency regression after release",
        description="Checkout became slow after the latest release.",
        expected_code="n_plus_one_query",
        transient_tool="query_metrics",
    ),
    IncidentCase(
        name="connection-leak",
        service="inventory",
        title="Inventory requests are failing",
        description="Inventory becomes unavailable under ordinary request traffic.",
        expected_code="database_connection_leak",
        transient_tool="query_metrics",
    ),
    IncidentCase(
        name="disk-exhaustion",
        service="worker",
        title="Worker jobs fail with storage errors",
        description="Worker processing fails after sustained output generation.",
        expected_code="disk_exhaustion",
        transient_tool="search_logs",
    ),
    IncidentCase(
        name="broken-config",
        service="payment",
        title="Payment authentication failures",
        description="Checkout fails because the payment dependency rejects requests.",
        expected_code="broken_payment_configuration",
        transient_tool="search_logs",
    ),
    IncidentCase(
        name="memory-leak",
        service="worker",
        title="Worker restarts after memory growth",
        description="Repeated jobs show resource growth followed by a service failure.",
        expected_code="memory_leak",
        transient_tool="query_metrics",
    ),
]


def incident_for(case: IncidentCase) -> Incident:
    return Incident(
        title=case.title,
        description=case.description,
        severity=IncidentSeverity.P1,
        service=case.service,
        start_time=datetime.now(UTC),
        scenario_id=f"phase5-transient-{case.name}",
    )


def build_registry(case: IncidentCase) -> RetryingToolRegistry:
    tool_names = {
        "query_metrics",
        "search_logs",
        "inspect_deployment",
        "inspect_git_diff",
        "rollback_sandbox_deployment",
        "rerun_load_test",
        "reproduce_request",
    }
    permissions = PermissionSet(
        principal=f"phase5-transient-{case.name}",
        allowed_tools=tool_names,
        allowed_services={"gateway", "checkout", "inventory", "payment", "worker"},
    )
    inner = ToolRegistry(
        timeout_seconds=1.0,
        max_output_bytes=32_000,
        permissions=permissions,
    )
    failed_once = False

    async def maybe_fail(tool_name: str) -> None:
        nonlocal failed_once
        if tool_name == case.transient_tool and not failed_once:
            failed_once = True
            raise ServiceUnavailable("injected transient dependency failure")

    async def query_metrics(args: QueryMetricsArgs) -> EvidenceEnvelope:
        await maybe_fail("query_metrics")
        values = {
            MetricName.P95_LATENCY: 0.85,
            MetricName.DB_QUERY_COUNT: 15 if case.name == "n-plus-one" else 1,
            MetricName.DB_CONNECTIONS: 4 if case.name == "connection-leak" else 0,
            MetricName.DISK_USAGE: 1.0 if case.name == "disk-exhaustion" else 0.0,
            MetricName.MEMORY_USAGE: 0.8 if case.name == "memory-leak" else 0.0,
            MetricName.CONTAINER_RESTARTS: 1 if case.name == "memory-leak" else 0,
        }
        return EvidenceEnvelope(
            evidence_type=EvidenceType.METRIC,
            source="test.query_metrics",
            service=args.service,
            payload={"value": values.get(args.metric, 0.0)},
        )

    async def search_logs(args: SearchLogsArgs) -> EvidenceEnvelope:
        await maybe_fail("search_logs")
        payload: list[dict[str, int]] = []
        if case.name == "n-plus-one" and args.service == "checkout":
            payload = [{"status": 200, "db_queries": 15}]
        elif case.name == "connection-leak" and args.service == "inventory":
            payload = [{"status": 503, "db_queries": 1}]
        elif case.name == "disk-exhaustion" and args.service == "worker":
            payload = [{"status": 507, "db_queries": 0}]
        elif case.name == "memory-leak" and args.service == "worker":
            payload = [{"status": 503, "db_queries": 0}]
        elif case.name == "broken-config" and args.service == "payment":
            payload = [{"status": 401, "db_queries": 0}]
        elif case.name == "broken-config" and args.service == "gateway":
            payload = [{"status": 502, "db_queries": 0}]
        return EvidenceEnvelope(
            evidence_type=EvidenceType.LOG,
            source="test.search_logs",
            service=args.service,
            payload=payload,
        )

    async def inspect_deployment(args: InspectDeploymentArgs) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_type=EvidenceType.DEPLOYMENT,
            source="test.inspect_deployment",
            service=args.service,
            payload={"service": args.service, "deployment": "phase5-transient"},
        )

    async def inspect_git_diff(_args: InspectGitDiffArgs) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_type=EvidenceType.CODE,
            source="test.inspect_git_diff",
            payload={"base": "HEAD~1", "head": "HEAD", "output": "query path changed"},
        )

    async def rollback(args: SandboxServiceArgs) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_type=EvidenceType.VERIFICATION,
            source="test.rollback",
            service=args.service,
            payload={"action_executed": True},
        )

    async def rerun_load(_args: RerunLoadTestArgs) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_type=EvidenceType.VERIFICATION,
            source="test.rerun_load_test",
            service="gateway",
            payload={"passed": True, "requests": 20, "errors": 0},
        )

    async def reproduce(args: ReproduceRequestArgs) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_type=EvidenceType.VERIFICATION,
            source="test.reproduce_request",
            service=args.service,
            payload={"passed": True, "observed_status": args.expected_status},
        )

    registrations = [
        RegisteredTool(
            "query_metrics",
            "Deterministic transient matrix metrics.",
            ToolCategory.METRICS,
            RiskLevel.R0,
            QueryMetricsArgs,
            query_metrics,
        ),
        RegisteredTool(
            "search_logs",
            "Deterministic transient matrix logs.",
            ToolCategory.LOGS,
            RiskLevel.R0,
            SearchLogsArgs,
            search_logs,
        ),
        RegisteredTool(
            "inspect_deployment",
            "Deterministic deployment context.",
            ToolCategory.DEPLOYMENTS,
            RiskLevel.R0,
            InspectDeploymentArgs,
            inspect_deployment,
        ),
        RegisteredTool(
            "inspect_git_diff",
            "Deterministic git context.",
            ToolCategory.GIT,
            RiskLevel.R0,
            InspectGitDiffArgs,
            inspect_git_diff,
        ),
        RegisteredTool(
            "rollback_sandbox_deployment",
            "Approved reversible sandbox rollback.",
            ToolCategory.OPERATIONS,
            RiskLevel.R2,
            SandboxServiceArgs,
            rollback,
        ),
        RegisteredTool(
            "rerun_load_test",
            "Deterministic post-action load verification.",
            ToolCategory.VERIFICATION,
            RiskLevel.R1,
            RerunLoadTestArgs,
            rerun_load,
        ),
        RegisteredTool(
            "reproduce_request",
            "Deterministic post-action request verification.",
            ToolCategory.VERIFICATION,
            RiskLevel.R1,
            ReproduceRequestArgs,
            reproduce,
        ),
    ]
    for registration in registrations:
        inner.register(registration)
    return RetryingToolRegistry(inner, max_retries=1, backoff_seconds=0.0)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda item: item.name)
async def test_each_core_incident_recovers_from_transient_evidence_failure(
    case: IncidentCase,
) -> None:
    runtime = Phase5Runtime(
        registry=build_registry(case),
        provider=DeterministicReasoningProvider(),
        store=InMemoryAgentStore(),
    )

    paused = await runtime.start(
        incident_for(case),
        AgentBudget(max_steps=30, max_tool_calls=24),
        operational_mode=True,
    )

    assert paused.status == AgentRunStatus.PAUSED
    assert paused.operation_stage == OperationStage.WAIT_APPROVAL
    assert paused.diagnosis_code == case.expected_code
    assert paused.approval is not None
    assert paused.approval.decision == ApprovalDecision.PENDING
    assert len(paused.failures) == 1
    assert paused.failures[0].tool == case.transient_tool
    assert paused.failures[0].retryable is True
    assert paused.retry_counts[case.transient_tool] == 1

    completed = await runtime.decide_approval(
        paused.run_id,
        decision=ApprovalDecision.APPROVED,
        actor="phase5-transient-test",
    )

    assert completed.status == AgentRunStatus.COMPLETED
    assert completed.operation_stage == OperationStage.COMPLETE
    assert completed.verification.status == VerificationStatus.PASSED
    assert completed.final_diagnosis is not None
    assert completed.final_diagnosis.verification_status == VerificationStatus.PASSED
    assert completed.failures == paused.failures
    assert completed.budget.tool_calls_used <= completed.budget.max_tool_calls
    assert all(call.risk_level != RiskLevel.R3 for call in completed.tool_history)
