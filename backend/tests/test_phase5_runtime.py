from datetime import UTC, datetime

import pytest

from app.agent.models import (
    AgentBudget,
    AgentState,
    ApprovalDecision,
    OperationStage,
    ProposedAction,
    ProviderUsage,
)
from app.agent.phase5_runtime import Phase5Runtime
from app.agent.providers import DeterministicReasoningProvider
from app.agent.store import InMemoryAgentStore
from app.mcp.models import EvidenceEnvelope, ToolInvocation, ToolResponse
from app.models.domain import (
    AgentRunStatus,
    EvidenceType,
    Incident,
    IncidentSeverity,
    RiskLevel,
    ToolCallStatus,
    VerificationStatus,
    utc_now,
)


class FakePhase5Registry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def invoke(
        self,
        invocation: ToolInvocation,
        *,
        trusted_approval_id: str | None = None,
    ) -> ToolResponse:
        self.calls.append((invocation.tool, trusted_approval_id))
        now = utc_now()
        service = invocation.arguments.get("service")
        risk = RiskLevel.R0
        evidence_type = EvidenceType.DIAGNOSTIC
        payload: object

        if invocation.tool == "query_metrics":
            evidence_type = EvidenceType.METRIC
            values = {"p95_latency": 0.85, "db_query_count": 15}
            payload = {"value": values.get(invocation.arguments["metric"], 0.0)}
        elif invocation.tool == "search_logs":
            evidence_type = EvidenceType.LOG
            payload = [{"path": "/orders", "status": 200, "db_queries": 15}]
        elif invocation.tool == "inspect_deployment":
            evidence_type = EvidenceType.DEPLOYMENT
            payload = {
                "service": service,
                "deployment": "phase5-test",
                "health": {"status": "ok"},
            }
        elif invocation.tool == "inspect_git_diff":
            evidence_type = EvidenceType.CODE
            payload = {
                "base": "HEAD~1",
                "head": "HEAD",
                "output": "checkout query path changed",
            }
        elif invocation.tool == "rollback_sandbox_deployment":
            risk = RiskLevel.R2
            assert trusted_approval_id is not None
            evidence_type = EvidenceType.VERIFICATION
            payload = {"action_executed": True, "receipt": {"status": "rolled_back"}}
        elif invocation.tool == "rerun_load_test":
            risk = RiskLevel.R1
            evidence_type = EvidenceType.VERIFICATION
            payload = {"passed": True, "requests": 20, "errors": 0}
        else:
            raise AssertionError(f"unexpected fake tool: {invocation.tool}")

        return ToolResponse(
            tool=invocation.tool,
            status=ToolCallStatus.SUCCEEDED,
            risk_level=risk,
            started_at=now,
            completed_at=utc_now(),
            data=EvidenceEnvelope(
                evidence_type=evidence_type,
                source=f"fake.{invocation.tool}",
                service=str(service) if service is not None else None,
                payload=payload,
            ),
        )


class DestructiveRecommendationProvider(DeterministicReasoningProvider):
    async def recommend(
        self,
        state: AgentState,
    ) -> tuple[ProposedAction | None, ProviderUsage]:
        assert state.final_diagnosis is not None
        return (
            ProposedAction(
                description="Destroy the sandbox database.",
                risk_level=RiskLevel.R3,
                rationale="Deliberately unsafe recommendation for a policy regression test.",
                evidence_ids=state.final_diagnosis.evidence_ids,
                tool="destroy_database",
                arguments={},
            ),
            ProviderUsage(),
        )


def checkout_incident() -> Incident:
    return Incident(
        title="Checkout latency regression after deployment",
        description="Users report severe checkout latency immediately after the latest deployment.",
        severity=IncidentSeverity.P1,
        service="checkout",
        start_time=datetime.now(UTC),
        scenario_id="phase5-unit-n-plus-one",
    )


