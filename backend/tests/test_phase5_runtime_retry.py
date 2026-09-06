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


def checkout_incident() -> Incident:
    return Incident(
        title="Checkout latency regression after deployment",
        description=(
            "Users report severe checkout latency immediately after the latest deployment."
        ),
        severity=IncidentSeverity.P1,
        service="checkout",
        start_time=datetime.now(UTC),
        scenario_id="phase5-retry-recovery",
    )


def build_retrying_registry() -> tuple[RetryingToolRegistry, dict[str, int]]:
    tool_names = {
        "query_metrics",
        "inspect_deployment",
        "inspect_git_diff",
        "search_logs",
        "rollback_sandbox_deployment",
        "rerun_load_test",
    }
    permissions = PermissionSet(
        principal="phase5-retry-trajectory-test",
        allowed_tools=tool_names,
        allowed_services={"checkout"},
    )
    registry = ToolRegistry(
        timeout_seconds=1.0,
        max_output_bytes=16_000,
        permissions=permissions,
    )
    attempts = {"db_query_count": 0}

    async def query_metrics(args: QueryMetricsArgs) -> EvidenceEnvelope:
        if args.metric == MetricName.DB_QUERY_COUNT:
            attempts["db_query_count"] += 1
            if attempts["db_query_count"] == 1:
                raise ServiceUnavailable("transient metrics dependency failure")
            value = 15
        else:
            value = 0.85
        return EvidenceEnvelope(
            evidence_type=EvidenceType.METRIC,
            source="test.query_metrics",
            service="checkout",
            payload={"value": value},
        )

    async def inspect_deployment(_args: InspectDeploymentArgs) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_type=EvidenceType.DEPLOYMENT,
            source="test.inspect_deployment",
            service="checkout",
            payload={
                "service": "checkout",
                "deployment": "phase5-retry-test",
                "health": {"status": "ok"},
            },
        )

    async def inspect_git_diff(_args: InspectGitDiffArgs) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_type=EvidenceType.CODE,
            source="test.inspect_git_diff",
            payload={
                "base": "HEAD~1",
                "head": "HEAD",
                "output": "checkout query path changed",
            },
        )

    async def search_logs(_args: SearchLogsArgs) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_type=EvidenceType.LOG,
            source="test.search_logs",
            service="checkout",
            payload=[{"path": "/orders", "status": 200, "db_queries": 15}],
        )

    async def rollback(_args: SandboxServiceArgs) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_type=EvidenceType.VERIFICATION,
            source="test.rollback_sandbox_deployment",
            service="checkout",
            payload={"action_executed": True, "receipt": {"status": "completed"}},
        )

    async def rerun_load_test(_args: RerunLoadTestArgs) -> EvidenceEnvelope:
        return EvidenceEnvelope(
            evidence_type=EvidenceType.VERIFICATION,
            source="test.rerun_load_test",
            service="gateway",
            payload={"passed": True, "requests": 20, "errors": 0},
        )

    for tool in (
        RegisteredTool(
            name="query_metrics",
            description="Return deterministic checkout metrics.",
            category=ToolCategory.METRICS,
            risk_level=RiskLevel.R0,
            args_model=QueryMetricsArgs,
            handler=query_metrics,
        ),
        RegisteredTool(
            name="inspect_deployment",
            description="Return deterministic deployment context.",
            category=ToolCategory.DEPLOYMENTS,
            risk_level=RiskLevel.R0,
            args_model=InspectDeploymentArgs,
            handler=inspect_deployment,
        ),
        RegisteredTool(
            name="inspect_git_diff",
            description="Return deterministic code-change context.",
            category=ToolCategory.GIT,
            risk_level=RiskLevel.R0,
            args_model=InspectGitDiffArgs,
            handler=inspect_git_diff,
        ),
        RegisteredTool(
            name="search_logs",
            description="Return deterministic checkout logs.",
            category=ToolCategory.LOGS,
            risk_level=RiskLevel.R0,
            args_model=SearchLogsArgs,
            handler=search_logs,
        ),
        RegisteredTool(
            name="rollback_sandbox_deployment",
            description="Perform a reversible approved sandbox rollback.",
            category=ToolCategory.OPERATIONS,
            risk_level=RiskLevel.R2,
            args_model=SandboxServiceArgs,
            handler=rollback,
        ),
        RegisteredTool(
            name="rerun_load_test",
            description="Verify checkout health after remediation.",
            category=ToolCategory.VERIFICATION,
            risk_level=RiskLevel.R1,
            args_model=RerunLoadTestArgs,
            handler=rerun_load_test,
        ),
    ):
        registry.register(tool)

    return (
        RetryingToolRegistry(
            registry,
            max_retries=2,
            backoff_seconds=0.0,
        ),
        attempts,
    )


@pytest.mark.asyncio
async def test_full_operational_run_recovers_from_retryable_investigation_failure() -> None:
    registry, attempts = build_retrying_registry()
    store = InMemoryAgentStore()
    runtime = Phase5Runtime(
        registry=registry,
        provider=DeterministicReasoningProvider(),
        store=store,
    )

    paused = await runtime.start(
        checkout_incident(),
        AgentBudget(max_steps=20, max_tool_calls=12),
        operational_mode=True,
    )

    assert paused.status == AgentRunStatus.PAUSED
    assert paused.operation_stage == OperationStage.WAIT_APPROVAL
    assert paused.diagnosis_code == "n_plus_one_query"
    assert paused.approval is not None
    assert paused.approval.decision == ApprovalDecision.PENDING
    assert attempts["db_query_count"] == 2
    assert len(paused.failures) == 1
    failure = paused.failures[0]
    assert failure.tool == "query_metrics"
    assert failure.retryable is True
    assert failure.attempt == 1
    assert paused.budget.tool_calls_used <= paused.budget.max_tool_calls

    completed = await runtime.decide_approval(
        paused.run_id,
        decision=ApprovalDecision.APPROVED,
        actor="incident-commander",
    )

    assert completed.status == AgentRunStatus.COMPLETED
    assert completed.operation_stage == OperationStage.COMPLETE
    assert completed.verification.status == VerificationStatus.PASSED
    assert completed.final_diagnosis is not None
    assert completed.final_diagnosis.verification_status == VerificationStatus.PASSED
    assert completed.failures == paused.failures
    assert completed.budget.tool_calls_used <= completed.budget.max_tool_calls
    assert all(call.risk_level != RiskLevel.R3 for call in completed.tool_history)
    assert [call.tool_name for call in completed.tool_history[-2:]] == [
        "rollback_sandbox_deployment",
        "rerun_load_test",
    ]

    persisted = store.load(completed.run_id)
    assert persisted is not None
    assert persisted.verification.status == VerificationStatus.PASSED
    assert persisted.failures == completed.failures
