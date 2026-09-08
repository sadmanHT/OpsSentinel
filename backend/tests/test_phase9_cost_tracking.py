import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.agent.models import (
    AgentBudget,
    AgentState,
    InvestigationPlan,
    PlanStep,
    ProposedAction,
    ProviderUsage,
)
from app.agent.providers import ReasoningProviderError
from app.agent.store import SqlAgentStore
from app.config import Settings
from app.models.domain import (
    AgentRunStatus,
    Diagnosis,
    Evidence,
    EvidenceType,
    Hypothesis,
    Incident,
    IncidentSeverity,
    RiskLevel,
    ToolCall,
    ToolCallStatus,
)
from app.observability.models import (
    ModelExecutionEvent,
    ModelExecutionStatus,
    ModelOperation,
)
from app.observability.provider import MeteredReasoningProvider
from app.observability.store import (
    InMemoryObservabilityStore,
    SqlObservabilityStore,
    latency_distribution,
    percentile,
)
from app.persistence.session import create_database_engine


class StaticUsageProvider:
    name = "phase8-provider-marker+static-usage"

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        return InvestigationPlan(
            summary="Observe without changing behavior.",
            steps=[
                PlanStep(
                    id="phase9-observe-metrics",
                    objective="Observe checkout latency without changing state.",
                    tool="query_metrics",
                    arguments={"service": state.incident.service, "metric": "p95_latency"},
                    rationale="Use one legal read-only step for a structurally valid test plan.",
                )
            ],
        ), ProviderUsage(
            input_tokens=10,
            output_tokens=2,
            estimated_cost=0.001,
        )

    async def update_hypotheses(
        self, state: AgentState
    ) -> tuple[list[Hypothesis], ProviderUsage]:
        del state
        return [], ProviderUsage(input_tokens=8, output_tokens=1, estimated_cost=0.001)

    async def enough_evidence(self, state: AgentState) -> tuple[bool, ProviderUsage]:
        del state
        return True, ProviderUsage(input_tokens=5, output_tokens=1, estimated_cost=0.001)

    async def diagnose(
        self, state: AgentState
    ) -> tuple[str, Diagnosis, ProviderUsage]:
        del state
        return (
            "test_root_cause",
            Diagnosis(primary_root_cause="Test root cause", confidence=0.9),
            ProviderUsage(input_tokens=7, output_tokens=3, estimated_cost=0.002),
        )

    async def recommend(
        self, state: AgentState
    ) -> tuple[ProposedAction | None, ProviderUsage]:
        del state
        return None, ProviderUsage(input_tokens=4, output_tokens=1, estimated_cost=0.001)


class FailingPlanProvider(StaticUsageProvider):
    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        del state
        raise ReasoningProviderError("planned failure")


def _incident() -> Incident:
    return Incident(
        title="Phase 9 observability test",
        description="Exercise cost and latency instrumentation.",
        severity=IncidentSeverity.P2,
        service="checkout",
        start_time=datetime.now(UTC),
        scenario_id="phase9-cost-test",
    )


def _state() -> AgentState:
    return AgentState(run_id=uuid4(), incident=_incident(), budget=AgentBudget())


@pytest.mark.asyncio
async def test_metered_provider_preserves_outputs_identity_and_records_all_operations() -> None:
    sink = InMemoryObservabilityStore()
    inner = StaticUsageProvider()
    provider = MeteredReasoningProvider(inner, sink)
    state = _state()

    plan, plan_usage = await provider.plan(state)
    hypotheses, hypothesis_usage = await provider.update_hypotheses(state)
    enough, enough_usage = await provider.enough_evidence(state)
    code, diagnosis, diagnosis_usage = await provider.diagnose(state)
    action, action_usage = await provider.recommend(state)

    assert provider.name == inner.name
    assert plan.summary == "Observe without changing behavior."
    assert hypotheses == []
    assert enough is True
    assert code == "test_root_cause"
    assert diagnosis.primary_root_cause == "Test root cause"
    assert action is None
    assert sum(
        usage.total_tokens
        for usage in (
            plan_usage,
            hypothesis_usage,
            enough_usage,
            diagnosis_usage,
            action_usage,
        )
    ) == 42

    events = sink.events_for(state.run_id)
    assert [event.operation for event in events] == [
        ModelOperation.PLAN,
        ModelOperation.UPDATE_HYPOTHESES,
        ModelOperation.ENOUGH_EVIDENCE,
        ModelOperation.DIAGNOSE,
        ModelOperation.RECOMMEND,
    ]
    assert all(event.provider == inner.name for event in events)
    assert all(event.status == ModelExecutionStatus.SUCCEEDED for event in events)
    assert sum(event.total_tokens for event in events) == 42
    assert sum(event.estimated_cost for event in events) == pytest.approx(0.006)
    assert all(event.latency_ms >= 0.0 for event in events)


