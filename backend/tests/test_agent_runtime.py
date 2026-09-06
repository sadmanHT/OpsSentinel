from datetime import UTC, datetime

import pytest

from app.agent.models import (
    AgentBudget,
    AgentNode,
    AgentReport,
    AgentState,
    GroundedClaim,
    InvestigationPlan,
    PlanStep,
    ProviderUsage,
    VerificationResult,
)
from app.agent.providers import DeterministicReasoningProvider
from app.agent.runtime import AgentRuntime
from app.agent.store import InMemoryAgentStore
from app.mcp.models import EvidenceEnvelope, ToolInvocation, ToolResponse
from app.models.domain import (
    AgentRunStatus,
    Diagnosis,
    EvidenceType,
    Incident,
    IncidentSeverity,
    RiskLevel,
    ToolCallStatus,
    VerificationStatus,
    utc_now,
)


class FakeRegistry:
    async def invoke(self, invocation: ToolInvocation) -> ToolResponse:
        now = utc_now()
        service = invocation.arguments.get("service")
        payload: object
        evidence_type: EvidenceType

        if invocation.tool == "query_metrics":
            evidence_type = EvidenceType.METRIC
            metric = invocation.arguments["metric"]
            values = {
                "p95_latency": 0.85,
                "db_query_count": 15,
            }
            payload = {"value": values.get(metric, 0.0)}
        elif invocation.tool == "search_logs":
            evidence_type = EvidenceType.LOG
            payload = [{"path": "/orders", "status": 200, "db_queries": 15}]
        elif invocation.tool == "inspect_deployment":
            evidence_type = EvidenceType.DEPLOYMENT
            payload = {"service": service, "deployment": "phase4-test", "health": {"status": "ok"}}
        elif invocation.tool == "inspect_git_diff":
            evidence_type = EvidenceType.CODE
            payload = {"base": "HEAD~1", "head": "HEAD", "output": "checkout query path changed"}
        else:
            raise AssertionError(f"unexpected fake tool: {invocation.tool}")

        return ToolResponse(
            tool=invocation.tool,
            status=ToolCallStatus.SUCCEEDED,
            risk_level=RiskLevel.R0,
            started_at=now,
            completed_at=utc_now(),
            data=EvidenceEnvelope(
                evidence_type=evidence_type,
                source=f"fake.{invocation.tool}",
                service=str(service) if service is not None else None,
                payload=payload,
            ),
        )