@pytest.mark.asyncio
async def test_operational_run_pauses_for_r2_approval_then_verifies() -> None:
    registry = FakePhase5Registry()
    store = InMemoryAgentStore()
    runtime = Phase5Runtime(
        registry=registry,  # type: ignore[arg-type]
        provider=DeterministicReasoningProvider(),
        store=store,
    )

    paused = await runtime.start(
        checkout_incident(),
        AgentBudget(max_tool_calls=12),
        operational_mode=True,
    )

    assert paused.status == AgentRunStatus.PAUSED
    assert paused.operation_stage == OperationStage.WAIT_APPROVAL
    assert paused.approval is not None
    assert paused.approval.decision == ApprovalDecision.PENDING
    assert paused.proposed_action is not None
    assert paused.proposed_action.risk_level == RiskLevel.R2
    assert not any(call[0] == "rollback_sandbox_deployment" for call in registry.calls)

    completed = await runtime.decide_approval(
        paused.run_id,
        decision=ApprovalDecision.APPROVED,
        actor="incident-commander",
    )

    assert completed.status == AgentRunStatus.COMPLETED
    assert completed.operation_stage == OperationStage.COMPLETE
    assert completed.approval is not None
    assert completed.approval.decision == ApprovalDecision.APPROVED
    assert completed.approval.decided_by == "incident-commander"
    assert completed.verification.status == VerificationStatus.PASSED
    assert completed.final_diagnosis is not None
    assert completed.final_diagnosis.verification_status == VerificationStatus.PASSED
    action_calls = [call for call in registry.calls if call[0] == "rollback_sandbox_deployment"]
    assert len(action_calls) == 1
    assert action_calls[0][1] == str(completed.approval.id)
    assert registry.calls[-1][0] == "rerun_load_test"
    persisted = store.load(completed.run_id)
    assert persisted is not None
    assert persisted.verification.status == VerificationStatus.PASSED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision",
    [ApprovalDecision.REJECTED, ApprovalDecision.ABANDONED],
)
async def test_rejected_or_abandoned_r2_action_never_executes(
    decision: ApprovalDecision,
) -> None:
    registry = FakePhase5Registry()
    runtime = Phase5Runtime(
        registry=registry,  # type: ignore[arg-type]
        provider=DeterministicReasoningProvider(),
        store=InMemoryAgentStore(),
    )
    paused = await runtime.start(
        checkout_incident(),
        AgentBudget(max_tool_calls=12),
        operational_mode=True,
    )

    completed = await runtime.decide_approval(
        paused.run_id,
        decision=decision,
        actor="incident-commander",
    )

    assert completed.status == AgentRunStatus.COMPLETED
    assert completed.operation_stage == OperationStage.COMPLETE
    assert completed.verification.status == VerificationStatus.NOT_RUN
    assert not any(call[0] == "rollback_sandbox_deployment" for call in registry.calls)


@pytest.mark.asyncio
async def test_resume_keeps_pending_approval_paused() -> None:
    runtime = Phase5Runtime(
        registry=FakePhase5Registry(),  # type: ignore[arg-type]
        provider=DeterministicReasoningProvider(),
        store=InMemoryAgentStore(),
    )
    paused = await runtime.start(
        checkout_incident(),
        AgentBudget(max_tool_calls=12),
        operational_mode=True,
    )

    resumed = await runtime.resume(paused.run_id)

    assert resumed.status == AgentRunStatus.PAUSED
    assert resumed.operation_stage == OperationStage.WAIT_APPROVAL
    assert resumed.approval is not None
    assert resumed.approval.decision == ApprovalDecision.PENDING


@pytest.mark.asyncio
async def test_r3_action_is_blocked_before_registry_execution() -> None:
    registry = FakePhase5Registry()
    runtime = Phase5Runtime(
        registry=registry,  # type: ignore[arg-type]
        provider=DestructiveRecommendationProvider(),
        store=InMemoryAgentStore(),
    )

    state = await runtime.start(
        checkout_incident(),
        AgentBudget(max_tool_calls=12),
        operational_mode=True,
    )

    assert state.status == AgentRunStatus.COMPLETED
    assert state.operation_stage == OperationStage.COMPLETE
    assert state.stop_reason == "R3 action blocked by safety policy"
    assert state.failures
    assert state.failures[-1].code == "r3_blocked"
    assert not any(call[0] == "destroy_database" for call in registry.calls)