@pytest.mark.asyncio
async def test_metered_provider_records_failure_and_reraises_original_error() -> None:
    sink = InMemoryObservabilityStore()
    provider = MeteredReasoningProvider(FailingPlanProvider(), sink)
    state = _state()

    with pytest.raises(ReasoningProviderError, match="planned failure"):
        await provider.plan(state)

    events = sink.events_for(state.run_id)
    assert len(events) == 1
    assert events[0].operation == ModelOperation.PLAN
    assert events[0].status == ModelExecutionStatus.FAILED
    assert events[0].error_type == "ReasoningProviderError"
    assert events[0].total_tokens == 0


def test_latency_percentiles_are_deterministic_and_missing_data_is_explicit() -> None:
    assert percentile([], 0.5) is None
    assert percentile([10.0, 20.0, 30.0, 40.0], 0.5) == pytest.approx(25.0)
    assert percentile([10.0, 20.0, 30.0, 40.0], 0.95) == pytest.approx(38.5)
    with pytest.raises(ValueError, match="quantile"):
        percentile([1.0], 1.1)

    missing = latency_distribution([])
    assert missing.count == 0
    assert missing.p50_ms is None
    assert missing.p95_ms is None


@pytest.mark.integration
def test_sql_observability_summary_cross_checks_persisted_agent_data() -> None:
    settings = Settings(_env_file=None, database_url=os.environ["OPSSENTINEL_DATABASE_URL"])
    engine = create_database_engine(settings)
    agent_store = SqlAgentStore(
        engine,
        architecture_version="phase9-test",
        model="phase8-provider-marker+static-usage",
    )
    observability_store = SqlObservabilityStore(engine)

    started_at = datetime.now(UTC)
    incident = _incident()
    evidence = Evidence(
        incident_id=incident.id,
        source="phase9.query_metrics",
        evidence_type=EvidenceType.METRIC,
        service="checkout",
        timestamp=started_at + timedelta(seconds=1),
        observation="Checkout latency is elevated.",
        raw_reference='{"payload":{"value":0.9}}',
    )
    tool_call = ToolCall(
        id=uuid4(),
        tool_name="query_metrics",
        arguments={"service": "checkout", "metric": "p95_latency"},
        started_at=started_at + timedelta(seconds=1),
        completed_at=started_at + timedelta(seconds=1, milliseconds=250),
        status=ToolCallStatus.SUCCEEDED,
        result_reference=str(evidence.id),
        risk_level=RiskLevel.R0,
    )
    state = AgentState(
        run_id=uuid4(),
        incident=incident,
        status=AgentRunStatus.COMPLETED,
        evidence=[evidence],
        tool_history=[tool_call],
        started_at=started_at,
        updated_at=started_at + timedelta(seconds=3),
        budget=AgentBudget(
            steps_used=3,
            tool_calls_used=1,
            tokens_used=30,
            cost_used=0.003,
        ),
    )
    agent_store.create(state)

    observability_store.record_model_execution(
        ModelExecutionEvent(
            run_id=state.run_id,
            operation=ModelOperation.PLAN,
            provider="phase8-provider-marker+static-usage",
            input_tokens=10,
            output_tokens=5,
            estimated_cost=0.001,
            latency_ms=100.0,
            recorded_at=started_at + timedelta(milliseconds=500),
        )
    )
    observability_store.record_model_execution(
        ModelExecutionEvent(
            run_id=state.run_id,
            operation=ModelOperation.DIAGNOSE,
            provider="phase8-provider-marker+static-usage",
            input_tokens=12,
            output_tokens=3,
            estimated_cost=0.002,
            latency_ms=200.0,
            recorded_at=started_at + timedelta(seconds=2),
        )
    )

    summary = observability_store.summarize(state.run_id)
    assert summary is not None
    assert summary.status == AgentRunStatus.COMPLETED.value
    assert summary.model == "phase8-provider-marker+static-usage"
    assert summary.model_execution_count == 2
    assert summary.failed_model_execution_count == 0
    assert summary.usage_breakdown_available is True
    assert summary.input_tokens == 22
    assert summary.output_tokens == 8
    assert summary.total_tokens == 30
    assert summary.provider_estimated_cost == pytest.approx(0.003)
    assert summary.total_estimated_cost == pytest.approx(0.003)
    assert summary.tool_call_count == 1
    assert summary.retrieval_depth == 1
    assert summary.model_latency.p50_ms == pytest.approx(150.0)
    assert summary.model_latency.p95_ms == pytest.approx(195.0)
    assert summary.tool_latency.p50_ms == pytest.approx(250.0)
    assert summary.time_to_first_investigation_step_ms == pytest.approx(500.0)
    assert summary.time_to_diagnosis_ms == pytest.approx(2000.0)
    assert summary.time_to_verified_resolution_ms is None
