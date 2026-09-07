from __future__ import annotations

import json
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
from app.agent.temporal import ExplicitTemporalReasoningProvider, TEMPORAL_PROVIDER_MARKER
from app.models.domain import (
    Diagnosis,
    Evidence,
    EvidenceType,
    Hypothesis,
    Incident,
    IncidentSeverity,
)


class StubProvider:
    name = "stub-provider"

    async def plan(self, state: AgentState) -> tuple[InvestigationPlan, ProviderUsage]:
        return (
            InvestigationPlan(
                summary="Inspect observable evidence.",
                steps=[
                    PlanStep(
                        id="logs",
                        objective="Inspect errors.",
                        tool="search_logs",
                        arguments={"service": state.incident.service, "limit": 20},
                        rationale="Find request failures.",
                    ),
                    PlanStep(
                        id="deployment",
                        objective="Inspect deployment context.",
                        tool="inspect_deployment",
                        arguments={"service": state.incident.service},
                        rationale="Treat deployment history as context.",
                    ),
                ],
            ),
            ProviderUsage(),
        )

    async def update_hypotheses(
        self, state: AgentState
    ) -> tuple[list[Hypothesis], ProviderUsage]:
        return (
            [
                Hypothesis(
                    description="Connection pressure explains the observed failures.",
                    root_cause_code="database_connection_leak",
                    confidence=0.9,
                    supporting_evidence=[state.evidence[0].id],
                )
            ],
            ProviderUsage(),
        )

    async def enough_evidence(self, state: AgentState) -> tuple[bool, ProviderUsage]:
        return True, ProviderUsage()

    async def diagnose(
        self, state: AgentState
    ) -> tuple[str, Diagnosis, ProviderUsage]:
        return (
            "database_connection_leak",
            Diagnosis(
                primary_root_cause="Connection pressure explains the failures.",
                confidence=0.9,
                evidence_ids=[state.evidence[0].id],
            ),
            ProviderUsage(),
        )

    async def recommend(
        self, state: AgentState
    ) -> tuple[ProposedAction | None, ProviderUsage]:
        return None, ProviderUsage()


def _state() -> AgentState:
    onset = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    incident = Incident(
        title="Inventory failures",
        description="User-visible inventory requests are failing.",
        severity=IncidentSeverity.P2,
        service="inventory",
        start_time=onset,
    )
    evidence = Evidence(
        incident_id=incident.id,
        source="chaoslab",
        evidence_type=EvidenceType.LOG,
        service="inventory",
        timestamp=onset,
        observation="search_logs returned observable log evidence",
        raw_reference=json.dumps(
            {
                "tool": "search_logs",
                "arguments": {"service": "inventory"},
                "payload": [
                    {
                        "timestamp": (onset - timedelta(minutes=5)).isoformat(),
                        "status": 503,
                    },
                    {
                        "timestamp": (onset + timedelta(minutes=1)).isoformat(),
                        "status": 503,
                    },
                ],
            }
        ),
    )
    return AgentState(
        run_id=uuid4(),
        incident=incident,
        budget=AgentBudget(),
        evidence=[evidence],
    )


@pytest.mark.asyncio
async def test_explicit_temporal_plan_bounds_observable_queries_before_onset() -> None:
    state = _state()
    provider = ExplicitTemporalReasoningProvider(StubProvider())

    plan, _ = await provider.plan(state)

    log_step = next(step for step in plan.steps if step.tool == "search_logs")
    deployment_step = next(step for step in plan.steps if step.tool == "inspect_deployment")
    assert log_step.arguments["end_time"] == state.incident.start_time.isoformat()
    assert log_step.arguments["start_time"] == (
        state.incident.start_time - timedelta(minutes=30)
    ).isoformat()
    assert "start_time" not in deployment_step.arguments
    assert "end_time" not in deployment_step.arguments
    assert TEMPORAL_PROVIDER_MARKER in provider.name


@pytest.mark.asyncio
async def test_explicit_temporal_hypothesis_uses_only_pre_onset_support_timestamp() -> None:
    state = _state()
    provider = ExplicitTemporalReasoningProvider(StubProvider())

    hypotheses, _ = await provider.update_hypotheses(state)

    assert len(hypotheses) == 1
    hypothesis = hypotheses[0]
    assert hypothesis.effect_time == state.incident.start_time
    assert hypothesis.first_possible_cause_time == state.incident.start_time - timedelta(
        minutes=5
    )
    assert hypothesis.first_possible_cause_time <= hypothesis.effect_time