class DuplicatePlanProvider(DeterministicReasoningProvider):
    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        arguments = {"service": state.incident.service, "metric": "p95_latency"}
        return (
            InvestigationPlan(
                summary="Deliberately repeat one legal tool call to exercise the repetition budget.",
                steps=[
                    PlanStep(
                        id="first",
                        objective="Measure latency once.",
                        tool="query_metrics",
                        arguments=arguments,
                        rationale="First observation.",
                    ),
                    PlanStep(
                        id="second",
                        objective="Measure the same latency again.",
                        tool="query_metrics",
                        arguments=arguments,
                        rationale="Intentional duplicate for the regression test.",
                    ),
                ],
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
        scenario_id="unit-n-plus-one",
    )


@pytest.mark.asyncio
async def test_agent_completes_grounded_n_plus_one_diagnosis() -> None:
    store = InMemoryAgentStore()
    runtime = AgentRuntime(
        registry=FakeRegistry(),  # type: ignore[arg-type]
        provider=DeterministicReasoningProvider(),
        store=store,
    )

    state = await runtime.start(checkout_incident(), AgentBudget())

    assert state.status == AgentRunStatus.COMPLETED
    assert state.next_node == AgentNode.END
    assert state.diagnosis_code == "n_plus_one_query"
    assert state.final_diagnosis is not None
    assert state.final_diagnosis.confidence >= 0.9
    assert state.final_diagnosis.evidence_ids
    assert state.report is not None
    assert state.report.claims
    diagnosis_evidence = set(state.final_diagnosis.evidence_ids)
    assert all(set(claim.evidence_ids) <= diagnosis_evidence for claim in state.report.claims)
    assert all("fault" not in call.tool_name for call in state.tool_history)
    assert [call.tool_name for call in state.tool_history] == [
        "query_metrics",
        "inspect_deployment",
        "inspect_git_diff",
        "query_metrics",
        "search_logs",
    ]
    assert state.report.verification.status == VerificationStatus.NOT_RUN
    assert state.report.proposed_action is not None
    assert state.report.proposed_action.risk_level == RiskLevel.R2


@pytest.mark.asyncio
async def test_agent_stops_cleanly_when_tool_budget_is_exhausted() -> None:
    runtime = AgentRuntime(
        registry=FakeRegistry(),  # type: ignore[arg-type]
        provider=DeterministicReasoningProvider(),
        store=InMemoryAgentStore(),
    )

    state = await runtime.start(
        checkout_incident(),
        AgentBudget(max_tool_calls=1, max_steps=20),
    )

    assert state.status == AgentRunStatus.BUDGET_EXHAUSTED
    assert state.budget.tool_calls_used == 1
    assert state.stop_reason is not None
    assert "tool-call budget exhausted" in state.stop_reason
    assert state.report is not None
    assert state.report.status == AgentRunStatus.BUDGET_EXHAUSTED
    assert state.final_diagnosis is not None
    assert state.final_diagnosis.evidence_ids


@pytest.mark.asyncio
async def test_agent_blocks_repeated_identical_tool_call_loop() -> None:
    runtime = AgentRuntime(
        registry=FakeRegistry(),  # type: ignore[arg-type]
        provider=DuplicatePlanProvider(),
        store=InMemoryAgentStore(),
    )

    state = await runtime.start(
        checkout_incident(),
        AgentBudget(max_repeated_identical_calls=1, max_tool_calls=10),
    )

    assert state.status == AgentRunStatus.BUDGET_EXHAUSTED
    assert state.budget.tool_calls_used == 1
    assert state.stop_reason is not None
    assert "repeated identical tool-call budget exhausted" in state.stop_reason


@pytest.mark.asyncio
async def test_agent_pause_then_resume_uses_persisted_next_node() -> None:
    store = InMemoryAgentStore()
    paused_runtime = AgentRuntime(
        registry=FakeRegistry(),  # type: ignore[arg-type]
        provider=DeterministicReasoningProvider(),
        store=store,
        interrupt_after=[AgentNode.PLAN],
    )

    paused = await paused_runtime.start(checkout_incident(), AgentBudget())
    assert paused.status == AgentRunStatus.PAUSED
    assert paused.next_node == AgentNode.SELECT_TOOL
    assert paused.plan is not None
    assert not paused.evidence

    resumed_runtime = AgentRuntime(
        registry=FakeRegistry(),  # type: ignore[arg-type]
        provider=DeterministicReasoningProvider(),
        store=store,
    )
    resumed = await resumed_runtime.resume(paused.run_id)

    assert resumed.status == AgentRunStatus.COMPLETED
    assert resumed.diagnosis_code == "n_plus_one_query"
    assert resumed.evidence
    assert store.load(paused.run_id) is not None
    assert store.load(paused.run_id).next_node == AgentNode.END  # type: ignore[union-attr]


def test_completed_report_rejects_ungrounded_claim_evidence() -> None:
    incident = checkout_incident()
    diagnosis = Diagnosis(
        primary_root_cause="Grounded diagnosis",
        confidence=0.9,
        evidence_ids=[],
    )
    with pytest.raises(ValueError):
        AgentReport(
            run_id=incident.id,
            status=AgentRunStatus.COMPLETED,
            root_cause_code="test",
            diagnosis=diagnosis,
            claims=[
                GroundedClaim(
                    statement="Unsupported claim",
                    evidence_ids=[incident.id],
                )
            ],
            verification=VerificationResult(
                status=VerificationStatus.NOT_RUN,
                summary="No verification in Phase 4.",
            ),
        )
